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
    runner.invoke(app, ["init"], input="")
    cfg = (tmp_path / "config.yaml").read_text()
    assert "auth:" in cfg
    assert "mode: pat" in cfg
    assert "default_provider: anthropic" in cfg