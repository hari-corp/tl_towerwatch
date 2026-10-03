from __future__ import annotations

import httpx

from tl_towerwatch.config import Settings
from tl_towerwatch.github.client import GitHubClient

GITHUB_OAUTH_URL = "https://github.com/login/oauth/access_token"

_REQUIRED_SCOPES = ("repo", "read:user")
_INVALID_TOKEN_MSG = (
    "GitHub token is invalid or missing required scopes (repo, read:user)"
)


def resolve_token(settings: Settings) -> str:
    """Return the active GitHub token.

    When a PAT (``settings.github_token``) is configured it is validated
    against ``GET /user`` and the required scopes (``repo``, ``read:user``)
    per spec §8.1. Otherwise an OAuth refresh is attempted.
    """
    if settings.github_token:
        return _validate_pat(settings)
    if settings.oauth_access_token and settings.oauth_refresh_token:
        return refresh_oauth_token(settings).oauth_access_token
    raise RuntimeError("No GitHub credentials configured. Run `tl_towerwatch init`.")


def _validate_pat(settings: Settings) -> str:
    """Validate the PAT by hitting ``GET /user`` and checking scopes.

    Raises ``RuntimeError`` if the request fails (e.g. 401) or the
    returned ``X-OAuth-Scopes`` header does not include both ``repo``
    and ``read:user``.
    """
    try:
        with GitHubClient(settings.github_token) as client:
            client.get_authenticated_user()
            scopes = client.last_oauth_scopes() or []
    except httpx.HTTPStatusError:
        scopes = []
    if not set(_REQUIRED_SCOPES).issubset(scopes):
        raise RuntimeError(_INVALID_TOKEN_MSG)
    return settings.github_token


def refresh_oauth_token(settings: Settings) -> Settings:
    """Exchange the OAuth refresh token for a new access token.

    Mutates ``settings`` in place (updates ``oauth_access_token`` and
    optionally ``oauth_refresh_token``), persists the new tokens to
    ``settings.data_dir / .env``, and returns the same ``Settings``
    instance so callers can read the updated values.
    """
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
    return settings


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