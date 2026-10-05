from pathlib import Path

from tl_towerwatch.skills.registry import PROMPT_SLOTS, load_prompts, save_prompts
from tl_towerwatch.skills.prompts import render_review_prompt


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


def test_render_review_prompt_substitutes_placeholders():
    p = render_review_prompt(
        pr_metadata={"title": "t", "body": "b", "author": "x", "number": 1,
                     "repo": "o/n", "head_sha": "abc"},
        diff="+ line\n- old\n",
        mode="compare",
        previous_findings=[{"finding_key":"a:1:foo","severity":"high",
                            "file_path":"a.py","line":1,"description":"foo",
                            "status":"pending"}],
        template="Title: {title}\nMode: {mode_intro}\nDiff:\n{diff}\nPrev: {findings_list}",
    )
    assert "t" in p
    assert "foo" in p
    assert "compare" in p.lower() or "previous" in p.lower()