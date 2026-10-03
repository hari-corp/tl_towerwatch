from fastapi.testclient import TestClient
from tl_towerwatch.web import create_app

def test_index_renders():
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "tl_towerwatch" in r.text

def test_theme_toggle_sets_cookie():
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/theme", data={"theme": "light"})
        assert r.status_code == 200
        assert "tl_towerwatch_theme" in r.cookies
        assert c.cookies["tl_towerwatch_theme"] == "light"

def test_dashboard_renders_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    app = create_app()
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "PRs" in r.text