from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

@dataclass
class Finding:
    severity: str
    file_path: str
    line: int
    description: str
    finding_key: str

@dataclass
class ReviewResult:
    markdown: str
    findings: list[Finding]
    error: str | None = None

@runtime_checkable
class AgentRunner(Protocol):
    name: str
    def run_review(self, *, pr_diff: str, pr_metadata: dict,
                   skills: list, prompt_template: str,
                   mode: str, previous_findings: list[dict],
                   timeout_seconds: int = 300) -> ReviewResult: ...