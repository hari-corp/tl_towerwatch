# tl_towerwatch — agent guide

Local-first PR dashboard for tech leads. Python 3.11+, FastAPI + Jinja2 +
SQLAlchemy/SQLite. Single user, runs on the developer's machine.

**v1.3.0 removed the in-app LLM/agent stack.** The app only *assembles*
review prompts; the user runs the model externally. Do not reintroduce LLM
calls, providers, or credentials.

## Commands

- Install: `uv sync --extra dev`
- Test: `uv run pytest` — no network; GitHub is mocked with `respx`
- Lint: `uv run ruff check .`
- **Definition of done: `make check`** (pytest + ruff)
- Run app: `uv run tl_towerwatch serve` → http://127.0.0.1:8000
- Render a prompt: `uv run tl_towerwatch review owner/name#123 --slot review`
  (`review` | `post_review` | `check_resolved`)
- First-time setup: `uv run tl_towerwatch init` (needs a real PAT; never in tests)

## Layout and boundaries

| Path | Owns |
|---|---|
| `config.py` | `Settings`; `.env` is loaded **relative to `TOWERWATCH_DATA_DIR`**, not CWD. Keep that contract (Docker depends on it). |
| `config_io.py` | Atomic YAML read/write for `config.yaml`. |
| `db/models.py` | ORM tables. |
| `db/database.py` | Engine/sessions + `_ensure_columns` hand-rolled SQLite migrations. Add fields to the model; old DBs upgrade automatically. |
| `github/client.py` | **The only GitHub REST caller** (httpx). `github/models.py` = response DTOs. |
| `auth/github.py` | Token resolution: PAT or OAuth device flow + refresh. |
| `services/` | Business logic. `pull_requests.sync_*` is the only writer of PR subresources; `prompt_assembly` is the single source of truth for prompts (CLI and web must stay byte-identical). |
| `skills/registry.py` | The three fixed prompt slots, their defaults, and persistence in `config.yaml`. |
| `web/routes.py` + `web/templates/` | FastAPI + Jinja. Routes may create a `GitHubClient` for pass-through actions (refresh, replies, auth test) but delegate sync/writes to `services/`. |
| `scheduler.py` | Daemon thread; 15 s tick, respects per-repo `refresh_interval_seconds`. |
| `cli.py` | Typer entrypoint: `init`, `repo *`, `refresh`, `status`, `config`, `auth *`, `serve`, `review`. |

## Rules

- No LLM/agent integration in the app. Removed in v1.3.0 — don't bring it back.
- No direct GitHub HTTP outside `github/client.py`; no PR writes outside services.
- Config is `TOWERWATCH_*` env vars. Never commit secrets; `.env` is gitignored,
  `.env.example` is the contract.
- Local-first: SQLite + files under the data dir; no hosted backend.
- Templates are server-rendered Jinja with small inline JS; no Node/build step.
- Tests: pytest + respx + `TestClient`; never require the network or a real PAT.
  Use `tmp_path` data dirs, not `./data`.
- Python: 3.11+, `from __future__ import annotations`, ruff line length 100.
  Types are annotations only — no type checker is enforced yet.

## Done means

`make check` is green and the app boots with `uv run tl_towerwatch serve`.
Any behaviour change needs a test in `tests/`.

## Docs

- `docs/architecture.md` — module map, data flow, persistence, testing.
- `docs/adr/0001-no-in-app-llm.md` — why v1.3.0 removed the LLM stack.
- `docs/superpowers/` is **historical** and does not describe current behaviour.
