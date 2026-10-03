from pathlib import Path

from tl_towerwatch.config import load_settings


def test_load_settings_defaults(tmp_path: Path):
    s = load_settings(tmp_path)
    assert s.llm.default_provider == "anthropic"
    assert s.refresh_interval_seconds == 300
    assert s.theme == "dark"
    assert (tmp_path / "tl_towerwatch.db").as_posix() in s.db_url

def test_load_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TOWERWATCH_GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("TOWERWATCH_ANTHROPIC_API_KEY", "sk-test")
    s = load_settings(tmp_path)
    assert s.github_token == "ghp_test"
    assert s.anthropic_api_key == "sk-test"

def test_settings_mirrors_llm_keys(monkeypatch, tmp_path):
    """Regression for C1: the flat anthropic_api_key env var must be visible
    to the LLM provider via settings.llm.anthropic.api_key, otherwise every
    summarize() call after a user-configured key silently fails."""
    monkeypatch.setenv("TOWERWATCH_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("TOWERWATCH_OPENAI_API_KEY", "sk-openai")
    s = load_settings(tmp_path)
    assert s.llm.anthropic.api_key == "sk-test"
    assert s.llm.openai.api_key == "sk-openai"
    # Ollama only mirrors when non-default; bundled default must be preserved
    # unless the user explicitly changed it.
    assert s.llm.ollama.base_url == "http://localhost:11434"

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