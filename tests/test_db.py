from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings, _ensure_columns
from tl_towerwatch.db.models import Repo, User

def test_db_create_and_insert(tmp_path: Path):
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    with db.session() as s:
        r = Repo(owner="o", name="n", added_at="2026-01-01T00:00:00Z")
        s.add(r)
    with db.session() as s:
        assert s.query(Repo).count() == 1


def test_user_table_persists_avatar_and_display_name(tmp_path: Path):
    """User rows carry optional avatar_url/display_name fields populated by
    _upsert_user on sync. Confirm both columns survive a commit and reload.
    """
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    with db.session() as s:
        s.add(User(login="dimh", avatar_url="https://x/y.png", display_name="David M"))
    with db.session() as s:
        u = s.get(User, "dimh")
        assert u is not None
        assert u.avatar_url == "https://x/y.png"
        assert u.display_name == "David M"


def test_ensure_columns_adds_missing_columns(tmp_path: Path):
    """Regression: a v1.2.0 install opening a v1.1.0 SQLite file used to
    crash on the dashboard with `no such column: pull_requests.additions`
    because ``Base.metadata.create_all`` only creates new tables and never
    adds columns to existing ones. _ensure_columns() introspects the live
    schema and runs ``ALTER TABLE ... ADD COLUMN ... DEFAULT ...`` for any
    declared column that's missing.

    Simulate the broken state by creating the database with the v1.1
    schema (no additions/deletions/changed_files/commits_count on
    pull_requests), then calling create_all() again — which must heal
    the schema.
    """
    from sqlalchemy import text

    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    # Bootstrap the v1.1 schema by removing the new fields, then create_all
    # to install the pre-v1.2 shape (no additions/deletions/changed_files/
    # commits_count).
    from tl_towerwatch.db.models import Base
    v11_columns = [
        c for c in Base.metadata.tables["pull_requests"].columns
        if c.name not in {"additions", "deletions", "changed_files", "commits_count"}
    ]
    # Create a stripped copy of the pull_requests table for the v1.1 shape.
    from sqlalchemy import Column, Integer, MetaData, String, Table
    from sqlalchemy.orm import sessionmaker
    meta = MetaData()
    Table("pull_requests", meta,
          Column("id", Integer, primary_key=True),
          Column("repo_id", Integer),
          Column("number", Integer),
          Column("title", String),
          Column("state", String),
          Column("draft", Integer, default=0),
          Column("head_sha", String),
          Column("base_ref", String),
          Column("html_url", String),
          Column("created_at", String),
          Column("updated_at", String),
          Column("cached_at", String),
          Column("body", String),
          Column("author_login", String))
    with db.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS pull_requests"))
    meta.create_all(db.engine)
    # Sanity check: PRAGMA table_info should NOT include additions yet.
    insp_before = [c["name"] for c in _ensure_columns.__globals__["inspect"](db.engine).get_columns("pull_requests")]
    assert "additions" not in insp_before

    # Now call create_all() which should run _ensure_columns and add the
    # missing columns.
    db.create_all()
    insp_after = [c["name"] for c in _ensure_columns.__globals__["inspect"](db.engine).get_columns("pull_requests")]
    for new_col in ("additions", "deletions", "changed_files", "commits_count"):
        assert new_col in insp_after, f"{new_col} should be present after create_all()"

    # Idempotency: calling _ensure_columns again must not raise (existing
    # columns are skipped; SQLite raises on duplicate ALTER which we catch).
    _ensure_columns(db.engine)


def test_ensure_columns_is_idempotent(tmp_path: Path):
    """Calling create_all() multiple times on a fresh DB must not raise."""
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    db.create_all()  # second call must be a no-op
    db.create_all()