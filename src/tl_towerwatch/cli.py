from __future__ import annotations
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.services.repos import (
    add_repo, list_repos, set_repo_enabled, remove_repo, set_allowed_authors,
)
from tl_towerwatch.auth.github import resolve_token
from tl_towerwatch.github.client import GitHubClient

app = typer.Typer(help="tl_towerwatch — local PR dashboard for tech leads")
repo_app = typer.Typer(help="Manage watched repos")
app.add_typer(repo_app, name="repo")

console = Console()

def _db():
    s = load_settings()
    return engine_from_settings(s)

@app.command()
def init():
    """First-time setup wizard (stub — expanded in Task 11)."""
    settings = load_settings()
    token = typer.prompt("GitHub PAT (will be stored in .env)", hide_input=True)
    settings.github_token = token
    (settings.data_dir / ".env").write_text(f"TOWERWATCH_GITHUB_TOKEN={token}\n")
    typer.echo(f"✓ Saved. Next: tl_towerwatch repo add owner/name")

@repo_app.command("add")
def repo_add(
    owner_name: str = typer.Argument(..., help="owner/name or full URL"),
    authors: str = typer.Option("", "--authors", help="comma-separated GitHub logins"),
):
    """Validate access and register a repo."""
    if owner_name.startswith("https://"):
        owner_name = owner_name.rstrip("/").split("/")[-2:]
        owner_name = f"{owner_name[0]}/{owner_name[1]}"
    owner, name = owner_name.split("/", 1)
    settings = load_settings()
    db = _db()
    db.create_all()
    with GitHubClient(token=resolve_token(settings)) as gh:
        meta = gh.get_repo(owner, name)
    authors_list = [a for a in authors.split(",") if a.strip()]
    add_repo(
        db, owner, name,
        refresh_interval_seconds=settings.refresh_interval_seconds,
        allowed_authors=authors_list or None,
    )
    typer.echo(f"✓ Added {meta.full_name}")

@repo_app.command("list")
def repo_list():
    db = _db()
    db.create_all()
    repos = list_repos(db)
    t = Table(title=f"Repos ({len(repos)})")
    for col in ("Owner/Name", "Enabled", "Self", "Open", "Allowed authors"):
        t.add_column(col)
    if not repos:
        typer.echo("0 repos registered.")
        return
    for r in repos:
        authors = json.loads(r.allowed_authors_json or "[]") or "*"
        t.add_row(f"{r.owner}/{r.name}", "✓" if r.enabled else "⏸",
                  "⭐" if r.is_self else "—", "?", ", ".join(authors))
    console.print(t)

@repo_app.command("remove")
def repo_remove(owner_name: str = typer.Argument(...)):
    db = _db()
    owner, name = owner_name.split("/", 1)
    remove_repo(db, owner, name)
    typer.echo(f"✓ Removed {owner}/{name}")

@repo_app.command("enable")
def repo_enable(owner_name: str = typer.Argument(...)):
    _enable(owner_name, True)

@repo_app.command("disable")
def repo_disable(owner_name: str = typer.Argument(...)):
    _enable(owner_name, False)

def _enable(owner_name: str, on: bool) -> None:
    db = _db()
    owner, name = owner_name.split("/", 1)
    set_repo_enabled(db, owner, name, on)
    typer.echo(f"✓ {'enabled' if on else 'paused'} {owner}/{name}")

@repo_app.command("set-authors")
def repo_set_authors(
    owner_name: str = typer.Argument(...),
    authors: str = typer.Option(..., "--authors"),
):
    db = _db()
    owner, name = owner_name.split("/", 1)
    set_allowed_authors(db, owner, name, [a for a in authors.split(",") if a.strip()])
    typer.echo(f"✓ Updated allowed_authors for {owner}/{name}")

@app.command()
def serve(host: str = typer.Option("127.0.0.1"),
          port: int = typer.Option(8000)):
    import uvicorn
    from tl_towerwatch.scheduler import RefreshScheduler
    settings = load_settings()
    sched = RefreshScheduler(settings)
    sched.start()
    try:
        uvicorn.run("tl_towerwatch.web:create_app", host=host, port=port,
                    factory=True, reload=False)
    finally:
        sched.stop()