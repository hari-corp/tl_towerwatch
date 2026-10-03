from __future__ import annotations
import shutil
import subprocess

from tl_towerwatch.agents.base import AgentRunner, ReviewResult
from tl_towerwatch.agents.claude import _parse  # same marker convention
from tl_towerwatch.skills.prompts import render_review_prompt
from tl_towerwatch.skills.registry import Skill


class MiniMaxCodeRunner:
    name = "minimax"

    def __init__(self, binary: str = "minimax") -> None:
        self._binary = binary
        if not shutil.which(self._binary):
            raise RuntimeError(
                f"{self._binary} CLI not found in PATH; install it or pick another runner"
            )

    def run_review(self, *, pr_diff, pr_metadata, skills, prompt_template, mode,
                   previous_findings, timeout_seconds=300) -> ReviewResult:
        prompt = render_review_prompt(
            pr_metadata=pr_metadata, mode=mode,
            previous_findings=previous_findings, skills=skills,
            diff=pr_diff, template=prompt_template,
        )
        flags = [s.cli_flag for s in skills if isinstance(s, Skill) and s.cli_flag]
        try:
            proc = subprocess.run(
                [self._binary, "--print", *flags],
                input=prompt, capture_output=True, text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ReviewResult(markdown="", findings=[], error="timeout")
        if proc.returncode != 0:
            return ReviewResult(markdown=proc.stdout, findings=[],
                                error=f"minimax exited {proc.returncode}")
        return ReviewResult(markdown=proc.stdout, findings=_parse(proc.stdout))