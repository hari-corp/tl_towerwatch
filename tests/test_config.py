from pathlib import Path

import pytest

from tl_towerwatch.config import load_settings


def test_settings_reads_data_dir_env_file(monkeypatch, tmp_path):
    """Regression for C2: .env must be read from <data_dir>/.env, not CWD.
    Simulates the Docker bind-mount case by writing TOWERWATCH_GITHUB_TOKEN
    to a tmp data_dir/.env and confirming load_settings() picks it up even
    though tmp_path is nowhere near CWD."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    env_file = tmp_path / ".env"
    env_file.write_text("TOWERWATCH_GITHUB_TOKEN=ghp_test\n")
    s = load_settings(tmp_path)
    assert s.github_token == "ghp_test"

def test_settings_oauth_keys_have_github_prefix(monkeypatch, tmp_path):
    """Regression for I5: OAuth env vars follow spec §10.3 naming."""
    monkeypatch.setenv("TOWERWATCH_GITHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN", "acc")
    monkeypatch.setenv("TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN", "ref")
    s = load_settings(tmp_path)
    assert s.github_oauth_client_id == "cid"
    assert s.github_oauth_client_secret == "csec"
    assert s.github_oauth_access_token == "acc"
    assert s.github_oauth_refresh_token == "ref"

def test_auth_mode_defaults_to_pat(tmp_path):
    s = load_settings(tmp_path)
    assert s.auth.mode == "pat"


def test_load_settings_no_args_reads_cwd_env(monkeypatch, tmp_path, fs_chdir):
    """Regression: `tl_towerwatch repo add` failed with
    "No GitHub credentials configured" right after a successful `init`
    because load_settings() skipped the CWD-relative ./data/.env when
    called with no arguments and no TOWERWATCH_DATA_DIR env var.

    After the fix, load_settings() with no args should default data_dir
    to ./data and load <./data>/.env into os.environ.
    """
    # Build a ./data/.env under tmp_path, mimicking init's output.
    data_dir = Path.cwd() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_cwd_test\n")
    # Strip any pre-existing values that would mask the regression.
    monkeypatch.delenv("TOWERWATCH_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("TOWERWATCH_DATA_DIR", raising=False)

    s = load_settings()
    assert s.github_token == "ghp_cwd_test"