from __future__ import annotations

import json as _json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from tl_towerwatch.auth.github import resolve_token
from tl_towerwatch.config import Settings, load_settings
from tl_towerwatch.config_io import load_config_yaml, save_config_yaml
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import (
    IssueComment,
    PRCommit,
    PRFile,
    PullRequest,
    Repo,
    Review,
    ReviewComment,
    User,
)
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.services.prompt_assembly import assemble_review_prompt
from tl_towerwatch.services.pull_requests import (
    list_prs_for_dashboard,
    post_issue_comment_reply,
    post_review_comment_reply,
    save_manual_description,
    save_manual_notes,
    sync_one_pr,
    sync_repo,
)
from tl_towerwatch.services.repos import (
    add_repo as svc_add_repo,
)
from tl_towerwatch.services.repos import (
    get_repo as svc_get_repo,
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
from tl_towerwatch.services.repos import (
    update_repo_config as svc_update_repo_config,
)
from tl_towerwatch.services.reviews import compute_badges
from tl_towerwatch.skills.registry import (
    PROMPT_SLOTS,
    load_prompts,
    save_prompts as _save_prompts,
)

_TPL_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TPL_DIR))


# ---------------------------------------------------------------------------
# Jinja filters + globals used by templates.
# ---------------------------------------------------------------------------


def _status_color(status: str) -> str:
    """Color for a finding lifecycle badge. The dashboard + PR detail
    templates both pipe the ``status`` field through this filter so the
    CSS stays consistent. Unknown values get a neutral grey."""
    return {
        "resolved": "#3fb950",
        "pending":  "#d29922",
        "new":      "#58a6ff",
    }.get(status, "#8b949e")


def _status_label(status: str) -> str:
    """Human-readable label for the badge."""
    return {
        "resolved": "✓ resuelto",
        "pending":  "⚠ pendiente",
        "new":      "🆕 nuevo",
    }.get(status, status or "")


def _from_json(text):
    """Decode the JSON-encoded list/dict columns we keep around
    (e.g. ``User`` rows still hold ``allowed_authors_json``). Returns an
    empty list when the value is missing or malformed so templates can
    iterate without try/except guards."""
    if not text:
        return []
    try:
        v = _json.loads(text)
    except Exception:
        return []
    return v if isinstance(v, list) else []


def _hace(ts: str | None) -> str:
    """Spanish ``hace X`` relative time label used in the breadcrumb / PR
    rows. Returns ``"hace ?"`` when the timestamp is missing or
    unparseable so the template never crashes on a bad row."""
    if not ts:
        return "hace ?"
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
    except Exception:
        return "hace ?"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "hace instantes"
    if secs < 60:
        return "hace instantes"
    if secs < 3600:
        m = secs // 60
        return f"hace {m} min"
    if secs < 86400:
        h = secs // 3600
        return f"hace {h} h"
    d = secs // 86400
    return f"hace {d} d"


templates.env.filters["status_color"] = _status_color
templates.env.filters["status_label"] = _status_label
templates.env.filters["hace"] = _hace
templates.env.filters["from_json"] = _from_json


# ---------------------------------------------------------------------------
# Auth helpers — convert GitHub auth failures into friendly redirects.
# ---------------------------------------------------------------------------


def _redirect_on_auth_error(e: RuntimeError) -> RedirectResponse:
    """Convert a ``RuntimeError`` raised by ``resolve_token`` about invalid
    or missing GitHub credentials into a redirect to ``/settings``.

    Per spec §8.1, a stale or 401-returning token must surface to the user
    so they can reconfigure it. Anything else (``RuntimeError`` from a
    code bug) is re-raised so the normal 500 handler reports it.
    """
    msg = str(e).lower()
    if "invalid" in msg or "401" in msg or "no github credentials" in msg:
        return RedirectResponse("/settings?error=github_auth", status_code=303)
    raise e


def _safe_resolve_token(settings: Settings) -> str | RedirectResponse:
    """Resolve the GitHub token, returning a redirect on auth or network
    failure. Routes that talk to GitHub should call this instead of
    ``resolve_token`` directly so a 401 / missing-credentials state ends in
    a friendly redirect instead of a 500.

    v1.3.x: widened the catch from ``RuntimeError`` to ``Exception`` so
    transient network failures (DNS, TLS, timeout) during the
    ``GET /user`` token-validation call also redirect cleanly. Those used
    to escape as 500s, which is a problem on the reply routes where the
    user has just typed a comment — losing their input to a traceback
    is a poor experience.
    """
    try:
        return resolve_token(settings)
    except RuntimeError as e:
        return _redirect_on_auth_error(e)
    except Exception as e:
        # Network errors / timeouts / TLS issues → bounce to /settings
        # with a generic token-validation error so the user can re-enter
        # the token or retry once their network recovers.
        return RedirectResponse(
            f"/settings?error=github_unreachable&reason={type(e).__name__}",
            status_code=303,
        )


def _theme(request: Request) -> str:
    """Resolve the current theme from cookie → config.yaml → default.

    Cookie wins so the user's in-page toggle feels instant; the cookie is
    also written to config.yaml by the /theme route so the choice sticks
    across server restarts."""
    c = request.cookies.get("tl_towerwatch_theme")
    if c in {"dark", "light", "system"}:
        return c
    settings = load_settings()
    data = load_config_yaml(settings.data_dir / "config.yaml")
    t = data.get("theme", "dark")
    return t if t in {"dark", "light", "system"} else "dark"


def _user_context(db, login: str) -> dict:
    """Resolve the avatar + display name for the top bar from the User row
    matching ``login``. Returns safe defaults so the top bar still renders
    when the user row hasn't been synced yet (avatars stay optional)."""
    from tl_towerwatch.db.models import User as UserModel
    try:
        with db.session() as s:
            row = s.get(UserModel, login)
    except Exception:
        row = None
    if row is None:
        return {"user_login": login, "user_avatar_url": None}
    return {
        "user_login": login,
        "user_avatar_url": row.avatar_url,
        "user_display_name": row.display_name,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request,
          scope: str = "attention",
          state: str = "open",
          repo: str = "",
          author: str = "",
          q: str = "",
          sort: str = "updated_desc"):
    """Dashboard list with full filter + sort wiring.

    Query params:
    - scope: "attention" (default), "mine", "review", "all"
    - state: "open" (default), "closed", "merged", "all"
    - repo: "owner/name" — restrict to one repo
    - author: GitHub login — restrict to PRs authored by this user
    - q: case-insensitive substring match against ``pr.title``
    - sort: "updated_desc" (default), "updated_asc", "created_desc",
      "created_asc", "title"

    v1.3.x: the ``state`` filter lets the user see closed / merged PRs
    that the scheduler picked up. Default is ``open`` so the
    "Attention / My PRs / Review-requested" tabs keep their
    "what needs my attention" semantics — a closed PR is no longer
    pending just because the local cache was stale.
    """
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    # First-run redirect: if neither a PAT nor an OAuth refresh token is
    # configured AND config.yaml carries no auth.mode, send the user
    # straight to /settings instead of an empty dashboard.
    cfg = load_config_yaml(settings.data_dir / "config.yaml")
    if not settings.github_token and not cfg.get("auth", {}).get("mode"):
        return RedirectResponse("/settings?first_run=1", status_code=303)
    # Validate the token eagerly so a stale/401 credential bounces to
    # /settings?error=github_auth before we try to render the dashboard.
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    login = "dimh"  # TODO: derive from auth in Task 18
    # Scope "attention" = "needs response + awaiting my review", which is
    # the union of `mine` and `review`. Resolve the two scopes, then
    # merge below.
    raw_scope = scope if scope in ("mine", "review", "all") else None
    # State filter — default "open" so closed/merged PRs don't
    # pollute the "what needs my attention" views. The user can
    # switch via the ?state=closed or ?state=merged query param.
    state_filter = state if state in ("open", "closed", "merged", "all") else "open"
    if scope == "attention":
        mine_prs = list_prs_for_dashboard(
            db, login=login, scope_filter="mine", state_filter=state_filter,
        )
        review_prs = list_prs_for_dashboard(
            db, login=login, scope_filter="review", state_filter=state_filter,
        )
        seen: set[int] = set()
        prs: list[PullRequest] = []
        for p in mine_prs + review_prs:
            if p.id in seen:
                continue
            seen.add(p.id)
            prs.append(p)
    else:
        prs = list_prs_for_dashboard(
            db, login=login, scope_filter=raw_scope, state_filter=state_filter,
        )
    # Dropdown sources are pulled BEFORE the row-level filters so the user
    # always sees every watched repo and every known User as a filter
    # option — not just the ones that survived the current scope+repo
    # filter.
    all_repos_rows: list[Repo] = []
    all_author_logins: list[str] = []
    with db.session() as s:
        all_repos_rows = list(s.execute(select(Repo).order_by(Repo.owner, Repo.name)).scalars())
        all_author_logins = [row[0] for row in s.execute(
            select(User.login).order_by(User.login)
        ).all() if row[0]]
    # Resolve owner/name BEFORE the row-level filters so ``?repo=owner/name``
    # can match.
    pr_ids: list[int] = [p.id for p in prs]
    reviewers_by_pr: dict[int, list[dict]] = {pid: [] for pid in pr_ids}
    review_rows: list[tuple[Review, User | None]] = []
    repos_by_id: dict[int, Repo] = {}
    if pr_ids:
        with db.session() as s:
            repos_by_id = {
                r.id: r for r in s.execute(select(Repo)).scalars()
            }
            # Join Review + User in a single query so the dashboard card
            # can render avatar bubbles + reviewer state without an n+1
            # round trip per PR.
            review_rows = list(s.execute(
                select(Review, User)
                .outerjoin(User, User.login == Review.reviewer_login)
                .where(Review.pr_id.in_(pr_ids))
                .order_by(Review.submitted_at.asc())
            ).all())
    for review, user in review_rows:
        state = (review.state or "").lower()
        if state == "approved":
            kind, color = "approved", "#3fb950"
        elif state == "changes_requested":
            kind, color = "changes_requested", "#d29922"
        elif state in ("commented", "dismissed"):
            kind, color = state, "#8b949e"
        else:
            kind, color = "commented", "#8b949e"
        reviewers_by_pr.setdefault(review.pr_id, []).append({
            "login": review.reviewer_login,
            "avatar_url": getattr(user, "avatar_url", None),
            "display_name": getattr(user, "display_name", None),
            "state": state,
            "kind": kind,
            "color": color,
        })
    for pr in prs:
        repo_row = repos_by_id.get(pr.repo_id)
        pr.repo_owner = repo_row.owner if repo_row else ""
        pr.repo_name = repo_row.name if repo_row else ""
        pr.reviewers = reviewers_by_pr.get(pr.id, [])
    # Apply row-level filters: repo, author, and title substring search.
    if repo:
        owner_filter, _, name_filter = repo.partition("/")
        prs = [p for p in prs
               if getattr(p, "repo_owner", "") == owner_filter
               and getattr(p, "repo_name", "") == name_filter]
    if author:
        prs = [p for p in prs if (p.author_login or "") == author]
    if q:
        needle = q.lower()
        prs = [p for p in prs if needle in (p.title or "").lower()]
    # Sort honouring the user's choice.
    if sort == "updated_desc":
        prs.sort(key=lambda p: p.updated_at, reverse=True)
    elif sort == "updated_asc":
        prs.sort(key=lambda p: p.updated_at)
    elif sort == "created_desc":
        prs.sort(key=lambda p: p.created_at, reverse=True)
    elif sort == "created_asc":
        prs.sort(key=lambda p: p.created_at)
    elif sort == "title":
        prs.sort(key=lambda p: (p.title or "").lower())
    # Status counters — translate `compute_badges` names to spec counter
    # names so the dashboard's status strip matches the brief.
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
         "login": login, "counts": counts,
         "scope": scope, "state": state_filter,
         "repo": repo, "author": author, "q": q, "sort": sort,
         "all_repos": all_repos_rows,
         "all_authors": all_author_logins,
         **_user_context(db, login)})


@router.post("/refresh-all")
def refresh_all():
    """Sync every enabled repo's open PRs from GitHub into the local
    cache. Used by the dashboard's "Refresh PRs" button. v1.3.0: no
    longer takes an LLM provider — summaries are author-only via the
    manual description / notes fields."""
    settings = load_settings()
    db = engine_from_settings(settings)
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    repos = svc_list_repos(db, enabled_only=True)
    with GitHubClient(token=token) as gh:
        for repo in repos:
            sync_repo(db, gh, repo)
    return RedirectResponse("/", status_code=303)


@router.post("/repos/pause-all")
def repos_pause_all():
    """Bulk-disable every repo. Matches the per-repo `repos_toggle` route
    semantics. Refresh / resume isn't exposed yet (visual placeholder in
    the mock)."""
    settings = load_settings()
    db = engine_from_settings(settings)
    with db.session() as s:
        repos = list(s.execute(select(Repo)).scalars())
        for r in repos:
            r.enabled = 0
    return RedirectResponse("/repos", status_code=303)


# ---------------------------------------------------------------------------
# Repos page
# ---------------------------------------------------------------------------


# Repo scope → human-readable label, per spec §5.3.
_SCOPE_LABELS = {
    "all": "todos los abiertos",
    "mine": "mis PRs",
    "mine_and_review": "mis PRs + review-requested",
    "review": "solo review-requested",
}


def _humanize_ago(iso_ts: str | None) -> str:
    """Render an ISO-8601 timestamp as a "hace X" relative string.
    Returns ``"—"`` when the timestamp is missing or unparseable so the
    badge stays compact."""
    if not iso_ts:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 0:
        return "—"
    if secs < 60:
        return f"{secs} seg"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min"
    hours = mins // 24 if mins >= 1440 else mins // 60
    if hours < 24:
        return f"{hours} h"
    return f"{hours // 24} d"


def _humanize_reset(reset_unix: int) -> str:
    """Render a unix timestamp as a "en X" relative string for the
    rate-limit banner's reset hint. Past timestamps clamp to "ahora" so
    a stale banner doesn't read "resetea en -3 min"."""
    if not reset_unix:
        return "—"
    delta = reset_unix - int(time.time())
    if delta <= 0:
        return "ahora"
    mins = delta // 60
    if mins < 60:
        return f"{mins} min"
    hours = mins // 60
    if hours < 24:
        return f"{hours} h"
    return f"{hours // 24} d"


@router.get("/repos", response_class=HTMLResponse)
def repos_page(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    # Validate the token up front so a 401 bounces to /settings?
    # error=github_auth instead of silently rendering the page without a
    # rate-limit banner.
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    # Cheap rate-limit probe for the banner. We hit GitHub's
    # /rate_limit endpoint via the proper client method (not the
    # internal ``_client``) so the auth + response shape are kept in
    # one place and a failure surfaces cleanly to the UI instead of
    # rendering a hard-coded "5,000 restantes".
    rl: dict | None = None
    try:
        with GitHubClient(token=token) as gh:
            rate = gh.get_rate_limit()
            limit = rate.limit or 5000
            remaining = max(0, min(limit, rate.remaining))
            pct = (remaining / limit * 100.0) if limit else 0.0
            rl = {
                "limit": limit,
                "remaining": remaining,
                "reset": rate.reset,
                "width_pct": f"{pct:.0f}%",
                "reset_human": _humanize_reset(rate.reset),
            }
    except httpx.HTTPStatusError as e:
        # Surface the failure reason so a 401/403 doesn't render as
        # an empty banner — the user thinks the rate limit is fine.
        rl = {
            "limit": 0,
            "remaining": 0,
            "reset": 0,
            "width_pct": "0%",
            "reset_human": "—",
            "error": f"HTTP{e.response.status_code}",
        }
    except Exception as e:
        rl = {
            "limit": 0,
            "remaining": 0,
            "reset": 0,
            "width_pct": "0%",
            "reset_human": "—",
            "error": type(e).__name__,
        }
    repo_rows = svc_list_repos(db)
    # Single grouped query: open PR count per repo (avoids N+1).
    open_counts: dict[int, int] = {}
    if repo_rows:
        with db.session() as s:
            open_counts = dict(s.execute(
                select(PullRequest.repo_id, func.count(PullRequest.id))
                .where(PullRequest.state == "open")
                .group_by(PullRequest.repo_id)
            ).all())
    repo_count = len(repo_rows)
    active_count = sum(1 for r in repo_rows if r.enabled)
    error_count = sum(1 for r in repo_rows if (r.last_fetch_status or "") == "error")
    global_interval_minutes = (settings.refresh_interval_seconds or 0) // 60
    for r in repo_rows:
        try:
            authors = _json.loads(r.allowed_authors_json or "[]")
        except Exception:
            authors = []
        r.allowed_authors_csv = ", ".join(authors)
        r.open_pr_count = int(open_counts.get(r.id, 0))
        r.scope_label = _SCOPE_LABELS.get(r.scope or "mine_and_review",
                                          r.scope or "mine_and_review")
        r.interval_minutes = (r.refresh_interval_seconds or 0) // 60
        r.last_fetch_human = _humanize_ago(r.last_fetched_at)
    return templates.TemplateResponse(request, "repos.html",
        {"nav": "repos", "theme": _theme(request),
         "repos": repo_rows, "rl": rl,
         "repo_count": repo_count,
         "active_count": active_count,
         "paused_count": repo_count - active_count,
         "error_count": error_count,
         "global_interval_minutes": global_interval_minutes,
         **_user_context(db, "dimh")})


@router.post("/repos/{owner}/{name}/refresh")
def repos_refresh(owner: str, name: str):
    """Per-repo refresh — counterpart to ``POST /refresh-all``. Bounces to
    /settings on auth failure so a stale PAT surfaces to the user
    instead of returning a 500."""
    settings = load_settings()
    db = engine_from_settings(settings)
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    with db.session() as s:
        repo = s.execute(select(Repo).where(
            Repo.owner == owner, Repo.name == name
        )).scalar_one()
    with GitHubClient(token=token) as gh:
        sync_repo(db, gh, repo)
    return RedirectResponse("/repos", status_code=303)


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


# ---------------------------------------------------------------------------
# Per-repo config page
# ---------------------------------------------------------------------------


_SCOPE_CHOICES = [
    ("all", "Todos los PRs abiertos"),
    ("mine", "Solo PRs donde soy autor"),
    ("mine_and_review", "PRs donde soy autor + los que me pidieron review"),
    ("review", "Solo los que me pidieron review"),
]


@router.get("/repos/{owner}/{name}", response_class=HTMLResponse)
def repo_config_page(request: Request, owner: str, name: str):
    """Per-repo config — scope, refresh interval, allowed authors,
    self / dogfooding flag. Reachable via the "⚙ config" button on
    the repos listing.
    """
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    repo = svc_get_repo(db, owner, name)
    if repo is None:
        return HTMLResponse(
            f"<h1>Repo no encontrado</h1>"
            f"<p>{owner}/{name} no está registrado. Volvé a "
            f"<a href='/repos'>/repos</a>.</p>",
            status_code=404,
        )
    try:
        authors = json.loads(repo.allowed_authors_json or "[]")
    except Exception:
        authors = []
    repo.allowed_authors_csv = ", ".join(authors)
    repo.interval_minutes = (repo.refresh_interval_seconds or 300) // 60
    return templates.TemplateResponse(request, "repo_config.html", {
        "nav": "repos",
        "theme": _theme(request),
        "repo": repo,
        "scope_choices": _SCOPE_CHOICES,
        **_user_context(db, "dimh"),
    })


@router.post("/repos/{owner}/{name}/config")
def repo_config_save(owner: str, name: str,
                     scope: str = Form(...),
                     refresh_minutes: int = Form(...),
                     authors: str = Form(""),
                     is_self: str = Form("")):
    """Persist per-repo config (scope / refresh / authors / self)."""
    settings = load_settings()
    db = engine_from_settings(settings)
    author_list = [a for a in authors.split(",") if a.strip()]
    try:
        svc_update_repo_config(
            db, owner, name,
            scope=scope,
            refresh_interval_seconds=int(refresh_minutes) * 60,
            allowed_authors=author_list,
            is_self=(is_self == "on"),
        )
    except KeyError:
        return RedirectResponse("/repos", status_code=303)
    return RedirectResponse(
        f"/repos/{owner}/{name}?ok=saved",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Theme toggle
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# PR detail — manual description / notes + review prompt viewer
# ---------------------------------------------------------------------------


@router.get("/pr/{owner}/{name}/{number}", response_class=HTMLResponse)
def pr_detail(request: Request, owner: str, name: str, number: int):
    """PR detail page. v1.3.0 layout:

    - Manual description / notes edit forms on the left (formerly the
      AI summary card).
    - Right-side widget: a tabbed prompt viewer that renders the
      ``review`` / ``post_review`` / ``check_resolved`` templates with
      the live PR metadata + diff spliced in. The user copies the
      output into their external LLM.

    The route doesn't talk to GitHub on GET — the prompt viewer is
    rendered on demand via ``POST /pr/.../show-review-prompt`` so the
    page stays snappy and we don't burn rate-limit on a refresh that
    didn't ask for fresh data.
    """
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    pr = None
    human_reviews: list[Review] = []
    human_comments: list[ReviewComment] = []
    issue_comments: list[IssueComment] = []
    pr_commits: list = []
    pr_files: list = []
    # User rows keyed by login so the template can render avatars and
    # display names without hitting the DB per row.
    user_by_login: dict[str, User] = {}
    resolved_count = 0
    pending_count = 0
    new_count = 0
    commits_count = 0
    human_reviews_count = 0
    human_comments_count = 0
    issue_comments_count = 0
    with db.session() as s:
        repo = s.execute(select(Repo).where(
            Repo.owner == owner, Repo.name == name
        )).scalar_one_or_none()
        if repo:
            pr = s.execute(select(PullRequest).where(
                PullRequest.repo_id == repo.id, PullRequest.number == number
            )).scalar_one_or_none()
            if pr:
                human_reviews = list(s.execute(
                    select(Review).where(Review.pr_id == pr.id)
                    .order_by(Review.submitted_at.asc())
                ).scalars())
                human_comments = list(s.execute(
                    select(ReviewComment).where(ReviewComment.pr_id == pr.id)
                    .order_by(ReviewComment.created_at.asc())
                ).scalars())
                issue_comments = list(s.execute(
                    select(IssueComment).where(IssueComment.pr_id == pr.id)
                    .order_by(IssueComment.created_at.asc())
                ).scalars())
                # v1.3.x: fetch the full commit list + per-file stats for
                # the new Commits / Files tabs. Cheap when the sync just
                # ran (in-memory), zero network calls on a GET.
                pr_commits = list(s.execute(
                    select(PRCommit).where(PRCommit.pr_id == pr.id)
                    .order_by(PRCommit.committed_at.asc().nulls_last())
                ).scalars())
                pr_files = list(s.execute(
                    select(PRFile).where(PRFile.pr_id == pr.id)
                    .order_by(PRFile.path.asc())
                ).scalars())
                # Pull every user we may need to render avatars in one shot.
                logins = {r.reviewer_login for r in human_reviews} \
                    | {c.reviewer_login for c in human_comments} \
                    | {c.author_login for c in issue_comments} \
                    | {c.author_login for c in pr_commits if c.author_login}
                if logins:
                    user_by_login = {
                        u.login: u for u in s.execute(
                            select(User).where(User.login.in_(logins))
                        ).scalars()
                    }
                human_reviews_count = len(human_reviews)
                human_comments_count = len(human_comments)
                issue_comments_count = len(issue_comments)
                # Prefer the live list count over the cached integer
                # so a sync that fetched more commits than the last
                # cached_at update reflects on the page immediately.
                commits_count = max(
                    len(pr_commits), getattr(pr, "commits_count", 0) or 0
                )
    # Thread the comments: build per-issue-comment reply trees so the
    # template can render GitHub-style nested conversation. Replies
    # render under their parent (linked by GitHub's ``in_reply_to_id``).
    # Top-level comments stay in chronological order.
    issue_threads = _thread_issue_comments(issue_comments)
    review_threads = _thread_review_comments(human_comments)
    # Attach avatar / display name to each comment row so the
    # template doesn't need a separate User lookup per row.
    for c in issue_comments:
        u = user_by_login.get(c.author_login)
        c.author_avatar_url = getattr(u, "avatar_url", None)
        c.author_display_name = getattr(u, "display_name", None)
    for c in human_comments:
        u = user_by_login.get(c.reviewer_login)
        c.reviewer_avatar_url = getattr(u, "avatar_url", None)
        c.reviewer_display_name = getattr(u, "display_name", None)
    for r in human_reviews:
        u = user_by_login.get(r.reviewer_login)
        r.reviewer_avatar_url = getattr(u, "avatar_url", None)
        r.reviewer_display_name = getattr(u, "display_name", None)
    for c in pr_commits:
        u = user_by_login.get(c.author_login) if c.author_login else None
        c.author_avatar_url = getattr(u, "avatar_url", None)
        c.author_display_name = getattr(u, "display_name", None)
    reply_ok = request.query_params.get("ok") in ("reply", "reply_stale")
    reply_ok_partial = request.query_params.get("ok") == "reply_stale"
    reply_stale_reason = request.query_params.get("reason") if reply_ok_partial else ""
    error_param = request.query_params.get("error", "")
    return templates.TemplateResponse(request, "pr_detail.html",
        {"nav": "home", "theme": _theme(request),
         "pr": pr,
         "human_reviews": human_reviews,
         "human_comments": human_comments,
         "issue_comments": issue_comments,
         "pr_commits": pr_commits,
         "pr_files": pr_files,
         "issue_threads": issue_threads,
         "review_threads": review_threads,
         "issue_comments_count": issue_comments_count,
         "resolved_count": resolved_count,
         "pending_count": pending_count,
         "new_count": new_count,
         "commits_count": commits_count,
         "human_reviews_count": human_reviews_count,
         "human_comments_count": human_comments_count,
         "prompt_slots": PROMPT_SLOTS,
         "owner": owner, "name": name,
         "reply_ok": reply_ok,
         "reply_ok_partial": reply_ok_partial,
         "reply_stale_reason": reply_stale_reason,
         "reply_error": error_param,
         **_user_context(db, "dimh")})


def _thread_issue_comments(comments: list[IssueComment]) -> list[dict]:
    """Group replies under their parent comment for GitHub-style
    rendering. Top-level comments stay in the order they were created
    (so a sync doesn't reshuffle mid-thread). Replies are sorted by
    ``created_at`` ascending inside each thread.
    """
    by_id: dict[int, IssueComment] = {c.github_id: c for c in comments if c.github_id}
    top: list[dict] = []
    replies: dict[int, list[IssueComment]] = {}
    for c in comments:
        parent = c.in_reply_to_id if c.in_reply_to_id and c.in_reply_to_id in by_id else None
        if parent is None:
            top.append({"comment": c, "replies": []})
        else:
            replies.setdefault(parent, []).append(c)
    for node in top:
        node["replies"] = sorted(replies.get(node["comment"].github_id, []),
                                 key=lambda c: c.created_at)
    return top


def _thread_review_comments(comments: list[ReviewComment]) -> list[dict]:
    """Same threading model as issue comments but for inline review
    comments (anchored to a diff line)."""
    by_id: dict[int, ReviewComment] = {c.github_id: c for c in comments if c.github_id}
    top: list[dict] = []
    replies: dict[int, list[ReviewComment]] = {}
    for c in comments:
        parent = c.in_reply_to_id if c.in_reply_to_id and c.in_reply_to_id in by_id else None
        if parent is None:
            top.append({"comment": c, "replies": []})
        else:
            replies.setdefault(parent, []).append(c)
    for node in top:
        node["replies"] = sorted(replies.get(node["comment"].github_id, []),
                                 key=lambda c: c.created_at)
    return top


@router.post("/pr/{owner}/{name}/{number}/refresh")
def pr_refresh(owner: str, name: str, number: int):
    """Refresh a single PR's metadata + reviews + comments from GitHub.
    Bounces to /settings on auth failure."""
    settings = load_settings()
    db = engine_from_settings(settings)
    with db.session() as s:
        repo = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    with GitHubClient(token=token) as gh:
        sync_one_pr(db, gh, repo, number)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)


@router.post("/pr/{owner}/{name}/{number}/manual-description")
def pr_save_manual_description(owner: str, name: str, number: int,
                               description: str = Form("")):
    """Persist the author's manual description for a PR. Empty text
    clears the field."""
    settings = load_settings()
    db = engine_from_settings(settings)
    with db.session() as s:
        repo = s.execute(select(Repo).where(
            Repo.owner == owner, Repo.name == name
        )).scalar_one()
    save_manual_description(db, repo, number, description)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}?ok=description",
                            status_code=303)


@router.post("/pr/{owner}/{name}/{number}/manual-notes")
def pr_save_manual_notes(owner: str, name: str, number: int,
                         notes: str = Form("")):
    """Persist the author's internal notes for a PR. Empty text clears
    the field."""
    settings = load_settings()
    db = engine_from_settings(settings)
    with db.session() as s:
        repo = s.execute(select(Repo).where(
            Repo.owner == owner, Repo.name == name
        )).scalar_one()
    save_manual_notes(db, repo, number, notes)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}?ok=notes",
                            status_code=303)


@router.post("/pr/{owner}/{name}/{number}/reply-issue")
def pr_reply_issue_comment(owner: str, name: str, number: int,
                           body: str = Form(...),
                           in_reply_to: str = Form("")):
    """Reply to a top-level (or threaded) issue conversation comment.

    Both the new comment and the parent's threading link are persisted
    locally so the GitHub-style timeline renders correctly. Posting to
    GitHub first means a network failure surfaces a friendly redirect
    instead of a half-saved reply.
    """
    body_text = (body or "").strip()
    if not body_text:
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?error=empty_reply",
            status_code=303,
        )
    settings = load_settings()
    db = engine_from_settings(settings)
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    in_reply_to_id = None
    if in_reply_to:
        try:
            in_reply_to_id = int(in_reply_to)
        except ValueError:
            in_reply_to_id = None
    with db.session() as s:
        repo = s.execute(select(Repo).where(
            Repo.owner == owner, Repo.name == name
        )).scalar_one()
    try:
        with GitHubClient(token=token) as gh:
            posted = post_issue_comment_reply(
                db, gh, repo, number, body_text,
                in_reply_to_github_id=in_reply_to_id,
            )
    except httpx.HTTPStatusError as e:
        # GitHub rejected the reply (401 bad token, 403 forbidden /
        # missing write scope, 422 invalid body, 404 on archived repo…).
        # Surface the status + GitHub's own error message so the user
        # knows exactly what to fix.
        body_text = ""
        try:
            body_text = (e.response.json().get("message") or "")[:140]
        except Exception:
            pass
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?error=reply_failed&reason="
            f"HTTP{e.response.status_code}&msg={body_text}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?error=reply_failed&reason="
            f"{type(e).__name__}",
            status_code=303,
        )
    # Reply succeeded on GitHub. If the post-reply sync failed, surface
    # that as a separate banner so they know their comment went through
    # but the local cache is stale.
    if posted.get("_sync_error"):
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?ok=reply_stale&reason="
            f"{posted['_sync_error']}",
            status_code=303,
        )
    return RedirectResponse(
        f"/pr/{owner}/{name}/{number}?ok=reply",
        status_code=303,
    )


@router.post("/pr/{owner}/{name}/{number}/reply-review-comment")
def pr_reply_review_comment(owner: str, name: str, number: int,
                            comment_github_id: str = Form(...),
                            body: str = Form(...)):
    """Reply to an inline review comment anchored to a diff line."""
    body_text = (body or "").strip()
    if not body_text:
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?error=empty_reply",
            status_code=303,
        )
    try:
        parent_id = int(comment_github_id)
    except ValueError:
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?error=reply_failed",
            status_code=303,
        )
    settings = load_settings()
    db = engine_from_settings(settings)
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    with db.session() as s:
        repo = s.execute(select(Repo).where(
            Repo.owner == owner, Repo.name == name
        )).scalar_one()
    try:
        with GitHubClient(token=token) as gh:
            posted = post_review_comment_reply(
                db, gh, repo, number, parent_id, body_text,
            )
    except httpx.HTTPStatusError as e:
        body_text = ""
        try:
            body_text = (e.response.json().get("message") or "")[:140]
        except Exception:
            pass
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?error=reply_failed&reason="
            f"HTTP{e.response.status_code}&msg={body_text}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?error=reply_failed&reason="
            f"{type(e).__name__}",
            status_code=303,
        )
    if posted.get("_sync_error"):
        return RedirectResponse(
            f"/pr/{owner}/{name}/{number}?ok=reply_stale&reason="
            f"{posted['_sync_error']}",
            status_code=303,
        )
    return RedirectResponse(
        f"/pr/{owner}/{name}/{number}?ok=reply",
        status_code=303,
    )


@router.post("/pr/{owner}/{name}/{number}/show-review-prompt")
def pr_show_review_prompt(request: Request, owner: str, name: str, number: int,
                          slot: str = Form("review"),
                          mode: str = Form("fresh")):
    """Render the assembled review prompt for the chosen slot.

    The page is HTMX-friendly: returns a fragment (the rendered prompt
    body inside a <pre>) so the right-side widget swaps the tab content
    in place. The full page redirect keeps the URL stable for users who
    disable JS.
    """
    if slot not in PROMPT_SLOTS:
        slot = "review"
    settings = load_settings()
    db = engine_from_settings(settings)
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    try:
        with GitHubClient(token=token) as gh:
            body = assemble_review_prompt(
                gh,
                data_dir=settings.data_dir,
                owner=owner,
                name=name,
                number=number,
                slot=slot,
                mode=mode,
            )
    except Exception as e:
        body = f"<error: {e}>"
    # If the request is from HTMX (hx-request header), return just the
    # fragment so the page doesn't re-render. Otherwise redirect back to
    # the PR detail with the body on the query so non-JS users still see
    # something useful.
    is_htmx = request.headers.get("hx-request") == "true"
    if is_htmx:
        from fastapi.responses import HTMLResponse as _HTML
        return _HTML(
            f'<article class="prompt-body" data-slot="{slot}" data-mode="{mode}">'
            f'<button class="copy-btn" data-action="copy">📋 copiar</button>'
            f'<pre>{body}</pre>'
            f'</article>'
        )
    return RedirectResponse(
        f"/pr/{owner}/{name}/{number}?prompt_slot={slot}&prompt_mode={mode}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Settings — auth + skills (no LLM block)
# ---------------------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """Settings tab — Auth + Skills.

    v1.3.0 removed the LLM block entirely. Settings now exposes only:
    - Auth (PAT / OAuth)
    - Skills registry with the three per-skill prompt slots editable
      inline (``review`` / ``post_review`` / ``check_resolved``).
    """
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    cfg = load_config_yaml(settings.data_dir / "config.yaml")
    # Global prompts — load from disk (preserves user edits) with the
    # built-in defaults as fallback so a first-run user sees the
    # templates pre-filled.
    prompts = load_prompts(settings.data_dir)
    if settings.github_oauth_access_token:
        auth_mode = "oauth"
    else:
        auth_mode = "pat"
    token_last4 = (settings.github_token[-4:]
                   if settings.github_token else "<none>")
    return templates.TemplateResponse(request, "settings.html",
        {"nav": "settings", "theme": _theme(request),
         "settings": settings,
         "prompts": prompts,
         "prompt_slots": PROMPT_SLOTS,
         "auth_mode": auth_mode,
         "token_last4": token_last4,
         **_user_context(db, "dimh")})


@router.post("/settings/auth/save")
def settings_auth_save(github_token: str = Form(""),
                       github_oauth_client_id: str = Form(""),
                       github_oauth_client_secret: str = Form(""),
                       github_token_edit: str = Form(""),
                       github_oauth_client_id_edit: str = Form(""),
                       github_oauth_client_secret_edit: str = Form(""),
                       auth_mode: str = Form("pat")):
    settings = load_settings()
    # The settings page submits *two* fields per credential: the hidden
    # current value (carries the previous token when the user didn't touch
    # it) and an editable input (`*_edit`) that the user actually fills
    # in. We honour `_edit` when non-empty and fall back to the hidden
    # current value when blank.
    _persist_auth_keys(
        settings.data_dir / ".env",
        github_token=github_token_edit or github_token,
        github_oauth_client_id=github_oauth_client_id_edit or github_oauth_client_id,
        github_oauth_client_secret=github_oauth_client_secret_edit or github_oauth_client_secret,
    )
    cfg_path = settings.data_dir / "config.yaml"
    cfg = load_config_yaml(cfg_path)
    cfg.setdefault("auth", {})["mode"] = auth_mode
    save_config_yaml(cfg_path, cfg)
    return RedirectResponse("/settings?ok=auth", status_code=303)


@router.post("/settings/prompts")
async def settings_prompts_save(request: Request):
    """Persist the global prompts editor submissions.

    The form posts one field per slot (``prompt.<slot>``). Empty
    submissions are tolerated — the slot falls back to the built-in
    default the next time it's loaded.
    """
    settings = load_settings()
    form = await request.form()
    out: dict[str, str] = {}
    for slot in PROMPT_SLOTS:
        # If the same key is repeated, keep the first non-empty value.
        values = form.getlist(f"prompt.{slot}")
        out[slot] = next((v for v in values if v), values[0] if values else "")
    _save_prompts(settings.data_dir, out)
    return RedirectResponse("/settings?ok=prompts", status_code=303)


@router.post("/settings/auth/disconnect")
def settings_auth_disconnect():
    """Clear OAuth credentials + config auth.mode. The dashboard
    re-validates the GitHub token eagerly on the next render, so a
    stale PAT will bounce to /settings?error=github_auth instead of
    silently using a dead credential."""
    settings = load_settings()
    env_path = settings.data_dir / ".env"
    if env_path.exists():
        import os
        lines = env_path.read_text().splitlines()
        keep = [ln for ln in lines
                if not (ln.startswith("TOWERWATCH_GITHUB_OAUTH_CLIENT_ID=")
                        or ln.startswith("TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET=")
                        or ln.startswith("TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN=")
                        or ln.startswith("TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN="))]
        tmp = env_path.with_suffix(env_path.suffix + ".tmp")
        tmp.write_text("\n".join(keep) + "\n")
        os.replace(tmp, env_path)
    cfg_path = settings.data_dir / "config.yaml"
    cfg = load_config_yaml(cfg_path)
    cfg.setdefault("auth", {})["mode"] = "pat"
    save_config_yaml(cfg_path, cfg)
    return RedirectResponse("/settings?ok=auth", status_code=303)


@router.post("/settings/restore-defaults")
def settings_restore_defaults():
    """Wipe both .env and config.yaml back to empty-template state.
    The user has to confirm via a JS prompt (template)."""
    import os
    settings = load_settings()
    env_path = settings.data_dir / ".env"
    if env_path.exists():
        env_path.unlink()
    cfg_path = settings.data_dir / "config.yaml"
    if cfg_path.exists():
        cfg_path.unlink()
    env_path.touch()
    cfg_path.touch()
    return RedirectResponse("/settings?ok=defaults", status_code=303)


@router.post("/settings/auth/test")
def settings_auth_test():
    """Probe GitHub with the current PAT and bounce to /settings with
    a status banner. The button labelled "🔄 Probar conexión" on the
    auth card wires here."""
    settings = load_settings()
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return RedirectResponse("/settings?test=auth_missing", status_code=303)
    try:
        with GitHubClient(token=token) as gh:
            user = gh.get_authenticated_user()
        return RedirectResponse(
            f"/settings?test=auth_ok&login={user.login}", status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            f"/settings?test=auth_fail&reason={type(e).__name__}", status_code=303
        )


def _persist_auth_keys(env_path: Path, github_token: str,
                       github_oauth_client_id: str,
                       github_oauth_client_secret: str) -> None:
    """Persist Auth-form values to .env, only touching the Auth keys.

    Empty form values are treated as "no change" so submitting a partial
    Auth form (e.g. only the PAT) cannot wipe secrets the user didn't
    intend to touch. Non-empty form values replace any existing line for
    that key. Keys owned by other helpers are never touched.
    """
    import os
    updates = {
        "TOWERWATCH_GITHUB_TOKEN": github_token,
        "TOWERWATCH_GITHUB_OAUTH_CLIENT_ID": github_oauth_client_id,
        "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET": github_oauth_client_secret,
    }
    keys = set(updates.keys())
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    existing = {}
    for ln in lines:
        for k in keys:
            if ln.startswith(k + "="):
                existing[k] = ln[len(k) + 1:]
                break
    new_lines = [ln for ln in lines if not any(ln.startswith(k + "=") for k in keys)]
    for k, v in updates.items():
        if v:
            new_lines.append(f"{k}={v}")
        elif k in existing:
            new_lines.append(f"{k}={existing[k]}")
    tmp = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp.write_text("\n".join(new_lines) + "\n")
    os.replace(tmp, env_path)