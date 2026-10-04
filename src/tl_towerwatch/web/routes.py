from __future__ import annotations

import json as _json
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

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
    User,
)
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.llm import get_provider
from tl_towerwatch.services.pull_requests import list_prs_for_dashboard, sync_one_pr, sync_repo
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


def _from_json(text: str | None) -> list:
    """Decode the JSON-encoded ``skills_json`` column for the run header
    chip. Returns an empty list when the field is missing or malformed
    so the template can iterate without a try/except."""
    import json as _json_local
    if not text:
        return []
    try:
        v = _json_local.loads(text)
    except Exception:
        return []
    return v if isinstance(v, list) else []


def _skill_chips(names: list[str]) -> str:
    """Render a run's skill list as the mock's icon-prefixed chips
    (``⚡ superpowers + 🐴 ponytail``). Unknown skills fall back to the
    raw name so future skills still show up in the UI."""
    out: list[str] = []
    for n in names:
        if n == "superpowers":
            out.append("⚡ superpowers")
        elif n == "ponytail":
            out.append("🐴 ponytail")
        else:
            out.append(str(n))
    return " + ".join(out)


def _run_duration(run) -> str:
    """Format the run's wall-clock duration as ``Xm Ys`` for the run
    header line. Falls back to ``""`` when either timestamp is missing
    so the header layout stays clean for runs that never finished."""
    from datetime import datetime, timezone
    if not getattr(run, "finished_at", None) or not getattr(run, "started_at", None):
        return ""
    try:
        s_raw = run.started_at
        e_raw = run.finished_at
        if s_raw.endswith("Z"):
            s_raw = s_raw[:-1] + "+00:00"
        if e_raw.endswith("Z"):
            e_raw = e_raw[:-1] + "+00:00"
        s = datetime.fromisoformat(s_raw)
        e = datetime.fromisoformat(e_raw)
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        if e.tzinfo is None:
            e = e.replace(tzinfo=timezone.utc)
    except Exception:
        return ""
    secs = int((e - s).total_seconds())
    if secs < 0:
        return ""
    if secs >= 300:
        return "timeout 5min ⚠️"
    if secs < 60:
        return f"{secs}s"
    m, s2 = divmod(secs, 60)
    return f"{m}m {s2:02d}s"


def _hace(ts: str | None) -> str:
    """Spanish ``hace X`` relative time label used in the breadcrumb / run
    history rows. Returns ``"hace ?"`` when the timestamp is missing or
    unparseable so the template never crashes on a bad row."""
    from datetime import datetime, timezone
    if not ts:
        return "hace ?"
    try:
        # ISO 8601 with optional trailing ``Z``.
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
templates.env.filters["skill_chips"] = _skill_chips
templates.env.globals["run_duration"] = _run_duration

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
def index(request: Request,
          scope: str = "attention",
          repo: str = "",
          author: str = "",
          q: str = "",
          sort: str = "updated_desc"):
    """Dashboard list with full filter + sort wiring (mock parity).

    Query params:
    - scope: "attention" (default — needs response + awaiting my review),
      "mine" (your PRs), "review" (review-requested), "all" (everything
      in the watched repos regardless of authorship/reviewer state).
    - repo: "owner/name" — restrict to one repo. Empty = all repos.
    - author: GitHub login — restrict to PRs authored by this user.
    - q: case-insensitive substring match against ``pr.title``.
    - sort: "updated_desc" (default), "created_desc", "title".

    Filter state is passed back to the template so each filter UI element
    can highlight its active value, build cross-filter preserving links for
    the sort/tab chips, and seed the search input.
    """
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
    # Scope "attention" isn't a primitive of list_prs_for_dashboard; it
    # means "needs response + awaiting my review" which is the union of
    # `mine` and `review`. Resolve the two scopes, then merge below.
    raw_scope = scope if scope in ("mine", "review", "all") else None
    if scope == "attention":
        mine_prs = list_prs_for_dashboard(db, login=login, scope_filter="mine")
        review_prs = list_prs_for_dashboard(db, login=login, scope_filter="review")
        seen: set[int] = set()
        prs: list[PullRequest] = []
        for p in mine_prs + review_prs:
            if p.id in seen:
                continue
            seen.add(p.id)
            prs.append(p)
    else:
        prs = list_prs_for_dashboard(db, login=login, scope_filter=raw_scope)
    # Dropdown sources are pulled BEFORE the row-level filters so the user
    # always sees every watched repo and every known User as a filter
    # option — not just the ones that survived the current scope+repo
    # filter. Without this, switching scope to one that hides everything
    # (e.g. scope=review when you have no review-requested PRs) leaves
    # the repo/author dropdowns empty and the user can't escape the
    # empty view because there's nothing to choose.
    all_repos_rows: list[Repo] = []
    all_author_logins: list[str] = []
    with db.session() as s:
        all_repos_rows = list(s.execute(select(Repo).order_by(Repo.owner, Repo.name)).scalars())
        all_author_logins = [row[0] for row in s.execute(
            select(User.login).order_by(User.login)
        ).all() if row[0]]
    # PullRequest only carries repo_id (FK); the template needs owner/name to
    # build detail-page links and per-PR action buttons. Resolve owner/name
    # BEFORE the row-level filters so ``?repo=owner/name`` can match.
    pr_ids: list[int] = [p.id for p in prs]
    reviewers_by_pr: dict[int, list[dict]] = {pid: [] for pid in pr_ids}
    summary_by_pr: dict[int, PRSummary] = {}
    # Default values; the ``if pr_ids`` block below may overwrite both. We
    # must bind them here so the post-loop iteration sees local variables
    # instead of raising UnboundLocalError when no PRs are in scope.
    review_rows: list[tuple[Review, User | None]] = []
    repos_by_id: dict[int, Repo] = {}
    if pr_ids:
        with db.session() as s:
            repos_by_id = {
                r.id: r for r in s.execute(select(Repo)).scalars()
            }
            # Join Review + User in a single query so the dashboard card can
            # render avatar bubbles + reviewer state without an n+1 round
            # trip per PR. ``outerjoin`` preserves review rows whose
            # reviewer hasn't been synced into the User table yet (those
            # cards then fall back to initials).
            review_rows = list(s.execute(
                select(Review, User)
                .outerjoin(User, User.login == Review.reviewer_login)
                .where(Review.pr_id.in_(pr_ids))
                .order_by(Review.submitted_at.asc())
            ).all())
            summary_rows = list(s.execute(
                select(PRSummary).where(PRSummary.pr_id.in_(pr_ids))
            ).scalars())
            summary_by_pr = {row.pr_id: row for row in summary_rows}
    # Bucket reviews by PR, attaching kind/color derived from the GitHub
    # review state. Pending reviewers (no Review record) intentionally
    # aren't here — the DB schema doesn't track them, so a UI bubble for
    # a not-yet-reviewed reviewer would require a separate GitHub sync.
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
        # Attached as ad-hoc attributes for the template; SQLAlchemy ORM
        # instances allow this without persisting anything new.
        pr.reviewers = reviewers_by_pr.get(pr.id, [])
        pr.summary = summary_by_pr.get(pr.id)
    # Apply the row-level filters that aren't covered by the scope: repo,
    # author, and title substring search. Run after owner/name resolution so
    # ``?repo=owner/name`` can match on the freshly-attached attributes.
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
    # Sort: list_prs_for_dashboard already sorts by updated_at desc; we
    # re-sort to honour the user's choice. Both ascending and descending
    # variants are supported so the user can flip the order without
    # losing the rest of their filter state.
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
         "login": login, "counts": counts,
         # Filter + sort state, echoed back so the template can highlight
         # the active tab/sort/select and build cross-filter preserving
         # links for the tab and sort chips.
         "scope": scope, "repo": repo, "author": author, "q": q, "sort": sort,
         "all_repos": all_repos_rows,
         "all_authors": all_author_logins,
         **_user_context(db, login)})

@router.post("/refresh-all")
def refresh_all():
    """Sync every enabled repo's open PRs from GitHub into the local cache.

    Used by the dashboard's "Refresh PRs" button. Errors per-repo are
    captured on the Repo row (last_fetch_status / last_fetch_error) so a
    single bad repo can't poison the rest of the sync. On auth failure
    the route bounces to /settings?error=github_auth, matching the
    per-PR refresh path (Task 10).
    """
    settings = load_settings()
    db = engine_from_settings(settings)
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    repos = svc_list_repos(db, enabled_only=True)
    llm = get_provider(settings) if settings.llm.anthropic.api_key else None
    with GitHubClient(token=token) as gh:
        for repo in repos:
            sync_repo(db, gh, repo, llm=llm)
    return RedirectResponse("/", status_code=303)


@router.post("/repos/pause-all")
def repos_pause_all():
    """Bulk-disable every repo. The bulk "Pausar todos" button on the
    /repos page wires here; matches the per-repo `repos_toggle` route's
    semantics. Refresh / resume isn't exposed yet (visual placeholder in
    the mock) — a future task will add `POST /repos/resume-all` and
    render the right label dynamically based on aggregate enabled state.
    """
    settings = load_settings()
    db = engine_from_settings(settings)
    with db.session() as s:
        repos = list(s.execute(select(Repo)).scalars())
        for r in repos:
            r.enabled = 0
    return RedirectResponse("/repos", status_code=303)

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
                remaining = int(core.get("remaining", 0) or 0)
                reset = int(core.get("reset", 0) or 0)
                # Width = remaining/5000 capped at 0..100% — the mock caps the
                # bar at the 5,000 calls/hour budget of a PAT.
                pct = max(0.0, min(100.0, remaining / 5000.0 * 100.0))
                rl = {
                    "remaining": remaining,
                    "reset": reset,
                    "width_pct": f"{pct:.0f}%",
                    "reset_human": _humanize_reset(reset),
                }
    except Exception:
        rl = None
    repo_rows = svc_list_repos(db)
    # Single grouped query: open PR count per repo (spec §5.3). Avoids an N+1
    # over `repo_rows` when the user has many repos registered.
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
    llm_default_model = _llm_default_model(settings)
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
        # Per-repo override wins over the global default; mirrors the LLM
        # resolution order in `services.pull_requests.sync_repo`.
        r.llm_display = r.llm_override or llm_default_model
    return templates.TemplateResponse(request, "repos.html",
        {"nav": "repos", "theme": _theme(request),
         "repos": repo_rows, "rl": rl,
         "repo_count": repo_count,
         "active_count": active_count,
         "paused_count": repo_count - active_count,
         "error_count": error_count,
         "global_interval_minutes": global_interval_minutes,
         **_user_context(db, "dimh")})


# Repo scope -> human-readable label, per spec §5.3. New scopes need a label
# here (and a matching entry in `services.pull_requests.list_prs_for_dashboard`)
# to surface in the repos UI.
_SCOPE_LABELS = {
    "all": "todos los abiertos",
    "mine": "mis PRs",
    "mine_and_review": "mis PRs + review-requested",
    "review": "solo review-requested",
}


def _humanize_ago(iso_ts: str | None) -> str:
    """Render an ISO-8601 timestamp as a "hace X" relative string.

    Used by the repos page to show how long ago each repo was last fetched
    (and, for paused repos, how long since they were paused). Returns ``"—"``
    when the timestamp is missing or unparseable so the badge stays compact.
    """
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
    hours = mins // 60
    if hours < 24:
        return f"{hours} h"
    days = hours // 24
    return f"{days} d"


def _humanize_reset(reset_unix: int) -> str:
    """Render a unix timestamp as a "en X" relative string for the rate-limit
    banner's reset hint. Matches the granularity ladder in ``_humanize_ago``
    (seg / min / h / d) and clamps past timestamps to "ahora" so a stale
    banner doesn't read "resetea en -3 min"."""
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
    days = hours // 24
    return f"{days} d"


def _llm_default_model(settings: Settings) -> str:
    """Resolve the configured LLM model name for the repos page. Mirrors the
    provider dispatch in ``tl_towerwatch.llm.get_provider`` so the UI label
    tracks the same default the sync path uses."""
    p = settings.llm.default_provider
    if p == "anthropic":
        return settings.llm.anthropic.model
    if p == "openai":
        return settings.llm.openai.model
    if p == "ollama":
        return settings.llm.ollama.model
    # Fallback to anthropic when an unknown provider slipped through.
    return settings.llm.anthropic.model


@router.post("/repos/{owner}/{name}/refresh")
def repos_refresh(owner: str, name: str):
    """Sync a single repo's open PRs from GitHub into the local cache.

    Per-repo counterpart to ``POST /refresh-all`` — used by the repos page's
    per-row "▶ Refrescar ahora" button. Bounces to /settings on auth failure
    so a stale PAT surfaces to the user instead of returning a 500.
    """
    settings = load_settings()
    db = engine_from_settings(settings)
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    with db.session() as s:
        repo = s.execute(select(Repo).where(
            Repo.owner == owner, Repo.name == name
        )).scalar_one()
    llm = get_provider(settings) if settings.llm.anthropic.api_key else None
    with GitHubClient(token=token) as gh:
        sync_repo(db, gh, repo, llm=llm)
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
    last_run: ReviewRun | None = None
    human_reviews: list[Review] = []
    human_comments: list[ReviewComment] = []
    resolved_count = 0
    pending_count = 0
    new_count = 0
    commits_count = 0
    human_reviews_count = 0
    human_comments_count = 0
    runs_count = 0
    pending_review_run = 0  # how many agent runs ended in a non-done state
    # Skills come from config.yaml via load_config_yaml, same plumbing the
    # settings page uses (the skill registry also reads the same file).
    # We deliberately fall back to the default registry (superpowers +
    # ponytail) when the file is absent or malformed so the widget still
    # renders for first-run users without a saved config.yaml.
    from tl_towerwatch.skills.registry import default_registry
    cfg_path = settings.data_dir / "config.yaml"
    cfg_data = load_config_yaml(cfg_path)
    enabled_skills: list[dict] = []
    raw_skills = cfg_data.get("skills", {})
    if isinstance(raw_skills, dict) and raw_skills:
        for skill_name, skill_val in raw_skills.items():
            if isinstance(skill_val, dict) and skill_val.get("enabled", True):
                enabled_skills.append({
                    "name": skill_name,
                    "cli_flag": skill_val.get("cli_flag", f"--skill {skill_name}"),
                    "description": skill_val.get("description", ""),
                })
    if not enabled_skills:
        for sk in default_registry():
            if sk.enabled:
                enabled_skills.append({
                    "name": sk.name,
                    "cli_flag": sk.cli_flag,
                    "description": sk.description,
                })
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
                human_reviews_count = len(human_reviews)
                human_comments_count = len(human_comments)
                # tl_towerwatch review runs (newest first). We attach the
                # findings to each run so the template can render them in
                # the loop without re-querying.
                runs = list(s.execute(
                    select(ReviewRun).where(ReviewRun.pr_id == pr.id)
                    .order_by(ReviewRun.id.desc())
                ).scalars())
                runs_count = len(runs)
                if runs:
                    last_run = runs[0]
                    if last_run.status != "done":
                        pending_review_run = 1
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
                # commits_count is populated by sync_one_pr from the
                # /pulls/:number endpoint. Default to 0 when missing so the
                # tab label still renders.
                commits_count = getattr(pr, "commits_count", 0) or 0
    return templates.TemplateResponse(request, "pr_detail.html",
        {"nav": "home", "theme": _theme(request),
         "pr": pr, "summary": summary, "runs": runs, "last_run": last_run,
         "human_reviews": human_reviews, "human_comments": human_comments,
         "resolved_count": resolved_count,
         "pending_count": pending_count,
         "new_count": new_count,
         "commits_count": commits_count,
         "human_reviews_count": human_reviews_count,
         "human_comments_count": human_comments_count,
         "runs_count": runs_count,
         "pending_review_run": pending_review_run,
         "enabled_skills": enabled_skills,
         "owner": owner, "name": name,
         **_user_context(db, "dimh")})

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


@router.post("/pr/{owner}/{name}/{number}/summarize")
def pr_summarize(owner: str, name: str, number: int):
    """Generate (or refresh) the AI summary for a single PR.

    Wired to the dashboard's "Generate summary" button on PR cards that
    have no PRSummary row yet. Diff is fetched live from GitHub so the
    LLM sees the same source-of-truth the reviewer would. Redirects
    back to the dashboard on success; bounces to /settings?error=
    summarize when no LLM key is configured so the user knows why
    nothing happened instead of getting a silent 500.
    """
    from tl_towerwatch.services.pull_requests import (
        _summarize_diff, _maybe_summarize,
    )
    settings = load_settings()
    db = engine_from_settings(settings)
    if not settings.llm.anthropic.api_key and not settings.llm.openai.api_key:
        # Friendly bounce to /settings instead of a JSON 400 blob —
        # the user is interacting via HTML and needs a real page.
        return RedirectResponse(
            f"/settings?error=no_llm_key&return=/pr/{owner}/{name}/{number}",
            status_code=303,
        )
    with db.session() as s:
        repo = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    llm = get_provider(settings)
    # Fetch the diff outside the persist session so the LLM call (which
    # may take a few seconds for big PRs) doesn't hold an open SQLAlchemy
    # session. Files list is needed for the diff cap helper.
    with GitHubClient(token=token) as gh:
        files = gh.list_pr_files(owner, name, number)
        diff_text = _summarize_diff(files, max_files=30, max_lines=2000)
    with db.session() as s:
        row = s.execute(select(PullRequest).where(
            PullRequest.repo_id == repo.id, PullRequest.number == number
        )).scalar_one()
        _maybe_summarize(
            s, row, llm=llm, diff_text=diff_text,
            repo_label=f"{repo.owner}/{repo.name}",
        )
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)

@router.post("/pr/{owner}/{name}/{number}/run-review")
def pr_run_review(owner: str, name: str, number: int,
                  agent: str = Form(...),
                  # Multi-value: the dashboard widget renders one checkbox
                  # per enabled skill. Declaring ``skills: list[str] = Form([])``
                  # lets FastAPI hand us every checked value; the prior
                  # ``skills: str = Form("")`` declaration silently dropped
                  # all but the last checked skill because ``form_data.get``
                  # returns a single value for non-multi params.
                  skills: list[str] = Form(default_factory=list),
                  mode: str = Form("fresh")):
    settings = load_settings()
    db = engine_from_settings(settings)
    # v1.1 (Task 10): see pr_refresh — bounce to /settings on auth failure.
    token = _safe_resolve_token(settings)
    if isinstance(token, RedirectResponse):
        return token
    skill_names = [s.strip() for s in (skills or []) if s.strip()]
    with GitHubClient(token=token) as gh:
        run_review(db, gh, owner=owner, name=name, number=number,
                   agent_name=agent, skill_names=skill_names, mode=mode,
                   timeout_seconds=300, settings=settings)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """Settings tab — Auth + LLM configuration page (Task 19 mock layout).

    Reads ``config.yaml`` so the skills-registry preview, auth mode, and
    provider labels all reflect the user's actual configuration. Empty /
    missing config falls back to safe defaults so the page never 500s on a
    fresh install.
    """
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    cfg = load_config_yaml(settings.data_dir / "config.yaml")
    # Skills registry preview — normalize the raw dict from config.yaml into
    # a list of dicts the template can iterate over without ad-hoc getattr
    # calls. We only render enabled skills in the preview per the mock.
    skills_section = cfg.get("skills") or {}
    enabled_skills = []
    if isinstance(skills_section, dict):
        for name, val in skills_section.items():
            if not isinstance(val, dict):
                continue
            enabled_skills.append({
                "name": name,
                "description": val.get("description", "") or "",
                "cli_flag": val.get("cli_flag", f"--skill {name}"),
                "enabled": bool(val.get("enabled", True)),
            })
    # Auth mode: OAuth wins if its access token is set, else PAT (which is
    # also the default for a fresh install with no tokens configured).
    if settings.github_oauth_access_token:
        auth_mode = "oauth"
    else:
        auth_mode = "pat"
    # Token masking for the Auth + LLM chips. We always show the prefix even
    # if the real token is empty so the chip layout is stable across the
    # "no token yet" / "configured" states.
    token_last4 = (settings.github_token[-4:]
                   if settings.github_token else "<none>")
    anthropic_key_last4 = (settings.llm.anthropic.api_key[-4:]
                           if settings.llm.anthropic.api_key else "<none>")
    # Provider labels for the `<select>` and the right-side status badges.
    # MiniMax is shown as a fourth option in the mock but isn't yet a valid
    # value in the ``LLMCfg.default_provider`` Literal, so it can never be
    # marked ``selected`` — it's a visual placeholder.
    PROVIDER_LABELS = {
        "anthropic": "Anthropic (Claude)",
        "openai":    "OpenAI (Codex / GPT)",
        "mavis":     "MiniMax Code (Mavis)",
        "ollama":    "Ollama (local)",
    }
    default_provider_label = PROVIDER_LABELS.get(
        settings.llm.default_provider, settings.llm.default_provider,
    )
    return templates.TemplateResponse(request, "settings.html",
        {"nav": "settings", "theme": _theme(request),
         "settings": settings,
         "enabled_skills": enabled_skills,
         "auth_mode": auth_mode,
         "token_last4": token_last4,
         "anthropic_key_last4": anthropic_key_last4,
         "default_provider_label": default_provider_label,
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
    # current value when blank — that way an empty edit box is a no-op
    # and the user never accidentally overwrites a valid token.
    _persist_auth_keys(
        settings.data_dir / ".env",
        github_token=github_token_edit or github_token,
        github_oauth_client_id=github_oauth_client_id_edit or github_oauth_client_id,
        github_oauth_client_secret=github_oauth_client_secret_edit or github_oauth_client_secret,
    )
    # Persist the auth mode selection to config.yaml so the radio stays
    # where the user put it across reloads (previously the selection was
    # recomputed from the saved token presence, silently overriding the
    # user's radio choice).
    cfg_path = settings.data_dir / "config.yaml"
    cfg = load_config_yaml(cfg_path)
    cfg.setdefault("auth", {})["mode"] = auth_mode
    save_config_yaml(cfg_path, cfg)
    return RedirectResponse("/settings?ok=auth", status_code=303)

@router.post("/settings/llm/save")
def settings_llm_save(provider: str = Form("anthropic"),
                      anthropic_api_key: str = Form(""),
                      openai_api_key: str = Form(""),
                      ollama_base_url: str = Form(""),
                      anthropic_api_key_edit: str = Form(""),
                      openai_api_key_edit: str = Form(""),
                      ollama_base_url_edit: str = Form(""),
                      anthropic_model: str = Form("")):
    settings = load_settings()
    # Mirror the auth-form "edit-or-current" semantics: the hidden field
    # carries the previous value, the visible `_edit` input is what the
    # user actually changes. Empty edit = no change.
    _persist_llm_keys(
        settings.data_dir / ".env",
        provider=provider,
        anthropic_api_key=anthropic_api_key_edit or anthropic_api_key,
        openai_api_key=openai_api_key_edit or openai_api_key,
        ollama_base_url=ollama_base_url_edit or ollama_base_url,
        anthropic_model=anthropic_model,
    )
    return RedirectResponse("/settings?ok=llm", status_code=303)


@router.post("/settings/auth/disconnect")
def settings_auth_disconnect():
    """Clear OAuth credentials + config auth.mode. The dashboard
    re-validates the GitHub token eagerly on the next render, so a
    stale PAT will bounce to /settings?error=github_auth instead of
    silently using a dead credential.
    """
    settings = load_settings()
    env_path = settings.data_dir / ".env"
    if env_path.exists():
        import os
        lines = env_path.read_text().splitlines()
        # Drop only OAuth credentials; keep the PAT untouched so the
        # user can still authenticate without re-entering the token.
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

    The user has to confirm via a JS prompt (template). After this the
    next dashboard request will redirect to /settings?first_run=1
    because there's no token and no auth.mode.
    """
    import os
    settings = load_settings()
    env_path = settings.data_dir / ".env"
    if env_path.exists():
        env_path.unlink()
    cfg_path = settings.data_dir / "config.yaml"
    if cfg_path.exists():
        cfg_path.unlink()
    # Re-touch the files so subsequent reads don't 404.
    env_path.touch()
    cfg_path.touch()
    return RedirectResponse("/settings?ok=defaults", status_code=303)


@router.post("/settings/auth/test")
def settings_auth_test():
    """Probe GitHub with the current PAT and bounce to /settings with
    a status banner. The button labelled "🔄 Probar conexión" on the
    auth card wires here; the redirect lands the user back on
    /settings with either ?test=ok or ?test=fail so the banner can
    render the right state.
    """
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


@router.post("/settings/llm/test")
def settings_llm_test():
    """Probe the configured LLM provider with a tiny "ping" request.
    Redirects to /settings?test=llm_ok or ?test=llm_fail. Lets the user
    confirm their API key works without running a full review.
    """
    settings = load_settings()
    if not settings.llm.anthropic.api_key and not settings.llm.openai.api_key:
        return RedirectResponse("/settings?test=llm_missing", status_code=303)
    try:
        llm = get_provider(settings)
        out = llm.summarize(
            title="ping",
            body="",
            diff="",
            metadata={"ping": True},
        )
        if not out:
            raise RuntimeError("empty response from LLM")
        return RedirectResponse("/settings?test=llm_ok", status_code=303)
    except Exception as e:
        return RedirectResponse(
            f"/settings?test=llm_fail&reason={type(e).__name__}", status_code=303
        )

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
                      openai_api_key: str, ollama_base_url: str,
                      anthropic_model: str = "") -> None:
    """Persist LLM-form values to .env, only touching the LLM keys.

    Empty form values are treated as "no change" so submitting a partial LLM
    form (e.g. only the Anthropic key) cannot wipe secrets the user didn't
    intend to touch — mirrors `_persist_auth_keys` and the regression test
    `test_settings_llm_save_does_not_wipe_auth_fields`. Non-empty form
    values replace any existing line for that key. Keys owned by other
    helpers are never touched.
    """
    import os
    updates = {
        "TOWERWATCH_LLM_PROVIDER": provider,
        "TOWERWATCH_ANTHROPIC_API_KEY": anthropic_api_key,
        "TOWERWATCH_OPENAI_API_KEY": openai_api_key,
        "TOWERWATCH_OLLAMA_BASE_URL": ollama_base_url,
        # Flat key — pydantic-settings auto-binds it to
        # Settings.anthropic_model, which the model_validator mirrors
        # into llm.anthropic.model. The nested key would be the more
        # "correct" name but isn't auto-bound because LLMCfg is a plain
        # BaseModel rather than a BaseSettings subclass.
        "TOWERWATCH_ANTHROPIC_MODEL": anthropic_model,
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