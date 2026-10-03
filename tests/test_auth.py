from pathlib import Path

import respx
from httpx import Response

from tl_towerwatch.auth.github import resolve_token
from tl_towerwatch.config import load_settings


@respx.mock
def test_resolve_token_pat(tmp_path: Path):
    s = load_settings(tmp_path)
    s.github_token = "ghp_test"
    respx.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"})
    )
    assert resolve_token(s) == "ghp_test"

@respx.mock
def test_resolve_token_oauth_refresh(tmp_path: Path):
    s = load_settings(tmp_path)
    s.oauth_access_token = "old_access"
    s.oauth_refresh_token = "old_refresh"
    s.oauth_client_id = "cid"
    s.oauth_client_secret = "csec"
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(
            200,
            json={"access_token": "new_access", "refresh_token": "new_refresh"},
            headers={"Content-Type": "application/json"},
        )
    )
    new = resolve_token(s)
    assert new == "new_access"
    assert s.oauth_refresh_token == "new_refresh"