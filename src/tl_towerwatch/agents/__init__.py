from tl_towerwatch.config import Settings
from tl_towerwatch.agents.base import AgentRunner
from tl_towerwatch.agents.claude import ClaudeRunner
from tl_towerwatch.agents.codex import CodexRunner
from tl_towerwatch.agents.minimax_code import MiniMaxCodeRunner
from tl_towerwatch.agents.ollama import OllamaAgentRunner


def get_runner(name: str, settings: Settings) -> AgentRunner:
    if name == "claude":
        return ClaudeRunner()
    if name == "codex":
        return CodexRunner()
    if name == "minimax":
        return MiniMaxCodeRunner()
    if name == "ollama":
        return OllamaAgentRunner(
            settings.llm.ollama.base_url,
            settings.llm.ollama.model,
        )
    raise ValueError(f"unknown runner: {name}")


__all__ = ["AgentRunner", "get_runner"]