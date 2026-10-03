from tl_towerwatch.skills.registry import default_registry, Skill
from tl_towerwatch.skills.prompts import render_review_prompt

def test_default_registry_has_superpowers_and_ponytail():
    r = default_registry()
    names = {s.name for s in r}
    assert "superpowers" in names
    assert "ponytail" in names

def test_render_review_prompt_mentions_skills():
    p = render_review_prompt(
        pr_metadata={"title": "t", "body": "b", "author": "x", "number": 1,
                     "repo": "o/n", "head_sha": "abc"},
        diff="+ line\n- old\n",
        mode="compare",
        previous_findings=[{"finding_key":"a:1:foo","severity":"high",
                            "file_path":"a.py","line":1,"description":"foo",
                            "status":"pending"}],
        skills=[Skill(name="superpowers", description="d", cli_flag="--x", enabled=True)],
        template="Title: {title}\nMode: {mode_intro}\nDiff:\n{diff}\nSkills: {skills_list}\nPrev: {findings_list}",
    )
    assert "superpowers" in p
    assert "foo" in p
    assert "compare" in p.lower() or "previous" in p.lower()