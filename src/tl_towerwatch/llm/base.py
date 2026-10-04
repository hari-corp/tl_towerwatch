from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMProvider(Protocol):
    name: str
    def summarize(self, *, title: str, body: str,
                  diff: str, metadata: dict) -> str: ...
    def health_check(self) -> bool: ...