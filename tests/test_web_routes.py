from fastapi.testclient import TestClient
from httpx import Response
from tl_towerwatch.web import create_app

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

def test_dashboard_renders_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    app = create_app()
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "PRs" in r.text

def test_repos_route_lists_and_adds(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
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


def test_dashboard_renders_status_counters(tmp_path, monkeypatch):
    """Seed DB with PRs in different states; assert the counters strip renders
    the spec §5.1 names with non-zero counts for the seeded badges."""
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
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


def test_dashboard_counters_aggregate_across_prs(tmp_path, monkeypatch):
    """Regression for the HIGH defect where the counters strip seeded the
    spec §5.1 names but was incremented by raw `compute_badges` output
    names. `pending_response` and `approved` badges therefore never
    populated `needs_response` / `ready_to_merge` counters. Seed 3 PRs
    covering each translation and assert `>1<` appears adjacent to the
    three spec labels we expected to be 1, with `>0<` for the
    `awaiting_my_review` label (no seeded PR targets it)."""
    import re
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
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