from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
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

class AuthCfg(BaseModel):
    mode: Literal["pat", "oauth"] = "pat"

class Settings(BaseSettings):
    # env_file is intentionally omitted: .env must be loaded relative to the
    # configured data_dir (see load_settings), not the current working
    # directory. Without this override, pydantic-settings silently swallows
    # the user's bind-mounted /data/.env in Docker (CWD is /app).
    model_config = SettingsConfigDict(
        env_prefix="TOWERWATCH_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("./data")
    github_token: str = ""
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_access_token: str = ""
    github_oauth_refresh_token: str = ""
    host_alias: str = "localhost"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    theme: Literal["dark", "light", "system"] = "dark"
    refresh_interval_seconds: int = 300
    # v1.1 (Task 12): cap the diff handed to the LLM for PR summarisation so
    # a single 5,000-file PR can't blow the model's context window. The old
    # char-based `[:20000]` truncation could still send tens of thousands of
    # lines when a single file was huge.
    max_diff_lines: int = 2000
    max_diff_files: int = 30

    llm: LLMCfg = Field(default_factory=LLMCfg)
    auth: AuthCfg = Field(default_factory=AuthCfg)

    @model_validator(mode="after")
    def _mirror_llm_keys(self) -> Settings:
        """Mirror flat ``anthropic_api_key``/``openai_api_key``/``ollama_base_url``
        into the nested ``llm.anthropic/openai/ollama`` cfg that they actually
        drive (C1 fix). Without this mirroring, the LLM providers are always
        constructed with empty credentials even though the flat fields are
        populated from env or the Settings UI."""
        if self.anthropic_api_key and not self.llm.anthropic.api_key:
            self.llm.anthropic.api_key = self.anthropic_api_key
        if self.openai_api_key and not self.llm.openai.api_key:
            self.llm.openai.api_key = self.openai_api_key
        # Only mirror ollama if the user changed it from the bundled default.
        if (
            self.ollama_base_url
            and self.ollama_base_url != "http://localhost:11434"
            and not self.llm.ollama.base_url
        ):
            self.llm.ollama.base_url = self.ollama_base_url
        return self

    @property
    def db_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'tl_towerwatch.db').as_posix()}"


def _load_env_file_into_environ(env_file: Path) -> None:
    """Populate os.environ from a dotenv file BEFORE Settings() is built.

    pydantic-settings only reads ``.env`` relative to CWD, which breaks in
    Docker (CWD is /app, the user's /data/.env is invisible). Doing it
    manually lets us honour the data_dir-relative contract.
    """
    if not env_file.exists():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Don't clobber an env var already set in the process environment.
        os.environ.setdefault(key, value)


def load_settings(data_dir: Path | None = None) -> Settings:
    # Honour the TOWERWATCH_DATA_DIR env var so web routes and the CLI
    # share the same data dir even when load_settings() is called with
    # no explicit argument. Otherwise default to ./data relative to CWD —
    # this matches the wizard's write target (init writes to ./data/.env),
    # so a fresh `tl_towerwatch init` followed by `tl_towerwatch repo add`
    # from the same directory works without requiring the user to set
    # TOWERWATCH_DATA_DIR.
    if data_dir is None:
        env_data_dir = os.environ.get("TOWERWATCH_DATA_DIR")
        data_dir = Path(env_data_dir) if env_data_dir else Path("./data")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.yaml").touch()
    # Materialize env vars from <data_dir>/.env into os.environ so that
    # Settings (which no longer declares env_file) still picks them up.
    _load_env_file_into_environ(data_dir / ".env")
    return Settings(data_dir=data_dir)