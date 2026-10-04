from __future__ import annotations
import shutil
import subprocess

from tl_towerwatch.agents.base import AgentEvent, AgentRunner, ReviewResult
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
                   previous_findings, timeout_seconds=300, on_event=None) -> ReviewResult:
        prompt = render_review_prompt(
            pr_metadata=pr_metadata, mode=mode,
            previous_findings=previous_findings, skills=skills,
            diff=pr_diff, template=prompt_template,
        )
        flags = [s.cli_flag for s in skills if isinstance(s, Skill) and s.cli_flag]
        if on_event:
            on_event(AgentEvent(kind="stderr", data="starting"))
        try:
            proc = subprocess.Popen(
                [self._binary, "--print", *flags],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            out, err = proc.communicate(input=prompt, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            if on_event:
                on_event(AgentEvent(kind="error", data="timeout"))
            return ReviewResult(markdown="", findings=[], error="timeout")
        if proc.returncode != 0:
            if on_event:
                on_event(AgentEvent(kind="error", data=err[:500]))
            return ReviewResult(markdown=out, findings=[],
                                error=f"minimax exited {proc.returncode}: {err[:500]}")
        if on_event:
            on_event(AgentEvent(kind="stdout", data=out))
            on_event(AgentEvent(kind="sentinel", data="TLTW:DONE"))
        return ReviewResult(markdown=out, findings=_parse(out))