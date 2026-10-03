# tl_towerwatch — Design Spec

**Date:** 2026-10-03
**Status:** Design agreed; written spec awaiting user review
**Owner:** David (@dimh)

## 1. Purpose

`tl_towerwatch` (TL = Tech Lead) is a local Python app that helps a tech lead keep
on top of pull requests across the GitHub repositories they own or are asked to
review. It pulls PR data from GitHub into a local SQLite DB, computes per-PR
status badges (awaiting review, needs response, etc.), generates LLM-powered
summaries, and lets the user trigger code reviews through a configurable agent
(skills are pluggable — `superpowers` and `ponytail` ship by default).

Everything runs on the user's machine; no SaaS, no servers to manage. The CLI
is the source of truth for setup and repo management; a local FastAPI dashboard
provides the visual interface.

## 2. Goals & non-goals

### Goals (v1)
- List PRs the user authored or was requested to review, with one-click visibility
  into review state, summary, and outstanding work.
- Generate a short natural-language summary of each PR (title + body + diff).
- Detect and surface review states: `awaiting_my_review`, `pending_response`,
  `changes_requested`, `approved`, `responded`.
- Trigger a code review on a PR using a configurable set of agent skills.
- Track review findings across runs: every finding has a status
  (`resolved` / `pending` / `new`) computed by comparing diffs between runs.
- Manage the set of repos to watch from the CLI and the dashboard.
- Support both GitHub PAT and OAuth (GitHub App) auth.
- Local-first: SQLite cache + config files in `./data/`. No telemetry.

### Non-goals (v1)
- Multiple SCM providers (GitLab / Bitbucket / Azure DevOps).
- Multi-user / team mode (single-user local app).
- Editing PRs, posting reviews back to GitHub, or merging.
- Mobile / responsive design below ~768px.
- Background daemonization (the user runs `tl_towerwatch serve` explicitly).

## 3. Architecture

### 3.1 Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | target runtime |
| CLI | Typer | modern, ergonomic, type-driven |
| Web | FastAPI + Uvicorn | small footprint, async-friendly |
| Templates | Jinja2 + HTMX | server-rendered, no build step |
| ORM | SQLAlchemy 2.x | standard, well-documented |
| DB | SQLite (file in `./data/`) | zero-setup local cache |
| HTTP client | httpx | sync + async, mocking-friendly |
| OAuth | Authlib | standard library for GitHub OAuth |
| Validation | Pydantic v2 | models + settings in one stack |
| Packaging | uv | fast, lockfile-friendly |
| LLM SDKs | anthropic, openai (also used for Codex), ollama HTTP | for PR summaries; MiniMax Code is exposed only via its CLI (see Agent runners) |

### 3.2 Package layout

```
tl_towerwatch/
├── pyproject.toml
├── README.md
├── .env.example
├── src/tl_towerwatch/
│   ├── __init__.py
│   ├── cli.py                    # Typer entrypoint
│   ├── web.py                    # FastAPI app factory
│   ├── config.py                 # Pydantic Settings (.env + config.yaml)
│   ├── auth/
│   │   ├── __init__.py
│   │   └── github.py             # PAT + OAuth providers
│   ├── github/
│   │   ├── __init__.py
│   │   ├── client.py             # REST API client
│   │   └── models.py             # Domain models (PR, Review, Repo, Comment)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py               # LLMProvider Protocol
│   │   ├── anthropic.py          # Claude
│   │   ├── openai.py             # OpenAI / Codex
│   │   ├── minimax.py            # MiniMax Code / Mavis
│   │   └── ollama.py             # local Ollama
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py               # AgentRunner Protocol
│   │   ├── claude.py             # shells out to `claude --print`
│   │   ├── codex.py              # shells out to `codex` CLI
│   │   ├── minimax_code.py       # shells out to `minimax` CLI
│   │   └── ollama.py             # local agent via Ollama
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── registry.py           # skill registry from config
│   │   └── prompts.py            # prompt templates
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py           # engine + session
│   │   └── models.py             # ORM models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── pull_requests.py      # fetch + cache + summarize
│   │   ├── reviews.py            # compute review states
│   │   ├── findings.py           # finding lifecycle (resolve/pend/new)
│   │   ├── repos.py              # manage repo config
│   │   └── review_runner.py      # orchestrate agent reviews
│   └── web/
│       ├── __init__.py
│       ├── routes.py
│       └── templates/
│           ├── base.html
│           ├── dashboard.html
│           ├── pr_detail.html
│           ├── repos.html
│           └── settings.html
├── tests/
│   ├── test_github_client.py
│   ├── test_auth.py
│   ├── test_llm_providers.py
│   ├── test_agent_runners.py
│   ├── test_services.py
│   └── test_web_routes.py
└── data/                          # gitignored, created at runtime
    ├── config.yaml
    └── tl_towerwatch.db
```

### 3.3 Data flow

1. **Setup (one-time)** — `tl_towerwatch init`:
   - Detect existing config in `./data/config.yaml` and `./data/.env`.
   - Ask auth mode (PAT or OAuth); store credentials.
   - Ask LLM provider; store API key + model default.
   - Ask about the skills registry; default to `superpowers` + `ponytail`.
2. **Repo onboarding** — `tl_towerwatch repo add owner/name`:
   - Validate the user can read the repo with the current token.
   - Insert row in `repos` table; trigger initial fetch in background.
3. **Serve** — `tl_towerwatch serve [--port 8000]`:
   - Start FastAPI on `localhost:<port>`.
   - Background scheduler refreshes each enabled repo every N minutes
     (configurable per-repo, default 5; the repo marked as `self` defaults
     to 1 minute for dogfooding).
   - On refresh: fetch PRs, comments, reviews from GitHub; upsert into SQLite;
     regenerate LLM summary only if `head_sha` changed; recompute findings
     status against the last review run.
4. **Dashboard** — `http://localhost:8000/`:
   - HTMX-driven; server-rendered. User actions (refresh, filter, run review)
     return HTML fragments that swap into the page.
5. **CLI** — all setup, repo management, and headless operations
   (`tl_towerwatch review owner/name#N`) work without the web server.

## 4. CLI

```
tl_towerwatch init                       # first-time setup wizard
tl_towerwatch serve [--port 8000]        # start FastAPI dashboard
tl_towerwatch repo add <owner>/<name>    # validate + register repo
tl_towerwatch repo remove <owner>/<name>
tl_towerwatch repo list
tl_towerwatch repo enable|disable <owner>/<name>
tl_towerwatch refresh [--repo owner/name]#N | --all
tl_towerwatch review <owner>/<name>#N    # run review headless
       [--skills superpowers,ponytail]
       [--agent claude|codex|minimax|ollama]
       [--mode fresh|compare]
       [--watch]                         # stream output to terminal
tl_towerwatch status                     # user, last refresh, rate limit
tl_towerwatch config show|edit
```

## 5. Web UI

Five screens, all server-rendered with Jinja + HTMX. Light/dark theme
toggle is persisted in localStorage and `config.yaml`.

### 5.1 Dashboard (`/`)
- Top bar: `tl_towerwatch` logo + nav (PRs · Repos · Settings) + theme toggle + avatar.
- Rate-limit strip with a bar showing remaining quota vs. 5,000 (PAT) or the
  OAuth app quota.
- Status counters: `awaiting_my_review`, `needs_response`, `changes_requested`,
  `ready_to_merge`.
- Filter row: tabs (Attention / Mine / Review-requested / All) + dropdowns
  (Repo, Creator) + free-text search on title.
- Per-repo refresh icon next to each repo in the filter dropdown.
- "Refresh all" button at the right of the filter row.
- Card list, one card per PR:
  - Header line: repo badge, PR number, "created Xd by Y", "N commits
    post-creation", "updated Xm ago".
  - Title (clickable → detail).
  - LLM summary (2-3 sentences, regenerated only if `head_sha` changes).
  - Reviewer row: avatars with state border (solid = acted, dashed = pending)
    + tooltip (`approved`, `changes_requested`, `commented`, `pending`).
  - Approval row (highlighted green) when all required reviews approve.
  - Status badge row: `awaiting_your_review`, `pending_response`, `changes_requested`,
    `approved`, `responded` — color-coded.
  - Expandable description section ("📄 Ver descripción ▾") loaded via HTMX.
  - Action buttons: `Review →` / `Run review →` and "Ver en GitHub ↗".

### 5.2 PR detail (`/pr/{owner}/{repo}/{number}`)
- Breadcrumb row: back link + repo + number + GitHub link +
  `actualizado hace X` + `↻ Refrescar este PR`.
- Header: title, base branch, creation date, post-creation commits, last update.
- Tabs: Overview · Commits · Files · Reviews · Comments · **tl_towerwatch reviews**.
- Overview tab:
  - LLM summary card (regenerable).
  - Author description (full markdown).
  - Files modified (compact list with `+/-` stats).
  - Human reviews timeline.
  - **tl_towerwatch reviews** (default tab content if requested from a deep link):
    - Aggregated counters: `✓ N resueltos`, `⚠ N pendientes`, `🆕 N nuevos`.
    - Per-run card with all findings expanded, each finding showing
      severity, file, line, description, status, and (for resolved findings)
      the commit that fixed it.
    - Old runs collapsed but accessible.
- Sticky right sidebar: `🤖 Run review` widget:
  - Mode toggle: `Fresh review` vs `↻ Comparar vs último run`.
  - Agent runner selector.
  - Skills multi-select (defaults from config).
  - Context preview (what is being passed to the agent: current diff, previous
    findings with status, pending human comments).
  - Collapsible prompt template editor (with `{findings_with_status}` etc.).
  - `▶ Run review` button (triggers background job, polls for status via HTMX).
  - Previous reviews list with status (✓ completed · ⚠ timeout) and quick links.

### 5.3 Repos (`/repos`)
- Rate-limit banner (same as dashboard).
- Add-repo form (inline) accepting `owner/name` or full URL; validates access
  before persisting.
- Filters: Todos · Activos · Pausados · Con error.
- Per-repo card:
  - Name, badges (`● ACTIVO`, `⏸ PAUSADO`, `⭐ SELF`), open PR count, last fetch time.
  - Repo config summary: refresh interval, scope, default LLM.
  - Actions: `▶ Refrescar ahora`, `⚙ config`, `⏸ pausar`/`▶ Activar`, `🗑 quitar`.
- Bulk action bar: `⏸ Pausar todos` · `▶ Refrescar todos ahora`.
- Per-repo `⚙ config` opens an inline panel for refresh interval, scope override,
  and LLM override (advanced; defaults come from Settings).

### 5.4 Settings (`/settings`)
Sub-tabs in v1 (only the first one has a detailed mockup; the others are
listed so the route exists but the UI is minimal until requested):
- **Auth & LLMs** (fully designed):
    - GitHub auth card: current user card + PAT/OAuth mode toggle + token
      controls (show/replace/test) + scopes + env var note.
    - LLM card: default provider selector + active provider config (API key
      masked, model selector, "Test connection") + collapsed other providers
      with status indicators + skills registry mini-card.
- **Apariencia** (minimal): theme default (`dark` / `light` / `system`).
- **Refresh global** (minimal): default interval in seconds; self-repo override.
- **Skills registry** (minimal): full editor — per-skill `enabled`, `description`,
  `cli_flag`. The mini-card on Auth & LLMs links here.

### 5.5 Status / first-run

`/` redirects to `/settings` if `init` hasn't been run.

## 6. Data model (SQLite)

```sql
CREATE TABLE repos (
  id INTEGER PRIMARY KEY,
  owner TEXT NOT NULL,
  name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  is_self INTEGER NOT NULL DEFAULT 0,
  refresh_interval_seconds INTEGER NOT NULL DEFAULT 300,
  scope TEXT NOT NULL DEFAULT 'mine_and_review',  -- mine_and_review | mine | review | all
  llm_override TEXT,                              -- NULL = use global default
  added_at TEXT NOT NULL,
  last_fetched_at TEXT,
  last_fetch_status TEXT,                         -- ok | error | timeout
  last_fetch_error TEXT,
  UNIQUE(owner, name)
);

CREATE TABLE users (                              -- minimal cache for avatars/names
  login TEXT PRIMARY KEY,
  avatar_url TEXT,
  display_name TEXT
);

CREATE TABLE pull_requests (
  id INTEGER PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  number INTEGER NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  author_login TEXT REFERENCES users(login),
  state TEXT NOT NULL,                            -- open | closed | merged
  draft INTEGER NOT NULL DEFAULT 0,
  head_sha TEXT NOT NULL,
  base_ref TEXT NOT NULL,
  html_url TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  cached_at TEXT NOT NULL,
  UNIQUE(repo_id, number)
);

CREATE TABLE reviews (
  id INTEGER PRIMARY KEY,
  pr_id INTEGER NOT NULL REFERENCES pull_requests(id),
  reviewer_login TEXT NOT NULL REFERENCES users(login),
  state TEXT NOT NULL,                            -- approved | changes_requested | commented | dismissed
  submitted_at TEXT NOT NULL,
  body TEXT
);

CREATE TABLE review_comments (
  id INTEGER PRIMARY KEY,
  pr_id INTEGER NOT NULL REFERENCES pull_requests(id),
  reviewer_login TEXT NOT NULL REFERENCES users(login),
  path TEXT,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE pr_summaries (
  pr_id INTEGER PRIMARY KEY REFERENCES pull_requests(id),
  summary TEXT NOT NULL,
  head_sha TEXT NOT NULL,
  model TEXT NOT NULL,
  generated_at TEXT NOT NULL
);

CREATE TABLE review_runs (
  id INTEGER PRIMARY KEY,
  pr_id INTEGER NOT NULL REFERENCES pull_requests(id),
  agent_runner TEXT NOT NULL,                     -- claude | codex | minimax | ollama
  skills_json TEXT NOT NULL,                      -- JSON array of skill names
  mode TEXT NOT NULL,                             -- fresh | compare
  status TEXT NOT NULL,                           -- pending | running | done | failed | timeout
  started_at TEXT NOT NULL,
  finished_at TEXT,
  error TEXT,
  result_markdown TEXT,                           -- full output for display
  context_snapshot_json TEXT                      -- what was passed to the agent
);

CREATE TABLE review_findings (
  id INTEGER PRIMARY KEY,
  review_run_id INTEGER NOT NULL REFERENCES review_runs(id),
  finding_key TEXT NOT NULL,                      -- stable across runs (file:line:slug)
  severity TEXT NOT NULL,                         -- high | medium | low
  file_path TEXT,
  line INTEGER,
  description TEXT NOT NULL,
  status TEXT NOT NULL,                           -- resolved | pending | new
  resolved_in_commit TEXT,                        -- head_sha where it was fixed
  UNIQUE(review_run_id, finding_key)
);

CREATE INDEX idx_pr_repo ON pull_requests(repo_id);
CREATE INDEX idx_reviews_pr ON reviews(pr_id);
CREATE INDEX idx_comments_pr ON review_comments(pr_id);
CREATE INDEX idx_findings_run ON review_findings(review_run_id);
CREATE INDEX idx_findings_key ON review_findings(finding_key);
```

`finding_key` is a stable hash of `file:line:description_slug` so that the same
finding in two consecutive runs maps to the same row, which makes the
`resolved / pending / new` lifecycle work.

## 7. External integrations

### 7.1 GitHub

- **REST API only** (no PyGithub) via `httpx`. Endpoints used:
  - `GET /user` — validate auth, fetch the current user
  - `GET /repos/{owner}/{repo}` — validate access + metadata
  - `GET /repos/{owner}/{repo}/pulls?state=open&per_page=100` — list open PRs
  - `GET /repos/{owner}/{repo}/pulls/{number}` — single PR
  - `GET /repos/{owner}/{repo}/pulls/{number}/reviews`
  - `GET /repos/{owner}/{repo}/pulls/{number}/comments`
  - `GET /repos/{owner}/{repo}/pulls/{number}/files?per_page=100`
  - `GET /repos/{owner}/{repo}/pulls/{number}/commits`
- Rate limit tracking via response headers `X-RateLimit-*`.
- Conditional requests via `ETag` / `If-None-Match` to save quota on repeated fetches.

### 7.2 LLM providers

Abstract `LLMProvider`:

```python
class LLMProvider(Protocol):
    name: str
    def summarize(self, *, title: str, body: str, diff: str,
                  metadata: dict) -> str: ...
    def health_check(self) -> bool: ...
```

Implementations:
- `AnthropicProvider` — uses the `anthropic` SDK; default model
  `claude-3-5-sonnet-latest`.
- `OpenAIProvider` — uses the `openai` SDK; default model `gpt-4o` (also used
  for Codex-shaped prompts).
- `OllamaProvider` — uses `http://localhost:11434/api/generate`; default
  model configurable per install.

MiniMax Code is intentionally **not** an LLM summary provider in v1 — its
primary surface is the CLI agent (next section). If a user wants MiniMax to
also produce summaries, they can wire its HTTP API later as a custom provider.

Summaries are cached in `pr_summaries` keyed by `(pr_id, head_sha)` so they
are only regenerated when the head SHA changes.

### 7.3 Agent runners

Abstract `AgentRunner`:

```python
class AgentRunner(Protocol):
    name: str
    def run_review(
        self,
        *,
        pr_diff: str,
        pr_metadata: dict,
        skills: list[str],
        prompt_template: str,
        mode: Literal["fresh", "compare"],
        previous_findings: list[dict] | None,
        timeout_seconds: int = 300,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> ReviewResult: ...
```

Implementations (all subprocess-based in v1):
- `ClaudeRunner` — invokes `claude --print --dangerously-skip-permissions`
  with the composed prompt on stdin; streams stdout until the agent emits the
  sentinel `<!-- TLTW:DONE -->` line, then parses the structured findings
  block (severity, file, line, description) before that sentinel.
- `CodexRunner` — invokes `codex exec --quiet --json` with the prompt on
  stdin; parses the JSON events until `task_complete`.
- `MinimaxCodeRunner` — invokes `minimax --print` (the documented
  non-interactive flag of the user's local MiniMax Code CLI); reads stdout
  until the `<!-- TLTW:DONE -->` sentinel.
- `OllamaAgentRunner` — for fully-local workflows, calls the Ollama HTTP API
  directly with the same prompt; no subprocess.

The exact CLI flags above are validated during `tl_towerwatch init` by
running each chosen CLI with `--help` and asserting the flag exists; if not,
the runner falls back to `--print` and surfaces a warning. If the chosen CLI
is not on `PATH` at all, the runner raises a clear error
(`claude CLI not found in PATH; install it or pick another runner`).

### 7.4 Skills

A skill is a named bundle of agent instructions the user wants invoked during
a review. Examples shipped by default:

| Skill | Purpose | CLI invocation hint |
|---|---|---|
| `superpowers` | Code-review and quality skills (requesting-code-review, verification-before-completion) | `--enable-superpowers` |
| `ponytail` | User's custom review heuristics | `--skill ponytail` |

The skills registry lives in `config.yaml`:

```yaml
skills:
  superpowers:
    enabled: true
    description: "Set of code-review and quality skills"
    cli_flag: "--enable-superpowers"
  ponytail:
    enabled: true
    description: "Custom review heuristics"
    cli_flag: "--skill ponytail"
  my_custom:
    enabled: false
    description: "My own review checklist"
    cli_flag: "--skill my_custom"
```

The runner passes each enabled skill's `cli_flag` to the agent CLI and includes
its `description` in the prompt so the agent knows what behavior to apply.

## 8. Auth flows

### 8.1 PAT
- `tl_towerwatch init` prompts for a PAT (or reads from `TOWERWATCH_GITHUB_TOKEN`).
- Validates by calling `GET /user` and checking `repo` and `read:user` scopes.
- Stores in `./data/.env` as `TOWERWATCH_GITHUB_TOKEN=<token>`.

### 8.2 OAuth
- User registers a GitHub App themselves (documentation link in Settings).
- `tl_towerwatch init` prompts for client_id + client_secret.
- App spins up an ephemeral HTTP server on `localhost:8765` to handle the
  redirect, opens the user's browser to GitHub's authorization URL with the
  required scopes (`repo`, `read:user`), exchanges the code for an access
  token, and stores both in `./data/.env` as
  `TOWERWATCH_GITHUB_OAUTH_CLIENT_ID`, `TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET`,
  `TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN`, `TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN`.
- Refresh tokens are used automatically when the access token expires.

## 9. Review run lifecycle

1. User clicks `▶ Run review` (web) or runs `tl_towerwatch review …` (CLI).
2. The app snapshots the current diff, the relevant previous findings
   (from the latest `done` review), and any pending human comments into a
   `context_snapshot_json` blob.
3. A `review_runs` row is created with `status = pending`.
4. The chosen `AgentRunner.run_review` is invoked in a background task with
   the rendered prompt + skill flags. Status flips to `running`.
5. The agent returns either:
   - `done` with structured findings (severity, file, line, description) and
     raw markdown (`result_markdown`).
   - `failed` / `timeout` with an `error` field.
6. On `done`, `services/findings` reconciles against the previous `done`
   review run's findings by `finding_key`:
   - Every finding emitted by the agent in this run is inserted/updated;
     its `status` is set to `pending` if `finding_key` existed before,
     or `new` if it's the first time.
   - Every finding from the previous run whose `finding_key` is **not**
     present in this run is marked `resolved`, with `resolved_in_commit`
     set to the new `head_sha`.
   - This gives the user a clean `(resolved | pending | new)` summary per run.
7. The web UI polls `/pr/{owner}/{repo}/{n}/review-runs/{run_id}` every 2 s
   (HTMX) until `status != running`, then swaps in the final fragment.
8. CLI mode (`tl_towerwatch review … --watch`) streams stdout/stderr from the
   agent CLI in the terminal until completion.

## 10. Configuration

Two files in `./data/`, both gitignored:

### `.env`
```
TOWERWATCH_GITHUB_TOKEN=ghp_...                # PAT mode
TOWERWATCH_GITHUB_OAUTH_CLIENT_ID=...          # OAuth mode
TOWERWATCH_GITHUB_OAUTH_CLIENT_SECRET=...
TOWERWATCH_GITHUB_OAUTH_ACCESS_TOKEN=...
TOWERWATCH_GITHUB_OAUTH_REFRESH_TOKEN=...
TOWERWATCH_LLM_PROVIDER=anthropic              # default provider
TOWERWATCH_ANTHROPIC_API_KEY=sk-ant-...
TOWERWATCH_OPENAI_API_KEY=sk-...
TOWERWATCH_MINIMAX_API_KEY=...
TOWERWATCH_OLLAMA_BASE_URL=http://localhost:11434
TOWERWATCH_THEME=dark                          # dark | light | system
TOWERWATCH_REFRESH_INTERVAL_SECONDS=300
```

### `config.yaml`
```yaml
auth:
  mode: pat                                     # pat | oauth

llm:
  default_provider: anthropic
  default_model: claude-3-5-sonnet-latest
  anthropic:
    model: claude-3-5-sonnet-latest
  openai:
    model: gpt-4o
  minimax:
    model: Mavis
  ollama:
    base_url: http://localhost:11434
    model: llama3.2

skills:
  superpowers:
    enabled: true
    cli_flag: "--enable-superpowers"
  ponytail:
    enabled: true
    cli_flag: "--skill ponytail"

repos:
  - owner: hari-corp
    name: tl_towerwatch
    is_self: true
    refresh_interval_seconds: 60
    scope: all
  - owner: hari-corp
    name: billing-svc
    scope: mine_and_review
```

Loaded via Pydantic Settings; writes happen atomically (tmp file + rename) so
a crashed write cannot corrupt config.

## 11. Error handling

- **GitHub API errors** — surfaced in the UI with the error message and a
  retry button. Rate-limit headers are parsed and the next allowed fetch
  time is shown. On 401 the user is sent back to Settings.
- **LLM errors** — summary fails → display the PR description with a
  "(resumen automático no disponible)" prefix; the rest of the dashboard
  keeps working.
- **Agent CLI missing** — clear error: `"claude CLI not found in PATH;
  install it or pick another runner."` with a link to the install page.
- **Agent timeout** — configurable per-call (default 5 min); on timeout the
  run is marked `timeout` and the partial output (if any) is kept in
  `result_markdown`.
- **OAuth failure** — error message with retry; tokens are never written on
  partial success.
- **DB locked / disk full** — surfaced as a banner with retry; the CLI also
  exits non-zero so cron-style usage fails fast.
- **Diff too large** — truncated to the configured `max_diff_lines` (default
  2000) / `max_files` (default 30) with an explanatory note in the prompt
  and a UI note on the review card.

## 12. Testing

| Layer | Approach |
|---|---|
| `github.client` | `httpx_mock` or `respx` fixtures; verify request shape, pagination, rate-limit parsing |
| `auth.github` | Mock GitHub endpoints; test PAT validation and OAuth flow end-to-end with a fake ASGI server |
| `llm.*` | Mock each SDK; verify prompt rendering and output parsing |
| `agents.*` | Subprocess tests with a fake `claude`/`codex` binary in a temp dir; verify CLI flags and prompt content |
| `services.*` | SQLite-in-memory or temp-file DB; fixtures for GitHub responses |
| `web.*` | `fastapi.testclient.TestClient`; snapshot golden HTML for each screen |
| `findings` lifecycle | Property-based: random diff deltas must always classify each finding into exactly one of the three statuses |

Coverage target: ≥ 85% on `services/`, `llm/`, `agents/`, `findings/`.

## 13. Open questions / future work

- **Multi-user / team mode** — not in v1. The data model doesn't preclude it,
  but the auth flow assumes one local user.
- **Posting reviews back to GitHub** — explicitly out of scope; users still
  review in GitHub itself.
- **Slack/Discord notifications** — likely a v2 feature.
- **WebSocket live updates** — v1 polls; HTMX 2.x supports websockets but
  polling is simpler and good enough at 5-minute refresh intervals.
- **MiniMax Code SDK** — needs concrete API surface before implementation;
  if not available, fall back to shelling out to the `minimax` CLI.
- **Skill versioning** — v1 assumes skills are opaque names; v2 could
  pin to a skill version.