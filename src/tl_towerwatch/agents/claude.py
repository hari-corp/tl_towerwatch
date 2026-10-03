from __future__ import annotations
import json
import re
import shutil
import subprocess

from tl_towerwatch.agents.base import AgentRunner, ReviewResult, Finding
from tl_towerwatch.skills.prompts import render_review_prompt
from tl_towerwatch.skills.registry import Skill

FINDINGS_RE = re.compile(r"<!-- TLTW:FINDINGS -->\s*(\[.*?\])\s*<!-- TLTW:DONE -->", re.S)


def _parse(markdown: str) -> list[Finding]:
    m = FINDINGS_RE.search(markdown)
    if not m:
        return []
    raw = json.loads(m.group(1))
    out: list[Finding] = []
    for f in raw:
        out.append(Finding(
            severity=f.get("severity", "medium"),
            file_path=f.get("file_path", ""),
            line=int(f.get("line") or 0),
            description=f.get("description", ""),
            finding_key=f.get("finding_key", f"{f.get('file_path', '')}:{f.get('line', '')}"),
        ))
    return out


class ClaudeRunner:
    name = "claude"

    def __init__(self, binary: str = "claude") -> None:
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
                [self._binary, "--print", "--dangerously-skip-permissions", *flags],
                input=prompt, capture_output=True, text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ReviewResult(markdown="", findings=[], error="timeout")
        if proc.returncode != 0:
            return ReviewResult(markdown=proc.stdout, findings=[],
                                error=f"claude exited {proc.returncode}: {proc.stderr[:500]}")
        return ReviewResult(markdown=proc.stdout, findings=_parse(proc.stdout))