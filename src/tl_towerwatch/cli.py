from __future__ import annotations

import json
import os

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from tl_towerwatch.auth.github import resolve_token
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import Repo
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.services.repos import (
    add_allowed_author,
    add_repo,
    clear_allowed_authors,
    list_repos,
    remove_allowed_author,
    remove_repo,
    set_allowed_authors,
    set_repo_enabled,
)
from tl_towerwatch.services.review_runner import run_review

app = typer.Typer(help="tl_towerwatch — local PR dashboard for tech leads")
repo_app = typer.Typer(help="Manage watched repos")
app.add_typer(repo_app, name="repo")
auth_app = typer.Typer(help="Auth-related subcommands")
app.add_typer(auth_app, name="auth")

console = Console()

def _db():
    s = load_settings()
    return engine_from_settings(s)

def _env_lines_for(s):
    """Render the on-disk .env representation of the active settings.

    Used by ``init`` after the wizard collects secrets so subsequent
    ``load_settings(data_dir)`` (v1.0 fix C2) sees them on next start.
    Only writes keys that have a non-empty value, matching the
    pre-existing behaviour of the stub init.
    """
    lines = []
    if s.github_token:
        lines.append(f"TOWERWATCH_GITHUB_TOKEN={s.github_token}")
    if s.github_oauth_client_id:
        lines.append(f"TOWERWATCH_GITHUB_OAUTH_CLIENT_ID={s.github_oauth_client_id}")
    if s.github_oauth_client_secret:
        lines.append(f"TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET={s.github_oauth_client_secret}")
    if s.llm.anthropic.api_key:
        lines.append(f"TOWERWATCH_ANTHROPIC_API_KEY={s.llm.anthropic.api_key}")
    if s.llm.openai.api_key:
        lines.append(f"TOWERWATCH_OPENAI_API_KEY={s.llm.openai.api_key}")
    return "\n".join(lines) + "\n"


@app.command()
def init():
    """First-time setup wizard."""
    import click

    settings = load_settings()
    from tl_towerwatch.config_io import save_config_yaml
    from tl_towerwatch.auth.github import resolve_token

    mode = typer.prompt(
        "Auth mode", type=click.Choice(["pat", "oauth"]), default="pat"
    )
    if mode == "pat":
        token = typer.prompt("GitHub PAT", hide_input=True)
        settings.github_token = token
        # Validate now (raises RuntimeError on failure → friendly message)
        try:
            resolve_token(settings)
            typer.echo("✓ Token validated")
        except RuntimeError as e:
            typer.echo(f"✗ {e}", err=True)
            raise typer.Exit(1)
    else:
        cid = typer.prompt("OAuth client_id")
        csec = typer.prompt("OAuth client_secret", hide_input=True)
        settings.github_oauth_client_id = cid
        settings.github_oauth_client_secret = csec
        typer.echo(
            "Run `tl_towerwatch auth login` to complete the browser flow."
        )

    provider = typer.prompt(
        "Default LLM provider",
        type=click.Choice(["anthropic", "openai", "ollama"]),
        default="anthropic",
    )
    default_model = {
        "anthropic": "claude-3-5-sonnet-latest",
        "openai": "gpt-4o",
        "ollama": "llama3.2",
    }[provider]
    model = typer.prompt(f"{provider} model", default=default_model)

    save_config_yaml(
        settings.data_dir / "config.yaml",
        {
            "auth": {"mode": mode},
            "llm": {"default_provider": provider, provider: {"model": model}},
            "skills": {
                "superpowers": {
                    "enabled": True,
                    "cli_flag": "--enable-superpowers",
                    "description": "Code-review and quality skills",
                },
                "ponytail": {
                    "enabled": True,
                    "cli_flag": "--skill ponytail",
                    "description": "Custom review heuristics",
                },
            },
        },
    )
    # Atomic write (.env.tmp → os.replace) so a partial write can't leave
    # the wizard with a half-empty file (matches _persist_env in auth/github.py).
    env_path = settings.data_dir / ".env"
    env_tmp = env_path.with_suffix(".env.tmp")
    env_tmp.write_text(_env_lines_for(settings))
    os.replace(env_tmp, env_path)
    typer.echo(
        "✓ Init complete. Next: tl_towerwatch repo add owner/name"
    )

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

@app.command("config")
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

@auth_app.command("refresh")
def auth_refresh_cmd():
    """Refresh OAuth access token."""
    from tl_towerwatch.auth.github import refresh_oauth_token
    s = load_settings()
    refresh_oauth_token(s)
    typer.echo("✓ OAuth token refreshed")


@auth_app.command("login")
def auth_login_cmd():
    """Run the OAuth browser flow (requires client_id/secret already set)."""
    from tl_towerwatch.auth.github import complete_oauth_flow
    from tl_towerwatch.config_io import load_config_yaml, save_config_yaml

    s = load_settings()
    if not (s.github_oauth_client_id and s.github_oauth_client_secret):
        typer.echo(
            "Set TOWERWATCH_GITHUB_OAUTH_CLIENT_ID and "
            "TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET first.",
            err=True,
        )
        raise typer.Exit(1)
    host_alias = s.host_alias or "localhost"
    cb = f"http://{host_alias}:8765/auth/callback"
    acc, ref = complete_oauth_flow(s.github_oauth_client_id, s.github_oauth_client_secret, cb)
    # Persist the new access/refresh tokens to .env so subsequent runs pick
    # them up via load_settings() (uses _persist_env — atomic .env write).
    s.github_oauth_access_token = acc
    s.github_oauth_refresh_token = ref
    from tl_towerwatch.auth.github import _persist_env
    _persist_env(s)
    # Flip config.yaml auth.mode to oauth so resolve_token uses the new
    # tokens instead of the PAT (which may not be set anyway).
    cfg_path = s.data_dir / "config.yaml"
    data = load_config_yaml(cfg_path)
    data.setdefault("auth", {})["mode"] = "oauth"
    save_config_yaml(cfg_path, data)
    typer.echo("✓ OAuth login complete. Tokens saved to .env.")

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

@app.command()
def review(
    target: str = typer.Argument(..., help="owner/name#N (e.g. 'hari-corp/billing-svc#482')"),
    skills: str = typer.Option("", "--skills", help="comma-separated skill names"),
    agent: str = typer.Option("claude", "--agent", help="agent runner (claude|codex|minimax|ollama)"),
    mode: str = typer.Option("fresh", "--mode", help="fresh|compare"),
    watch: bool = typer.Option(False, "--watch", help="stream output to terminal (v1.1)"),
):
    """Run a code review on a PR headlessly (spec §9)."""
    if "#" not in target:
        typer.echo("target must be owner/name#N (e.g. 'hari-corp/billing-svc#482')", err=True)
        raise typer.Exit(1)
    owner_name, _, number = target.rpartition("#")
    if "/" not in owner_name:
        typer.echo("target must be owner/name#N", err=True)
        raise typer.Exit(1)
    owner, _, name = owner_name.partition("/")
    skill_names = [s.strip() for s in skills.split(",") if s.strip()]
    settings = load_settings()
    from tl_towerwatch.auth.github import resolve_token
    from tl_towerwatch.github.client import GitHubClient

    if watch:
        # v1.1 (Task 6): stream agent events to the terminal as they happen.
        # Deliberately bypasses services.review_runner.run_review (no DB
        # persistence, no ReviewRun row) — streaming callers want live
        # output, not a persisted run record. Skills/registry is loaded
        # straight from settings.data_dir (same source as the service).
        from tl_towerwatch.agents import get_runner
        from tl_towerwatch.skills.registry import load_registry
        with GitHubClient(token=resolve_token(settings)) as gh:
            pr = gh.get_pr(owner, name, int(number))
            files = gh.list_pr_files(owner, name, int(number))[:30]
            pr_diff = "\n".join((f.patch or "") for f in files)[:20000]
            sk = load_registry(settings.data_dir)
            runner = get_runner(agent, settings)
            def on_event(e):
                typer.echo(f"[{e.kind}] {e.data[:200]}")
            runner.run_review(
                pr_diff=pr_diff,
                pr_metadata={
                    "title": pr.title,
                    "body": pr.body,
                    "author": pr.author_login,
                    "number": pr.number,
                    "repo": f"{owner}/{name}",
                    "head_sha": pr.head_sha,
                },
                skills=sk,
                prompt_template=None,
                mode=mode,
                previous_findings=[],
                timeout_seconds=300,
                on_event=on_event,
            )
    else:
        db = _db()
        db.create_all()
        with GitHubClient(token=resolve_token(settings)) as gh:
            run_review(
                db, gh,
                owner=owner, name=name, number=int(number),
                agent_name=agent, skill_names=skill_names, mode=mode,
                timeout_seconds=300, settings=settings,
            )
        typer.echo(f"✓ Review submitted for {owner}/{name}#{number}")