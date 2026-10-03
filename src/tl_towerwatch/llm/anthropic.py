from __future__ import annotations
from tl_towerwatch.llm.base import LLMProvider

PROMPT_TEMPLATE = (
    "Summarize this GitHub PR in 2-3 concise sentences explaining what it does "
    "and why.\n\nTitle: {title}\n\nDescription: {body}\n\nDiff:\n{diff}\n"
)

class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self.name = "anthropic"

    def summarize(self, *, title, body, diff, metadata) -> str:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError("anthropic SDK not installed") from e
        client = Anthropic(api_key=self._api_key)
        msg = client.messages.create(
            model=self._model,
            max_tokens=400,
            messages=[{"role": "user",
                       "content": PROMPT_TEMPLATE.format(title=title,
                                                          body=body or "",
                                                          diff=diff[:12000])}],
        )
        return msg.content[0].text.strip()

    def health_check(self) -> bool:
        return bool(self._api_key)