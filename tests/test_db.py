from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
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