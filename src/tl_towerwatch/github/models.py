from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class User:
    login: str
    avatar_url: str | None = None
    display_name: str | None = None

@dataclass
class RepoMeta:
    owner: str
    name: str
    full_name: str
    private: bool

@dataclass
class PullRequestData:
    number: int
    title: str
    body: str | None
    author_login: str | None
    state: str
    draft: bool
    head_sha: str
    base_ref: str
    html_url: str
    created_at: str
    updated_at: str
    requested_reviewers: list[str] = field(default_factory=list)
    author_avatar_url: str | None = None
    author_display_name: str | None = None
    # Diff stats + commit count for the mock dashboard cards (e.g.
    # "+247 / -89 líneas · 12 archivos · 3 commits post-creación").
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    commits_count: int = 0
    # ``merged_at`` distinguishes a "closed" PR (not merged) from a
    # "merged" PR — GitHub's ``state`` field is just "closed" for
    # both. None while the PR is still open.
    merged_at: str | None = None

@dataclass
class ReviewData:
    reviewer_login: str
    state: str
    submitted_at: str
    body: str | None
    reviewer_avatar_url: str | None = None
    reviewer_display_name: str | None = None

@dataclass
class CommentData:
    """Inline review comment (diff-anchored). Distinct from IssueComment,
    which lives on the conversation tab."""
    github_id: int
    reviewer_login: str
    path: str | None
    line: int | None
    body: str
    created_at: str
    in_reply_to_id: int | None = None
    reviewer_avatar_url: str | None = None
    reviewer_display_name: str | None = None


@dataclass
class IssueCommentData:
    """Top-level PR conversation comment."""
    github_id: int
    author_login: str
    body: str
    created_at: str
    in_reply_to_id: int | None = None
    author_avatar_url: str | None = None
    author_display_name: str | None = None

@dataclass
class FileData:
    path: str
    additions: int
    deletions: int
    status: str
    patch: str | None

@dataclass
class CommitData:
    sha: str
    message: str
    author_login: str | None
    author_avatar_url: str | None = None
    author_display_name: str | None = None
    committed_at: str | None = None

@dataclass
class RateLimit:
    """Snapshot of GitHub's rate-limit window for the current token.

    ``limit`` is the per-hour ceiling (5,000 for a PAT, but GitHub Apps
    and enterprise tokens can return different numbers — read from the
    response, never hard-coded). ``remaining`` is what's left in the
    current window; ``reset`` is the unix timestamp when the window
    rolls over."""
    limit: int = 0
    remaining: int = 0
    reset: int = 0