import time as _time
from pathlib import Path

import pytest
import respx
from httpx import Response

from tl_towerwatch.auth.github import complete_oauth_flow, resolve_token
from tl_towerwatch.config import load_settings


@respx.mock
def test_resolve_token_pat(tmp_path: Path):
    s = load_settings(tmp_path)
    s.github_token = "ghp_test"
    respx.get("https://api.github.com/user").mock(
        return_value=Response(
            200,
            json={"login": "dimh"},
            headers={"X-OAuth-Scopes": "repo, read:user"},
        )
    )
    assert resolve_token(s) == "ghp_test"


@respx.mock
def test_resolve_token_oauth_refresh(tmp_path: Path):
    s = load_settings(tmp_path)
    s.github_oauth_access_token = "old_access"
    s.github_oauth_refresh_token = "old_refresh"
    s.github_oauth_client_id = "cid"
    s.github_oauth_client_secret = "csec"
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(
            200,
            json={"access_token": "new_access", "refresh_token": "new_refresh"},
            headers={"Content-Type": "application/json"},
        )
    )
    new = resolve_token(s)
    assert new == "new_access"
    assert s.github_oauth_refresh_token == "new_refresh"


@respx.mock
def test_resolve_token_pat_invalid_raises(tmp_path: Path):
    """A 401 from GET /user must surface as a clear RuntimeError."""
    s = load_settings(tmp_path)
    s.github_token = "ghp_bad"
    respx.get("https://api.github.com/user").mock(
        return_value=Response(401, json={"message": "Bad credentials"})
    )
    with pytest.raises(RuntimeError, match="GitHub token is invalid"):
        resolve_token(s)


@respx.mock
def test_complete_oauth_flow_exchanges_code(monkeypatch):
    """v1.1 (Task 4): the OAuth initial flow exchanges the captured code for
    access + refresh tokens via GitHub's /login/oauth/access_token endpoint.

    The callback server is stubbed (no real HTTP listener spins up during
    pytest); the respx-mocked token endpoint returns canned tokens so we can
    assert the wiring without touching the network.
    """
    captured = {}

    def fake_server(port):
        captured["port"] = port

        class R:
            auth_code = "test_code"
            state = "x"

        return R()

    monkeypatch.setattr(
        "tl_towerwatch.auth.github.start_callback_server", fake_server
    )
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(
            200,
            json={"access_token": "new_acc", "refresh_token": "new_ref"},
            headers={"Content-Type": "application/json"},
        )
    )
    # Default open_browser is webbrowser.open — patch it so the test doesn't
    # actually open a browser tab. The function only needs to be called once
    # with the authorize URL.
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    acc, ref = complete_oauth_flow(
        "cid", "csec", "http://localhost:8765/auth/callback"
    )
    assert acc == "new_acc"
    assert ref == "new_ref"
    assert captured["port"] == 8765


def test_complete_oauth_flow_opens_browser_before_blocking_server(monkeypatch):
    """Regression (Fix round 1): ``complete_oauth_flow`` must open the browser
    BEFORE the callback server blocks. Otherwise the user never sees the
    authorize page and the CLI hangs forever.

    The fake ``start_callback_server`` sleeps 5s before returning — long
    enough that any implementation which blocks on it first would not get
    around to opening the browser for ~5s. We assert ``webbrowser.open`` was
    called within the first second.
    """

    def slow_server(_port):
        _time.sleep(5)
        return "abc"

    browser_calls: list[tuple[float, str]] = []

    def fake_browser(url):
        browser_calls.append((_time.time(), url))
        return True

    monkeypatch.setattr(
        "tl_towerwatch.auth.github.start_callback_server", slow_server
    )
    monkeypatch.setattr("webbrowser.open", fake_browser)

    with respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=Response(
                200,
                json={"access_token": "x", "refresh_token": "y"},
                headers={"Content-Type": "application/json"},
            )
        )
        start = _time.time()
        acc, ref = complete_oauth_flow(
            "cid", "csec", "http://localhost:8765/auth/callback"
        )
        elapsed = _time.time() - start

    # Browser must have been called once, with the GitHub authorize URL, and
    # within the first second (well before the 5s slow_server returns).
    assert browser_calls, "open_browser was never called"
    _call_time, url = browser_calls[0]
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert (_call_time - start) < 1.0, (
        f"open_browser was called too late ({_call_time - start:.2f}s) — "
        "complete_oauth_flow is likely blocking on start_callback_server "
        "before opening the browser."
    )
    # Sanity: exchange still completes successfully.
    assert acc == "x"
    assert ref == "y"
    # The whole call should have taken ~5s (dominated by the fake server).
    assert elapsed >= 5.0, f"Flow returned too fast ({elapsed:.2f}s)"


def test_complete_oauth_flow_enforces_timeout(monkeypatch):
    """Regression (Fix round 1): if no callback arrives, ``complete_oauth_flow``
    must surface a ``TimeoutError`` promptly — the real
    :func:`start_callback_server` enforces a ``timeout`` deadline and raises
    ``TimeoutError`` when it expires.
    """

    def hanging_server(_port, timeout=120):
        # Mirror the real server's behaviour: enforce the timeout and raise
        # immediately (the real one blocks on ``handle_request`` until the
        # deadline expires).
        raise TimeoutError(f"Callback server timed out after {timeout}s")

    monkeypatch.setattr(
        "tl_towerwatch.auth.github.start_callback_server", hanging_server
    )
    # Browser must still be opened even if the callback never comes.
    monkeypatch.setattr("webbrowser.open", lambda url: True)

    start = _time.time()
    with pytest.raises(TimeoutError):
        complete_oauth_flow("cid", "csec", "http://localhost:8765/auth/callback")
    elapsed = _time.time() - start

    # Must propagate the timeout promptly — definitely not wait the full 120s.
    assert elapsed < 5.0, (
        f"Timeout took too long to surface ({elapsed:.2f}s) — "
        "complete_oauth_flow may be hanging on the callback thread."
    )