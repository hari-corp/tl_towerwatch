import json
from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.services.repos import (
    add_repo, list_repos, set_repo_enabled, set_allowed_authors, normalize_authors,
)

def _setup(tmp_path: Path):
    s = load_settings(tmp_path)
    db = engine_from_settings(s)
    db.create_all()
    return db

def test_add_and_list_repo(tmp_path: Path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    assert len(list_repos(db)) == 1

def test_set_allowed_authors_normalizes(tmp_path: Path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    set_allowed_authors(db, "o", "n", ["Marta.G", "luis.f", "marta.g"])
    r = list_repos(db)[0]
    assert json.loads(r.allowed_authors_json) == ["luis.f", "marta.g"]

def test_normalize_authors_dedupes():
    assert normalize_authors(["Marta.G", "marta.g", " luis.f "]) == ["luis.f", "marta.g"]