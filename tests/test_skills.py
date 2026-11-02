from pathlib import Path

from tl_towerwatch.skills.registry import PROMPT_SLOTS, load_prompts, save_prompts


def test_load_prompts_defaults_when_no_config(tmp_path: Path):
    """v1.3.0 (revised): prompts are a single global set. Without a
    config.yaml, the bundled prompts ship."""
    p = load_prompts(tmp_path)
    assert set(p.keys()) == set(PROMPT_SLOTS)
    assert all(isinstance(p[s], str) and p[s] for s in PROMPT_SLOTS)


def test_save_prompts_round_trip(tmp_path: Path):
    """v1.3.0 (revised): save_prompts persists the 3 slots and
    load_prompts returns them unchanged.
    """
    out = {
        "review": "REV {title}",
        "post_review": "POST {findings}",
        "check_resolved": "CHECK {findings}",
    }
    save_prompts(tmp_path, out)
    loaded = load_prompts(tmp_path)
    assert loaded == out


def test_save_prompts_preserves_other_blocks(tmp_path: Path):
    """v1.3.0 (revised): save_prompts only replaces the ``prompts``
    block; theme, auth, refresh interval are preserved.
    """
    from tl_towerwatch.config_io import load_config_yaml
    cfg = tmp_path / "config.yaml"
    cfg.write_text("theme: dark\nauth:\n  mode: pat\n")
    save_prompts(tmp_path, {
        "review": "r1", "post_review": "p1", "check_resolved": "c1",
    })
    data = load_config_yaml(cfg)
    assert data["theme"] == "dark"
    assert data["auth"] == {"mode": "pat"}
    assert data["prompts"]["review"] == "r1"