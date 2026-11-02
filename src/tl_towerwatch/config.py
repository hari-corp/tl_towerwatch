from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthCfg(BaseModel):
    mode: Literal["pat", "oauth"] = "pat"


class Settings(BaseSettings):
    # env_file is intentionally omitted: .env must be loaded relative to the
    # configured data_dir (see load_settings), not the current working
    # directory. Without this override, pydantic-settings silently swallows
    # the user's bind-mounted /data/.env in Docker (CWD is /app).
    #
    # extra="ignore" is critical: pre-v1.3.0 installs wrote
    # TOWERWATCH_ANTHROPIC_API_KEY / TOWERWATCH_LLM_PROVIDER etc. to
    # .env. After the v1.3.0 cut we no longer expose those fields here
    # (LLM is fully removed from the app) but old .env files still
    # carry them. The ignore policy means pydantic-settings drops them
    # silently — the user can clean their .env at their own pace and
    # the Settings model never 500s on startup.
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
    theme: Literal["dark", "light", "system"] = "dark"
    refresh_interval_seconds: int = 300
    # Cap the diff included in the manually assembled review prompt so a
    # single 5,000-file PR doesn't produce an unusable prompt for the
    # external LLM.
    max_diff_lines: int = 2000
    max_diff_files: int = 30

    auth: AuthCfg = Field(default_factory=AuthCfg)

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
    # no explicit argument.
    if data_dir is None:
        env_data_dir = os.environ.get("TOWERWATCH_DATA_DIR")
        data_dir = Path(env_data_dir) if env_data_dir else Path("./data")
    # Always resolve to an absolute path so the env-file load below
    # doesn't depend on the caller's CWD after the function returns.
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.yaml").touch()
    # Materialize env vars from <data_dir>/.env into os.environ so that
    # Settings (which no longer declares env_file) still picks them up.
    _load_env_file_into_environ(data_dir / ".env")
    return Settings(data_dir=data_dir)