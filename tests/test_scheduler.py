"""Regression tests for the background refresh scheduler (Task 22)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import Repo, now_iso
from tl_towerwatch.scheduler import RefreshScheduler


def _setup_db(tmp_path: Path):
    s = load_settings(tmp_path)
    db = engine_from_settings(s)
    db.create_all()
    return s, db


class _StubGH:
    """Stand-in for GitHubClient; never used because sync_repo is patched to raise."""


class _StubLLM:
    name = "stub"


def test_scheduler_persists_last_fetch_error_on_sync_failure(env, tmp_path):
    """Regression: when ``sync_repo`` raises, the scheduler must persist
    ``last_fetch_status='error'`` and the exception message on the Repo row.

    The original implementation re-loaded the repo via
    ``next(r for r in list_repos(db) if r.id == repo.id)``, which returned a
    detached instance from a *different* session; field assignments on it were
    dropped on commit and the error was silently lost. The fix re-loads the
    row with ``s.get(Repo, repo.id)`` inside the same session as the mutation.
    """
    settings, db = _setup_db(tmp_path)
    # Seed an enabled repo with a small refresh interval so the tick fires.
    with db.session() as s:
        s.add(Repo(
            owner="o", name="n", enabled=1, is_self=0,
            refresh_interval_seconds=1, scope="mine_and_review",
            allowed_authors_json=json.dumps([]),
            added_at=now_iso(),
        ))
        s.flush()
        repo_id = s.execute(
            __import__("sqlalchemy").select(Repo).where(
                Repo.owner == "o", Repo.name == "n"
            )
        ).scalar_one().id

    sched = RefreshScheduler(settings)
    with patch(
        "tl_towerwatch.scheduler.sync_repo",
        side_effect=RuntimeError("boom"),
    ):
        sched._tick(db, _StubGH(), last_run={})

    with db.session() as s:
        repo = s.get(Repo, repo_id)
        assert repo is not None
        assert repo.last_fetch_status == "error"
        assert repo.last_fetch_error is not None
        assert "boom" in repo.last_fetch_error