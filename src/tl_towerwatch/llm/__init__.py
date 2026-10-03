from tl_towerwatch.config import Settings
from tl_towerwatch.llm.base import LLMProvider
from tl_towerwatch.llm.anthropic import AnthropicProvider
from tl_towerwatch.llm.openai import OpenAIProvider
from tl_towerwatch.llm.ollama import OllamaProvider

def get_provider(settings: Settings) -> LLMProvider:
    p = settings.llm.default_provider
    if p == "anthropic":
        return AnthropicProvider(settings.llm.anthropic.api_key, settings.llm.anthropic.model)
    if p == "openai":
        return OpenAIProvider(settings.llm.openai.api_key, settings.llm.openai.model)
    if p == "ollama":
        return OllamaProvider(settings.llm.ollama.base_url, settings.llm.ollama.model)
    raise ValueError(f"Unknown LLM provider: {p}")

__all__ = ["LLMProvider", "get_provider"]