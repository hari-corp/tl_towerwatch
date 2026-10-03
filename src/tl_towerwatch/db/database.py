from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tl_towerwatch.config import Settings
from tl_towerwatch.db.models import Base


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

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