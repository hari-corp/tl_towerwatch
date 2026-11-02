# Architecture

tl_towerwatch is a local-first dashboard for GitHub pull requests. It caches
PR data in SQLite, shows what needs a tech lead's attention, and assembles
review prompts that the user pastes into an external model.

**Non-goals:** running an LLM in-process, multi-user hosting, a hosted
backend, or real-time updates. See
[ADR 0001](adr/0001-no-in-app-llm.md) for the v1.3.0 decision that removed
the in-app LLM stack.

## Runtime topology

```
                 ┌─────────────────────────────┐
  browser ──────▶│ FastAPI web app (routes.py) │──┐
                 └─────────────────────────────┘  │
                 ┌─────────────────────────────┐  │   ┌──────────────┐
  terminal ─────▶│ Typer CLI (cli.py)          │──┼──▶│  services/   │
                 └─────────────────────────────┘  │   └──────┬───────┘
                 ┌─────────────────────────────┐  │          │
  daemon ───────▶│ RefreshScheduler (15 s)     │──┘          ▼
                 └─────────────────────────────┘      ┌──────────────┐
                                                      │ SQLite cache │
                     GitHub REST API ◀── github/ ─────└──────────────┘
```

All three entry points (web, CLI, scheduler) use the same settings loader,
the same `GitHubClient`, and the same service layer. There is no second
implementation of business rules anywhere.

## Data flow

### Sync

1. `scheduler.py` wakes every 15 s and selects enabled repos whose
   `refresh_interval_seconds` has elapsed, or the user triggers a refresh
   from the web/CLI.
2. `services.pull_requests.sync_repo` (or `sync_one_pr`) calls
   `github/client.py` for PRs, commits, files, reviews, review comments,
   and issue comments.
3. The service upserts `Repo`/`User`/`PullRequest` rows and **replaces**
   the per-PR subresource tables, so deleted/edited comments disappear from
   the cache instead of lingering.
4. State changes (open → closed → merged) are persisted, and failures are
   recorded on `Repo.last_fetch_status` rather than raised to the UI.

### Read paths

- Dashboard: `services.pull_requests.list_prs_for_dashboard` + badge
  computation in `services/reviews.py`.
- PR detail: `services.pull_requests.get_pr_with_details`, plus direct ORM
  reads in `web/routes.py` for the per-tab data.
- Prompt rendering: `services.prompt_assembly.assemble_review_prompt` is
  shared by the CLI (`tl_towerwatch review`) and the web route
  (`/pr/{owner}/{name}/{number}/show-review-prompt`), so both produce
  byte-identical output.

## Module map

| Module | Responsibility |
|---|---|
| `config.py` | `Settings` (pydantic-settings). Loads `.env` relative to `TOWERWATCH_DATA_DIR`, not the CWD, and ignores unknown keys so pre-v1.3.0 env files still boot. |
| `config_io.py` | Atomic `config.yaml` read/write (temp file + replace). |
| `db/models.py` | `Repo`, `User`, `PullRequest`, `Review`, `ReviewComment`, `IssueComment`, `PRCommit`, `PRFile`. Timestamps are ISO-8601 UTC strings. |
| `db/database.py` | Engine/session factory, `create_all`, legacy-table drops, and `_ensure_columns` (SQLite "migrations" via `PRAGMA table_info` + `ALTER TABLE`). |
| `github/client.py` | The only module that performs GitHub HTTP. Context-managed; pagination and error mapping live here. |
| `github/models.py` | Typed DTOs for API payloads. |
| `auth/github.py` | `resolve_token`: PAT, OAuth device flow, refresh. |
| `services/pull_requests.py` | Sync + PR mutations (manual description/notes, comment replies, dashboard query). |
| `services/repos.py` | Repo CRUD, enable/disable, allowed author lists. |
| `services/reviews.py` | Badge computation for the dashboard. |
| `services/prompt_assembly.py` | Fetches PR metadata + diff and renders a slot template with diff-size caps. |
| `skills/registry.py` | The three prompt slots (`review`, `post_review`, `check_resolved`), built-in defaults, load/save. |
| `web/routes.py` | FastAPI router, Jinja filters, all pages and form actions. |
| `web/templates/` | Server-rendered Jinja templates; small inline scripts only. |
| `scheduler.py` | Background refresh daemon. |
| `cli.py` | Typer app: `init`, `repo *`, `refresh`, `status`, `config`, `auth *`, `serve`, `review`. |

## Persistence

Everything lives under the data directory (`./data` by default):

- `.env` — GitHub token/OAuth credentials and tuning knobs.
- `config.yaml` — prompt slots, theme, auth mode, per-repo overrides.
- `tl_towerwatch.db` — SQLite cache.

Schema changes are handled in two ways, both in `db/database.py`:

- `create_all` creates new tables.
- `_ensure_columns` adds missing columns to existing tables (SQLAlchemy's
  `create_all` never alters tables). New columns need a safe default so old
  rows remain queryable.
- `_drop_legacy_tables` removes tables from removed features (v1.3.0 dropped
  the LLM/summary/findings tables).

## Testing strategy

- `pytest` with `respx` for GitHub HTTP and FastAPI `TestClient` for routes.
- Every test receives a temporary data directory; nothing touches `./data`.
- No test requires network access or a real token.
- `tests/conftest.py` holds the shared fixtures (`fs_chdir`, `tmp_data_dir`,
  `env`).
- Shell: `make check` = `uv run pytest` + `uv run ruff check .`.

## Invariants

1. The app never calls an LLM. Prompt assembly is a pure string operation.
2. GitHub HTTP exists only in `github/client.py`.
3. PR persistence exists only in `services/`.
4. `.env` resolution is data-dir-relative; changing it breaks Docker.
5. The CLI and web render prompts through the same function.
