import json
import os
import stat
import textwrap
from pathlib import Path

import pytest

from tl_towerwatch.agents.claude import ClaudeRunner


def test_claude_runner_parses_findings(fake_claude):
    r = ClaudeRunner()
    res = r.run_review(
        pr_diff="+ a\n",
        pr_metadata={"title": "t", "body": None, "author": "x",
                     "number": 1, "repo": "o/n", "head_sha": "abc"},
        skills=[],
        prompt_template="{diff}",
        mode="fresh",
        previous_findings=[],
        timeout_seconds=30,
    )
    assert res.findings[0].file_path == "a.py"
    assert res.error is None


def test_claude_runner_emits_events(fake_claude):
    r = ClaudeRunner()
    events = []
    res = r.run_review(
        pr_diff="+ a\n",
        pr_metadata={"title": "t", "body": None, "author": "x",
                     "number": 1, "repo": "o/n", "head_sha": "abc"},
        skills=[],
        prompt_template="{diff}",
        mode="fresh",
        previous_findings=[],
        timeout_seconds=30,
        on_event=lambda e: events.append(e),
    )
    kinds = [e.kind for e in events]
    assert "stdout" in kinds
    assert "sentinel" in kinds
    assert res.findings and res.findings[0].file_path == "a.py"