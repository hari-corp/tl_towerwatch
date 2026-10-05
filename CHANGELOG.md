# Changelog

All notable changes to `tl_towerwatch` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-10-04

First polished release. Adds auth hardening, a full CLI, init wizard, OAuth flow,
in-app review streaming, theme persistence, status counters, and PR-detail tabs.

### Added

- **`auth.mode` + `config.yaml` helpers** (`tl_towerwatch config`, `tl_towerwatch init`).
  Configurable PAT or OAuth mode persisted in `data/config.yaml`.
- **Six new CLI subcommands** under `tl_towerwatch repo {add,remove,list,enable,
  disable,set-authors,add-author,remove-author,clear-authors}` and `tl_towerwatch
  auth {login,refresh}`.
- **First-time setup wizard** (`tl_towerwatch init`) walks the user through PAT
  validation, LLM provider selection, and skill registry confirmation. Writes
  `data/.env` and `data/config.yaml` atomically.
- **Initial OAuth flow** (`tl_towerwatch auth login`) — opens the browser to
  GitHub's authorization page, persists the access + refresh tokens to
  `data/.env`, and stores the user record in SQLite.
- **`AgentRunner.on_event` streaming hook** that emits
  `reasoning` / `finding` / `done` events for live UI updates.
- **`tl_towerwatch review --watch`** streams findings to stdout as the agent
  produces them, with `--skill` and `--runner` overrides for one-off reviews.
- **Theme persistence + hardening** — `theme: dark | light | system` field on
  Settings, sticky across reloads, plus a `Settings | Theme` dropdown in the UI.
- **Status counters + rate-limit banner** — dashboard header shows counts for
  *Your PRs*, *Review requested*, *Pending review*, and *Drafts*, plus the live
  GitHub rate-limit remaining from `/rate_limit`.
- **PR detail tabs** — `Overview`, `Diff`, `Findings`, `Checks` tabs on the
  PR detail page, with the findings tab sourcing from `tl_towerwatch_findings`
  directly.
- **First-run + 401 redirect** — `/` redirects to `/repos` (or `/onboarding` on
  a virgin install) and 401 responses bounce the user back to `/settings`.
- **DB indexes** on `pull_requests.updated_at`, `findings.repo_owner + repo_name
  + pr_number`, `repos.owner + name`, and `users.login` for sub-100ms dashboard
  loads at scale.
- **`User` model** for OAuth users, plus dead-code removal in `review_runner.py`
  and explicit `body_type` hints on httpx calls.
- **Diff line truncation** — `_diff_text` now caps at
  `max_diff_lines` (default 2000) + `max_diff_files` (default 30) so a single
  5,000-file PR can't blow the model's context window.

### Fixed

- Init wizard wrote `TOWERWATCH_GITHUB_TOKEN` (correct) instead of the legacy
  `GITHUB_PAT` (silent fallback). _Patch landed in v1.1.0._
- OAuth callback no longer deadlocks when the user closes the browser before
  completing the flow.
- Dashboard counter names now match the spec §5.1 contract.

## [1.0.0] — 2026-10-03

Initial release. PR dashboard, GitHub sync, configurable LLM summarisation,
configurable agent runners, configurable skills registry, FastAPI + Jinja2 +
HTMX UI, SQLite cache, Docker image.

[1.1.0]: https://github.com/hari-corp/tl_towerwatch/compare/c898968...850c956
[1.0.0]: https://github.com/hari-corp/tl_towerwatch/releases/tag/c898968