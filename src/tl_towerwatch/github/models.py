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

@dataclass
class ReviewData:
    reviewer_login: str
    state: str
    submitted_at: str
    body: str | None

@dataclass
class CommentData:
    reviewer_login: str
    path: str | None
    body: str
    created_at: str

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