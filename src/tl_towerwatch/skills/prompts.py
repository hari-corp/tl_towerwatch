from __future__ import annotations
from typing import Iterable
from tl_towerwatch.skills.registry import Skill

DEFAULT_TEMPLATE = """\
You are reviewing GitHub PR #{number} in repo {repo}.

Title: {title}
Author: {author}
Head SHA: {head_sha}

PR description:
{body}

Diff (truncated):
{diff}

{mode_intro}

Skills you MUST invoke:
{skills_list}

Previous findings (status from last run):
{findings_list}

Output format:
- After your reasoning, emit a final block delimited by these exact lines:
    <!-- TLTW:FINDINGS -->
    [{{"severity":"high|medium|low","file_path":"...","line":N,"description":"..."}}, ...]
    <!-- TLTW:DONE -->
- Each finding must have a stable `finding_key` derived from file_path:line:slug(description).
"""

def render_review_prompt(*, pr_metadata: dict, mode: str,
                         previous_findings: list[dict],
                         skills: list[Skill],
                         diff: str, template: str | None = None) -> str:
    tpl = template or DEFAULT_TEMPLATE
    mode_intro = (
        "This is a FRESH review — ignore any prior context; review only the diff above."
        if mode == "fresh" else
        "This is a COMPARE review — for each previous finding, decide if it is still "
        "applicable to the current diff. Mark it `pending` if yes, omit it if it was fixed. "
        "Also flag any new issues."
    )
    skills_lines = "\n".join(
        f"- {s.name}: {s.description} (CLI flag: {s.cli_flag})" for s in skills if s.enabled
    ) or "- (none)"
    findings_lines = "\n".join(
        f"- [{f['status']}] {f['severity']} {f.get('file_path','?')}:{f.get('line','?')} — {f['description']}"
        for f in previous_findings
    ) or "- (none)"
    return tpl.format(
        title=pr_metadata.get("title", ""),
        body=pr_metadata.get("body") or "",
        author=pr_metadata.get("author", ""),
        number=pr_metadata.get("number", ""),
        repo=pr_metadata.get("repo", ""),
        head_sha=pr_metadata.get("head_sha", ""),
        diff=diff,
        mode_intro=mode_intro,
        skills_list=skills_lines,
        findings_list=findings_lines,
    )