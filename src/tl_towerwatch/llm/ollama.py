from __future__ import annotations
import httpx
from tl_towerwatch.llm.base import LLMProvider

PROMPT_TEMPLATE = (
    "Summarize this GitHub PR in 2-3 concise sentences.\n\n"
    "Title: {title}\n\nDescription: {body}\n\nDiff:\n{diff}\n"
)

class OllamaProvider:
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.name = "ollama"

    def summarize(self, *, title, body, diff, metadata) -> str:
        r = httpx.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt":
                  PROMPT_TEMPLATE.format(title=title, body=body or "",
                                         diff=diff[:12000]),
                  "stream": False},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()["response"].strip()

    def health_check(self) -> bool:
        try:
            r = httpx.get(f"{self._base_url}/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False