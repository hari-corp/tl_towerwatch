from tl_towerwatch.config import Settings, LLMCfg, AnthropicCfg
from tl_towerwatch.llm.base import LLMProvider
from tl_towerwatch.llm import get_provider


def test_get_provider_anthropic(monkeypatch):
    monkeypatch.setenv("TOWERWATCH_ANTHROPIC_API_KEY", "sk-test")
    s = Settings(llm=LLMCfg(default_provider="anthropic",
                             anthropic=AnthropicCfg(api_key="sk-test")))
    p = get_provider(s)
    assert isinstance(p, LLMProvider)
    assert p.name == "anthropic"
    assert p.health_check() is True