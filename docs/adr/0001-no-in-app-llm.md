# ADR 0001 — No LLM integration inside the app

- **Status:** Accepted (v1.3.0)
- **Date:** 2026-11-01
- **Supersedes:** the pre-v1.3.0 in-app LLM/agent design

## Context

Earlier versions of tl_towerwatch called an LLM directly: it stored provider
credentials, generated PR summaries, ran review agents, and persisted
"findings". That created a second configuration surface (providers, models,
API keys, retries, cost), coupled every feature to a specific vendor, and
made the local-first promise harder to keep — summaries and findings went
stale, and the prompt that produced them was not visible to the user.

The core value of the tool is smaller than that: collect PR state, show what
needs attention, and give the user a well-formed prompt.

## Decision

1. The app **never calls an LLM**. It only assembles prompt text from a
   template plus live PR metadata and the diff.
2. The user chooses the external model (Claude Code, ChatGPT, …), copies the
   prompt, and interprets the result themselves.
3. All prompt logic lives in `services/prompt_assembly.py`; the CLI and the
   web route call the same function so their output is byte-identical.
4. The three fixed slots (`review`, `post_review`, `check_resolved`) live in
   `skills/registry.py` and persist in `config.yaml`.
5. LLM credentials, provider settings, generated summaries, review runs, and
   findings are removed from `Settings`, the database, and the UI.

## Consequences

- `Settings` keeps `extra="ignore"` so old `.env` files containing
  `TOWERWATCH_ANTHROPIC_API_KEY` / `TOWERWATCH_LLM_PROVIDER` still boot.
- `db/database.py` drops the legacy LLM tables on startup.
- `docs/superpowers/` is historical design material and no longer describes
  the architecture.
- Adding an LLM feature requires a new ADR that explicitly supersedes this
  one. Do not reintroduce provider SDKs, model selection, or API keys
  without that decision.
