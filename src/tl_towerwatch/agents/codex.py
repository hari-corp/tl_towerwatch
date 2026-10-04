from __future__ import annotations
import json
import shutil
import subprocess

from tl_towerwatch.agents.base import AgentEvent, AgentRunner, ReviewResult, Finding
from tl_towerwatch.skills.prompts import render_review_prompt
from tl_towerwatch.skills.registry import Skill


def _parse(stdout: str) -> list[Finding]:
    out: list[Finding] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "finding":
            f = obj["data"]
            out.append(Finding(
                f.get("severity", "medium"),
                f.get("file_path", ""),
                int(f.get("line") or 0),
                f.get("description", ""),
                f.get("finding_key", f"{f.get('file_path', '')}:{f.get('line', '')}"),
            ))
    return out


class CodexRunner:
    name = "codex"

    def __init__(self, binary: str = "codex") -> None:
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
                [self._binary, "exec", "--quiet", "--json", *flags],
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
                                error=f"codex exited {proc.returncode}: {err[:500]}")
        if on_event:
            on_event(AgentEvent(kind="stdout", data=out))
            on_event(AgentEvent(kind="sentinel", data="TLTW:DONE"))
        return ReviewResult(markdown=out, findings=_parse(out))