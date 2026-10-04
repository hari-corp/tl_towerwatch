from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repo(Base):
    __tablename__ = "repos"
    id = Column(Integer, primary_key=True)
    owner = Column(String, nullable=False)
    name = Column(String, nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    is_self = Column(Integer, nullable=False, default=0)
    refresh_interval_seconds = Column(Integer, nullable=False, default=300)
    scope = Column(String, nullable=False, default="mine_and_review")
    llm_override = Column(String)
    allowed_authors_json = Column(Text)
    added_at = Column(String, nullable=False)
    last_fetched_at = Column(String)
    last_fetch_status = Column(String)
    last_fetch_error = Column(Text)
    __table_args__ = (Index("uq_repos_owner_name", "owner", "name", unique=True),)


class User(Base):
    __tablename__ = "users"
    login = Column(String, primary_key=True)
    avatar_url = Column(String)
    display_name = Column(String)


class PullRequest(Base):
    __tablename__ = "pull_requests"
    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repos.id"), nullable=False)
    number = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text)
    author_login = Column(String, ForeignKey("users.login"))
    state = Column(String, nullable=False)
    draft = Column(Integer, nullable=False, default=0)
    head_sha = Column(String, nullable=False)
    base_ref = Column(String, nullable=False)
    html_url = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    cached_at = Column(String, nullable=False)
    __table_args__ = (
        Index("uq_pr_repo_number", "repo_id", "number", unique=True),
        Index("idx_pr_repo", "repo_id"),
    )


class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True)
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    reviewer_login = Column(String, ForeignKey("users.login"), nullable=False)
    state = Column(String, nullable=False)
    submitted_at = Column(String, nullable=False)
    body = Column(Text)
    __table_args__ = (Index("idx_reviews_pr", "pr_id"),)


class ReviewComment(Base):
    __tablename__ = "review_comments"
    id = Column(Integer, primary_key=True)
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    reviewer_login = Column(String, ForeignKey("users.login"), nullable=False)
    path = Column(String)
    body = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)
    __table_args__ = (Index("idx_comments_pr", "pr_id"),)


class PRSummary(Base):
    __tablename__ = "pr_summaries"
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), primary_key=True)
    summary = Column(Text, nullable=False)
    head_sha = Column(String, nullable=False)
    model = Column(String, nullable=False)
    generated_at = Column(String, nullable=False)


class ReviewRun(Base):
    __tablename__ = "review_runs"
    id = Column(Integer, primary_key=True)
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    agent_runner = Column(String, nullable=False)
    skills_json = Column(Text, nullable=False)
    mode = Column(String, nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(String, nullable=False)
    finished_at = Column(String)
    error = Column(Text)
    result_markdown = Column(Text)
    context_snapshot_json = Column(Text)


class ReviewFinding(Base):
    __tablename__ = "review_findings"
    id = Column(Integer, primary_key=True)
    review_run_id = Column(Integer, ForeignKey("review_runs.id"), nullable=False)
    finding_key = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    file_path = Column(String)
    line = Column(Integer)
    description = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    resolved_in_commit = Column(String)
    __table_args__ = (
        Index("uq_finding_run_key", "review_run_id", "finding_key", unique=True),
        Index("idx_findings_run", "review_run_id"),
        Index("idx_findings_key", "finding_key"),
    )