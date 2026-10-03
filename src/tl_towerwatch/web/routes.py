from __future__ import annotations
import json as _json
from sqlalchemy import select
from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import PullRequest, ReviewRun, PRSummary, Repo
from tl_towerwatch.services.pull_requests import list_prs_for_dashboard
from tl_towerwatch.services.reviews import compute_badges
from tl_towerwatch.services.repos import (
    list_repos as svc_list_repos, add_repo as svc_add_repo,
    set_repo_enabled as svc_set_repo_enabled, remove_repo as svc_remove_repo,
    set_allowed_authors as svc_set_allowed_authors,
)
from tl_towerwatch.services.review_runner import run_review
from tl_towerwatch.services.pull_requests import sync_one_pr
from tl_towerwatch.llm import get_provider
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.auth.github import resolve_token

_TPL_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TPL_DIR))

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    login = "dimh"  # TODO: derive from auth in Task 18
    prs = list_prs_for_dashboard(db, login=login, scope_filter="mine_and_review")
    badges_by_pr = {pr.id: compute_badges(db, login, pr) for pr in prs}
    return templates.TemplateResponse(request, "dashboard.html",
        {"nav": "home", "theme": _theme(request),
         "prs": prs, "badges_by_pr": badges_by_pr, "login": login})

@router.get("/repos", response_class=HTMLResponse)
def repos_page(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    repo_rows = svc_list_repos(db)
    for r in repo_rows:
        try:
            authors = _json.loads(r.allowed_authors_json or "[]")
        except Exception:
            authors = []
        r.allowed_authors_csv = ", ".join(authors)
    return templates.TemplateResponse(request, "repos.html",
        {"nav": "repos", "theme": _theme(request), "repos": repo_rows})

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
    try:
        with GitHubClient(token=resolve_token(settings)) as gh:
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

@router.post("/theme")
async def theme(theme: str = Form(...)):
    resp = Response(status_code=200, content="")
    resp.set_cookie("tl_towerwatch_theme", theme, httponly=False, samesite="lax")
    return resp

def _theme(request: Request) -> str:
    return request.cookies.get("tl_towerwatch_theme", "dark")

@router.get("/pr/{owner}/{name}/{number}", response_class=HTMLResponse)
def pr_detail(request: Request, owner: str, name: str, number: int):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    with db.session() as s:
        repo = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one_or_none()
        pr = None
        summary = None
        runs = []
        if repo:
            pr = s.execute(select(PullRequest).where(
                PullRequest.repo_id == repo.id, PullRequest.number == number
            )).scalar_one_or_none()
            if pr:
                summary = s.get(PRSummary, pr.id)
                runs = list(s.execute(select(ReviewRun).where(ReviewRun.pr_id == pr.id)
                             .order_by(ReviewRun.id.desc())).scalars())
    return templates.TemplateResponse(request, "pr_detail.html",
        {"nav": "home", "theme": _theme(request),
         "pr": pr, "summary": summary, "runs": runs, "owner": owner, "name": name})

@router.post("/pr/{owner}/{name}/{number}/refresh")
def pr_refresh(owner: str, name: str, number: int):
    settings = load_settings()
    db = engine_from_settings(settings)
    with db.session() as s:
        repo = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
    llm = get_provider(settings) if settings.llm.anthropic.api_key else None
    with GitHubClient(token=resolve_token(settings)) as gh:
        sync_one_pr(db, gh, repo, number, llm=llm)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)

@router.post("/pr/{owner}/{name}/{number}/run-review")
def pr_run_review(owner: str, name: str, number: int,
                  agent: str = Form(...),
                  skills: str = Form(""),
                  mode: str = Form("fresh")):
    settings = load_settings()
    db = engine_from_settings(settings)
    skill_names = [s.strip() for s in skills.split(",") if s.strip()]
    with GitHubClient(token=resolve_token(settings)) as gh:
        run_review(db, gh, owner=owner, name=name, number=number,
                   agent_name=agent, skill_names=skill_names, mode=mode,
                   timeout_seconds=300, settings=settings)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)