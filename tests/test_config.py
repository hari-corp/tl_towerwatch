from pathlib import Path
from tl_towerwatch.config import Settings, load_settings

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