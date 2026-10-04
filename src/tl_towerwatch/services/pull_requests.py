from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tl_towerwatch.config import Settings, load_settings
from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import (
    PRSummary,
    PullRequest,
    Repo,
    Review,
    ReviewComment,
    User,
    now_iso,
)
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.llm.base import LLMProvider
from tl_towerwatch.services.repos import normalize_authors


def _upsert_user(
    s: Session,
    login: str | None,
    *,
    avatar_url: str | None = None,
    display_name: str | None = None,
) -> None:
    if not login:
        return
    u = s.get(User, login)
    if u is None:
        s.add(User(login=login, avatar_url=avatar_url, display_name=display_name))
        s.flush()
        return
    if avatar_url and not u.avatar_url:
        u.avatar_url = avatar_url
    if display_name and not u.display_name:
        u.display_name = display_name


def _upsert_pr(s: Session, repo_id: int, pr) -> PullRequest:
    _upsert_user(
        s,
        pr.author_login,
        avatar_url=getattr(pr, "author_avatar_url", None),
        display_name=getattr(pr, "author_display_name", None),
    )
    existing = s.execute(
        select(PullRequest).where(
            PullRequest.repo_id == repo_id, PullRequest.number == pr.number
        )
    ).scalar_one_or_none()
    if existing is not None:
        for f in (
            "title", "body", "author_login", "state", "draft",
            "head_sha", "base_ref", "html_url", "created_at", "updated_at",
        ):
            setattr(existing, f, getattr(pr, f))
        existing.cached_at = now_iso()
        return existing
    new = PullRequest(
        repo_id=repo_id,
        number=pr.number,
        title=pr.title,
        body=pr.body,
        author_login=pr.author_login,
        state=pr.state,
        draft=1 if pr.draft else 0,
        head_sha=pr.head_sha,
        base_ref=pr.base_ref,
        html_url=pr.html_url,
        created_at=pr.created_at,
        updated_at=pr.updated_at,
        cached_at=now_iso(),
    )
    s.add(new)
    s.flush()
    return new


def _replace_reviews_and_comments(
    s: Session, pr_id: int, gh: GitHubClient, owner: str, name: str, number: int
) -> None:
    s.query(Review).filter(Review.pr_id == pr_id).delete()
    s.query(ReviewComment).filter(ReviewComment.pr_id == pr_id).delete()
    for r in gh.list_reviews(owner, name, number):
        _upsert_user(
            s,
            r.reviewer_login,
            avatar_url=getattr(r, "reviewer_avatar_url", None),
            display_name=getattr(r, "reviewer_display_name", None),
        )
        s.add(
            Review(
                pr_id=pr_id,
                reviewer_login=r.reviewer_login,
                state=r.state,
                submitted_at=r.submitted_at,
                body=r.body,
            )
        )
    for c in gh.list_comments(owner, name, number):
        _upsert_user(
            s,
            c.reviewer_login,
            avatar_url=getattr(c, "reviewer_avatar_url", None),
            display_name=getattr(c, "reviewer_display_name", None),
        )
        s.add(
            ReviewComment(
                pr_id=pr_id,
                reviewer_login=c.reviewer_login,
                path=c.path,
                body=c.body,
                created_at=c.created_at,
            )
        )


def _summarize_diff(files, *, max_files: int, max_lines: int) -> str:
    """Concatenate file patches, truncating to ``max_files`` files and
    ``max_lines`` lines so the LLM sees the salient diff without exceeding
    its context window. Replaces the old char-based `[:20000]` cap that could
    still send tens of thousands of lines when a single file was huge
    (v1.1 / Task 12).
    """
    diff_parts = [f.patch for f in files[:max_files] if f.patch]
    diff_text = "\n".join(diff_parts)
    lines = diff_text.splitlines()
    if len(lines) > max_lines:
        diff_text = "\n".join(lines[:max_lines])
        diff_text += f"\n... [truncated to {max_lines} lines of {len(lines)} total]\n"
    return diff_text


def _maybe_summarize(
    s: Session,
    row: PullRequest,
    *,
    llm: LLMProvider | None,
    diff_text: str,
    repo_label: str,
) -> None:
    """Generate / refresh a PRSummary when `llm` is provided and the head SHA
    changed (or no summary exists yet).
    """
    if llm is None:
        return
    existing_summary = s.get(PRSummary, row.id)
    if existing_summary is not None and existing_summary.head_sha == row.head_sha:
        return
    text = llm.summarize(
        title=row.title,
        body=row.body or "",
        diff=diff_text,
        metadata={"number": row.number, "repo": repo_label},
    )
    if existing_summary is None:
        s.add(
            PRSummary(
                pr_id=row.id,
                summary=text,
                head_sha=row.head_sha,
                model=llm.name,
                generated_at=now_iso(),
            )
        )
    else:
        existing_summary.summary = text
        existing_summary.head_sha = row.head_sha
        existing_summary.model = llm.name
        existing_summary.generated_at = now_iso()


def sync_repo(
    db: Database, gh: GitHubClient, repo: Repo, *,
    llm: LLMProvider | None = None,
    settings: Settings | None = None,
) -> int:
    count = 0
    repo_label = f"{repo.owner}/{repo.name}"
    if settings is None:
        settings = load_settings()
    with db.session() as s:
        for pr in gh.list_open_prs(repo.owner, repo.name):
            row = _upsert_pr(s, repo.id, pr)
            s.flush()
            _replace_reviews_and_comments(s, row.id, gh, repo.owner, repo.name, pr.number)
            if llm is not None:
                files = gh.list_pr_files(repo.owner, repo.name, pr.number)
                _maybe_summarize(
                    s, row, llm=llm,
                    diff_text=_summarize_diff(
                        files,
                        max_files=settings.max_diff_files,
                        max_lines=settings.max_diff_lines,
                    ),
                    repo_label=repo_label,
                )
            count += 1
        # Re-fetch the repo row in the current session before mutating: callers
        # typically pass a Repo loaded by an earlier `list_repos(db)` call, so
        # the instance is detached and field assignments would be dropped on
        # commit.
        fresh = s.get(Repo, repo.id)
        fresh.last_fetched_at = now_iso()
        fresh.last_fetch_status = "ok"
        fresh.last_fetch_error = None
    return count


def sync_one_pr(
    db: Database,
    gh: GitHubClient,
    repo: Repo,
    number: int,
    *,
    llm: LLMProvider | None = None,
    settings: Settings | None = None,
) -> PullRequest:
    diff_text = ""
    if llm is not None:
        if settings is None:
            settings = load_settings()
        diff_text = _summarize_diff(
            gh.list_pr_files(repo.owner, repo.name, number),
            max_files=settings.max_diff_files,
            max_lines=settings.max_diff_lines,
        )
    with db.session() as s:
        pr = gh.get_pr(repo.owner, repo.name, number)
        row = _upsert_pr(s, repo.id, pr)
        _replace_reviews_and_comments(s, row.id, gh, repo.owner, repo.name, number)
        _maybe_summarize(
            s, row, llm=llm,
            diff_text=diff_text,
            repo_label=f"{repo.owner}/{repo.name}",
        )
        return row


def get_pr_with_details(
    db: Database, repo: Repo, number: int
) -> PullRequest | None:
    with db.session() as s:
        return s.execute(
            select(PullRequest).where(
                PullRequest.repo_id == repo.id, PullRequest.number == number
            )
        ).scalar_one_or_none()


def list_prs_for_dashboard(
    db: Database,
    *,
    login: str,
    scope_filter: str,
    allowed_authors_filter: list[str] | None = None,
) -> list[PullRequest]:
    """Return PRs visible on the dashboard given the current filters.

    Filter order follows spec §12: `scope_filter` is applied first, then
    `allowed_authors_filter`.
    """
    with db.session() as s:
        rows: list[PullRequest] = list(s.execute(select(PullRequest)).scalars())

        if scope_filter == "mine":
            rows = [p for p in rows if p.author_login == login]
        elif scope_filter == "review":
            reviewer_pr_ids = {
                pid
                for (pid,) in s.execute(
                    select(Review.pr_id).where(Review.reviewer_login == login)
                ).all()
            }
            rows = [p for p in rows if p.id in reviewer_pr_ids]
        elif scope_filter == "mine_and_review":
            reviewer_pr_ids = {
                pid
                for (pid,) in s.execute(
                    select(Review.pr_id).where(Review.reviewer_login == login)
                ).all()
            }
            rows = [
                p
                for p in rows
                if p.author_login == login or p.id in reviewer_pr_ids
            ]
        # "all" or unknown -> no extra filter

        if allowed_authors_filter:
            allowed = set(normalize_authors(allowed_authors_filter))
            rows = [p for p in rows if (p.author_login or "").lower() in allowed]

        rows.sort(key=lambda p: p.updated_at, reverse=True)
        return rows