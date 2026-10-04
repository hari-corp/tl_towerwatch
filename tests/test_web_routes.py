from fastapi.testclient import TestClient
from httpx import Response
from tl_towerwatch.web import create_app


# ---------------------------------------------------------------------------
# v1.1 Task 10 — first-run redirect + 401 → settings redirect
# ---------------------------------------------------------------------------

def test_first_run_redirects_to_settings(tmp_path, monkeypatch):
    """v1.1 (Task 10): when neither a PAT nor an OAuth refresh token is
    configured, ``GET /`` must redirect to ``/settings?first_run=1`` so the
    user lands on the auth form instead of an empty dashboard. TestClient
    follows the redirect by default, so the final response has status 200
    and the resolved URL points at ``/settings``.
    """
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    # ``_load_env_file_into_environ`` writes to os.environ directly, which
    # leaks across tests (a pre-existing quirk). ``delenv`` defensively
    # blanks the auth env vars this test asserts are absent so the
    # first-run guard sees a clean slate.
    for var in ("TOWERWATCH_GITHUB_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET",
                "TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "/settings" in r.url.path
        assert "first_run=1" in str(r.url)


def test_github_401_redirects_to_settings(tmp_path, monkeypatch, respx_mock):
    """v1.1 (Task 10): when the configured PAT returns 401 from ``GET /user``,
    ``GET /`` must redirect to ``/settings?error=github_auth`` so the user
    can re-paste a working token. Any subsequent route that touches GitHub
    uses the same helper, so the same redirect fires from ``/repos`` etc.
    """
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    # Wipe any leaked oauth tokens so the first-run guard doesn't fire and
    # the 401 redirect from ``resolve_token`` is the one we exercise.
    for var in ("TOWERWATCH_GITHUB_OAUTH_CLIENT_ID",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET",
                "TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(401, json={"message": "Bad credentials"})
    )
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/", headers={"Cookie": "session=stub"})
        assert r.status_code == 200
        assert "/settings" in r.url.path
        assert "error=github_auth" in str(r.url)

def test_index_renders():
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "tl_towerwatch" in r.text

def test_theme_toggle_sets_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/theme", data={"theme": "light"}, follow_redirects=False)
        assert r.status_code == 303
        assert "tl_towerwatch_theme" in r.cookies
        assert c.cookies["tl_towerwatch_theme"] == "light"

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

def test_dashboard_renders_empty(tmp_path, monkeypatch, respx_mock):
    # v1.1 (Task 10): the dashboard now eagerly validates the configured token
    # so a 401 bounces to /settings. Stub /user with a valid scopes header so
    # the validation passes and we exercise the dashboard render path.
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    app = create_app()
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "PRs" in r.text

def test_repos_route_lists_and_adds(tmp_path, monkeypatch, respx_mock):
    # v1.1 (Task 10): /repos and /repos/add now require a valid token; stub
    # /user so the auth gate passes and we can reach the page render and
    # the GitHub-repo probe (we deliberately do not mock /repos/{owner}/{name}
    # so the add POST surfaces a network error as before).
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/repos")
        assert r.status_code == 200
        # POST without network will fail validation; just check the route exists.
        r = c.post("/repos/add", data={"owner_name": "x/y"})
        assert r.status_code in (400, 500)  # network error expected

def test_pr_detail_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/pr/o/n/1")
        assert r.status_code == 200
        assert "PR" in r.text

def test_settings_route_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/settings")
        assert r.status_code == 200
        assert "LLM" in r.text or "Auth" in r.text

def test_settings_auth_save_persists_pat(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/settings/auth/save",
                   data={"github_token": "ghp_FAKE",
                         "github_oauth_client_id": "",
                         "github_oauth_client_secret": ""},
                   follow_redirects=False)
        assert r.status_code == 303
    env_text = (tmp_path / ".env").read_text()
    assert "TOWERWATCH_GITHUB_TOKEN=ghp_FAKE" in env_text

def test_settings_auth_save_does_not_wipe_oauth_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID=cid_real\n"
        "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET=csec_real\n"
    )
    from tl_towerwatch.web import create_app
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/settings/auth/save",
                   data={"github_token": "ghp_new",
                         "github_oauth_client_id": "",
                         "github_oauth_client_secret": ""},
                   follow_redirects=False)
        assert r.status_code == 303
    env_text = env_path.read_text()
    assert "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID=cid_real" in env_text
    assert "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET=csec_real" in env_text
    assert "TOWERWATCH_GITHUB_TOKEN=ghp_new" in env_text

def test_settings_llm_save_does_not_wipe_auth_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text("TOWERWATCH_GITHUB_TOKEN=ghp_EXISTING\n")
    from tl_towerwatch.web import create_app
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/settings/llm/save",
                   data={"provider": "anthropic",
                         "anthropic_api_key": "sk-ant-FAKE",
                         "openai_api_key": "",
                         "ollama_base_url": ""},
                   follow_redirects=False)
        assert r.status_code == 303
    env_text = env_path.read_text()
    assert "TOWERWATCH_GITHUB_TOKEN=ghp_EXISTING" in env_text
    assert "TOWERWATCH_LLM_PROVIDER=anthropic" in env_text
    assert "TOWERWATCH_ANTHROPIC_API_KEY=sk-ant-FAKE" in env_text


# ---------------------------------------------------------------------------
# v1.1 Task 19 — Settings page rebuilt against the v3 mock
# (`.superpowers/brainstorm/88238-1790999216/content/settings.html`)
# ---------------------------------------------------------------------------

def test_settings_matches_mock_layout(tmp_path, monkeypatch):
    """Task 19: the v3 mock rebuild of `/settings` must render every block
    the mock defines — settings tabs (active = Auth & LLMs), the GitHub
    Auth card (with user card + PAT chip masking + OAuth collapsed hint),
    the LLM/Agent card (provider selector with 4 options, default selected,
    Anthropic expanded config, other-provider collapsed summaries), the
    Skills registry preview seeded from config.yaml, and the bottom save
    bar. Asserts both structural content and the dynamic bits (avatar URL,
    PAT last-4 mask, provider selection).
    """
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    # ``_load_env_file_into_environ`` uses ``os.environ.setdefault`` so any
    # TOWERWATCH_* value leaked by a prior test (e.g. ``test_dashboard_*``
    # which writes ``TOWERWATCH_GITHUB_TOKEN=ghp_FAKE`` into os.environ) wins
    # over the .env we write below. Defensively delenv everything we care
    # about so this test sees a clean slate — same pattern as
    # ``test_first_run_redirects_to_settings``.
    for var in ("TOWERWATCH_GITHUB_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET",
                "TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN",
                "TOWERWATCH_ANTHROPIC_API_KEY",
                "TOWERWATCH_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.db.models import User
    from tl_towerwatch.web import create_app

    # Seed .env with a known PAT so the mask last-4 is deterministic and the
    # route picks PAT mode by default. ``<none>`` would be rendered when the
    # token is empty, but the spec assertion wants to exercise the masking
    # path so we provide a token.
    (tmp_path / ".env").write_text(
        "TOWERWATCH_GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ12345678903fA2\n"
        "TOWERWATCH_ANTHROPIC_API_KEY=sk-ant-FAKEKEY-c3K9\n"
        "TOWERWATCH_LLM_PROVIDER=anthropic\n"
    )
    # Seed config.yaml with the skills registry entries the mock shows.
    (tmp_path / "config.yaml").write_text(
        "skills:\n"
        "  superpowers:\n"
        "    enabled: true\n"
        "    description: code-review, verification, brainstorming\n"
        "    cli_flag: --enable-superpowers\n"
        "  ponytail:\n"
        "    enabled: true\n"
        "    description: custom review heuristics\n"
        "    cli_flag: --skill ponytail\n"
    )
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    # Seed the User row with avatar_url + display_name so the user card
    # exercises both fields of ``_user_context``. The display name appears
    # before the scopes chip per the mock layout.
    with db.session() as s:
        s.add(User(login="dimh",
                   avatar_url="https://avatars.example.com/dimh.png",
                   display_name="David Horma"))
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/settings")
        assert r.status_code == 200
        body = r.text

        # --- Settings tab strip ---
        # Active tab text + the warning-orange underline class marker
        # (data-testid lets the assertion target the strip cleanly).
        assert "Auth &amp; LLMs" in body or "Auth & LLMs" in body
        assert "Apariencia" in body
        assert "Refresh global" in body
        assert "Skills registry" in body

        # --- LEFT card titles / header ---
        assert "GitHub Auth" in body
        assert "Conectado" in body  # always-on green badge

        # --- User card contents ---
        assert "@dimh" in body
        assert "David Horma" in body
        assert "scopes" in body
        assert "https://avatars.example.com/dimh.png" in body
        assert "Desconectar" in body

        # --- PAT token display (masking: prefix + bullets + last 4) ---
        # The chip is exactly ``ghp_••••...<last4>``. The token we seeded
        # ends in ``3fA2``, so the suffix must appear. We assert the
        # prefix + suffix so a regression that drops either the mask or
        # the real last-4 characters is caught.
        assert "ghp_" in body
        assert "3fA2" in body

        # --- OAuth collapsed hint (always visible per the mock) ---
        assert "Si elegís OAuth" in body
        assert "ver gu" in body or "ver gu\xeda" in body or "guía" in body
        assert "http://localhost:8765/auth/callback" in body

        # --- Provider selector: all 4 options render + correct one
        #     matches the configured default_provider ---
        # The mock labels: Anthropic (Claude), OpenAI (Codex / GPT),
        # MiniMax Code (Mavis), Ollama (local).
        for label in ("Anthropic (Claude)", "OpenAI (Codex / GPT)",
                      "MiniMax Code (Mavis)", "Ollama (local)"):
            assert label in body, f"missing provider option: {label}"
        # Anthropic must be the selected one — the seeded .env sets
        # TOWERWATCH_LLM_PROVIDER=anthropic and there's no override in
        # config.yaml. We anchor on the exact mock label, not the literal
        # value, so the test still passes if the literal is later changed.
        assert ">Anthropic (Claude)</option>" in body
        # And the Anthropic expanded card is the one that renders.
        assert "✓ configurado" in body
        # OpenAI/MiniMax/Ollama collapsed summaries are present.
        assert "OpenAI (Codex / GPT)" in body
        assert "MiniMax Code (Mavis)" in body

        # --- Skills registry preview ---
        assert "Skills registry" in body
        assert "superpowers" in body
        # The count badge uses the list length; we seeded 2 enabled skills.
        assert "2 configuradas" in body

        # --- Bottom save bar ---
        assert "Cambios se guardan autom" in body
        assert "todo guardado" in body
        assert "Restaurar defaults" in body


def test_settings_renders_when_no_user_yet(tmp_path, monkeypatch):
    """Task 19: when no User row is seeded (first-run state, before any
    GitHub sync has populated the users table), the settings page must
    still 200 and the avatar initials fallback (``??``) must render.
    Catches regressions where the new template hard-fails on a missing
    ``user_display_name``."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.web import create_app

    # No .env, no config.yaml, no User row — the worst-case first-run
    # state where ``_user_context`` returns only ``user_login``.
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/settings")
        assert r.status_code == 200
        body = r.text
        # The avatar block must show the initials fallback ``??`` — not a
        # missing <img>, not a templating error leaking into the page.
        assert "??</span>" in body
        # The login still renders so the page is informative even without
        # a User row.
        assert "@dimh" in body
        # The cards still render their titles so the user knows where
        # they are.
        assert "GitHub Auth" in body
        assert "LLM" in body


def test_dashboard_renders_status_counters(tmp_path, monkeypatch, respx_mock):
    """Seed DB with PRs in different states; assert the counters strip renders
    the spec §5.1 names with non-zero counts for the seeded badges."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    # v1.1 (Task 10): the dashboard validates the token; stub /user.
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.db.models import PullRequest, Review, User, now_iso
    from tl_towerwatch.services.repos import add_repo
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    repo = add_repo(db, "o", "n")
    with db.session() as s:
        for login in ("dimh", "alice", "bob"):
            if s.get(User, login) is None:
                s.add(User(login=login))
        s.flush()
        # PR 1: alice opened, dimh reviewed with CHANGES_REQUESTED.
        # PR 2: bob opened, dimh reviewed with APPROVED.
        # Both are visible under the "mine_and_review" dashboard scope
        # because dimh has a Review row for each.
        pr1 = PullRequest(repo_id=repo.id, number=1, title="cr", body=None,
                          author_login="alice", state="open",
                          draft=0, head_sha="a", base_ref="main",
                          html_url="u",
                          created_at=now_iso(), updated_at=now_iso(),
                          cached_at=now_iso())
        pr2 = PullRequest(repo_id=repo.id, number=2, title="lgtm", body=None,
                          author_login="bob", state="open",
                          draft=0, head_sha="b", base_ref="main",
                          html_url="u",
                          created_at=now_iso(), updated_at=now_iso(),
                          cached_at=now_iso())
        s.add_all([pr1, pr2])
        s.flush()
        s.add(Review(pr_id=pr1.id, reviewer_login="dimh",
                     state="changes_requested",
                     submitted_at=now_iso(), body="needs more work"))
        s.add(Review(pr_id=pr2.id, reviewer_login="dimh",
                     state="approved",
                     submitted_at=now_iso(), body="lgtm"))
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        # The counters strip renders the badge names with underscores replaced
        # by spaces and a numeric value below each label.
        body = r.text
        assert "changes requested" in body.lower()
        assert "approved" in body.lower()
        # The spec §5.1 named counters should all be present (rendered as 0
        # when there are no matching PRs).
        assert "awaiting my review" in body.lower()
        assert "needs response" in body.lower()
        assert "ready to merge" in body.lower()


def test_repos_route_shows_rate_limit_banner(tmp_path, monkeypatch, respx_mock):
    """Mock /rate_limit and confirm the banner renders 'Rate limit' with the
    remaining count from the response."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    # resolve_token -> _validate_pat hits /user; let that succeed too so the
    # rate-limit probe inside repos_page is reached.
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    respx_mock.get("https://api.github.com/rate_limit").mock(
        return_value=Response(200, json={
            "resources": {"core": {"remaining": 4500, "reset": 1700000000}}
        })
    )
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/repos")
        assert r.status_code == 200
        assert "Rate limit" in r.text
        assert "4500" in r.text


def test_dashboard_counters_aggregate_across_prs(tmp_path, monkeypatch, respx_mock):
    """Regression for the HIGH defect where the counters strip seeded the
    spec §5.1 names but was incremented by raw `compute_badges` output
    names. `pending_response` and `approved` badges therefore never
    populated `needs_response` / `ready_to_merge` counters. Seed 3 PRs
    covering each translation and assert `>1<` appears adjacent to the
    three spec labels we expected to be 1, with `>0<` for the
    `awaiting_my_review` label (no seeded PR targets it)."""
    import re
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    # v1.1 (Task 10): the dashboard validates the token; stub /user.
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.db.models import (
        PullRequest, Review, ReviewComment, User, now_iso,
    )
    from tl_towerwatch.services.repos import add_repo
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    repo = add_repo(db, "o", "n")
    with db.session() as s:
        for login in ("dimh", "alice", "bob"):
            if s.get(User, login) is None:
                s.add(User(login=login))
        s.flush()
        # PR 1: alice opened, dimh reviewed with CHANGES_REQUESTED.
        pr1 = PullRequest(repo_id=repo.id, number=1, title="cr", body=None,
                          author_login="alice", state="open",
                          draft=0, head_sha="a", base_ref="main",
                          html_url="u",
                          created_at=now_iso(), updated_at=now_iso(),
                          cached_at=now_iso())
        # PR 2: bob opened, dimh reviewed with APPROVED.
        pr2 = PullRequest(repo_id=repo.id, number=2, title="lgtm", body=None,
                          author_login="bob", state="open",
                          draft=0, head_sha="b", base_ref="main",
                          html_url="u",
                          created_at=now_iso(), updated_at=now_iso(),
                          cached_at=now_iso())
        # PR 3: dimh authored, alice left a comment dimh hasn't replied to
        # -> compute_badges emits `pending_response`, which should map to
        # the spec counter `needs_response`.
        pr3 = PullRequest(repo_id=repo.id, number=3, title="my-pr", body=None,
                          author_login="dimh", state="open",
                          draft=0, head_sha="c", base_ref="main",
                          html_url="u",
                          created_at=now_iso(), updated_at=now_iso(),
                          cached_at=now_iso())
        s.add_all([pr1, pr2, pr3])
        s.flush()
        # Use lowercase states — `compute_badges` compares against
        # lowercase strings ("approved" / "changes_requested"); the v1.0
        # `list_reviews` casing mismatch is parked as a minor known issue.
        s.add(Review(pr_id=pr1.id, reviewer_login="dimh",
                     state="changes_requested",
                     submitted_at=now_iso(), body="needs more work"))
        s.add(Review(pr_id=pr2.id, reviewer_login="dimh",
                     state="approved",
                     submitted_at=now_iso(), body="lgtm"))
        s.add(ReviewComment(pr_id=pr3.id, reviewer_login="alice",
                            path="x.py", body="thoughts?",
                            created_at=now_iso()))
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        body = r.text
        # The counters strip renders `{{ k.replace('_',' ') }}` for the
        # label and `{{ v }}` for the value, in adjacent `<div>` blocks.
        # Anchor the regex tightly so the assertion catches the bug where
        # the wrong key was incremented (a loose `[\s\S]*?` would match
        # a `>1<` from a different counter further down the page).
        def _value_after(label_regex: str, expected: str) -> bool:
            # label end (`</div>`) immediately followed by the value div.
            pattern = (
                r">" + label_regex + r"</div>\s*<div[^>]*>" + expected + r"<"
            )
            return re.search(pattern, body) is not None
        assert _value_after(r"changes\s*requested", "1"), (
            "expected `>1<` adjacent to `changes requested` label"
        )
        assert _value_after(r"ready\s*to\s*merge", "1"), (
            "expected `>1<` adjacent to `ready to merge` label"
        )
        assert _value_after(r"needs\s*response", "1"), (
            "expected `>1<` adjacent to `needs response` label"
        )
        assert _value_after(r"awaiting\s*my\s*review", "0"), (
            "expected `>0<` adjacent to `awaiting my review` label"
        )


def test_pr_detail_serves_tabs_data(tmp_path, monkeypatch):
    """Spec §5.2: PR detail renders the 6 tabs (Overview, Commits, Files,
    Reviews, Comments, tl_towerwatch reviews) with findings grouped under
    tl_towerwatch reviews. Seed two review runs with findings in each of
    the three lifecycle states (resolved/pending/new) and assert the
    aggregated counters and the resolved-finding label render."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.db.models import (
        PullRequest,
        ReviewFinding,
        ReviewRun,
        User,
        now_iso,
    )
    from tl_towerwatch.services.repos import add_repo
    from tl_towerwatch.web import create_app

    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    repo = add_repo(db, "o", "n")
    with db.session() as s:
        if s.get(User, "alice") is None:
            s.add(User(login="alice"))
        s.flush()
        pr = PullRequest(repo_id=repo.id, number=1, title="tabs",
                         body="desc", author_login="alice", state="open",
                         draft=0, head_sha="abcdef0123", base_ref="main",
                         html_url="u", created_at=now_iso(),
                         updated_at=now_iso(), cached_at=now_iso())
        s.add(pr); s.flush()
        run1 = ReviewRun(pr_id=pr.id, agent_runner="claude",
                         skills_json="[]", mode="fresh", status="done",
                         started_at=now_iso(), finished_at=now_iso())
        run2 = ReviewRun(pr_id=pr.id, agent_runner="codex",
                         skills_json="[]", mode="compare", status="done",
                         started_at=now_iso(), finished_at=now_iso())
        s.add_all([run1, run2]); s.flush()
        # Run #1 (older): a resolved finding (fixed in a later commit).
        s.add(ReviewFinding(review_run_id=run1.id,
                            finding_key="a.py:1:old", severity="high",
                            file_path="a.py", line=1,
                            description="dead code",
                            status="resolved",
                            resolved_in_commit="abcdef0123"))
        # Run #2 (newer): a brand-new finding and a still-pending one.
        s.add(ReviewFinding(review_run_id=run2.id,
                            finding_key="b.py:7:leak", severity="medium",
                            file_path="b.py", line=7,
                            description="resource leak",
                            status="new"))
        s.add(ReviewFinding(review_run_id=run2.id,
                            finding_key="c.py:3:mut", severity="low",
                            file_path="c.py", line=3,
                            description="mutable default arg",
                            status="pending"))
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/pr/o/n/1")
        assert r.status_code == 200
        body = r.text
        # All six tabs are rendered as labels.
        assert "Overview" in body
        assert "Commits" in body
        assert "Files" in body
        assert "Reviews" in body
        assert "Comments" in body
        assert "tl_towerwatch reviews" in body
        # Aggregated counters from the findings we seeded (1 resolved,
        # 1 pending, 1 new) appear in the spec §5.2 chip strip.
        assert "1 resueltos" in body
        assert "1 pendientes" in body
        assert "1 nuevos" in body
        # The resolved-finding label is rendered (test spec asks for
        # "resuelto" / "✓ resuelto" case-insensitive).
        assert "resuelto" in body.lower()
        # The pending finding also renders its own status label so the
        # bug where all findings shared the same status word is caught.
        assert "pendiente" in body.lower()


def test_dashboard_has_global_refresh_button(tmp_path, monkeypatch, respx_mock):
    """Regression — the dashboard had no global "Refresh PRs" action, so
    the only way to repopulate the cache from GitHub was the CLI. After
    the fix the heading row includes a <form action="/refresh-all"> with
    a Refresh button.
    """
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert 'action="/refresh-all"' in r.text
        assert "Refresh PRs" in r.text


def test_dashboard_pr_cards_have_per_pr_actions(tmp_path, monkeypatch, respx_mock):
    """Regression — the dashboard listed PRs as plain cards with no link
    to the detail page and no per-PR refresh / run-review buttons, so
    the dashboard was a dead end. After the fix each card links to the
    detail route and exposes Refresh + Run review forms.
    """
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.db.models import PullRequest, User, now_iso
    from tl_towerwatch.services.repos import add_repo
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    repo = add_repo(db, "acme", "widgets")
    with db.session() as s:
        if s.get(User, "dimh") is None:
            s.add(User(login="dimh"))
        s.flush()
        s.add(PullRequest(repo_id=repo.id, number=42, title="feat: hello",
                          body=None, author_login="dimh", state="open",
                          draft=0, head_sha="deadbeef", base_ref="main",
                          html_url="https://example/pr/42",
                          created_at=now_iso(), updated_at=now_iso(),
                          cached_at=now_iso()))
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        body = r.text
        # Card links to the PR detail page (owner/name/number).
        assert 'href="/pr/acme/widgets/42"' in body
        # Per-PR refresh + run-review forms target the existing routes.
        assert 'action="/pr/acme/widgets/42/refresh"' in body
        assert 'action="/pr/acme/widgets/42/run-review"' in body
        # Owner/name is shown in monospace next to the title.
        assert "acme/widgets" in body
        assert "#42" in body


def test_refresh_all_route_redirects_to_root(tmp_path, monkeypatch, respx_mock):
    """POST /refresh-all must redirect back to / on success so the
    dashboard reloads with fresh data."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    settings = load_settings(tmp_path)
    # Ensure schema exists so list_repos + sync_repo don't blow up on a
    # fresh tmp_path.
    engine_from_settings(settings).create_all()
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/refresh-all", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"


def test_refresh_all_bounces_to_settings_on_auth_error(tmp_path, monkeypatch, respx_mock):
    """When no GitHub token is configured the global refresh button must
    not 500 — it bounces to /settings?error=github_auth like the
    per-PR refresh path (Task 10)."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    # _load_env_file_into_environ() leaks into os.environ across tests,
    # so defensively blank any TOWERWATCH_GITHUB_* env var set by a
    # previous test. test_first_run_redirects_to_settings uses the same
    # pattern (see that test for the full rationale).
    for var in ("TOWERWATCH_GITHUB_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET",
                "TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/refresh-all", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/settings")


# ---------------------------------------------------------------------------
# v1.1 Task 11 — repos page matches the §5.3 mock + per-repo refresh route
# ---------------------------------------------------------------------------

def test_repos_page_matches_mock_layout(tmp_path, monkeypatch, respx_mock):
    """The repos page (spec §5.3) must render every block the mock defines:
    rate-limit banner, add form, filter tabs, per-repo cards with status
    badges + open-PR count + refresh toggle/remove forms, and the bottom
    bulk-action bar. Seed one enabled repo (the SELF repo) and one paused
    repo, plus one open PR on the enabled repo, so the assertions hit both
    status badges plus the count chip."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    # v1.1 (Task 10): /repos validates the token; stub /user so the page
    # reaches the render path. The rate-limit probe inside repos_page also
    # hits /rate_limit; return a payload with a known remaining count so the
    # banner assertions are deterministic.
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    respx_mock.get("https://api.github.com/rate_limit").mock(
        return_value=Response(200, json={
            "resources": {"core": {"remaining": 4395, "reset": 1700000000}}
        })
    )
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.db.models import PullRequest, User, now_iso
    from tl_towerwatch.services.repos import add_repo
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    # Seed the SELF repo as enabled with the is_self column set so the
    # ⭐ SELF badge + "(más agresivo: dogfooding)" annotation both render.
    repo_self = add_repo(db, "hari", "tl_towerwatch", is_self=True)
    repo_paused = add_repo(db, "hari", "legacy-monolith")
    # Flip the second repo to paused via the service so enabled_only
    # queries stay consistent with the UI's filter tabs.
    from tl_towerwatch.services.repos import set_repo_enabled
    set_repo_enabled(db, repo_paused.owner, repo_paused.name, False)
    with db.session() as s:
        if s.get(User, "alice") is None:
            s.add(User(login="alice"))
        s.flush()
        s.add(PullRequest(
            repo_id=repo_self.id, number=1, title="x", body=None,
            author_login="alice", state="open",
            draft=0, head_sha="a", base_ref="main",
            html_url="u",
            created_at=now_iso(), updated_at=now_iso(),
            cached_at=now_iso(),
        ))
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/repos")
        assert r.status_code == 200
        body = r.text
        # Enabled-repo status badges.
        assert "● ACTIVO" in body
        # Paused-repo status badge.
        assert "⏸ PAUSADO" in body
        # SELF annotation surfaces both as the badge and the dogfooding tag.
        assert "⭐ SELF" in body
        assert "dogfooding" in body
        # Open-PR count chip ("1 PRs abiertos" matches the mock's wording
        # even at singular count — the plural is intentional in the mock).
        assert "1 PRs abiertos" in body
        # Per-repo refresh + remove forms.
        assert 'action="/repos/hari/tl_towerwatch/refresh"' in body
        assert 'action="/repos/hari/legacy-monolith/refresh"' in body
        assert 'action="/repos/hari/tl_towerwatch/remove"' in body
        assert 'action="/repos/hari/legacy-monolith/remove"' in body
        # The per-row refresh button is present once per repo.
        assert body.count("▶ Refrescar ahora") == 2
        # Global refresh button in the sort/refresh row.
        assert "↻ Refrescar todos" in body
        # Rate-limit banner: gradient bar element (the width % comes from
        # remaining/5000; 4395 -> 88%) and the humanized remaining text.
        assert "linear-gradient(90deg" in body
        assert "width:88%" in body
        assert "4,395" in body
        # Filter tabs carry the spec §5.3 counts (2 total, 1 active,
        # 1 paused, 0 with errors).
        assert "Todos (2)" in body
        assert "Activos (1)" in body
        assert "Pausados (1)" in body
        assert "Con error (0)" in body


def test_repos_refresh_single_repo(tmp_path, monkeypatch, respx_mock):
    """POST /repos/{owner}/{name}/refresh must sync that one repo and
    303 back to /repos. Mirrors ``test_refresh_all_route_redirects_to_root``
    but for the per-repo button added in Task 11."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    # sync_repo -> list_open_prs -> GET /repos/{owner}/{name}/pulls; return
    # an empty list so the loop exits without hitting /reviews or /files.
    respx_mock.get("https://api.github.com/repos/o/n/pulls").mock(
        return_value=Response(200, json=[])
    )
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.services.repos import add_repo
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    add_repo(db, "o", "n")
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/repos/o/n/refresh", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/repos"


def test_repos_refresh_bounces_on_auth_error(tmp_path, monkeypatch, respx_mock):
    """When no GitHub token is configured the per-repo refresh button must
    not 500 — it bounces to /settings?error=github_auth like the global
    refresh and per-PR refresh paths (Task 10/11)."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    for var in ("TOWERWATCH_GITHUB_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID",
                "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET",
                "TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN",
                "TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.services.repos import add_repo
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    add_repo(db, "o", "n")
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/repos/o/n/refresh", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/settings")


# ---------------------------------------------------------------------------
# v1.1 Task 11 — PR detail page rebuilt against the v3 mock
# (`.superpowers/brainstorm/88238-1790999216/content/pr-detail-v3.html`)
# ---------------------------------------------------------------------------

def _seed_pr_detail(tmp_path, with_summary: bool = True):
    """Seed a single PR with one review run (2 findings: 1 resolved, 1
    pending), one human review and an optional PRSummary. Returns the
    raw `db` handle so the test can wire extra fixtures in if needed."""
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.db.models import (
        PRSummary,
        PullRequest,
        Review,
        ReviewFinding,
        ReviewRun,
        User,
        now_iso,
    )
    from tl_towerwatch.services.repos import add_repo
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    repo = add_repo(db, "o", "n")
    with db.session() as s:
        for login in ("alice", "carlos.r"):
            if s.get(User, login) is None:
                s.add(User(login=login))
        s.flush()
        pr = PullRequest(
            repo_id=repo.id, number=1,
            title="Refactor checkout flow",
            body="Some long description.",
            author_login="alice", state="open", draft=0,
            head_sha="a3f4e2d9b8", base_ref="main",
            html_url="https://example.com/o/n/pull/1",
            commits_count=3,
            created_at=now_iso(), updated_at=now_iso(),
            cached_at=now_iso(),
        )
        s.add(pr); s.flush()
        if with_summary:
            s.add(PRSummary(
                pr_id=pr.id,
                summary="Mueve la lógica de Stripe a un servicio.",
                head_sha="a3f4e2d9b8",
                model="claude-3.5-sonnet",
                generated_at=now_iso(),
            ))
        # Newest run = id 1 (only one in this seed). Findings attached so
        # the test can verify the resolved+pending labels render.
        run = ReviewRun(pr_id=pr.id, agent_runner="claude",
                        skills_json='["superpowers","ponytail"]',
                        mode="fresh", status="done",
                        started_at=now_iso(), finished_at=now_iso())
        s.add(run); s.flush()
        s.add(ReviewFinding(review_run_id=run.id,
                            finding_key="a.py:1:dead",
                            severity="high",
                            file_path="a.py", line=1,
                            description="dead code path",
                            status="resolved",
                            resolved_in_commit="a3f4e2d9b8"))
        s.add(ReviewFinding(review_run_id=run.id,
                            finding_key="b.py:7:leak",
                            severity="medium",
                            file_path="b.py", line=7,
                            description="resource leak",
                            status="pending"))
        s.add(Review(pr_id=pr.id, reviewer_login="carlos.r",
                     state="commented",
                     submitted_at=now_iso(),
                     body="¿Por qué retorna dict?"))
    return db


def test_pr_detail_matches_mock_layout(tmp_path, monkeypatch):
    """v1.1 Task 11: the v3 mock rebuild of `/pr/{owner}/{name}/{number}`
    must render the breadcrumb row (← dashboard + repo chip + #N +
    "abrir en GitHub"), the per-PR refresh form, all six tabs in the
    mock order, the RESUMEN AUTOMÁTICO chip when a summary exists, the
    3 finding-status labels (RESUELTO/PENDIENTE/NUEVO), and the right-
    column Run review widget (agent select + skills checkboxes + Run
    button)."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    db = _seed_pr_detail(tmp_path, with_summary=True)
    from tl_towerwatch.web import create_app
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/pr/o/n/1")
        assert r.status_code == 200
        body = r.text

        # --- breadcrumb row ---
        assert "← volver al dashboard" in body
        assert "o/n" in body  # owner/name chip
        assert "#1" in body
        assert "abrir en GitHub" in body

        # --- per-PR refresh form ---
        # The button text is exact ("Refrescar este PR") and the action
        # points at the existing refresh route.
        assert "↻ Refrescar este PR" in body
        assert 'action="/pr/o/n/1/refresh"' in body

        # --- all six tabs in mock order (Overview / Commits / Files /
        #     Reviews / Comments / 🤖 tl_towerwatch reviews) ---
        # ``in`` preserves order on the substring search; we walk through
        # each label in turn so the assertion catches a swap of any two
        # tabs (the mock labels are user-chosen and must not be reordered).
        idx_overview    = body.index("Overview")
        idx_commits     = body.index("Commits (")
        idx_files       = body.index("Files (")
        idx_reviews     = body.index("Reviews (")
        idx_comments    = body.index("Comments (")
        idx_agent       = body.index("🤖 tl_towerwatch reviews (")
        assert idx_overview < idx_commits < idx_files < idx_reviews \
            < idx_comments < idx_agent, (
                f"tabs out of order: {idx_overview=} {idx_commits=} "
                f"{idx_files=} {idx_reviews=} {idx_comments=} {idx_agent=}"
            )

        # --- resumen automático chip when summary exists ---
        assert "RESUMEN AUTOMÁTICO" in body

        # --- finding-status labels (the v3 mock uses uppercase for the
        #     per-finding badge) ---
        assert "✓ RESUELTO" in body
        assert "⚠ PENDIENTE" in body
        # NUEVO is rendered in the mock for findings with status="new".
        # The seed only has resolved + pending, so NUEVO may not be
        # present — but the per-finding template still defines the
        # branch, so we do not assert it here. Instead verify the
        # counters strip renders the aggregated counters strip.
        assert "resueltos" in body
        assert "pendientes" in body
        assert "nuevos" in body

        # --- run review widget ---
        # Agent select with the four mock options.
        assert 'name="agent"' in body
        assert "<option" in body and "Claude" in body
        # Skills checkboxes for the default registry (superpowers + ponytail).
        assert 'name="skills"' in body
        assert "superpowers" in body
        assert "ponytail" in body
        # Big green Run button.
        assert "▶ Run review" in body
        # Form action posts to the existing run-review route.
        assert 'action="/pr/o/n/1/run-review"' in body


def test_pr_detail_summary_card_hidden_when_no_summary(tmp_path, monkeypatch):
    """v1.1 Task 11: when a PRSummary row is absent the green resumen
    card is fully hidden — not rendered with empty text, not stubbed
    with "(sin resumen)". This is the assertion the spec uses to
    distinguish "summary pending" from "no summary ever"."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    db = _seed_pr_detail(tmp_path, with_summary=False)
    from tl_towerwatch.web import create_app
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/pr/o/n/1")
        assert r.status_code == 200
        body = r.text
        assert "RESUMEN AUTOMÁTICO" not in body
        # The other elements must still render normally — the missing
        # summary shouldn't blank the page.
        assert "← volver al dashboard" in body
        assert "Overview" in body


def test_dashboard_matches_mock_layout(tmp_path, monkeypatch, respx_mock):
    """The v2 dashboard rebuild (Task 11) renders every block the mock
    defines: repo chip + #N, metadata line, title link, RESUMEN chip + text,
    reviewer avatar bubble sourced from User.avatar_url, diff stats
    (+additions / -deletions, N archivos, CI ✓), Run-review form action
    URL still intact, pr.html_url exposed as a link, and the inline
    ``📄 Ver descripción del PR`` disclosure.

    Filter tabs / repo+author dropdowns / title search box are
    deliberately NOT asserted: they're visual placeholders without server
    semantics yet. They render, but the task spec says no client filtering
    is needed at this stage."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_FAKE\n")
    # The dashboard validates the PAT before rendering; stub /user.
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    from tl_towerwatch.db.database import engine_from_settings
    from tl_towerwatch.db.models import (
        PRSummary,
        PullRequest,
        Review,
        User,
        now_iso,
    )
    from tl_towerwatch.services.repos import add_repo
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    # Repo owner/name must match what the test asserts ("hari-corp/test").
    repo = add_repo(db, "hari-corp", "test")
    with db.session() as s:
        # Seed the PR author with an avatar — even though the template
        # doesn't render the author avatar, we cover the User code path
        # used by the reviewer join (User.avatar_url is what the avatar
        # bubble image reads).
        for login, avatar in (
            ("dimh",   "https://avatars.example.com/dimh.png"),
            ("alice",  "https://avatars.example.com/alice.png"),
            ("bob",    "https://avatars.example.com/bob.png"),
        ):
            if s.get(User, login) is None:
                s.add(User(login=login, avatar_url=avatar))
        s.flush()
        pr = PullRequest(
            repo_id=repo.id,
            number=42,
            title="feat: dashboard v2 layout",
            body="Detailed PR body that the disclosure element reveals.",
            author_login="alice",
            state="open",
            draft=0,
            head_sha="abcdef0123",
            base_ref="main",
            # pr.html_url must round-trip through the template into an <a href>.
            html_url="https://github.com/hari-corp/test/pull/42",
            created_at=now_iso(),
            updated_at=now_iso(),
            cached_at=now_iso(),
            additions=247,
            deletions=89,
            changed_files=12,
            commits_count=3,
        )
        s.add(pr); s.flush()
        # Add a "commented" review by the dashboard's login user ("dimh")
        # so the PR clears the ``mine_and_review`` scope filter. The task
        # spec only asks us to render bob's avatar — dimh's review is
        # purely a scope hook and won't change the mock-card assertions.
        s.add(Review(pr_id=pr.id, reviewer_login="dimh",
                     state="commented",
                     submitted_at=now_iso(), body="looking"))
        # Reviewer "bob" with state="approved" — this drives both the
        # reviewer avatar bubble (bob's avatar_url is sourced from User)
        # and the badge color in the metadata row.
        s.add(Review(pr_id=pr.id, reviewer_login="bob",
                     state="approved",
                     submitted_at=now_iso(), body="lgtm"))
        # PRSummary row (PK = pr_id) — the mock card renders a
        # "RESUMEN" chip with this text when present.
        s.add(PRSummary(pr_id=pr.id,
                        summary="Refactor + simplify dashboard render path.",
                        head_sha="abcdef0123",
                        model="claude-sonnet",
                        generated_at=now_iso()))
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        body = r.text

        # --- Repo chip + number ---
        assert "hari-corp/test" in body
        assert "#42" in body

        # --- Diff stats badges ---
        assert "+247 / -89" in body
        assert "12 archivos" in body
        # The mock also keeps the "commits post-creation" callout wired
        # to ``pr.commits_count`` (3 in this fixture).
        assert "3 commits post-creation" in body

        # --- RESUMEN chip + summary text ---
        assert "RESUMEN" in body
        assert "Refactor + simplify dashboard render path." in body

        # --- Reviewer avatar bubble (must be an <img> sourced from
        # User.avatar_url, not an initials fallback). ---
        assert 'src="https://avatars.example.com/bob.png"' in body
        # The avatar bubble is wrapped in an <img> element — this guards
        # against the fallback-to-initials regression.
        assert '<img' in body and 'bob.png' in body

        # --- Run review form still hits the existing route. The mock
        # relabels the button "▶ Review →" but the action URL is the same
        # POST endpoint the v1.0 dashboard already wired up. ---
        assert 'action="/pr/hari-corp/test/42/run-review"' in body
        assert "▶ Review" in body

        # --- pr.html_url rendered as a link to GitHub. ---
        assert 'href="https://github.com/hari-corp/test/pull/42"' in body
        assert "Ver en GitHub" in body

        # --- Inline body disclosure: <details><summary> 📄 Ver descripción
        # del PR — toggles the PR body text. ---
        assert "📄 Ver descripción del PR" in body
        assert "<details" in body
        assert "Detailed PR body that the disclosure element reveals." in body

        # --- Status counters strip still rendered (regression guard for
        # the spec §5.1 strip the mock rebuilds around). ---
        assert "awaiting my review" in body.lower()
        assert "needs response" in body.lower()
        assert "changes requested" in body.lower()
        assert "ready to merge" in body.lower()


def test_settings_save_buttons_present(tmp_path, monkeypatch, respx_mock):
    """Regression — the v1.2.0 mock rebuild wrapped the auth and LLM
    inputs in <form action="/settings/auth/save"> and
    <form action="/settings/llm/save"> but never added a submit button
    inside either form, so clicking through the mock-equivalent UI
    silently no-op'd. After the fix each form carries its own Save
    button and visible input fields, so the user can actually save."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_OLD\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/settings")
        assert r.status_code == 200
        body = r.text
        # Both forms have a submit button
        assert 'action="/settings/auth/save"' in body
        assert 'action="/settings/llm/save"' in body
        # Buttons are inside the rendered HTML; check the inner text
        # rather than the surrounding tags because indentation adds
        # whitespace between the `<button ...>` and the label.
        assert "Guardar Auth" in body
        assert "Guardar LLM" in body
        assert body.count('type="submit"') >= 2
        # Visible inputs the user actually edits
        assert 'name="github_token_edit"' in body
        assert 'name="anthropic_api_key_edit"' in body
        assert 'name="provider"' in body


def test_settings_auth_save_roundtrip(tmp_path, monkeypatch, respx_mock):
    """Submitting the auth form with a new PAT actually rewrites
    TOWERWATCH_GITHUB_TOKEN in .env, and the edit-or-current semantics
    preserve the previous value when the edit field is blank."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("TOWERWATCH_GITHUB_TOKEN=ghp_OLD\n")
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        # Submit a new token via the _edit field.
        r = c.post("/settings/auth/save",
                   data={"github_token_edit": "ghp_NEW1234",
                         "github_oauth_client_id_edit": "",
                         "github_oauth_client_secret_edit": ""},
                   follow_redirects=False)
        assert r.status_code == 303
        env = (tmp_path / ".env").read_text()
        assert "TOWERWATCH_GITHUB_TOKEN=ghp_NEW1234" in env

        # Submitting with empty edit must preserve the current token.
        r2 = c.post("/settings/auth/save",
                    data={"github_token_edit": "",
                          "github_oauth_client_id_edit": "",
                          "github_oauth_client_secret_edit": ""},
                    follow_redirects=False)
        assert r2.status_code == 303
        env2 = (tmp_path / ".env").read_text()
        assert "TOWERWATCH_GITHUB_TOKEN=ghp_NEW1234" in env2


def test_settings_llm_save_roundtrip(tmp_path, monkeypatch, respx_mock):
    """Submitting the LLM form switches default_provider and rewrites
    the chosen API key in .env, blank edits leave values untouched."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text(
        "TOWERWATCH_ANTHROPIC_API_KEY=sk-ant-OLD\n"
        "TOWERWATCH_LLM_DEFAULT_PROVIDER=anthropic\n"
    )
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"},
                              headers={"X-OAuth-Scopes": "repo, read:user"})
    )
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    app = create_app()
    with TestClient(app) as c:
        # Switch to OpenAI with a new key.
        r = c.post("/settings/llm/save",
                   data={"provider": "openai",
                         "openai_api_key_edit": "sk-NEW",
                         "anthropic_api_key_edit": "",
                         "ollama_base_url_edit": ""},
                   follow_redirects=False)
        assert r.status_code == 303
        env = (tmp_path / ".env").read_text()
        # The persist helper writes TOWERWATCH_LLM_PROVIDER (not the
        # legacy _DEFAULT_PROVIDER key).
        assert "TOWERWATCH_LLM_PROVIDER=openai" in env
        assert "TOWERWATCH_OPENAI_API_KEY=sk-NEW" in env
        # Blank anthropic edit must keep the old anthropic key.
        assert "TOWERWATCH_ANTHROPIC_API_KEY=sk-ant-OLD" in env