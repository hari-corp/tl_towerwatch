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
    reviewer_login: str
    path: str | None
    body: str
    created_at: str
    reviewer_avatar_url: str | None = None
    reviewer_display_name: str | None = None

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

@dataclass
class RateLimit:
    remaining: int
    reset: int