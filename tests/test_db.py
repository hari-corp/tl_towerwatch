from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import Repo

def test_db_create_and_insert(tmp_path: Path):
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    with db.session() as s:
        r = Repo(owner="o", name="n", added_at="2026-01-01T00:00:00Z")
        s.add(r)
    with db.session() as s:
        assert s.query(Repo).count() == 1