from __future__ import annotations
from tl_towerwatch.llm.base import LLMProvider

PROMPT_TEMPLATE = (
    "Summarize this GitHub PR in 2-3 concise sentences.\n\n"
    "Title: {title}\n\nDescription: {body}\n\nDiff:\n{diff}\n"
)

class OpenAIProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self.name = "openai"

    def summarize(self, *, title, body, diff, metadata) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("openai SDK not installed") from e
        client = OpenAI(api_key=self._api_key)
        r = client.chat.completions.create(
            model=self._model,
            max_tokens=400,
            messages=[{"role": "user", "content":
                       PROMPT_TEMPLATE.format(title=title, body=body or "",
                                              diff=diff[:12000])}],
        )
        return r.choices[0].message.content.strip()

    def health_check(self) -> bool:
        return bool(self._api_key)