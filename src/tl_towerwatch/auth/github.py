from __future__ import annotations

import secrets
import threading
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from tl_towerwatch.config import Settings
from tl_towerwatch.github.client import GitHubClient

GITHUB_OAUTH_URL = "https://github.com/login/oauth/access_token"
GITHUB_OAUTH_AUTHORIZE = "https://github.com/login/oauth/authorize"
OAUTH_SCOPES = "repo read:user"

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
    if settings.github_oauth_access_token and settings.github_oauth_refresh_token:
        return refresh_oauth_token(settings).github_oauth_access_token
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

    Mutates ``settings`` in place (updates ``github_oauth_access_token`` and
    optionally ``github_oauth_refresh_token``), persists the new tokens to
    ``settings.data_dir / .env``, and returns the same ``Settings`` instance
    so callers can read the updated values.
    """
    r = httpx.post(
        GITHUB_OAUTH_URL,
        data={
            "client_id": settings.github_oauth_client_id,
            "client_secret": settings.github_oauth_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": settings.github_oauth_refresh_token,
        },
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    settings.github_oauth_access_token = data["access_token"]
    if "refresh_token" in data:
        settings.github_oauth_refresh_token = data["refresh_token"]
    _persist_env(settings)
    return settings


def _persist_env(settings: Settings) -> None:
    """Append updated OAuth tokens to data_dir/.env (atomic write).

    Key names align with spec §10.3: ``TOWERWATCH_GITHUB_OAUTH_*``.
    """
    import os

    env_path = settings.data_dir / ".env"
    updates = {
        "TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN": settings.github_oauth_access_token,
        "TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN": settings.github_oauth_refresh_token,
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


def start_callback_server(port: int, timeout: int = 120) -> str:
    """Tiny HTTP server that captures the ``?code=`` query param from the
    OAuth redirect and returns it. Blocks until a single request arrives
    or ``timeout`` seconds elapse, at which point it raises ``TimeoutError``.

    Used by ``complete_oauth_flow``; kept top-level and patchable so tests
    can stub it without binding to ``127.0.0.1``.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer

    code_holder = {"code": None}
    deadline = time.time() + timeout

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # stdlib name
            q = parse_qs(urlparse(self.path).query)
            code_holder["code"] = q.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"OK \xe2\x80\x94 you can close this tab.")

        def log_message(self, *_a, **_kw):  # silence noisy stderr
            pass

    httpd = HTTPServer(("127.0.0.1", port), _Handler)
    try:
        while code_holder["code"] is None and time.time() < deadline:
            httpd.handle_request()
    finally:
        httpd.server_close()
    if code_holder["code"] is None:
        raise TimeoutError(f"Callback server timed out after {timeout}s")
    return code_holder["code"]


def complete_oauth_flow(
    client_id: str,
    client_secret: str,
    callback_url: str,
    *,
    port: int = 8765,
    host_alias: str | None = None,
    open_browser=None,
    start_server=None,
) -> tuple[str, str]:
    """Run the full OAuth dance: build the authorize URL, start the callback
    server in a background thread, open the browser so the user can authorize,
    wait for the callback to deliver the ``code``, then exchange it for tokens.

    Returns ``(access_token, refresh_token)``. ``refresh_token`` may be empty
    when GitHub does not rotate it (older OAuth Apps).

    ``open_browser`` and ``start_server`` default to ``webbrowser.open`` and
    :func:`start_callback_server` respectively; tests can inject fakes.
    """
    if start_server is None:
        start_server = start_callback_server
    if open_browser is None:
        open_browser = webbrowser.open

    # 1. Build the authorize URL FIRST so the browser has somewhere to send
    #    the user before anything else blocks.
    state = secrets.token_urlsafe(16)
    authorize_url = (
        GITHUB_OAUTH_AUTHORIZE
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": callback_url,
                "scope": OAUTH_SCOPES,
                "state": state,
            }
        )
    )

    # 2. Start the callback server in a background thread so it's already
    #    listening on the port BEFORE we open the browser (otherwise the
    #    GitHub redirect would hit a closed port and the CLI would hang).
    code_holder: dict[str, object] = {"code": None, "error": None}

    def _server() -> None:
        try:
            code_holder["code"] = start_server(port)
        except Exception as exc:  # noqa: BLE001 — re-raised after t.join()
            code_holder["error"] = exc

    t = threading.Thread(target=_server, daemon=True)
    t.start()
    # Tiny sleep so the server has time to bind the port before the browser
    # resolves the redirect target.
    time.sleep(0.1)

    # 3. Open the browser (non-blocking — the actual auth happens in the user's
    #    browser, then GitHub redirects to our local server).
    open_browser(authorize_url)

    # 4. Wait for the callback. ``start_server`` enforces its own timeout and
    #    raises ``TimeoutError`` if no request arrives in time.
    t.join()
    if code_holder["error"] is not None:
        raise code_holder["error"]
    code = code_holder["code"]
    if code is None:
        raise TimeoutError("OAuth callback did not return a code")

    # 5. Exchange the code for access + refresh tokens.
    r = httpx.post(
        GITHUB_OAUTH_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": callback_url,
            "state": state,
        },
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    r.raise_for_status()
    d = r.json()
    return d["access_token"], d.get("refresh_token", "")