from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnthropicCfg(BaseModel):
    api_key: str = ""
    model: str = "claude-3-5-sonnet-latest"

class OpenAICfg(BaseModel):
    api_key: str = ""
    model: str = "gpt-4o"

class OllamaCfg(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "llama3.2"

class LLMCfg(BaseModel):
    default_provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    anthropic: AnthropicCfg = Field(default_factory=AnthropicCfg)
    openai: OpenAICfg = Field(default_factory=OpenAICfg)
    ollama: OllamaCfg = Field(default_factory=OllamaCfg)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOWERWATCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("./data")
    github_token: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_access_token: str = ""
    oauth_refresh_token: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    theme: Literal["dark", "light", "system"] = "dark"
    refresh_interval_seconds: int = 300

    llm: LLMCfg = Field(default_factory=LLMCfg)

    @property
    def db_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'tl_towerwatch.db').as_posix()}"

def load_settings(data_dir: Path | None = None) -> Settings:
    s = Settings()
    if data_dir is not None:
        s.data_dir = data_dir
        (data_dir / "config.yaml").touch()
    return s