# tl_towerwatch (v1.3.0)

![tests](https://img.shields.io/badge/tests-106%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-Proprietary-red)

Local-first PR dashboard for tech leads. Tracks your GitHub pull requests,
surfaces what needs attention, and assembles review prompts you can paste
into any external LLM (Claude Code, ChatGPT, …).

**v1.3.0:** tl_towerwatch no longer runs an LLM or an agent itself. The
app only builds the prompt — you choose the model and copy the result.
The old LLM/agent stack (summaries, review runs, findings) has been
removed, including its database tables.

## Features

- **Dashboard** — all tracked repos and PRs with state, review, and
  attention filters, plus badges for changes requested, pending
  responses, and review status.
- **PR detail** — Overview, Commits, Files, Reviews, and Comments tabs;
  manual TL;DR descriptions and notes; reply to review threads.
- **Manual review prompts** — three editable slots (`review`,
  `post_review`, `check_resolved`) rendered from a global template
  with live PR metadata and the diff, capped by
  `TOWERWATCH_MAX_DIFF_FILES` / `TOWERWATCH_MAX_DIFF_LINES`.
- **Background sync** — periodic refresh of repo PRs and per-PR
  subresources from the GitHub REST API, with state changes
  (open → closed → merged) picked up on each tick.
- **Auth** — GitHub PAT or OAuth device flow.
- **Local storage** — SQLite cache and files under your data directory;
  no hosted backend.

## Quick start (uv tool)

```bash
uv tool install tl_towerwatch
tl_towerwatch init             # paste a GitHub PAT
tl_towerwatch repo add owner/name
tl_towerwatch serve
# open http://localhost:8000
```

Render a review prompt from the CLI:

```bash
tl_towerwatch review owner/name#482
tl_towerwatch review owner/name#482 --slot post_review
```

## Quick start (Docker)

```bash
mkdir -p ~/tl_towerwatch-data
echo 'TOWERWATCH_GITHUB_TOKEN=ghp_...' > ~/tl_towerwatch-data/.env
docker compose up -d
# open http://localhost:8000
```

## Development

```bash
uv sync --extra dev
make check     # pytest + ruff — the definition of done
make run       # same as: uv run tl_towerwatch serve
```

Agent instructions live in `AGENTS.md` (Claude Code reads it through the
`CLAUDE.md` shim). Architecture and decisions are documented in
`docs/architecture.md` and `docs/adr/`. To bootstrap the same setup in
another repository, reuse [`docs/ai-onboarding-prompt.md`](docs/ai-onboarding-prompt.md).

## Configuration

Everything lives in your data directory (`./data` by default, or the
directory mounted in Docker):

- `.env` — GitHub token and OAuth credentials; optional theme,
  refresh interval, and diff-size caps (see `.env.example`)
- `config.yaml` — prompt slots, theme, auth mode, per-repo settings
- `tl_towerwatch.db` — SQLite cache

`tl_towerwatch init` bootstraps a PAT. For OAuth credentials, prompt
templates, and repo overrides open **Settings** at
`http://localhost:8000/settings` after `serve`.

The implementation plans and specs under `docs/superpowers/` are
historical documents from earlier versions and do not describe the
current architecture.
