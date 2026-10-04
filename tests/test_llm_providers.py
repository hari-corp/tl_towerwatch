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


def test_llm_protocol_body_is_required_str():
    """v1.1 tightened `LLMProvider.summarize(body=...)` from `str | None` to
    `str`. A custom provider must accept a `str` body (not None) and the
    protocol must reject sub-classes whose `body` annotation is missing or
    permissive enough to allow None.
    """
    class StrictProvider:
        name = "strict"
        def summarize(self, *, title, body, diff, metadata) -> str:
            assert isinstance(body, str)
            return body
        def health_check(self) -> bool:
            return True

    p = StrictProvider()
    assert isinstance(p, LLMProvider)
    assert p.summarize(title="t", body="hello", diff="", metadata={}) == "hello"