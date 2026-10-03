# tl_towerwatch

Local PR dashboard + agent reviewer for tech leads. Tracks your GitHub PRs,
shows you what needs attention, and triggers AI code reviews with pluggable
skills (superpowers, ponytail, …).

## Quick start (uv tool)

```bash
uv tool install tl_towerwatch
tl_towerwatch init             # paste a GitHub PAT
tl_towerwatch repo add owner/name
tl_towerwatch serve
# open http://localhost:8000
```

## Quick start (Docker)

```bash
mkdir -p ~/tl_towerwatch-data
echo 'TOWERWATCH_GITHUB_TOKEN=ghp_...' > ~/tl_towerwatch-data/.env
docker compose up -d
# open http://localhost:8000
```

## Configuration

Everything lives in `~/tl_towerwatch-data/`:

- `.env` — secrets (GitHub token, LLM API keys)
- `config.yaml` — skills registry, per-repo overrides
- `tl_towerwatch.db` — SQLite cache

See `docs/superpowers/specs/2026-10-03-tl-towerwatch-design.md` for the
full design and `docs/superpowers/plans/2026-10-03-tl-towerwatch.md` for
the implementation plan.