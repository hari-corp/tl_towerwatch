from __future__ import annotations
from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

_TPL_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TPL_DIR))

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "base.html", {"nav": "home", "theme": _theme(request)})

@router.post("/theme")
async def theme(theme: str = Form(...)):
    resp = Response(status_code=200, content="")
    resp.set_cookie("tl_towerwatch_theme", theme, httponly=False, samesite="lax")
    return resp

def _theme(request: Request) -> str:
    return request.cookies.get("tl_towerwatch_theme", "dark")