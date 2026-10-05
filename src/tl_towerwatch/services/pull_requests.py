from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import (
    IssueComment,
    PRCommit,
    PRFile,
    PullRequest,
    Repo,
    Review,
    ReviewComment,
    User,
    now_iso,
)
from tl_towerwatch.github.client import GitHubClient
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
            "additions", "deletions", "changed_files", "commits_count",
            "merged_at", "manual_description", "manual_notes",
        ):
            setattr(existing, f, getattr(pr, f, getattr(existing, f, None)))
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
        additions=pr.additions,
        deletions=pr.deletions,
        changed_files=pr.changed_files,
        commits_count=pr.commits_count,
        merged_at=getattr(pr, "merged_at", None),
        manual_description=getattr(pr, "manual_description", None),
        manual_notes=getattr(pr, "manual_notes", None),
    )
    s.add(new)
    s.flush()
    return new


def _replace_pr_subresources(
    s: Session, pr_id: int, gh: GitHubClient, owner: str, name: str, number: int
) -> None:
    """Wipe and re-insert every per-PR subresource (reviews, review
    comments, conversation comments, commits, files).

    The schema's missing key for FK enforcement: every commit's
    ``author_login`` must exist in ``users`` before the commit inserts.
    Same for the other author-referencing rows. ``_upsert_user``
    handles that for each row we see coming back from GitHub.
    """
    s.query(Review).filter(Review.pr_id == pr_id).delete()
    s.query(ReviewComment).filter(ReviewComment.pr_id == pr_id).delete()
    s.query(IssueComment).filter(IssueComment.pr_id == pr_id).delete()
    s.query(PRCommit).filter(PRCommit.pr_id == pr_id).delete()
    s.query(PRFile).filter(PRFile.pr_id == pr_id).delete()
    s.query(IssueComment).filter(IssueComment.pr_id == pr_id).delete()
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
                github_id=c.github_id,
                pr_id=pr_id,
                reviewer_login=c.reviewer_login,
                path=c.path,
                line=c.line,
                body=c.body,
                created_at=c.created_at,
                in_reply_to_id=c.in_reply_to_id,
            )
        )
    for c in gh.list_issue_comments(owner, name, number):
        _upsert_user(
            s,
            c.author_login,
            avatar_url=c.author_avatar_url,
            display_name=c.author_display_name,
        )
        s.add(
            IssueComment(
                github_id=c.github_id,
                pr_id=pr_id,
                author_login=c.author_login,
                body=c.body,
                created_at=c.created_at,
                in_reply_to_id=c.in_reply_to_id,
            )
        )
    # Commits — store the full message + committed_at so the
    # "Commits" tab can render a timeline without an extra GitHub
    # round-trip. Author login may be null (signed-off but no GitHub
    # account attached); we still want the commit to show.
    for c in gh.list_pr_commits(owner, name, number):
        if c.author_login:
            _upsert_user(
                s,
                c.author_login,
                avatar_url=c.author_avatar_url,
                display_name=c.author_display_name,
            )
        s.add(
            PRCommit(
                pr_id=pr_id,
                sha=c.sha,
                message=c.message,
                author_login=c.author_login,
                committed_at=c.committed_at,
            )
        )
    # Files — store path / +/- / status / patch so the "Files" tab
    # can render a stat-list with snippet preview. We only keep files
    # that have a path (some GitHub responses omit it for binary or
    # rename-only entries).
    for f in gh.list_pr_files(owner, name, number):
        if not f.path:
            continue
        s.add(
            PRFile(
                pr_id=pr_id,
                path=f.path,
                additions=int(f.additions or 0),
                deletions=int(f.deletions or 0),
                status=f.status or "",
                patch=f.patch,
            )
        )


def sync_repo(db: Database, gh: GitHubClient, repo: Repo) -> int:
    """Sync every PR for ``repo`` from GitHub into the local cache.

    v1.3.x: fetches all PRs (open + closed + merged) so state
    transitions get picked up. The old ``list_open_prs``-only loop
    missed the open→closed/merged transition entirely (GitHub's
    ``state=open`` filter omits closed PRs), so a PR closed on
    GitHub would forever read as "open" in the local cache. The
    pagination guard stops at 2,000 PRs per repo which is plenty
    for any real project.
    """
    count = 0
    with db.session() as s:
        for pr in gh.list_repo_prs(repo.owner, repo.name, state="all"):
            # The list endpoint omits additions / deletions / changed_files /
            # commits. Fetch the per-PR payload so the dashboard tab
            # counts (``changed_files`` etc.) match what the PR detail
            # page actually shows. Without this the counts stuck at 0
            # because ``_parse_pr`` defaulted them to 0.
            try:
                pr = gh.get_pr(repo.owner, repo.name, pr.number)
            except Exception:  # noqa: BLE001 — fall back to list payload
                pass
            row = _upsert_pr(s, repo.id, pr)
            s.flush()
            _replace_pr_subresources(s, row.id, gh, repo.owner, repo.name, pr.number)
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
) -> PullRequest:
    """Refresh a single PR's metadata + reviews + comments.

    v1.3.0: dropped the ``llm`` parameter. Summaries are now author-only
    via the ``manual_description`` column on PullRequest.
    """
    with db.session() as s:
        pr = gh.get_pr(repo.owner, repo.name, number)
        row = _upsert_pr(s, repo.id, pr)
        _replace_pr_subresources(s, row.id, gh, repo.owner, repo.name, number)
        return row


def post_issue_comment_reply(
    db: Database, gh: GitHubClient, repo: Repo, number: int, body: str,
    in_reply_to_github_id: int | None = None,
) -> dict:
    """Post a reply to the PR's issue conversation and persist it locally.

    Posts to GitHub first so a network failure bubbles up cleanly, then
    refreshes the PR's comment cache so the new comment shows up in the
    UI. When ``in_reply_to_github_id`` is supplied, the local row is
    threaded under the parent so the timeline renders as a nested reply.

    The post-reply refresh is best-effort: a transient failure here
    means the reply is on GitHub but not in our local cache, which the
    next sync will catch up. The route surfaces the partial success via
    the ``?error=reply_sync_failed`` banner rather than as a full
    failure.
    """
    posted = gh.post_issue_comment(repo.owner, repo.name, number, body)
    sync_error: str | None = None
    try:
        sync_one_pr(db, gh, repo, number)
    except Exception as e:  # noqa: BLE001 — partial-success path
        sync_error = type(e).__name__
    # If the user posted a threaded reply, patch the local row so the
    # UI threads it without waiting for the next refresh to round-trip.
    if in_reply_to_github_id and posted.get("id"):
        with db.session() as s:
            row = s.execute(
                select(IssueComment).where(
                    IssueComment.github_id == int(posted["id"])
                )
            ).scalar_one_or_none()
            if row is not None:
                row.in_reply_to_id = in_reply_to_github_id
    if sync_error:
        # Surface partial success to the caller. The reply landed on
        # GitHub; only the cache refresh failed.
        return {**posted, "_sync_error": sync_error}
    return posted


def post_review_comment_reply(
    db: Database, gh: GitHubClient, repo: Repo, number: int,
    parent_github_id: int, body: str,
) -> dict:
    """Post a threaded reply to an inline review comment and refresh."""
    posted = gh.post_review_comment_reply(
        repo.owner, repo.name, number, parent_github_id, body
    )
    sync_error: str | None = None
    try:
        sync_one_pr(db, gh, repo, number)
    except Exception as e:  # noqa: BLE001 — partial-success path
        sync_error = type(e).__name__
    if sync_error:
        return {**posted, "_sync_error": sync_error}
    return posted


def save_manual_description(
    db: Database, repo: Repo, number: int, text: str
) -> PullRequest:
    """Persist the author's manual description for a PR.

    Manual description replaces the AI summary that used to live on
    PRSummary — the user writes their own TL;DR for reviewers. Empty
    text clears the field.
    """
    with db.session() as s:
        row = s.execute(
            select(PullRequest).where(
                PullRequest.repo_id == repo.id, PullRequest.number == number
            )
        ).scalar_one()
        row.manual_description = text or None
        return row


def save_manual_notes(
    db: Database, repo: Repo, number: int, text: str
) -> PullRequest:
    """Persist the author's internal notes for a PR.

    Manual notes are author-only context (release notes, things-to-
    remember) that doesn't belong in the public PR description.
    """
    with db.session() as s:
        row = s.execute(
            select(PullRequest).where(
                PullRequest.repo_id == repo.id, PullRequest.number == number
            )
        ).scalar_one()
        row.manual_notes = text or None
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
    state_filter: str = "open",
) -> list[PullRequest]:
    """Return PRs visible on the dashboard given the current filters.

    Filter order follows spec §12: ``scope_filter`` is applied first,
    then ``allowed_authors_filter``, then ``state_filter``.

    ``state_filter`` accepts:
    - ``"open"`` (default) — only ``state == "open"`` PRs
    - ``"closed"`` — only closed, not merged
    - ``"merged"`` — only closed AND ``merged_at`` is set
    - ``"all"`` — no state filter
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

        # State filter — runs after the scope/author filters so the
        # "open" count matches what the user actually sees on the
        # dashboard when they switch tabs.
        if state_filter == "open":
            rows = [p for p in rows if p.state == "open"]
        elif state_filter == "closed":
            rows = [p for p in rows
                    if p.state == "closed" and not p.merged_at]
        elif state_filter == "merged":
            rows = [p for p in rows
                    if p.state == "closed" and p.merged_at]
        # "all" or unknown -> no extra filter

        rows.sort(key=lambda p: p.updated_at, reverse=True)
        return rows