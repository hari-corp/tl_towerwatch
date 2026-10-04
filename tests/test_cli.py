import os
from pathlib import Path

from typer.testing import CliRunner

from tl_towerwatch.cli import app

runner = CliRunner()


class _StubFile:
    patch = "+ x\n"


class _StubPR:
    number = 1
    title = "t"
    body = "b"
    author_login = "a"
    head_sha = "s1"


class _StubGH:
    def __init__(self, *a, **kw) -> None:
        pass
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def get_pr(self, owner, name, number):
        return _StubPR()
    def list_pr_files(self, owner, name, number):
        return [_StubFile()]

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


def test_auth_login_help():
    """v1.1 (Task 4): `tl_towerwatch auth login` must exist with --help."""
    r = runner.invoke(app, ["auth", "login", "--help"])
    assert r.exit_code == 0


def test_auth_login_without_creds_errors(tmp_path, monkeypatch):
    """`auth login` must exit non-zero with a clear error when OAuth
    client_id/secret are not configured."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / "config.yaml").touch()
    r = runner.invoke(app, ["auth", "login"])
    assert r.exit_code != 0
    combined = (r.stdout or "") + (getattr(r, "stderr", None) or "")
    assert "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID" in combined


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