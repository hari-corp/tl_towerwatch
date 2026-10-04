from __future__ import annotations
import httpx

from tl_towerwatch.agents.base import AgentEvent, AgentRunner, ReviewResult
from tl_towerwatch.agents.claude import _parse
from tl_towerwatch.skills.prompts import render_review_prompt
from tl_towerwatch.skills.registry import Skill


class OllamaAgentRunner:
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def run_review(self, *, pr_diff, pr_metadata, skills, prompt_template, mode,
                   previous_findings, timeout_seconds=300, on_event=None) -> ReviewResult:
        prompt = render_review_prompt(
            pr_metadata=pr_metadata, mode=mode,
            previous_findings=previous_findings, skills=skills,
            diff=pr_diff, template=prompt_template,
        )
        if on_event:
            on_event(AgentEvent(kind="stderr", data="starting"))
        try:
            r = httpx.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
                timeout=timeout_seconds,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            if on_event:
                on_event(AgentEvent(kind="error", data=str(e)))
            return ReviewResult(markdown="", findings=[], error=str(e))
        md = r.json()["response"]
        if on_event:
            on_event(AgentEvent(kind="stdout", data=md))
            on_event(AgentEvent(kind="sentinel", data="TLTW:DONE"))
        return ReviewResult(markdown=md, findings=_parse(md))