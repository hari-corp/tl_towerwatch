# AI onboarding prompt

Reusable prompt that makes a coding agent derive and create the same
AI-friendly setup used in this repo: a short `AGENTS.md`, a `CLAUDE.md`
shim, a one-command `check`, shared permissions, architecture docs, and ADRs.

**How to use:** open the target repository in Claude Code, Codex, Cursor, or
another coding agent and paste the block below as the first message. The agent
inspects the repo first and only records commands it has actually run.

> Tip: on this machine the same prompt is installed as the `/ai-onboard`
> command in `~/.claude/commands/`, so it can be replayed from any project.

## Prompt

```text
You are setting up AI-agent onboarding for this repository. Work from evidence,
not assumptions: inspect the code, config, tests, and scripts first, then create
the files below. Do not invent commands, module names, or conventions.

## Phase 1 — Discover (before writing anything)
- Identify the language(s), package manager, runtime version, test framework,
  linter/formatter/type checker, and how the app runs.
- Read: README, pyproject.toml / package.json / go.mod / Cargo.toml, CI config,
  Dockerfiles, Makefile/justfile, and the top 2 levels of the source tree.
- Actually run the install, test, lint, and run commands. Note any pre-existing
  lint/test failures as a baseline.
- Check for existing AGENTS.md, CLAUDE.md, .cursorrules,
  .github/copilot-instructions.md. Merge with them; never overwrite.

## Phase 2 — Create
1. AGENTS.md (60–100 lines, pointer-heavy). Sections:
   - What the project is and its non-goals.
   - Commands: install, test, lint, check, run (only commands you verified).
   - Layout and boundaries: which module owns what; where new code goes.
   - Rules: invariants, "do not touch" areas, security/secret handling,
     testing expectations.
   - "Done means": the exact command that must pass.
   - Docs: links to architecture and ADRs.
2. CLAUDE.md — exactly one line: `@AGENTS.md`.
3. Task runner with equivalent targets (Makefile, justfile, or package.json
   scripts): `install`, `test`, `lint`, `check`, `run`. `check` must combine
   tests + lint and exit 0 on a healthy tree.
4. .claude/settings.json — permissions that allow the safe commands
   (install, test, lint, run, read-only git) and deny reading `.env` and
   local data directories.
5. docs/architecture.md — runtime topology, data flow, module map,
   persistence, testing strategy, and an explicit list of invariants.
6. docs/adr/0001-*.md — only if there is a non-obvious architectural decision
   (e.g. a removed subsystem, vendor choice, storage model). Otherwise adapt
   or skip it.
7. .gitignore — add `.claude/settings.local.json`, `CLAUDE.local.md`,
   `AGENTS.local.md`. Keep shared files committed.
8. README.md — a short Development section pointing at `check` and the docs.

## Phase 3 — Verify
- Run the full `check` command and the app's boot command. Paste real output.
- Confirm AGENTS.md contains no command or path you did not verify.
- Confirm the brief stays under ~100 lines; move depth into docs/.

## Rules
- Never claim a command works without running it.
- If lint/tests already fail, record the baseline and make the tooling
  reproducible (pinned linter rules/version). Do not silently weaken rules
  just to make `check` green; either fix trivial violations or document the
  backlog explicitly.
- Keep AGENTS.md as an index, not an encyclopedia. No README duplication.
- No secrets in any committed file.
- Do not create config for tools this project does not use.
- Do not commit, push, or modify CI unless I ask.
- Ask me before overwriting existing context files or adding dependencies.

Report: files created, commands verified with their output summary, and
anything you could not verify.
```
