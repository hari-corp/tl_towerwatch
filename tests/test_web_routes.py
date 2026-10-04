from fastapi.testclient import TestClient
from tl_towerwatch.web import create_app

def test_index_renders():
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "tl_towerwatch" in r.text

def test_theme_toggle_sets_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/theme", data={"theme": "light"}, follow_redirects=False)
        assert r.status_code == 303
        assert "tl_towerwatch_theme" in r.cookies
        assert c.cookies["tl_towerwatch_theme"] == "light"

def test_theme_persists_to_config_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/theme", data={"theme": "light"}, follow_redirects=False)
        assert r.status_code == 303  # now redirects
        cfg = (tmp_path / "config.yaml").read_text()
        assert "theme:" in cfg
        assert "light" in cfg

def test_theme_validates_input(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/theme", data={"theme": "rainbow"})
        assert r.status_code == 400

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

def test_repos_route_lists_and_adds(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/repos")
        assert r.status_code == 200
        # POST without network will fail validation; just check the route exists.
        r = c.post("/repos/add", data={"owner_name": "x/y"})
        assert r.status_code in (400, 500)  # network error expected

def test_pr_detail_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/pr/o/n/1")
        assert r.status_code == 200
        assert "PR" in r.text

def test_settings_route_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/settings")
        assert r.status_code == 200
        assert "LLM" in r.text or "Auth" in r.text

def test_settings_auth_save_persists_pat(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/settings/auth/save",
                   data={"github_token": "ghp_FAKE",
                         "github_oauth_client_id": "",
                         "github_oauth_client_secret": ""},
                   follow_redirects=False)
        assert r.status_code == 303
    env_text = (tmp_path / ".env").read_text()
    assert "TOWERWATCH_GITHUB_TOKEN=ghp_FAKE" in env_text

def test_settings_auth_save_does_not_wipe_oauth_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID=cid_real\n"
        "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET=csec_real\n"
    )
    from tl_towerwatch.web import create_app
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/settings/auth/save",
                   data={"github_token": "ghp_new",
                         "github_oauth_client_id": "",
                         "github_oauth_client_secret": ""},
                   follow_redirects=False)
        assert r.status_code == 303
    env_text = env_path.read_text()
    assert "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID=cid_real" in env_text
    assert "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET=csec_real" in env_text
    assert "TOWERWATCH_GITHUB_TOKEN=ghp_new" in env_text

def test_settings_llm_save_does_not_wipe_auth_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text("TOWERWATCH_GITHUB_TOKEN=ghp_EXISTING\n")
    from tl_towerwatch.web import create_app
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/settings/llm/save",
                   data={"provider": "anthropic",
                         "anthropic_api_key": "sk-ant-FAKE",
                         "openai_api_key": "",
                         "ollama_base_url": ""},
                   follow_redirects=False)
        assert r.status_code == 303
    env_text = env_path.read_text()
    assert "TOWERWATCH_GITHUB_TOKEN=ghp_EXISTING" in env_text
    assert "TOWERWATCH_LLM_PROVIDER=anthropic" in env_text
    assert "TOWERWATCH_ANTHROPIC_API_KEY=sk-ant-FAKE" in env_text