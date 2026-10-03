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