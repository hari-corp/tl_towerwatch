from __future__ import annotations
import json

from sqlalchemy import select

from tl_towerwatch.agents import get_runner
from tl_towerwatch.config import Settings
from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import (
    Repo,
    ReviewFinding,
    ReviewRun,
    now_iso,
)
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.services.findings import finding_key, reconcile
from tl_towerwatch.services.pull_requests import sync_one_pr
from tl_towerwatch.skills.registry import load_registry


DEFAULT_TEMPLATE = None  # runners fall back to skills.prompts.DEFAULT_TEMPLATE


def run_review(
    db: Database, gh: GitHubClient,
    *,
    owner: str, name: str, number: int,
    agent_name: str, skill_names: list[str], mode: str,
    timeout_seconds: int, settings: Settings,
) -> ReviewRun:
    """Sync a PR, run the chosen agent against it, and reconcile findings.

    The PR is refreshed (`sync_one_pr`, no LLM summary), a `ReviewRun` row is
    inserted in `running` status with a JSON context snapshot, the agent
    subprocess is invoked, the run is closed in `done`/`failed`/`timeout`, and
    findings are recorded and classified (see `tl_towerwatch.services.findings`).
    """
    with db.session() as s:
        repo_row = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one()
        pr = sync_one_pr(db, gh, repo_row, number, llm=None)
        context_snapshot = json.dumps({
            "pr": {
                "number": pr.number,
                "title": pr.title,
                "body": pr.body,
                "head_sha": pr.head_sha,
                "author_login": pr.author_login,
            },
            "diff": _diff_text(gh, owner, name, number),
            "previous_findings": _prior_findings_payload(s, pr.id),
        })
        run = ReviewRun(
            pr_id=pr.id,
            agent_runner=agent_name,
            skills_json=json.dumps(skill_names),
            mode=mode,
            status="running",
            started_at=now_iso(),
            context_snapshot_json=context_snapshot,
        )
        s.add(run)
        s.flush()
        run_id = run.id

    skills = [
        sk for sk in load_registry(settings.data_dir)
        if sk.name in skill_names and sk.enabled
    ]
    runner = get_runner(agent_name, settings)
    res = runner.run_review(
        pr_diff=_diff_text(gh, owner, name, number),
        pr_metadata={
            "title": pr.title,
            "body": pr.body,
            "author": pr.author_login,
            "number": pr.number,
            "repo": f"{owner}/{name}",
            "head_sha": pr.head_sha,
        },
        skills=skills,
        prompt_template=DEFAULT_TEMPLATE,
        mode=mode,
        previous_findings=_prior_findings_payload_dict(db, pr.id),
        timeout_seconds=timeout_seconds,
    )

    with db.session() as s:
        run = s.get(ReviewRun, run_id)
        run.finished_at = now_iso()
        run.result_markdown = res.markdown
        if res.error:
            run.status = "timeout" if res.error == "timeout" else "failed"
            run.error = res.error
        else:
            run.status = "done"
            for f in res.findings:
                k = f.finding_key or finding_key(f.file_path, f.line, f.description)
                s.add(ReviewFinding(
                    review_run_id=run_id,
                    finding_key=k,
                    severity=f.severity,
                    file_path=f.file_path,
                    line=f.line,
                    description=f.description,
                    status="new",
                ))

    reconcile(db, run_id)
    return run


def _diff_text(gh: GitHubClient, owner: str, name: str, number: int) -> str:
    files = gh.list_pr_files(owner, name, number)
    return "\n".join((f.patch or "") for f in files[:30])[:20000]


def _prior_findings_payload(s, pr_id: int) -> list[dict]:
    runs = list(s.execute(
        select(ReviewRun).where(
            ReviewRun.pr_id == pr_id, ReviewRun.status == "done",
        ).order_by(ReviewRun.id.desc())
    ).scalars())
    if not runs:
        return []
    last = runs[0]
    out: list[dict] = []
    for f in s.execute(
        select(ReviewFinding).where(ReviewFinding.review_run_id == last.id)
    ).scalars():
        out.append({
            "finding_key": f.finding_key,
            "severity": f.severity,
            "file_path": f.file_path,
            "line": f.line,
            "description": f.description,
            "status": f.status,
        })
    return out


def _prior_findings_payload_dict(db: Database, pr_id: int) -> list[dict]:
    with db.session() as s:
        return _prior_findings_payload(s, pr_id)