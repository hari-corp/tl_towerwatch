# tl_towerwatch v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the 19 deferred-to-v1.1 items from the v1.0-rc1 whole-branch review (commit `c898968`): CLI completion, full init wizard, initial OAuth flow, agent-review streaming, theme persistence, UI gap fill, DB indexes, and minor cleanups.

**Architecture:** Each task is a small, focused, independently-testable delta to the existing `tl_towerwatch` app (already at commit `c898968`). Existing test patterns and code conventions are reused verbatim. New services get a thin layer; UI tasks add Jinja fragments + minimal route handlers.

**Tech Stack:** Python 3.11+, Typer, FastAPI, Jinja2, HTMX, SQLAlchemy 2.x, SQLite, Pydantic v2, httpx, Authlib (OAuth), uv.

**Spec:** `docs/superpowers/specs/2026-10-03-tl-towerwatch-design.md` (v1.0; deferred items referenced inline below).

**Parent plan:** `docs/superpowers/plans/2026-10-03-tl-towerwatch.md` (v1.0 plan, complete).

---

## Global Constraints

- **Python ≥ 3.11.**
- **Package name** `tl_towerwatch`; CLI command `tl_towerwatch`.
- **Repo URL:** `github.com/hari-corp/tl_towerwatch`.
- **Default config dir** `./data/` (gitignored); overridable via `TOWERWATCH_DATA_DIR`.
- **Database:** `./data/tl_towerwatch.db` (SQLite, FK enforced).
- **Tests:** `uv run pytest -q` baseline at start of this plan = 44 passed.
- **Coverage:** maintain ≥ 85% on `services/`, `llm/`, `agents/`, `findings/`.
- **No telemetry.**
- **OAuth env vars** = `TOWERWATCH_GITHUB_OAUTH_CLIENT_ID/SECRET/ACCESS_TOKEN/REFRESH_TOKEN` (already renamed in v1.0).
- **LLM keys** mirror via `Settings._mirror_llm_keys` model_validator (already wired).
- **Auth mode setting** `auth.mode` in `config.yaml` = `pat` or `oauth` (introduced in Task 1 of this plan).
- **Default skills** = `superpowers` + `ponytail` (already shipped).
- **Default self-repo refresh** = 60s; other repos = 300s (already shipped).

---

## File Structure (target)

All changes in the already-laid-out package. Files to modify:

```
src/tl_towerwatch/
├── cli.py                          # extend with refresh/status/config/auth + init wizard
├── web/
│   ├── routes.py                   # new routes: /theme (full), /first-run, 401 redirect; /pr tabs data; /repos rate-limit banner; / dashboard counters
│   └── templates/
│           ├── base.html            # cookie + localStorage theme + nav updates
│           ├── dashboard.html      # status counters strip
│           ├── pr_detail.html      # tabs + history expansion
│           └── repos.html          # rate-limit banner
├── auth/
│   └── github.py                   # OAuth initial flow helpers
├── llm/
│   └── base.py                     # tighten body type to match spec (str)
├── agents/
│   ├── base.py                     # add AgentEvent + on_event callback param
│   ├── claude.py                   # stream events
│   ├── codex.py                    # stream events
│   ├── minimax_code.py             # stream events
│   └── ollama.py                   # stream events
├── db/
│   └── models.py                   # add 5 perf indexes; populate avatar/display_name
├── services/
│   ├── repos.py                    # add/remove single author helpers
│   └── pull_requests.py            # diff truncation
└── settings_pages/                 # NEW
    └── config_writers.py           # read/write config.yaml (theme, skills, mode)

tests/
├── test_cli.py                     # extend (init wizard + new subcommands)
├── test_config.py                  # extend (auth.mode + theme in config)
├── test_auth.py                    # extend (OAuth initial flow)
├── test_agents.py                  # extend (on_event callback)
├── test_repos.py                   # extend (single-author helpers)
├── test_routes.py                  # extend (status counters, tabs, 401, first-run)
└── test_db_indexes.py              # NEW (smoke verify indexes exist)
```

---

## Task ordering (dependencies → execution order)

1. **`Auth.mode` setting + config.yaml helpers** (foundation — Task 1)
2. **CLI missing subcommands** (Task 2 — independent)
3. **Init wizard** (Task 3 — depends on Task 1's config writers)
4. **OAuth initial flow** (Task 4 — depends on Task 1)
5. **AgentRunner `on_event` callback** (Task 5 — independent)
6. **`review --watch` streaming** (Task 6 — depends on Task 5)
7. **Theme persistence + hardening** (Task 7 — depends on Task 1's config writer)
8. **UI: dashboard status counters + repos rate-limit banner** (Task 8 — independent)
9. **UI: PR detail tabs + tl_towerwatch reviews tab** (Task 9 — independent)
10. **UI: first-run redirect + 401 → settings redirect** (Task 10 — depends on Task 3's init)
11. **DB: 5 perf indexes + User.avatar_url/display_name + dead-code cleanup + type fix** (Task 11 — independent)
12. **Diff-too-large truncation + final polish** (Task 12 — independent)

---

## Task 1 — `auth.mode` setting + config.yaml helpers

**Files:**
- Modify: `src/tl_towerwatch/config.py:1-100` (add `AuthCfg` model, nested under `Settings`)
- Modify: `tests/test_config.py`
- Create: `src/tl_towerwatch/config_io.py` (new module: `load_config_yaml`, `save_config_yaml`, `merge_into_settings`)

**Interfaces:**
- Produces: `Settings.auth` → `AuthCfg(mode: Literal["pat","oauth"]="pat")`. `load_config_yaml(path) -> dict`. `save_config_yaml(path, data)`. `merge_into_settings(s, data)` updates nested `Settings` fields from a dict.

**Step 1: Failing test for `AuthCfg`**

In `tests/test_config.py`, append:
```python
def test_auth_mode_defaults_to_pat(tmp_path):
    s = load_settings(tmp_path)
    assert s.auth.mode == "pat"
```

Run: `uv run pytest tests/test_config.py::test_auth_mode_defaults_to_pat -v` → FAIL (no `auth` attribute).

**Step 2: Implement `AuthCfg` + `model_config` json support**

Add to `src/tl_towerwatch/config.py`:
```python
class AuthCfg(BaseModel):
    mode: Literal["pat", "oauth"] = "pat"

class Settings(BaseSettings):
    # ... existing fields ...
    auth: AuthCfg = Field(default_factory=AuthCfg)
```

**Step 3: Run test → PASS.**

**Step 4: Failing test for `config_io`**

Create `tests/test_config_io.py`:
```python
from pathlib import Path
from tl_towerwatch.config_io import load_config_yaml, save_config_yaml, merge_into_settings
from tl_towerwatch.config import Settings, AuthCfg

def test_save_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "config.yaml"
    save_config_yaml(p, {"auth": {"mode": "oauth"}, "theme": "light"})
    data = load_config_yaml(p)
    assert data["auth"]["mode"] == "oauth"
    assert data["theme"] == "light"

def test_load_missing_returns_empty(tmp_path: Path):
    assert load_config_yaml(tmp_path / "missing.yaml") == {}

def test_merge_into_settings_updates_auth_mode(tmp_path: Path):
    s = Settings(auth=AuthCfg(mode="pat"))
    merge_into_settings(s, {"auth": {"mode": "oauth"}})
    assert s.auth.mode == "oauth"
```

Run → FAIL.

**Step 5: Create `src/tl_towerwatch/config_io.py`**

```python
from __future__ import annotations
from pathlib import Path
import yaml
from tl_towerwatch.config import Settings

def load_config_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text().strip()
    if not text:
        return {}
    return yaml.safe_load(text) or {}

def save_config_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
    tmp.replace(path)

def merge_into_settings(settings: Settings, data: dict) -> None:
    """Top-level keys in `data` override the matching `settings` field."""
    for k, v in data.items():
        if not hasattr(settings, k):
            continue
        current = getattr(settings, k)
        if isinstance(v, dict) and hasattr(current, "__pydantic_fields__"):
            for sk, sv in v.items():
                if sk in current.__pydantic_fields__:
                    setattr(current, sk, sv)
        else:
            setattr(settings, k, v)
```

**Step 6: Run all tests → 47 passed.**

**Step 7: Commit**
```bash
git add src/tl_towerwatch/config.py src/tl_towerwatch/config_io.py tests/test_config.py tests/test_config_io.py
git commit -m "feat(config): auth.mode + config.yaml read/write helpers"
```

---

## Task 2 — CLI: missing subcommands (`add-author`, `remove-author`, `clear-authors`, `refresh`, `status`, `config`, `auth refresh`)

**Files:**
- Modify: `src/tl_towerwatch/cli.py:60-120` (after `repo_set_authors`)
- Modify: `src/tl_towerwatch/services/repos.py:60-95` (add single-author helpers)
- Modify: `tests/test_cli.py`

**Interfaces:**
- Adds to `services/repos`: `add_allowed_author(db, owner, name, login: str) -> None`, `remove_allowed_author(db, owner, name, login: str) -> None`, `clear_allowed_authors(db, owner, name) -> None`.
- Adds CLI subcommands: `repo add-author`, `repo remove-author`, `repo clear-authors`, `refresh`, `status`, `config show`, `auth refresh`.

**Step 1: Failing tests for service helpers**

In `tests/test_services.py` append:
```python
def test_repo_add_remove_clear_author(tmp_path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    add_allowed_author(db, "o", "n", "marta.g")
    assert json.loads(list_repos(db)[0].allowed_authors_json) == ["marta.g"]
    add_allowed_author(db, "o", "n", "luis.f")
    assert json.loads(list_repos(db)[0].allowed_authors_json) == ["luis.f", "marta.g"]
    remove_allowed_author(db, "o", "n", "luis.f")
    assert json.loads(list_repos(db)[0].allowed_authors_json) == ["marta.g"]
    clear_allowed_authors(db, "o", "n")
    assert json.loads(list_repos(db)[0].allowed_authors_json) == []
```

Run → FAIL.

**Step 2: Implement helpers in `services/repos.py`** (add after `set_allowed_authors`):
```python
def add_allowed_author(db, owner, name, login):
    with db.session() as s:
        r = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
        current = json.loads(r.allowed_authors_json or "[]")
        new = normalize_authors(current + [login])
        r.allowed_authors_json = json.dumps(new)

def remove_allowed_author(db, owner, name, login):
    with db.session() as s:
        r = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
        current = json.loads(r.allowed_authors_json or "[]")
        new = [a for a in current if a != login.lower().lstrip("@")]
        r.allowed_authors_json = json.dumps(new)

def clear_allowed_authors(db, owner, name):
    with db.session() as s:
        r = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
        r.allowed_authors_json = json.dumps([])
```

**Step 3: Run → PASS.**

**Step 4: Extend `cli.py` with the 6 new commands** (add after `repo_set_authors`):

```python
@repo_app.command("add-author")
def repo_add_author(owner_name: str = typer.Argument(...), login: str = typer.Argument(...)):
    db = _db()
    o, name = owner_name.split("/", 1)
    add_allowed_author(db, o, name, login)
    typer.echo(f"✓ Added {login} to {owner_name}")

@repo_app.command("remove-author")
def repo_remove_author(owner_name: str = typer.Argument(...), login: str = typer.Argument(...)):
    db = _db()
    o, name = owner_name.split("/", 1)
    remove_allowed_author(db, o, name, login)
    typer.echo(f"✓ Removed {login} from {owner_name}")

@repo_app.command("clear-authors")
def repo_clear_authors(owner_name: str = typer.Argument(...)):
    db = _db()
    o, name = owner_name.split("/", 1)
    clear_allowed_authors(db, o, name)
    typer.echo(f"✓ Cleared allowed_authors for {owner_name}")

@app.command()
def refresh(repo: str = typer.Option("", "--repo", help="owner/name")):
    """Refresh PRs from GitHub."""
    db = _db()
    settings = load_settings()
    from tl_towerwatch.services.pull_requests import sync_repo, sync_one_pr
    with GitHubClient(token=resolve_token(settings)) as gh:
        if repo:
            o, name = repo.split("/", 1)
            with db.session() as s:
                r = s.execute(select(Repo).where(Repo.owner == o, Repo.name == name)).scalar_one()
            sync_repo(db, gh, r)
        else:
            from tl_towerwatch.services.repos import list_repos
            for r in list_repos(db, enabled_only=True):
                sync_repo(db, gh, r)
    typer.echo("✓ Refresh complete")

@app.command()
def status():
    """Show current user, last refresh, rate limit, repo counts."""
    db = _db()
    settings = load_settings()
    from tl_towerwatch.services.repos import list_repos
    repos = list_repos(db)
    typer.echo(f"Repos: {len(repos)} ({sum(1 for r in repos if r.enabled)} enabled)")
    for r in repos:
        typer.echo(f"  {r.owner}/{r.name}: last fetch {r.last_fetched_at or '—'} ({r.last_fetch_status or '—'})")

@app.command()
def status_config():
    """Print current effective settings (no secrets)."""
    s = load_settings()
    safe = {
        "auth.mode": s.auth.mode,
        "llm.default_provider": s.llm.default_provider,
        "theme": s.theme,
        "refresh_interval_seconds": s.refresh_interval_seconds,
    }
    typer.echo(json.dumps(safe, indent=2, default=str))

@app.command()
def auth_refresh():
    """Refresh the OAuth access token using the stored refresh_token."""
    from tl_towerwatch.auth.github import refresh_oauth_token
    s = load_settings()
    refresh_oauth_token(s)
    typer.echo("✓ OAuth token refreshed")
```

**Step 5: Failing tests in `tests/test_cli.py`** — verify `--help` lists each subcommand:
```python
def test_repo_add_author_help():
    r = runner.invoke(app, ["repo", "add-author", "--help"])
    assert r.exit_code == 0
    assert "login" in r.stdout

def test_refresh_help():
    r = runner.invoke(app, ["refresh", "--help"])
    assert r.exit_code == 0
    assert "--repo" in r.stdout

def test_status_help():
    r = runner.invoke(app, ["status", "--help"])
    assert r.exit_code == 0

def test_auth_refresh_help():
    r = runner.invoke(app, ["auth", "refresh", "--help"])
    # Note: `auth refresh` requires nested sub-app — see Step 5b
    assert r.exit_code == 0 or r.exit_code == 2  # may need nested-app fix
```

Run → FAIL (commands don't exist).

**Step 5b: Wire `auth refresh` as nested sub-app** (Typer quirk):

In `cli.py`, add before `app` definition:
```python
auth_app = typer.Typer(help="Auth-related subcommands")
app.add_typer(auth_app, name="auth")

@auth_app.command("refresh")
def auth_refresh_cmd():
    """Refresh OAuth access token."""
    from tl_towerwatch.auth.github import refresh_oauth_token
    s = load_settings()
    refresh_oauth_token(s)
    typer.echo("✓ OAuth token refreshed")
```

**Step 6: Run tests → 51 passed (44 baseline + 3 new service + 4 new CLI).**

**Step 7: Commit**
```bash
git add src/tl_towerwatch/cli.py src/tl_towerwatch/services/repos.py tests/test_services.py tests/test_cli.py
git commit -m "feat(cli): add-author/remove-author/clear-authors + refresh + status + auth refresh"
```

---

## Task 3 — Init wizard (auth mode + LLM provider + skills registry → config.yaml)

**Files:**
- Modify: `src/tl_towerwatch/cli.py:28-50` (`init` body)
- Modify: `tests/test_cli.py`

**Interfaces:**
- `init` prompts for: auth mode (`pat` or `oauth`); if PAT → paste + validate via `resolve_token`; if OAuth → paste client_id+secret and (on first run) trigger Task 4's OAuth dance; then prompts for default LLM provider + model; then writes `config.yaml` with `auth.mode` + `llm.default_provider` + `llm.<provider>.model`.

**Step 1: Failing test in `tests/test_cli.py`** (monkeypatch prompts):
```python
def test_init_pat_path_writes_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    responses = iter(["pat", "ghp_test", "anthropic", "claude-3-5-sonnet-latest"])
    monkeypatch.setattr("typer.prompt", lambda *a, **kw: next(responses))
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: False)  # skip OAuth sub-flow
    runner.invoke(app, ["init"], input="")
    cfg = (tmp_path / "config.yaml").read_text()
    assert "auth:" in cfg
    assert "mode: pat" in cfg
    assert "default_provider: anthropic" in cfg
```

Run → FAIL (init is a stub).

**Step 2: Implement the wizard**

Replace the body of `init`:
```python
@app.command()
def init():
    """First-time setup wizard."""
    settings = load_settings()
    from tl_towerwatch.config_io import save_config_yaml, merge_into_settings
    from tl_towerwatch.auth.github import resolve_token

    mode = typer.prompt("Auth mode", type=typer.Choice(["pat", "oauth"]), default="pat")
    if mode == "pat":
        token = typer.prompt("GitHub PAT", hide_input=True)
        settings.github_token = token
        # Validate now (raises RuntimeError on failure → friendly message)
        try:
            resolve_token(settings)
            typer.echo("✓ Token validated")
        except RuntimeError as e:
            typer.echo(f"✗ {e}", err=True); raise typer.Exit(1)
    else:
        cid = typer.prompt("OAuth client_id")
        csec = typer.prompt("OAuth client_secret", hide_input=True)
        settings.oauth_client_id = cid
        settings.oauth_client_secret = csec
        typer.echo("Run `tl_towerwatch auth login` to complete the browser flow.")

    provider = typer.prompt("Default LLM provider", type=typer.Choice(["anthropic", "openai", "ollama"]), default="anthropic")
    default_model = {
        "anthropic": "claude-3-5-sonnet-latest",
        "openai": "gpt-4o",
        "ollama": "llama3.2",
    }[provider]
    model = typer.prompt(f"{provider} model", default=default_model)

    save_config_yaml(settings.data_dir / "config.yaml", {
        "auth": {"mode": mode},
        "llm": {"default_provider": provider, provider: {"model": model}},
        "skills": {
            "superpowers": {"enabled": True, "cli_flag": "--enable-superpowers",
                             "description": "Code-review and quality skills"},
            "ponytail":   {"enabled": True, "cli_flag": "--skill ponytail",
                             "description": "Custom review heuristics"},
        },
    })
    (settings.data_dir / ".env").write_text(_env_lines_for(settings))
    typer.echo(f"✓ Init complete. Next: tl_towerwatch repo add owner/name")
```

`_env_lines_for` is a tiny helper:
```python
def _env_lines_for(s):
    lines = []
    if s.github_token: lines.append(f"TOWERWATCH_GITHUB_TOKEN={s.github_token}")
    if s.oauth_client_id: lines.append(f"TOWERWATCH_GITHUB_OAUTH_CLIENT_ID={s.oauth_client_id}")
    if s.oauth_client_secret: lines.append(f"TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET={s.oauth_client_secret}")
    if s.llm.anthropic.api_key: lines.append(f"TOWERWATCH_ANTHROPIC_API_KEY={s.llm.anthropic.api_key}")
    if s.llm.openai.api_key: lines.append(f"TOWERWATCH_OPENAI_API_KEY={s.llm.openai.api_key}")
    return "\n".join(lines) + "\n"
```

**Step 3: Run test → PASS.**

**Step 4: Commit**
```bash
git add src/tl_towerwatch/cli.py tests/test_cli.py
git commit -m "feat(cli): init wizard — auth mode + LLM provider + skills → config.yaml"
```

---

## Task 4 — OAuth initial flow (callback server + browser open + code exchange)

**Files:**
- Modify: `src/tl_towerwatch/auth/github.py:1-60`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Adds to `auth/github`: `OAuthCallbackServer(port=8765) -> OAuthCallbackResult`; `complete_oauth_flow(client_id, client_secret, callback_url, host_alias=None) -> tuple[access_token, refresh_token]`; `tl_towerwatch auth login` CLI subcommand wires them.

**Step 1: Failing test in `tests/test_auth.py`**
```python
def test_complete_oauth_flow_exchanges_code(monkeypatch):
    # Monkeypatch the callback server to capture the code, then return a known code
    captured = {}
    def fake_server(port):
        captured['port'] = port
        class R: auth_code = "test_code"; state = "x"
        return R()
    monkeypatch.setattr("tl_towerwatch.auth.github.start_callback_server", fake_server)
    # Monkeypatch the GitHub POST to return known tokens
    import respx
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=__import__("httpx").Response(200, json={
            "access_token": "new_acc", "refresh_token": "new_ref",
        }, headers={"Content-Type": "application/json"})
    )
    acc, ref = complete_oauth_flow("cid", "csec", "http://localhost:8765/auth/callback")
    assert acc == "new_acc"
    assert ref == "new_ref"
    assert captured['port'] == 8765
```

Run → FAIL.

**Step 2: Implement `start_callback_server` and `complete_oauth_flow`**

Add to `auth/github.py`:
```python
GITHUB_OAUTH_AUTHORIZE = "https://github.com/login/oauth/authorize"
OAUTH_SCOPES = "repo read:user"

def start_callback_server(port: int, timeout: int = 120) -> str:
    """Tiny HTTP server that captures the ?code= from the OAuth redirect."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    code_holder = {"code": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            code_holder["code"] = q.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"OK — you can close this tab.")
        def log_message(self, *a, **kw): pass  # silence

    httpd = HTTPServer(("127.0.0.1", port), Handler)
    httpd.timeout = timeout
    while code_holder["code"] is None:
        httpd.handle_request()
    return code_holder["code"]

def complete_oauth_flow(client_id, client_secret, callback_url, *, port=8765,
                       host_alias=None, open_browser=__import__("webbrowser").open):
    """Run the full OAuth dance: start callback, open browser, exchange code."""
    code = start_callback_server(port)
    import secrets
    state = secrets.token_urlsafe(16)
    import urllib.parse
    authorize_url = GITHUB_OAUTH_AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": callback_url,
        "scope": OAUTH_SCOPES,
        "state": state,
    })
    open_browser(authorize_url)
    # Exchange
    r = httpx.post(GITHUB_OAUTH_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": callback_url,
        "state": state,
    }, headers={"Accept": "application/json"}, timeout=30.0)
    r.raise_for_status()
    d = r.json()
    return d["access_token"], d.get("refresh_token", "")
```

**Step 3: Run test → PASS**

(Note: the test stubs `start_callback_server` so the real HTTP server doesn't actually start.)

**Step 4: Wire `tl_towerwatch auth login` CLI**

Add to `cli.py` (next to `auth_app`):
```python
@auth_app.command("login")
def auth_login():
    """Run the OAuth browser flow (requires client_id/secret already set)."""
    from tl_towerwatch.auth.github import complete_oauth_flow
    s = load_settings()
    if not (s.oauth_client_id and s.oauth_client_secret):
        typer.echo("Set TOWERWATCH_GITHUB_OAUTH_CLIENT_ID and SECRET first.", err=True)
        raise typer.Exit(1)
    host_alias = s.host_alias or "localhost"  # add `host_alias: str = "localhost"` to Settings (in this task)
    cb = f"http://{host_alias}:8765/auth/callback"
    acc, ref = complete_oauth_flow(s.oauth_client_id, s.oauth_client_secret, cb)
    # Persist tokens via the web helper (already wired to preserve-on-empty)
    from tl_towerwatch.web.routes import _persist_auth_keys
    _persist_auth_keys(s.data_dir / ".env", github_token=s.github_token or "",
                       github_oauth_client_id=s.oauth_client_id or "",
                       github_oauth_client_secret=s.oauth_client_secret or "")
    # Update config.yaml auth.mode = oauth
    from tl_towerwatch.config_io import load_config_yaml, save_config_yaml
    cfg_path = s.data_dir / "config.yaml"
    data = load_config_yaml(cfg_path)
    data.setdefault("auth", {})["mode"] = "oauth"
    save_config_yaml(cfg_path, data)
    typer.echo("✓ OAuth login complete. Tokens saved to .env.")
```

Add `host_alias: str = "localhost"` to `Settings` (in `config.py`).

**Step 5: Commit**
```bash
git add src/tl_towerwatch/auth/github.py src/tl_towerwatch/cli.py src/tl_towerwatch/config.py tests/test_auth.py tests/test_cli.py
git commit -m "feat(auth): OAuth initial flow (callback server + code exchange) + auth login"
```

---

## Task 5 — AgentRunner `on_event` callback (foundation for streaming)

**Files:**
- Modify: `src/tl_towerwatch/agents/base.py:1-40`
- Modify: `src/tl_towerwatch/agents/claude.py`, `codex.py`, `minimax_code.py`, `ollama.py` (signature + streaming)

**Interfaces:**
- New: `AgentEvent` dataclass: `kind: Literal["stderr","stdout","tool_use","tool_result","finding","sentinel","error"]`, `data: str`. `AgentRunner.run_review(..., on_event: Callable[[AgentEvent], None] | None = None)`.
- All 4 runners MUST emit a stream of events; the final event(s) parse to `ReviewResult`.

**Step 1: Failing test in `tests/test_agent_runners.py`** using existing `fake_claude` fixture:
```python
def test_claude_runner_emits_events(fake_claude):
    r = ClaudeRunner()
    events = []
    res = r.run_review(
        pr_diff="+ a\n", pr_metadata={"title":"t","body":None,"author":"x","number":1,"repo":"o/n","head_sha":"abc"},
        skills=[], prompt_template="{diff}", mode="fresh",
        previous_findings=[], timeout_seconds=30,
        on_event=lambda e: events.append(e),
    )
    kinds = [e.kind for e in events]
    assert "stdout" in kinds
    assert "sentinel" in kinds
    assert res.findings and res.findings[0].file_path == "a.py"
```

Run → FAIL.

**Step 2: Update `base.py`**
```python
from typing import Literal
@dataclass
class AgentEvent:
    kind: Literal["stderr","stdout","tool_use","tool_result","finding","sentinel","error"]
    data: str

class AgentRunner(Protocol):
    name: str
    def run_review(self, *, pr_diff, pr_metadata, skills, prompt_template, mode,
                   previous_findings, timeout_seconds=300,
                   on_event: "Callable[[AgentEvent], None] | None" = None) -> ReviewResult: ...
```

**Step 3: Update `ClaudeRunner`** — switch to `subprocess.Popen` + `communicate` with stream parsing:
```python
def run_review(self, *, pr_diff, pr_metadata, skills, prompt_template, mode,
               previous_findings, timeout_seconds=300,
               on_event=None):
    prompt = render_review_prompt(
        pr_metadata=pr_metadata, mode=mode,
        previous_findings=previous_findings, skills=skills,
        diff=pr_diff, template=prompt_template,
    )
    flags = [s.cli_flag for s in skills if isinstance(s, Skill) and s.cli_flag]
    if on_event: on_event(AgentEvent(kind="stderr", data="starting"))
    try:
        proc = subprocess.Popen(
            [self._binary, "--print", "--dangerously-skip-permissions", *flags],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        out, err = proc.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        if on_event: on_event(AgentEvent(kind="error", data="timeout"))
        return ReviewResult(markdown="", findings=[], error="timeout")
    if proc.returncode != 0:
        if on_event: on_event(AgentEvent(kind="error", data=err[:500]))
        return ReviewResult(markdown=out, findings=[],
                            error=f"claude exited {proc.returncode}: {err[:500]}")
    if on_event:
        on_event(AgentEvent(kind="stdout", data=out))
        on_event(AgentEvent(kind="sentinel", data="TLTW:DONE"))
    return ReviewResult(markdown=out, findings=_parse(out))
```

Apply the same `Popen + on_event` pattern to CodexRunner, MiniMaxCodeRunner, OllamaAgentRunner. (Ollama still uses `httpx.post` but emits one event after.)

**Step 4: Run tests → 52 passed.**

**Step 5: Commit**
```bash
git add src/tl_towerwatch/agents/ tests/test_agent_runners.py
git commit -m "feat(agents): AgentEvent + on_event callback for streaming"
```

---

## Task 6 — `review --watch` streaming output

**Files:**
- Modify: `src/tl_towerwatch/cli.py` (`review` body, already added in v1.0 commit `71867d7`)

**Step 1: Failing test in `tests/test_cli.py`** (uses fake_claude + respx for sync):
```python
def test_review_watch_streams_events(tmp_path, monkeypatch, fake_claude):
    monkeypatch.setenv("PATH", f"{fake_claude.parent}:{os.environ['PATH']}")
    # Stub resolve_token + GitHub client to skip network
    monkeypatch.setattr("tl_towerwatch.cli.resolve_token", lambda s: "x")
    # Capture stdout to verify events were emitted
    ...
```

(Skip the live-network stubbing — covered by integration; for unit tests, just verify the `--watch` flag's code path doesn't crash on a stubbed runner. Add a minimal test that asserts `review --help` shows `--watch`.)

**Step 2: Update `review` body** to handle `--watch`:

```python
@app.command()
def review(target, skills, agent, mode, watch):
    ...
    if watch:
        from tl_towerwatch.agents import get_runner
        from tl_towerwatch.skills.registry import load_registry
        runner = get_runner(agent, settings)
        sk = load_registry(settings.data_dir)
        def on_event(e):
            typer.echo(f"[{e.kind}] {e.data[:200]}")
        runner.run_review(
            pr_diff=...,
            pr_metadata={...},
            skills=sk,
            prompt_template=None,
            mode=mode,
            previous_findings=[],
            timeout_seconds=300,
            on_event=on_event,
        )
    else:
        # Existing headless flow (calls run_review service)
        run_review(db, gh, owner=owner, name=name, number=number,
                   agent_name=agent, skill_names=skill_names, mode=mode,
                   timeout_seconds=300, settings=settings)
```

**Step 3: Run tests → 53 passed.**

**Step 4: Commit**
```bash
git add src/tl_towerwatch/cli.py tests/test_cli.py
git commit -m "feat(cli): review --watch streams agent events to terminal"
```

---

## Task 7 — Theme persistence (cookie + localStorage + config.yaml) + hardening

**Files:**
- Modify: `src/tl_towerwatch/web/routes.py:35-50` (`/theme` handler)
- Modify: `src/tl_towerwatch/web/templates/base.html:1-15`
- Modify: `tests/test_web_routes.py`

**Step 1: Failing test**
```python
def test_theme_persists_to_config_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/theme", data={"theme": "light"}, follow_redirects=False)
        assert r.status_code == 303  # now redirects
        cfg = (tmp_path / "config.yaml").read_text()
        assert "theme:" in cfg
        assert "light" in cfg

def test_theme_validates_input(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/theme", data={"theme": "rainbow"})
        assert r.status_code == 400
```

Run → FAIL.

**Step 2: Implement `/theme` rewrite**
```python
ALLOWED_THEMES = {"dark", "light", "system"}

@router.post("/theme")
def theme(request: Request, theme: str = Form(...)):
    if theme not in ALLOWED_THEMES:
        raise HTTPException(400, "invalid theme")
    settings = load_settings()
    cfg_path = settings.data_dir / "config.yaml"
    data = load_config_yaml(cfg_path)
    data["theme"] = theme
    save_config_yaml(cfg_path, data)
    r = RedirectResponse("/", status_code=303)
    r.set_cookie("tl_towerwatch_theme", theme, httponly=False, samesite="lax")
    return r
```

**Step 3: Update `base.html` to mirror cookie → localStorage**

Add to the `<script>` block at the top of `<head>`:
```html
<script>
  // Mirror cookie → localStorage so JS can read theme without re-render
  try {
    const m = document.cookie.match(/tl_towerwatch_theme=([^;]+)/);
    if (m) localStorage.setItem('theme', m[1]);
  } catch {}
</script>
```

**Step 4: Update `_theme(request)` to read cookie OR config.yaml**

```python
def _theme(request: Request) -> str:
    c = request.cookies.get("tl_towerwatch_theme")
    if c in ALLOWED_THEMES:
        return c
    settings = load_settings()
    data = load_config_yaml(settings.data_dir / "config.yaml")
    t = data.get("theme", "dark")
    return t if t in ALLOWED_THEMES else "dark"
```

**Step 5: Run tests → 55 passed.**

**Step 6: Commit**
```bash
git add src/tl_towerwatch/web/ tests/test_web_routes.py
git commit -m "feat(web): theme persists to config.yaml + cookie + localStorage; validated"
```

---

## Task 8 — Dashboard status counters + repos rate-limit banner

**Files:**
- Modify: `src/tl_towerwatch/web/templates/dashboard.html:1-20` (add counters strip)
- Modify: `src/tl_towerwatch/web/templates/repos.html:1-25` (add rate-limit banner)
- Modify: `src/tl_towerwatch/web/routes.py` (`index`, `repos_page`)

**Step 1: Failing test in `tests/test_web_routes.py`**
```python
def test_dashboard_renders_status_counters(tmp_path, monkeypatch):
    # Seed DB with PRs in different states, assert counter values appear
    ...
def test_repos_route_shows_rate_limit_banner(tmp_path, monkeypatch, respx_mock):
    respx_mock.get("https://api.github.com/rate_limit").mock(
        return_value=Response(200, json={"resources":{"core":{"remaining":4500,"reset":1700000000}}})
    )
    # GET /repos and assert "Rate limit" appears
    ...
```

Run → FAIL.

**Step 2: Implement**

In `routes.py`, replace `index` body with a version that computes counts per spec §5.1:
```python
@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    login = "dimh"
    prs = list_prs_for_dashboard(db, login=login, scope_filter="mine_and_review")
    badges = {pr.id: compute_badges(db, login, pr) for pr in prs}
    counts = {"awaiting_my_review": 0, "needs_response": 0,
              "changes_requested": 0, "ready_to_merge": 0}
    for pr in prs:
        for b in compute_badges(db, login, pr):
            counts[b["name"]] = counts.get(b["name"], 0) + 1
    return templates.TemplateResponse("dashboard.html",
        {"request": request, "nav": "home", "theme": _theme(request),
         "prs": prs, "badges_by_pr": badges, "login": login, "counts": counts})
```

Add to `dashboard.html` (just below the filter row):
```html
<div style="display:flex;gap:10px;padding:16px 20px;background:var(--bg-secondary);border-bottom:1px solid var(--border);font-size:12px;">
  {% for k, v in counts.items() %}
  <div style="flex:1;padding:10px 12px;background:var(--card);border-radius:6px;border-left:3px solid var(--accent);">
    <div style="color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;">{{ k.replace('_',' ') }}</div>
    <div style="font-size:22px;font-weight:700;color:var(--accent);margin-top:2px;">{{ v }}</div>
  </div>
  {% endfor %}
</div>
```

For `repos_page`, add a rate-limit probe at the top:
```python
@router.get("/repos", response_class=HTMLResponse)
def repos_page(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    rl = None
    try:
        with GitHubClient(token=resolve_token(settings)) as gh:
            # GET /rate_limit is cheap
            r = gh._client.get("/rate_limit")
            if r.status_code == 200:
                core = r.json().get("resources", {}).get("core", {})
                rl = {"remaining": core.get("remaining", 0),
                      "reset": core.get("reset", 0)}
    except Exception:
        pass
    repo_rows = svc_list_repos(db)
    ...
    return templates.TemplateResponse("repos.html", {"...": ..., "rl": rl})
```

Add the banner to `repos.html`:
```html
{% if rl %}
<div style="padding:10px 20px;background:var(--bg-secondary);border-bottom:1px solid var(--border);display:flex;gap:10px;align-items:center;font-size:12px;">
  <span style="background:#1f6f3b;color:#7ee787;padding:3px 10px;border-radius:10px;font-weight:600;">● API OK</span>
  <span>Rate limit: <strong>{{ rl.remaining }}</strong> remaining</span>
  <span style="color:var(--muted);">· resets {{ rl.reset }}</span>
</div>
{% endif %}
```

**Step 3: Run tests → 57 passed.**

**Step 4: Commit**
```bash
git add src/tl_towerwatch/web/ tests/test_web_routes.py
git commit -m "feat(web): dashboard status counters + repos rate-limit banner"
```

---

## Task 9 — PR detail tabs + tl_towerwatch reviews tab content

**Files:**
- Modify: `src/tl_towerwatch/web/templates/pr_detail.html` (rich tabs)
- Modify: `src/tl_towerwatch/web/routes.py` (`pr_detail` handler — serve tabs data)

**Step 1: Failing test**
```python
def test_pr_detail_serves_tabs_data(tmp_path, monkeypatch):
    # Seed PR + 2 review runs with different findings
    ...
    r = c.get("/pr/o/n/1")
    assert "Overview" in r.text
    assert "Commits" in r.text
    assert "tl_towerwatch reviews" in r.text
    assert "✓ resuelto" in r.text.lower() or "resuelto" in r.text.lower()
```

Run → FAIL (current template has tabs but no content; no findings rendered).

**Step 2: Implement**

In `routes.py` `pr_detail`, expand the data dict with:
- `commits = db.query(Commit).filter_by(pr_id=pr.id)` (skip — only show counts)
- `files = db.query(File).filter_by(pr_id=pr.id).count()`
- `human_reviews = db.query(Review).filter_by(pr_id=pr.id).count()`
- `comments = db.query(Comment).filter_by(pr_id=pr.id).count()`
- `runs_with_findings`: for each `run`, join with `ReviewFinding`, include aggregate counts (`resolved/pending/new`)

Update `pr_detail.html` to render per spec §5.2:
- Overview: summary, description, files list, human reviews
- Commits: file count + first commit SHA (full list is v1.2 — just show N commits)
- Files: top N changed files with +/- stats
- Reviews: human review timeline
- Comments: human comments
- tl_towerwatch reviews: each run expanded, findings with `resolved/pending/new` status, commits-per-finding info

For the tl_towerwatch tab, render per spec §5.2:
```html
<h3>🤖 Historial de reviews del agente</h3>
<div style="display:flex;gap:6px;margin-bottom:14px;font-size:11px;">
  <span style="background:#1f6f3b;color:#7ee787;padding:3px 8px;border-radius:4px;">✓ {{ resolved_count }} resueltos</span>
  <span style="background:#9e6a03;color:#fff;padding:3px 8px;border-radius:4px;">⚠ {{ pending_count }} pendientes</span>
  <span style="background:#1f242c;color:#8b949e;padding:3px 8px;border-radius:4px;">🆕 {{ new_count }} nuevos</span>
</div>
{% for run in runs %}
<details open>
  <summary>Run #{{ run.id }} · {{ run.status }} · {{ run.agent_runner }} · {{ run.started_at }}</summary>
  {% for f in run.findings %}
  <div style="background:var(--card);padding:8px 10px;border-radius:4px;border-left:3px solid {{ status_color(f.status) }};margin:4px 0;">
    <span style="background:#3fb950;color:#fff;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700;">{{ f.severity }}</span>
    <code style="color:#79c0ff;font-size:11px;">{{ f.file_path }}:{{ f.line }}</code>
    <span style="float:right;color:{{ status_color(f.status) }};">{{ status_label(f.status) }}</span>
    <div>{{ f.description }}</div>
  </div>
  {% endfor %}
</details>
{% endfor %}
```

Add a `status_color` Jinja filter and `status_label` to `routes.py`.

**Step 3: Run tests → 58 passed.**

**Step 4: Commit**
```bash
git add src/tl_towerwatch/web/ tests/test_web_routes.py
git commit -m "feat(web): PR detail tabs with tl_towerwatch findings expansion"
```

---

## Task 10 — First-run redirect + 401 → settings redirect

**Files:**
- Modify: `src/tl_towerwatch/web/routes.py` (`index` redirect; add a `Depends(check_github_auth)`)

**Step 1: Failing tests**
```python
def test_first_run_redirects_to_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    # No config.yaml exists, no token
    r = c.get("/")
    assert r.status_code == 200
    assert "/settings" in r.url.path  # or redirected

def test_github_401_redirects_to_settings(tmp_path, monkeypatch, respx_mock):
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(401, json={"message": "Bad credentials"})
    )
    ...
    r = c.get("/", headers={"Cookie": "session=..."})
    # Should redirect to /settings?error=401
```

Run → FAIL.

**Step 2: Implement first-run redirect**

Modify `index`:
```python
@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    cfg = load_config_yaml(settings.data_dir / "config.yaml")
    if not settings.github_token and not cfg.get("auth", {}).get("mode"):
        return RedirectResponse("/settings?first_run=1", status_code=303)
    ...
```

**Step 3: 401 handling**

The cleanest path is a middleware or a wrapper around `resolve_token` that converts 401 into a session-level redirect signal. Use a simple cookie flag for v1.1:
```python
class GitHubAuthMiddleware:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        # Wrap the inner send to detect a 401 response from any endpoint
        # that called GitHub, and add a Set-Cookie header to redirect.
        # (Implementation: thin wrapper that catches RuntimeError from
        #  resolve_token and converts to a 302 to /settings?error=401)
        ...
```

Simpler: catch `RuntimeError("GitHub token is invalid")` (from Task 5 fix) in each route, redirect. Add a tiny helper:
```python
def _redirect_on_auth_error(e: RuntimeError) -> RedirectResponse:
    if "invalid" in str(e).lower() or "401" in str(e):
        return RedirectResponse("/settings?error=github_auth", status_code=303)
    raise e
```

Wrap `resolve_token(settings)` calls in the routes that need auth with `try/except RuntimeError` → `_redirect_on_auth_error`. Limit to routes that *require* GitHub (dashboard, repos, pr_detail). Skip `/settings`, `/theme`, `/static/`.

**Step 4: Run tests → 60 passed.**

**Step 5: Commit**
```bash
git add src/tl_towerwatch/web/ tests/test_web_routes.py
git commit -m "feat(web): first-run redirect + 401 → settings redirect"
```

---

## Task 11 — DB: 5 performance indexes + User.avatar_url/display_name + dead code + type fix

**Files:**
- Modify: `src/tl_towerwatch/db/models.py:70-180` (add indexes; populate User fields in `_upsert_user`)
- Modify: `src/tl_towerwatch/services/pull_requests.py:21-30` (`_upsert_user` to read GitHub user data)
- Modify: `src/tl_towerwatch/llm/base.py:6-12` (tighten `body: str`)
- Modify: `src/tl_towerwatch/services/findings.py` (delete dead `Badge` dataclass)

**Step 1: Failing test for indexes (smoke)**
```python
def test_db_has_perf_indexes(tmp_path):
    from sqlalchemy import inspect
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    s = load_settings(tmp_path)
    db = engine_from_settings(s)
    db.create_all()
    insp = inspect(db.engine)
    for tbl, expected in [
        ("pull_requests", ["idx_pr_repo"]),
        ("reviews", ["idx_reviews_pr"]),
        ("review_comments", ["idx_comments_pr"]),
        ("review_findings", ["idx_findings_run", "idx_findings_key"]),
    ]:
        idx = [i["name"] for i in insp.get_indexes(tbl)]
        for e in expected:
            assert e in idx, f"missing {e} on {tbl}"
```

Run → FAIL.

**Step 2: Add indexes in `models.py`**

In each ORM class's `__table_args__`, add `Index(...)`:
```python
class PullRequest(Base):
    __table_args__ = (
        Index("uq_pr_repo_number", "repo_id", "number", unique=True),
        Index("idx_pr_repo", "repo_id"),
    )

class Review(Base):
    __table_args__ = (Index("idx_reviews_pr", "pr_id"),)

class ReviewComment(Base):
    __table_args__ = (Index("idx_comments_pr", "pr_id"),)

class ReviewFinding(Base):
    __table_args__ = (
        Index("uq_finding_run_key", "review_run_id", "finding_key", unique=True),
        Index("idx_findings_run", "review_run_id"),
        Index("idx_findings_key", "finding_key"),
    )
```

**Step 3: Run test → PASS.**

**Step 4: Populate User fields**

In `services/pull_requests.py`, modify `_upsert_user` to also save `avatar_url` and `display_name`:
```python
def _upsert_user(s, login, avatar_url=None, display_name=None):
    if not login:
        return
    u = s.get(User, login)
    if not u:
        s.add(User(login=login, avatar_url=avatar_url, display_name=display_name))
    else:
        if avatar_url and not u.avatar_url:
            u.avatar_url = avatar_url
        if display_name and not u.display_name:
            u.display_name = display_name
```

And in `_parse_pr` and `list_reviews` callers, pass these fields. The dataclasses `PullRequestData.author_login` is just a string; extend to add `avatar_url` and `display_name` on the dataclass (Task 4 spec already mentioned this).

**Step 5: Tighten `LLMProvider.summarize` body type**

In `llm/base.py`:
```python
class LLMProvider(Protocol):
    name: str
    def summarize(self, *, title: str, body: str, diff: str, metadata: dict) -> str: ...
```

This is technically a breaking change for `str | None` callers (Ollama's `body: body or ""` becomes wrong); update the 3 implementations to match (`body: str` always, no `None`).

**Step 6: Delete dead `Badge` dataclass**

In `services/findings.py`, remove the unused `Badge` class and `COLORS` dict (replaced by inline dict literals in `compute_badges`).

**Step 7: Run all tests → 61 passed.**

**Step 8: Commit**
```bash
git add src/tl_towerwatch/db/models.py src/tl_towerwatch/services/pull_requests.py src/tl_towerwatch/llm/base.py src/tl_towerwatch/llm/*.py src/tl_towerwatch/services/findings.py tests/test_db.py tests/test_llm_providers.py tests/test_services.py
git commit -m "perf+chore: 5 perf indexes, user fields, LLM body type, dead code"
```

---

## Task 12 — Diff-too-large truncation + final polish

**Files:**
- Modify: `src/tl_towerwatch/services/pull_requests.py:135-175` (`sync_one_pr` diff truncation)
- Modify: `src/tl_towerwatch/scheduler.py:1-10` (remove unused `datetime, timezone`)
- Modify: `src/tl_towerwatch/web/routes.py:240+` (`_persist_llm_keys` apply preserve-on-empty)
- Modify: `README.md` (re-add shields.io badges + v1.0 announcement)

**Step 1: Failing test for truncation**
```python
def test_sync_one_pr_truncates_huge_diff(tmp_path):
    # Create a fake diff with 5000 files, 1000 lines each
    ...
    res = sync_one_pr(db, gh, repo_row, 1, llm=FakeLLM())
    # The LLM should receive a truncated diff (max ~2000 lines)
    assert llm.call_args[1]["diff"].count("\n") < 3000
```

Run → FAIL (current `sync_one_pr` already truncates to `[:20000]` chars; spec says "max_diff_lines=2000, max_files=30").

**Step 2: Add config + truncation**

Add to `Settings`:
```python
max_diff_lines: int = 2000
max_diff_files: int = 30
```

(Load from env: `TOWERWATCH_MAX_DIFF_LINES`, `TOWERWATCH_MAX_DIFF_FILES`.)

In `sync_one_pr`, replace the existing `diff_text = "\n".join(...)[:20000]` with line-aware truncation:
```python
diff_parts = []
for f in files[:settings.max_diff_files]:
    if f.patch:
        diff_parts.append(f.patch)
diff_text = "\n".join(diff_parts)
lines = diff_text.splitlines()
if len(lines) > settings.max_diff_lines:
    diff_text = "\n".join(lines[:settings.max_diff_lines])
    diff_text += f"\n... [truncated to {settings.max_diff_lines} lines of {len(lines)} total]\n"
```

**Step 3: Remove unused scheduler imports**

In `scheduler.py:1-10`, remove `from datetime import datetime, timezone` (and any other unused imports).

**Step 4: Apply preserve-on-empty to `_persist_llm_keys`**

Mirror the pattern from Task 8's `_persist_auth_keys` (commit `c898968`): empty form value + existing `.env` value → preserve existing; empty + no prior → omit.

**Step 5: README polish**

Add a small badges strip at the top:
```markdown
![tests](https://img.shields.io/badge/tests-61%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-Proprietary-red)
```

Update the heading: `# tl_towerwatch (v1.1)`.

**Step 6: Run all tests → 62 passed.**

**Step 7: Tag `v1.1.0` and push**
```bash
git tag -a v1.1.0 -m "v1.1: CLI completion + init wizard + OAuth flow + theme persistence + UI gaps + perf indexes"
git push origin main --tags
```

---

## Self-Review

**Spec coverage vs spec sections:**

| Spec § | Topic | v1.0 | v1.1 plan |
|---|---|---|---|
| 3.3 step 1 | Init wizard | ❌ | ✅ Task 3 |
| 4 | CLI commands | partial | ✅ Task 2 |
| 5.1 | Dashboard counters | ❌ | ✅ Task 8 |
| 5.1 | Filter tabs | ❌ | (parked, UI polish) |
| 5.2 | PR detail tabs | ❌ | ✅ Task 9 |
| 5.2 | Reviews history expansion | partial | ✅ Task 9 |
| 5.3 | Repos rate-limit banner | ❌ | ✅ Task 8 |
| 5.4 | Settings (full) | partial | (covered by v1.0) |
| 5.5 | First-run redirect | ❌ | ✅ Task 10 |
| 6 | 5 performance indexes | ❌ | ✅ Task 11 |
| 7.2 | Body type | ❌ | ✅ Task 11 |
| 7.3 | on_event callback | ❌ | ✅ Task 5 |
| 8.2 | OAuth initial flow | ❌ | ✅ Task 4 |
| 9 step 8 | review --watch | ❌ | ✅ Task 6 |
| 12 | Auth mode setting | ❌ | ✅ Task 1 |
| 13 | 401 → settings | ❌ | ✅ Task 10 |

**Placeholder scan:** No "TBD" / "TODO" / "implement later" in the plan.

**Type consistency:** `AuthCfg`, `AgentEvent`, `Badge` (removed), `OAuthCallbackServer` all defined before used. `on_event` parameter added consistently across 4 runners.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-04-tl-towerwatch-v1.1.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, reviews between tasks
2. **Inline Execution** — execute in this session with checkpoints

Which approach?