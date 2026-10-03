from __future__ import annotations
from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.services.pull_requests import list_prs_for_dashboard
from tl_towerwatch.services.reviews import compute_badges

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

@router.post("/theme")
async def theme(theme: str = Form(...)):
    resp = Response(status_code=200, content="")
    resp.set_cookie("tl_towerwatch_theme", theme, httponly=False, samesite="lax")
    return resp

def _theme(request: Request) -> str:
    return request.cookies.get("tl_towerwatch_theme", "dark")