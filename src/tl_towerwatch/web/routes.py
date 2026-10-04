from __future__ import annotations

import json as _json
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from tl_towerwatch.auth.github import resolve_token
from tl_towerwatch.config import Settings, load_settings
from tl_towerwatch.config_io import load_config_yaml, save_config_yaml
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import (
    PRSummary,
    PullRequest,
    Repo,
    Review,
    ReviewComment,
    ReviewFinding,
    ReviewRun,
)
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.llm import get_provider
from tl_towerwatch.services.pull_requests import list_prs_for_dashboard, sync_one_pr
from tl_towerwatch.services.repos import (
    add_repo as svc_add_repo,
)
from tl_towerwatch.services.repos import (
    list_repos as svc_list_repos,
)
from tl_towerwatch.services.repos import (
    remove_repo as svc_remove_repo,
)
from tl_towerwatch.services.repos import (
    set_allowed_authors as svc_set_allowed_authors,
)
from tl_towerwatch.services.repos import (
    set_repo_enabled as svc_set_repo_enabled,
)
from tl_towerwatch.services.review_runner import run_review
from tl_towerwatch.services.reviews import compute_badges

_TPL_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TPL_DIR))

# Spec §5.2 — color and label per finding lifecycle status. Reused by the
# pr_detail template (counters strip + per-finding badge) via the Jinja
# filters registered below.
_FINDING_STATUS_COLORS = {
    "resolved": "#3fb950",
    "pending":  "#d29922",
    "new":      "#58a6ff",
}
_FINDING_STATUS_LABELS = {
    "resolved": "✓ resuelto",
    "pending":  "⚠ pendiente",
    "new":      "🆕 nuevo",
}


def _status_color(status: str) -> str:
    return _FINDING_STATUS_COLORS.get(status, "#8b949e")


def _status_label(status: str) -> str:
    return _FINDING_STATUS_LABELS.get(status, status or "")


templates.env.filters["status_color"] = _status_color
templates.env.filters["status_label"] = _status_label

router = APIRouter()


def _redirect_on_auth_error(e: RuntimeError) -> RedirectResponse:
    """Convert a ``RuntimeError`` raised by ``resolve_token`` about invalid or
    missing GitHub credentials into a redirect to ``/settings``.

    Per spec §8.1, a stale or 401-returning token must surface to the user so
    they can reconfigure it. Anything else (``RuntimeError`` from a code bug)
    is re-raised so the normal 500 handler reports it.
    """
    msg = str(e).lower()
    if "invalid" in msg or "401" in msg or "no github credentials" in msg:
        return RedirectResponse("/settings?error=github_auth", status_code=303)
    raise e


def _safe_resolve_token(settings: Settings) -> str | RedirectResponse:
    """Resolve the GitHub token, returning a redirect to /settings on auth failure.

    Routes that talk to GitHub should call this instead of ``resolve_token``
    directly so a 401 / missing-credentials state ends in a friendly redirect
    instead of a 500. On success returns the token string; on auth failure
    returns a ``RedirectResponse`` the route should propagate.
    """
    try:
        return resolve_token(settings)
    except RuntimeError as e:
        return _redirect_on_auth_error(e)


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    # v1.1 (Task 10): first-run redirect — if neither a PAT nor an OAuth
    # refresh token is configured AND config.yaml carries no auth.mode,
    # send the user straight to /settings instead of an empty dashboard.
    cfg = load_config_yaml(settings.data_dir / "config.yaml")
    if not settings.github_token and not cfg.get("auth", {}).get("mode"):
        return RedirectResponse("/settings?first_run=1", status_code=303)
    # Validate the token eagerly so a stale/401 credential bounces to
    # /settings?error=github_auth before we try to render the dashboard.
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    login = "dimh"  # TODO: derive from auth in Task 18
    prs = list_prs_for_dashboard(db, login=login, scope_filter="mine_and_review")
    # Status counters per spec §5.1. `compute_badges` uses its own names
    # (`pending_response`, `approved`, ...) that don't 1:1 match the spec
    # counter names (`needs_response`, `ready_to_merge`, ...), so translate
    # through `BADGE_TO_COUNTER` before incrementing. Any badge name absent
    # from the mapping (e.g. `responded`) is intentionally not counted in
    # the spec strip.
    BADGE_TO_COUNTER = {
        "awaiting_my_review": "awaiting_my_review",
        "pending_response":   "needs_response",
        "changes_requested":  "changes_requested",
        "approved":           "ready_to_merge",
    }
    counts = {name: 0 for name in set(BADGE_TO_COUNTER.values())}
    badges_by_pr: dict[int, list[dict]] = {}
    for pr in prs:
        badges = compute_badges(db, login, pr)
        badges_by_pr[pr.id] = badges
        for b in badges:
            key = BADGE_TO_COUNTER.get(b["name"])
            if key:
                counts[key] += 1
    return templates.TemplateResponse(request, "dashboard.html",
        {"nav": "home", "theme": _theme(request),
         "prs": prs, "badges_by_pr": badges_by_pr,
         "login": login, "counts": counts})

@router.get("/repos", response_class=HTMLResponse)
def repos_page(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    # v1.1 (Task 10): validate the token up front so a 401 bounces to
    # /settings?error=github_auth instead of silently rendering the page
    # without a rate-limit banner (the swallowed-exception path was
    # masking the auth failure from the user).
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    # Cheap rate-limit probe: surfaces in the banner whether the configured
    # credentials are usable. Network errors are swallowed so the page still
    # renders; auth errors are caught by ``_safe_resolve_token`` above.
    rl: dict | None = None
    try:
        with GitHubClient(token=token) as gh:
            r = gh._client.get("/rate_limit")
            if r.status_code == 200:
                core = r.json().get("resources", {}).get("core", {})
                rl = {"remaining": core.get("remaining", 0),
                      "reset": core.get("reset", 0)}
    except Exception:
        rl = None
    repo_rows = svc_list_repos(db)
    for r in repo_rows:
        try:
            authors = _json.loads(r.allowed_authors_json or "[]")
        except Exception:
            authors = []
        r.allowed_authors_csv = ", ".join(authors)
    return templates.TemplateResponse(request, "repos.html",
        {"nav": "repos", "theme": _theme(request),
         "repos": repo_rows, "rl": rl})

@router.post("/repos/add")
def repos_add(owner_name: str = Form(...), authors: str = Form("")):
    if owner_name.startswith("https://"):
        parts = owner_name.rstrip("/").split("/")
        owner_name = f"{parts[-2]}/{parts[-1]}"
    owner, name = owner_name.split("/", 1)
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    authors_list = [a for a in authors.split(",") if a.strip()]
    # v1.1 (Task 10): a 401 from the token bounces to /settings?error=github_auth
    # so the user re-pastes a working PAT instead of seeing a misleading
    # "could not validate repo" message.
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    try:
        with GitHubClient(token=token) as gh:
            gh.get_repo(owner, name)
    except Exception as e:
        return HTMLResponse(f"<p>No pude validar {owner}/{name}: {e}</p>", status_code=400)
    svc_add_repo(db, owner, name,
                 refresh_interval_seconds=settings.refresh_interval_seconds,
                 allowed_authors=authors_list or None)
    return RedirectResponse("/repos", status_code=303)

@router.post("/repos/{owner}/{name}/set-authors")
def repos_set_authors(owner: str, name: str, authors: str = Form("")):
    settings = load_settings()
    db = engine_from_settings(settings)
    authors_list = [a for a in authors.split(",") if a.strip()]
    svc_set_allowed_authors(db, owner, name, authors_list)
    return RedirectResponse("/repos", status_code=303)

@router.post("/repos/{owner}/{name}/toggle")
def repos_toggle(owner: str, name: str):
    settings = load_settings()
    db = engine_from_settings(settings)
    repo_rows = svc_list_repos(db)
    cur = next((r for r in repo_rows if r.owner == owner and r.name == name), None)
    if cur is None:
        return RedirectResponse("/repos", status_code=303)
    svc_set_repo_enabled(db, owner, name, not cur.enabled)
    return RedirectResponse("/repos", status_code=303)

@router.post("/repos/{owner}/{name}/remove")
def repos_remove(owner: str, name: str):
    settings = load_settings()
    db = engine_from_settings(settings)
    svc_remove_repo(db, owner, name)
    return RedirectResponse("/repos", status_code=303)

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

def _theme(request: Request) -> str:
    c = request.cookies.get("tl_towerwatch_theme")
    if c in ALLOWED_THEMES:
        return c
    settings = load_settings()
    data = load_config_yaml(settings.data_dir / "config.yaml")
    t = data.get("theme", "dark")
    return t if t in ALLOWED_THEMES else "dark"

@router.get("/pr/{owner}/{name}/{number}", response_class=HTMLResponse)
def pr_detail(request: Request, owner: str, name: str, number: int):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    # Per spec §5.2 the PR detail exposes six tabs (Overview, Commits, Files,
    # Reviews, Comments, tl_towerwatch reviews). The data dict we hand to
    # the template carries everything each tab needs in a single round trip
    # so the handler stays the single source of truth.
    pr = None
    summary = None
    runs: list[ReviewRun] = []
    human_reviews: list[Review] = []
    human_comments: list[ReviewComment] = []
    resolved_count = 0
    pending_count = 0
    new_count = 0
    with db.session() as s:
        repo = s.execute(select(Repo).where(
            Repo.owner == owner, Repo.name == name
        )).scalar_one_or_none()
        if repo:
            pr = s.execute(select(PullRequest).where(
                PullRequest.repo_id == repo.id, PullRequest.number == number
            )).scalar_one_or_none()
            if pr:
                summary = s.get(PRSummary, pr.id)
                # Reviews + comments for the human-facing tabs.
                human_reviews = list(s.execute(
                    select(Review).where(Review.pr_id == pr.id)
                    .order_by(Review.submitted_at.asc())
                ).scalars())
                human_comments = list(s.execute(
                    select(ReviewComment).where(ReviewComment.pr_id == pr.id)
                    .order_by(ReviewComment.created_at.asc())
                ).scalars())
                # tl_towerwatch review runs (newest first). We attach the
                # findings to each run so the template can render them in
                # the loop without re-querying.
                runs = list(s.execute(
                    select(ReviewRun).where(ReviewRun.pr_id == pr.id)
                    .order_by(ReviewRun.id.desc())
                ).scalars())
                findings_by_run: dict[int, list[ReviewFinding]] = {}
                if runs:
                    rows = list(s.execute(
                        select(ReviewFinding).where(
                            ReviewFinding.review_run_id.in_([r.id for r in runs])
                        ).order_by(ReviewFinding.id.asc())
                    ).scalars())
                    for f in rows:
                        findings_by_run.setdefault(f.review_run_id, []).append(f)
                        if f.status == "resolved":
                            resolved_count += 1
                        elif f.status == "pending":
                            pending_count += 1
                        elif f.status == "new":
                            new_count += 1
                for run in runs:
                    # Attach as a plain attribute; SQLAlchemy ORM instances
                    # allow ad-hoc attributes for template consumption.
                    run.findings = findings_by_run.get(run.id, [])
    return templates.TemplateResponse(request, "pr_detail.html",
        {"nav": "home", "theme": _theme(request),
         "pr": pr, "summary": summary, "runs": runs,
         "human_reviews": human_reviews, "human_comments": human_comments,
         "resolved_count": resolved_count,
         "pending_count": pending_count,
         "new_count": new_count,
         "owner": owner, "name": name})

@router.post("/pr/{owner}/{name}/{number}/refresh")
def pr_refresh(owner: str, name: str, number: int):
    settings = load_settings()
    db = engine_from_settings(settings)
    with db.session() as s:
        repo = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
    # v1.1 (Task 10): a 401 from the token bounces to /settings?error=github_auth
    # before we hit the network on sync_one_pr.
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    llm = get_provider(settings) if settings.llm.anthropic.api_key else None
    with GitHubClient(token=token) as gh:
        sync_one_pr(db, gh, repo, number, llm=llm)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)

@router.post("/pr/{owner}/{name}/{number}/run-review")
def pr_run_review(owner: str, name: str, number: int,
                  agent: str = Form(...),
                  skills: str = Form(""),
                  mode: str = Form("fresh")):
    settings = load_settings()
    db = engine_from_settings(settings)
    # v1.1 (Task 10): see pr_refresh — bounce to /settings on auth failure.
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    skill_names = [s.strip() for s in skills.split(",") if s.strip()]
    with GitHubClient(token=token) as gh:
        run_review(db, gh, owner=owner, name=name, number=number,
                   agent_name=agent, skill_names=skill_names, mode=mode,
                   timeout_seconds=300, settings=settings)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    settings = load_settings()
    return templates.TemplateResponse(request, "settings.html",
        {"nav": "settings", "theme": _theme(request),
         "settings": settings})

@router.post("/settings/auth/save")
def settings_auth_save(github_token: str = Form(""),
                       github_oauth_client_id: str = Form(""),
                       github_oauth_client_secret: str = Form("")):
    settings = load_settings()
    _persist_auth_keys(
        settings.data_dir / ".env",
        github_token=github_token,
        github_oauth_client_id=github_oauth_client_id,
        github_oauth_client_secret=github_oauth_client_secret,
    )
    return RedirectResponse("/settings", status_code=303)

@router.post("/settings/llm/save")
def settings_llm_save(provider: str = Form("anthropic"),
                      anthropic_api_key: str = Form(""),
                      openai_api_key: str = Form(""),
                      ollama_base_url: str = Form("")):
    settings = load_settings()
    _persist_llm_keys(
        settings.data_dir / ".env",
        provider=provider,
        anthropic_api_key=anthropic_api_key,
        openai_api_key=openai_api_key,
        ollama_base_url=ollama_base_url,
    )
    return RedirectResponse("/settings", status_code=303)

def _persist_auth_keys(env_path: Path, github_token: str,
                       github_oauth_client_id: str,
                       github_oauth_client_secret: str) -> None:
    """Persist Auth-form values to .env, only touching the Auth keys.

    Empty form values are treated as "no change" so submitting a partial Auth
    form (e.g. only the PAT) cannot wipe secrets the user didn't intend to
    touch — see `test_settings_auth_save_does_not_wipe_oauth_fields`. Non-empty
    form values replace any existing line for that key. Keys owned by other
    helpers are never touched.

    Key names align with spec §10.3: ``TOWERWATCH_GITHUB_OAUTH_*``.
    """
    import os
    updates = {
        "TOWERWATCH_GITHUB_TOKEN": github_token,
        "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID": github_oauth_client_id,
        "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET": github_oauth_client_secret,
    }
    keys = set(updates.keys())
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    # Snapshot existing values for the keys this helper owns so we can
    # preserve them when the corresponding form field arrives empty.
    existing = {}
    for ln in lines:
        for k in keys:
            if ln.startswith(k + "="):
                existing[k] = ln[len(k) + 1:]
                break
    # Drop any line this helper owns; we'll re-emit them below.
    new_lines = [ln for ln in lines if not any(ln.startswith(k + "=") for k in keys)]
    for k, v in updates.items():
        if v:
            new_lines.append(f"{k}={v}")
        elif k in existing:
            # Empty form value → keep the prior secret untouched.
            new_lines.append(f"{k}={existing[k]}")
    tmp = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp.write_text("\n".join(new_lines) + "\n")
    os.replace(tmp, env_path)

def _persist_llm_keys(env_path: Path, provider: str, anthropic_api_key: str,
                      openai_api_key: str, ollama_base_url: str) -> None:
    """Persist LLM-form values to .env, only touching the LLM keys.

    Replaces any existing lines for the keys this helper owns so a stale value
    can't leak through, but never strips keys owned by other helpers.
    """
    import os
    updates = {
        "TOWERWATCH_LLM_PROVIDER": provider,
        "TOWERWATCH_ANTHROPIC_API_KEY": anthropic_api_key,
        "TOWERWATCH_OPENAI_API_KEY": openai_api_key,
        "TOWERWATCH_OLLAMA_BASE_URL": ollama_base_url,
    }
    keys = set(updates.keys())
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    new_lines = [ln for ln in lines if not any(ln.startswith(k + "=") for k in keys)]
    new_lines += [f"{k}={v}" for k, v in updates.items() if v]
    tmp = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp.write_text("\n".join(new_lines) + "\n")
    os.replace(tmp, env_path)