from __future__ import annotations
import json
from typing import Iterable

from sqlalchemy import select
from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import Repo, now_iso

def normalize_authors(authors: Iterable[str]) -> list[str]:
    out: set[str] = set()
    for a in authors:
        a = a.strip().lstrip("@").lower()
        if a:
            out.add(a)
    return sorted(out)

def add_repo(
    db: Database, owner: str, name: str,
    *, is_self: bool = False, refresh_interval_seconds: int = 300,
    scope: str = "mine_and_review", allowed_authors: list[str] | None = None,
) -> Repo:
    with db.session() as s:
        existing = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one_or_none()
        if existing:
            existing.enabled = 1
            existing.is_self = 1 if is_self else existing.is_self
            existing.refresh_interval_seconds = refresh_interval_seconds
            existing.scope = scope
            if allowed_authors is not None:
                existing.allowed_authors_json = json.dumps(normalize_authors(allowed_authors))
            s.flush()
            return existing
        r = Repo(
            owner=owner, name=name, enabled=1,
            is_self=1 if is_self else 0,
            refresh_interval_seconds=refresh_interval_seconds,
            scope=scope,
            allowed_authors_json=json.dumps(normalize_authors(allowed_authors or [])),
            added_at=now_iso(),
        )
        s.add(r)
        s.flush()
        return r

def list_repos(db: Database, *, enabled_only: bool = False) -> list[Repo]:
    with db.session() as s:
        q = select(Repo)
        if enabled_only:
            q = q.where(Repo.enabled == 1)
        return list(s.execute(q).scalars())

def set_repo_enabled(db: Database, owner: str, name: str, enabled: bool) -> None:
    with db.session() as s:
        r = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one_or_none()
        if r is None:
            raise KeyError(f"{owner}/{name} not registered")
        r.enabled = 1 if enabled else 0

def remove_repo(db: Database, owner: str, name: str) -> None:
    with db.session() as s:
        r = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one_or_none()
        if r is not None:
            s.delete(r)

def set_allowed_authors(db: Database, owner: str, name: str, authors: list[str]) -> None:
    with db.session() as s:
        r = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one_or_none()
        if r is None:
            raise KeyError(f"{owner}/{name} not registered")
        r.allowed_authors_json = json.dumps(normalize_authors(authors))