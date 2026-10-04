from pathlib import Path

from tl_towerwatch.config import AuthCfg, Settings
from tl_towerwatch.config_io import load_config_yaml, merge_into_settings, save_config_yaml


def test_save_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "config.yaml"
    save_config_yaml(p, {"auth": {"mode": "oauth"}, "theme": "light"})
    data = load_config_yaml(p)
    assert data["auth"]["mode"] == "oauth"
    assert data["theme"] == "light"


def test_load_missing_returns_empty(tmp_path: Path):
    assert load_config_yaml(tmp_path / "missing.yaml") == {}


def test_merge_into_settings_updates_auth_mode(tmp_path: Path):
    s = Settings(auth=AuthCfg(mode="pat"))
    merge_into_settings(s, {"auth": {"mode": "oauth"}})
    assert s.auth.mode == "oauth"