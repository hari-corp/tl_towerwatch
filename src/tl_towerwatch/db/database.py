from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tl_towerwatch.config import Settings
from tl_towerwatch.db.models import Base


def _column_type_sql(column) -> str:
    """Render a SQLAlchemy column type as a SQLite-compatible type name.

    Used by ``_ensure_columns`` to emit ``ALTER TABLE ... ADD COLUMN name TYPE``
    so SQLite can re-parse the statement. We map the Python types the model
    uses today rather than relying on a generic visitor — the surface is small
    and stable (Integer, String, Text, Boolean, Float, DateTime as ISO TEXT).
    """
    py_type = getattr(column.type, "python_type", None)
    if py_type is int:
        return "INTEGER"
    if py_type is float:
        return "REAL"
    if py_type is bool:
        return "INTEGER"
    if py_type is str:
        return "TEXT"
    return "TEXT"


def _column_default_for(column) -> object:
    """Pick a safe DEFAULT literal for ALTER TABLE ADD COLUMN.

    SQLAlchemy's ``Column.default`` only fires at INSERT time, not on the
    server. ALTER TABLE ADD COLUMN needs an inline DEFAULT so existing rows
    get a value; without one, the column would be NULL which breaks NOT
    NULL constraints and queries that expect integers."""
    py_type = getattr(column.type, "python_type", None)
    if py_type is int:
        return 0
    if py_type is float:
        return 0.0
    if py_type is bool:
        return 0
    if py_type is str:
        return ""
    return ""


def _ensure_columns(engine: Engine) -> None:
    """Add missing columns to existing SQLite tables.

    ``Base.metadata.create_all`` only creates new tables; it never adds
    columns to tables that already exist from a previous install. Without
    this step, any v1.2.0+ field (e.g. ``pull_requests.additions``) breaks
    the dashboard query with ``OperationalError: no such column``.

    We introspect the live schema with ``PRAGMA table_info`` (via the SQLAlchemy
    inspector) and run ``ALTER TABLE ... ADD COLUMN ... DEFAULT ...`` for
    each declared column that's missing. The DEFAULT is materialised on the
    existing rows so NOT NULL + INTEGER columns work without violating the
    constraint.

    Safe to run on every startup: existing columns are skipped, new columns
    are added idempotently (SQLite raises if the column already exists, we
    catch that).
    """
    insp = inspect(engine)
    for table_name, table in Base.metadata.tables.items():
        if not insp.has_table(table_name):
            continue
        existing = {c["name"] for c in insp.get_columns(table_name)}
        for column in table.columns:
            if column.name in existing:
                continue
            default = _column_default_for(column)
            sql_type = _column_type_sql(column)
            # SQLite ALTER TABLE ADD COLUMN does not support NOT NULL on
            # existing rows unless DEFAULT is supplied; the declared
            # nullable/primary_key flags from SQLAlchemy don't translate
            # to a safe inline clause here, so we just emit the
            # column-name + DEFAULT and let SQLite relax the constraint
            # (the CREATE TABLE did the same for new installs).
            try:
                with engine.begin() as conn:
                    # SQLite's ALTER TABLE parser does not accept bound
                    # parameters in the DEFAULT clause — it requires a
                    # literal. Use SQL composition (we control the type
                    # string and the column name, both sourced from the
                    # model) rather than a parameter binding.
                    literal = (
                        repr(int(default)) if isinstance(default, (int, float)) and not isinstance(default, bool)
                        else repr(default) if isinstance(default, str)
                        else "0"
                    )
                    conn.execute(text(
                        f"ALTER TABLE {table_name} ADD COLUMN "
                        f"{column.name} {sql_type} DEFAULT {literal}"
                    ))
            except Exception:
                # SQLite raises "duplicate column" if two callers race;
                # surface as best-effort and let the next call succeed.
                pass


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        # Catch up any pre-existing tables to the latest model so old
        # installs don't 500 on `no such column: <new_field>`.
        _ensure_columns(self.engine)

    @contextmanager
    def session(self) -> Session:
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()


def engine_from_settings(settings: Settings) -> Database:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        settings.db_url,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return Database(engine)