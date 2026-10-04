from pathlib import Path

from typer.testing import CliRunner

from tl_towerwatch.cli import app

runner = CliRunner()

def test_help_runs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.stdout

def test_repo_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / "config.yaml").touch()
    result = runner.invoke(app, ["repo", "list"])
    assert result.exit_code == 0
    assert "no repos" in result.stdout.lower() or "0" in result.stdout

def test_serve_help():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "port" in result.stdout

def test_review_help():
    """The `review` CLI command must exist with the spec §9 options."""
    result = runner.invoke(app, ["review", "--help"])
    assert result.exit_code == 0
    assert "--agent" in result.stdout
    assert "--skills" in result.stdout
    assert "--mode" in result.stdout
    assert "--watch" in result.stdout

def test_repo_add_author_help():
    r = runner.invoke(app, ["repo", "add-author", "--help"])
    assert r.exit_code == 0
    assert "login" in r.stdout

def test_repo_remove_author_help():
    r = runner.invoke(app, ["repo", "remove-author", "--help"])
    assert r.exit_code == 0
    assert "login" in r.stdout

def test_repo_clear_authors_help():
    r = runner.invoke(app, ["repo", "clear-authors", "--help"])
    assert r.exit_code == 0

def test_refresh_help():
    r = runner.invoke(app, ["refresh", "--help"])
    assert r.exit_code == 0
    assert "--repo" in r.stdout

def test_status_help():
    r = runner.invoke(app, ["status", "--help"])
    assert r.exit_code == 0

def test_config_help():
    r = runner.invoke(app, ["config", "--help"])
    assert r.exit_code == 0

def test_auth_refresh_help():
    r = runner.invoke(app, ["auth", "refresh", "--help"])
    assert r.exit_code == 0


def test_init_pat_path_writes_config(tmp_path: Path, monkeypatch):
    """v1.1 init wizard (Task 3): PAT path must write config.yaml with
    auth.mode=pat and the chosen LLM provider + model."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    responses = iter(["pat", "ghp_test", "anthropic", "claude-3-5-sonnet-latest"])
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: next(responses))
    # Skip any OAuth sub-flow confirm; init returns after writing config.
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: False)
    # Avoid hitting GitHub in the token validation path.
    monkeypatch.setattr(
        "tl_towerwatch.auth.github.resolve_token",
        lambda settings: "ghp_test",
    )
    r = runner.invoke(app, ["init"], input="")
    assert r.exit_code == 0, f"init failed: {r.stdout!r} {r.exception!r}"
    cfg = (tmp_path / "config.yaml").read_text()
    assert "auth:" in cfg
    assert "mode: pat" in cfg
    assert "default_provider: anthropic" in cfg
    # Fix round 1: also assert the .env write happened and contains the token,
    # which exercises _env_lines_for (the verifier-flagged defect).
    env_file = tmp_path / ".env"
    assert env_file.exists()
    env_text = env_file.read_text()
    assert "TOWERWATCH_GITHUB_TOKEN=ghp_test" in env_text


def test_init_oauth_path_persists_oauth_fields(tmp_path: Path, monkeypatch):
    """v1.1 init wizard (Task 3, fix round 1): the OAuth branch must
    persist client_id and client_secret into .env using the
    TOWERWATCH_GITHUB_OAUTH_* env-var names (matching v1.0 fix I5 rename).
    """
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    responses = iter(
        ["oauth", "cid", "csec", "anthropic", "claude-3-5-sonnet-latest"]
    )
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: next(responses))
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: False)
    r = runner.invoke(app, ["init"], input="")
    assert r.exit_code == 0, f"init failed: {r.stdout!r} {r.exception!r}"
    cfg = (tmp_path / "config.yaml").read_text()
    assert "auth:" in cfg
    assert "mode: oauth" in cfg
    env_file = tmp_path / ".env"
    assert env_file.exists()
    env_text = env_file.read_text()
    assert "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID=cid" in env_text
    assert "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET=csec" in env_text