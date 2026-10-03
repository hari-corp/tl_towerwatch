from __future__ import annotations

import httpx

from tl_towerwatch.config import Settings

GITHUB_OAUTH_URL = "https://github.com/login/oauth/access_token"

def resolve_token(settings: Settings) -> str:
    if settings.github_token:
        return settings.github_token
    if settings.oauth_access_token and settings.oauth_refresh_token:
        # In v1 we always refresh when the OAuth path is the source.
        return _refresh_oauth(settings)
    raise RuntimeError("No GitHub credentials configured. Run `tl_towerwatch init`.")

def _refresh_oauth(settings: Settings) -> str:
    r = httpx.post(
        GITHUB_OAUTH_URL,
        data={
            "client_id": settings.oauth_client_id,
            "client_secret": settings.oauth_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": settings.oauth_refresh_token,
        },
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    settings.oauth_access_token = data["access_token"]
    if "refresh_token" in data:
        settings.oauth_refresh_token = data["refresh_token"]
    _persist_env(settings)
    return data["access_token"]

def _persist_env(settings: Settings) -> None:
    """Append updated OAuth tokens to data_dir/.env (atomic write)."""
    import os
    env_path = settings.data_dir / ".env"
    updates = {
        "TOWERWATCH_OAUTH_ACCESS_TOKEN": settings.oauth_access_token,
        "TOWERWATCH_OAUTH_REFRESH_TOKEN": settings.oauth_refresh_token,
    }
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    keys = set(updates.keys())
    new_lines = [ln for ln in lines if not any(ln.startswith(k + "=") for k in keys)]
    new_lines += [f"{k}={v}" for k, v in updates.items()]
    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(new_lines) + "\n")
    os.replace(tmp, env_path)