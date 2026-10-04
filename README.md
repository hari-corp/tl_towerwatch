# tl_towerwatch (v1.1)

![tests](https://img.shields.io/badge/tests-78%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-Proprietary-red)

Local PR dashboard + agent reviewer for tech leads. Tracks your GitHub PRs,
shows you what needs attention, and triggers AI code reviews with pluggable
skills (superpowers, ponytail, …).

**v1.1 highlights:** `tl_towerwatch init` wizard, OAuth initial flow, PR
detail tabs, theme persistence, performance indexes, and diff-size
limitations on the LLM summariser — see the
[plan](docs/superpowers/plans/2026-10-04-tl-towerwatch-v1.1.md) for the
full changelog.

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

`tl_towerwatch init` is a PAT-only bootstrap. For the full setup (OAuth
client credentials, LLM provider switching, custom Ollama URL) open the
**Settings** page at `http://localhost:8000/settings` after `serve`.

See `docs/superpowers/specs/2026-10-03-tl-towerwatch-design.md` for the
full design and `docs/superpowers/plans/2026-10-03-tl-towerwatch.md` for
the implementation plan.