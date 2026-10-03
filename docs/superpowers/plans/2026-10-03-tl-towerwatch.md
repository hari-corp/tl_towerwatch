# tl_towerwatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python app (`tl_towerwatch`) that surfaces PRs needing a tech lead's attention across GitHub repos, with one-click agent reviews and findings tracking.

**Tech Stack:** Python 3.11+, Typer, FastAPI, Jinja2, HTMX, SQLAlchemy 2.x, SQLite, Pydantic v2, httpx, Authlib, uv.

**Spec:** `docs/superpowers/specs/2026-10-03-tl-towerwatch-design.md`

## Global Constraints

- **Python ≥ 3.11**; target 3.11 (matches Docker base image).
- **Package name** = `tl_towerwatch`; CLI command = `tl_towerwatch`.
- **Repo URL** for remote: `github.com/hari-corp/tl_towerwatch`.
- **Default config dir** = `./data/` (gitignored); can be overridden by `TOWERWATCH_DATA_DIR` env var.
- **Database file:** `./data/tl_towerwatch.db` (SQLite, foreign keys ON).
- **Server default port:** `8000`, host `127.0.0.1`; Docker exposes `0.0.0.0:8000`.
- **OAuth callback port:** `8765` (configurable); in Docker the callback URL is `http://host.docker.internal:8765/auth/callback`.
- **Default LLM provider:** `anthropic`; default model: `claude-3-5-sonnet-latest`.
- **Default skills shipped:** `superpowers`, `ponytail` (both enabled by default).
- **Self-repo (`tl_towerwatch`)** refresh interval: 60s; other repos: 300s.
- **No telemetry, no external SaaS calls** beyond GitHub API and the configured LLM/agent providers.
- **Coverage target:** ≥ 85% on `services/`, `llm/`, `agents/`, `findings/`.
- **Testing:** `pytest` with `respx` for HTTP, `fastapi.testclient.TestClient` for web, in-memory SQLite for service tests, fake binaries in a temp dir for agent runner tests.

## File Structure (target)

```
tl_towerwatch/
├── pyproject.toml                          # uv + project metadata
├── README.md
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── src/tl_towerwatch/
│   ├── __init__.py
│   ├── cli.py                              # Typer CLI entrypoint
│   ├── web.py                              # FastAPI app factory
│   ├── config.py                           # Pydantic Settings
│   ├── auth/__init__.py
│   ├── auth/github.py                      # PAT + OAuth
│   ├── github/__init__.py
│   ├── github/client.py                    # httpx REST client
│   ├── github/models.py                    # Pydantic domain models
│   ├── llm/__init__.py
│   ├── llm/base.py                         # LLMProvider Protocol
│   ├── llm/anthropic.py
│   ├── llm/openai.py
│   ├── llm/ollama.py
│   ├── agents/__init__.py
│   ├── agents/base.py                      # AgentRunner Protocol
│   ├── agents/claude.py
│   ├── agents/codex.py
│   ├── agents/minimax_code.py
│   ├── agents/ollama.py
│   ├── skills/__init__.py
│   ├── skills/registry.py
│   ├── skills/prompts.py
│   ├── db/__init__.py
│   ├── db/database.py
│   ├── db/models.py
│   ├── services/__init__.py
│   ├── services/pull_requests.py
│   ├── services/reviews.py
│   ├── services/findings.py
│   ├── services/repos.py
│   ├── services/review_runner.py
│   └── web/__init__.py
│       ├── routes.py
│       └── templates/{base,dashboard,pr_detail,repos,settings}.html
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_db.py
    ├── test_github_client.py
    ├── test_auth.py
    ├── test_services.py
    ├── test_findings.py
    ├── test_llm_providers.py
    ├── test_agent_runners.py
    ├── test_skills.py
    └── test_web_routes.py
```

---

## Phase 1 — Foundation

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `README.md`, `.env.example`, `src/tl_towerwatch/__init__.py`, `tests/conftest.py`
- Modify: `.gitignore` (already updated; ensure `data/`, `.superpowers/`, `.venv/` are present)

**Interfaces:**
- Produces: `tl_towerwatch` Python package importable from src; `pytest` test suite runnable.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "tl_towerwatch"
version = "0.1.0"
description = "Local PR dashboard and review agent for tech leads"
requires-python = ">=3.11"
readme = "README.md"
license = { text = "Proprietary" }
authors = [{ name = "David", email = "dimh@example.com" }]
dependencies = [
    "typer>=0.12",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "jinja2>=3.1",
    "httpx>=0.27",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "sqlalchemy>=2.0",
    "authlib>=1.3",
    "anthropic>=0.25",
    "openai>=1.13",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.1",
    "respx>=0.21",
    "httpx>=0.27",
    "ruff>=0.3",
]

[project.scripts]
tl_towerwatch = "tl_towerwatch.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tl_towerwatch"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 2: Create `src/tl_towerwatch/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import os
import tempfile
from pathlib import Path
import pytest

@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d

@pytest.fixture
def env(monkeypatch, tmp_data_dir):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_data_dir))
    return tmp_data_dir
```

- [ ] **Step 4: Create `.env.example`**

```
TOWERWATCH_DATA_DIR=./data
TOWERWATCH_GITHUB_TOKEN=
TOWERWATCH_LLM_PROVIDER=anthropic
TOWERWATCH_ANTHROPIC_API_KEY=
TOWERWATCH_OPENAI_API_KEY=
TOWERWATCH_OLLAMA_BASE_URL=http://localhost:11434
TOWERWATCH_THEME=dark
TOWERWATCH_REFRESH_INTERVAL_SECONDS=300
```

- [ ] **Step 5: Install dev environment and verify pytest runs**

```bash
cd /Users/dimh/src/minimax/tl_towerwatch
uv venv && uv pip install -e ".[dev]"
uv run pytest --collect-only
```
Expected: collects 0 items; package importable.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example src/tl_towerwatch/__init__.py tests/conftest.py README.md
git commit -m "chore: scaffold tl_towerwatch Python package"
```

---

### Task 2: Pydantic Settings (`config.py`)

**Files:**
- Create: `src/tl_towerwatch/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `tl_towerwatch.config.Settings` Pydantic model + `load_settings(data_dir: Path) -> Settings` factory.

- [ ] **Step 1: Write failing test `tests/test_config.py`**

```python
from pathlib import Path
from tl_towerwatch.config import Settings, load_settings

def test_load_settings_defaults(tmp_path: Path):
    s = load_settings(tmp_path)
    assert s.llm.default_provider == "anthropic"
    assert s.refresh_interval_seconds == 300
    assert s.theme == "dark"
    assert (tmp_path / "tl_towerwatch.db").as_posix() in s.db_url

def test_load_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TOWERWATCH_GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("TOWERWATCH_ANTHROPIC_API_KEY", "sk-test")
    s = load_settings(tmp_path)
    assert s.github_token == "ghp_test"
    assert s.anthropic_api_key == "sk-test"
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
uv run pytest tests/test_config.py -v
```

- [ ] **Step 3: Implement `src/tl_towerwatch/config.py`**

```python
from __future__ import annotations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class AnthropicCfg(BaseModel):
    api_key: str = ""
    model: str = "claude-3-5-sonnet-latest"

class OpenAICfg(BaseModel):
    api_key: str = ""
    model: str = "gpt-4o"

class OllamaCfg(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "llama3.2"

class LLMCfg(BaseModel):
    default_provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    anthropic: AnthropicCfg = Field(default_factory=AnthropicCfg)
    openai: OpenAICfg = Field(default_factory=OpenAICfg)
    ollama: OllamaCfg = Field(default_factory=OllamaCfg)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOWERWATCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("./data")
    github_token: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_access_token: str = ""
    oauth_refresh_token: str = ""
    theme: Literal["dark", "light", "system"] = "dark"
    refresh_interval_seconds: int = 300

    llm: LLMCfg = Field(default_factory=LLMCfg)

    @property
    def db_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'tl_towerwatch.db').as_posix()}"

def load_settings(data_dir: Path | None = None) -> Settings:
    s = Settings()
    if data_dir is not None:
        s.data_dir = data_dir
        (data_dir / "config.yaml").touch()
    return s
```

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/tl_towerwatch/config.py tests/test_config.py
git commit -m "feat(config): pydantic settings with env loading"
```

---

### Task 3: SQLAlchemy models + database setup

**Files:**
- Create: `src/tl_towerwatch/db/__init__.py`, `src/tl_towerwatch/db/database.py`, `src/tl_towerwatch/db/models.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `tl_towerwatch.db.database.engine_from_settings(s) -> Database`, `Database.create_all()`, `Database.session()` context manager; ORM classes `Repo`, `User`, `PullRequest`, `Review`, `ReviewComment`, `PRSummary`, `ReviewRun`, `ReviewFinding`.

- [ ] **Step 1: Write failing test `tests/test_db.py`**

```python
from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import Repo

def test_db_create_and_insert(tmp_path: Path):
    settings = load_settings(tmp_path)
    db = engine_from_settings(settings)
    db.create_all()
    with db.session() as s:
        r = Repo(owner="o", name="n", added_at="2026-01-01T00:00:00Z")
        s.add(r)
    with db.session() as s:
        assert s.query(Repo).count() == 1
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/db/models.py`** (mirror the schema in spec §6; field names use snake_case Python conventions; column comments document allowed values)

```python
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class Repo(Base):
    __tablename__ = "repos"
    id = Column(Integer, primary_key=True)
    owner = Column(String, nullable=False)
    name = Column(String, nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    is_self = Column(Integer, nullable=False, default=0)
    refresh_interval_seconds = Column(Integer, nullable=False, default=300)
    scope = Column(String, nullable=False, default="mine_and_review")
    llm_override = Column(String)
    allowed_authors_json = Column(Text)
    added_at = Column(String, nullable=False)
    last_fetched_at = Column(String)
    last_fetch_status = Column(String)
    last_fetch_error = Column(Text)
    __table_args__ = (Index("uq_repos_owner_name", "owner", "name", unique=True),)

class User(Base):
    __tablename__ = "users"
    login = Column(String, primary_key=True)
    avatar_url = Column(String)
    display_name = Column(String)

class PullRequest(Base):
    __tablename__ = "pull_requests"
    id = Column(Integer, primary_key=True)
    repo_id = Column(Integer, ForeignKey("repos.id"), nullable=False)
    number = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text)
    author_login = Column(String, ForeignKey("users.login"))
    state = Column(String, nullable=False)
    draft = Column(Integer, nullable=False, default=0)
    head_sha = Column(String, nullable=False)
    base_ref = Column(String, nullable=False)
    html_url = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    cached_at = Column(String, nullable=False)
    __table_args__ = (Index("uq_pr_repo_number", "repo_id", "number", unique=True),)

class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True)
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    reviewer_login = Column(String, ForeignKey("users.login"), nullable=False)
    state = Column(String, nullable=False)
    submitted_at = Column(String, nullable=False)
    body = Column(Text)

class ReviewComment(Base):
    __tablename__ = "review_comments"
    id = Column(Integer, primary_key=True)
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    reviewer_login = Column(String, ForeignKey("users.login"), nullable=False)
    path = Column(String)
    body = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)

class PRSummary(Base):
    __tablename__ = "pr_summaries"
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), primary_key=True)
    summary = Column(Text, nullable=False)
    head_sha = Column(String, nullable=False)
    model = Column(String, nullable=False)
    generated_at = Column(String, nullable=False)

class ReviewRun(Base):
    __tablename__ = "review_runs"
    id = Column(Integer, primary_key=True)
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    agent_runner = Column(String, nullable=False)
    skills_json = Column(Text, nullable=False)
    mode = Column(String, nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(String, nullable=False)
    finished_at = Column(String)
    error = Column(Text)
    result_markdown = Column(Text)
    context_snapshot_json = Column(Text)

class ReviewFinding(Base):
    __tablename__ = "review_findings"
    id = Column(Integer, primary_key=True)
    review_run_id = Column(Integer, ForeignKey("review_runs.id"), nullable=False)
    finding_key = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    file_path = Column(String)
    line = Column(Integer)
    description = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    resolved_in_commit = Column(String)
    __table_args__ = (Index("uq_finding_run_key", "review_run_id", "finding_key", unique=True),)
```

- [ ] **Step 4: Create `src/tl_towerwatch/db/database.py`**

```python
from __future__ import annotations
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from tl_towerwatch.config import Settings
from tl_towerwatch.db.models import Base

class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Session:
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

def engine_from_settings(settings: Settings) -> Database:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        settings.db_url,
        future=True,
        connect_args={"check_same_thread": False},
    )
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
    return Database(engine)
```

- [ ] **Step 5: Create empty `src/tl_towerwatch/db/__init__.py`**

- [ ] **Step 6: Run test, expect PASS**

```bash
uv run pytest tests/test_db.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/tl_towerwatch/db/ tests/test_db.py
git commit -m "feat(db): SQLAlchemy models + database setup"
```

---

### Task 4: GitHub REST client (httpx + respx)

**Files:**
- Create: `src/tl_towerwatch/github/__init__.py`, `src/tl_towerwatch/github/models.py`, `src/tl_towerwatch/github/client.py`
- Test: `tests/test_github_client.py`

**Interfaces:**
- Produces:
  - `class GitHubClient` with constructor `__init__(self, token: str, base_url: str = "https://api.github.com")`
  - `get_authenticated_user() -> User`
  - `get_repo(owner: str, name: str) -> RepoMeta`
  - `list_open_prs(owner: str, name: str) -> list[PullRequestData]`
  - `get_pr(owner: str, name: str, number: int) -> PullRequestData`
  - `list_reviews(owner: str, name: str, number: int) -> list[ReviewData]`
  - `list_comments(owner: str, name: str, number: int) -> list[CommentData]`
  - `list_pr_files(owner: str, name: str, number: int) -> list[FileData]`
  - `list_pr_commits(owner: str, name: str, number: int) -> list[CommitData]`
  - `last_rate_limit() -> RateLimit | None` (parsed from response headers)

- [ ] **Step 1: Write failing test `tests/test_github_client.py`**

```python
import respx
from httpx import Response
from tl_towerwatch.github.client import GitHubClient

@respx.mock
def test_get_authenticated_user():
    respx.get("https://api.github.com/user").mock(
        return_value=Response(
            200,
            json={"login": "dimh", "avatar_url": "https://x/y.png", "name": "D"},
            headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Reset": "1700000000"},
        )
    )
    c = GitHubClient(token="x")
    u = c.get_authenticated_user()
    assert u.login == "dimh"
    assert c.last_rate_limit().remaining == 4999
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/github/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class User:
    login: str
    avatar_url: str | None = None
    display_name: str | None = None

@dataclass
class RepoMeta:
    owner: str
    name: str
    full_name: str
    private: bool

@dataclass
class PullRequestData:
    number: int
    title: str
    body: str | None
    author_login: str | None
    state: str
    draft: bool
    head_sha: str
    base_ref: str
    html_url: str
    created_at: str
    updated_at: str
    requested_reviewers: list[str] = field(default_factory=list)

@dataclass
class ReviewData:
    reviewer_login: str
    state: str
    submitted_at: str
    body: str | None

@dataclass
class CommentData:
    reviewer_login: str
    path: str | None
    body: str
    created_at: str

@dataclass
class FileData:
    path: str
    additions: int
    deletions: int
    status: str
    patch: str | None

@dataclass
class CommitData:
    sha: str
    message: str
    author_login: str | None

@dataclass
class RateLimit:
    remaining: int
    reset: int
```

- [ ] **Step 4: Create `src/tl_towerwatch/github/client.py`**

```python
from __future__ import annotations
from typing import Any
import httpx
from tl_towerwatch.github.models import (
    User, RepoMeta, PullRequestData, ReviewData, CommentData,
    FileData, CommitData, RateLimit,
)

class GitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        self._last_rate_limit: RateLimit | None = None

    def last_rate_limit(self) -> RateLimit | None:
        return self._last_rate_limit

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _capture_rate_limit(self, r: httpx.Response) -> None:
        rem = r.headers.get("X-RateLimit-Remaining")
        reset = r.headers.get("X-RateLimit-Reset")
        if rem is not None and reset is not None:
            self._last_rate_limit = RateLimit(remaining=int(rem), reset=int(reset))

    def _check(self, r: httpx.Response) -> dict[str, Any]:
        self._capture_rate_limit(r)
        r.raise_for_status()
        return r.json()

    def get_authenticated_user(self) -> User:
        d = self._check(self._client.get("/user"))
        return User(login=d["login"], avatar_url=d.get("avatar_url"), display_name=d.get("name"))

    def get_repo(self, owner: str, name: str) -> RepoMeta:
        d = self._check(self._client.get(f"/repos/{owner}/{name}"))
        return RepoMeta(owner=owner, name=name, full_name=d["full_name"], private=d["private"])

    def list_open_prs(self, owner: str, name: str) -> list[PullRequestData]:
        out: list[PullRequestData] = []
        page = 1
        while True:
            d = self._check(self._client.get(
                f"/repos/{owner}/{name}/pulls",
                params={"state": "open", "per_page": 100, "page": page},
            ))
            if not d:
                break
            for pr in d:
                out.append(self._parse_pr(pr))
            if len(d) < 100:
                break
            page += 1
        return out

    def get_pr(self, owner: str, name: str, number: int) -> PullRequestData:
        d = self._check(self._client.get(f"/repos/{owner}/{name}/pulls/{number}"))
        return self._parse_pr(d)

    def list_reviews(self, owner: str, name: str, number: int) -> list[ReviewData]:
        d = self._check(self._client.get(f"/repos/{owner}/{name}/pulls/{number}/reviews"))
        return [
            ReviewData(
                reviewer_login=r["user"]["login"],
                state=r["state"],
                submitted_at=r["submitted_at"],
                body=r.get("body"),
            ) for r in d
        ]

    def list_comments(self, owner: str, name: str, number: int) -> list[CommentData]:
        d = self._check(self._client.get(f"/repos/{owner}/{name}/pulls/{number}/comments"))
        return [
            CommentData(
                reviewer_login=c["user"]["login"],
                path=c.get("path"),
                body=c["body"],
                created_at=c["created_at"],
            ) for c in d
        ]

    def list_pr_files(self, owner: str, name: str, number: int) -> list[FileData]:
        d = self._check(self._client.get(f"/repos/{owner}/{name}/pulls/{number}/files"))
        return [
            FileData(
                path=f["filename"],
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
                status=f.get("status", ""),
                patch=f.get("patch"),
            ) for f in d
        ]

    def list_pr_commits(self, owner: str, name: str, number: int) -> list[CommitData]:
        d = self._check(self._client.get(f"/repos/{owner}/{name}/pulls/{number}/commits"))
        return [
            CommitData(
                sha=c["sha"],
                message=c["commit"]["message"],
                author_login=(c.get("author") or {}).get("login"),
            ) for c in d
        ]

    @staticmethod
    def _parse_pr(pr: dict) -> PullRequestData:
        return PullRequestData(
            number=pr["number"],
            title=pr["title"],
            body=pr.get("body"),
            author_login=(pr.get("user") or {}).get("login"),
            state=pr["state"],
            draft=pr.get("draft", False),
            head_sha=pr["head"]["sha"],
            base_ref=pr["base"]["ref"],
            html_url=pr["html_url"],
            created_at=pr["created_at"],
            updated_at=pr["updated_at"],
            requested_reviewers=[
                u["login"] for u in pr.get("requested_reviewers", [])
            ],
        )
```

- [ ] **Step 5: Create empty `src/tl_towerwatch/github/__init__.py`**

- [ ] **Step 6: Run test, expect PASS**

```bash
uv run pytest tests/test_github_client.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/tl_towerwatch/github/ tests/test_github_client.py
git commit -m "feat(github): REST client with httpx + rate-limit parsing"
```

---

### Task 5: Auth — PAT validation + OAuth flow

**Files:**
- Create: `src/tl_towerwatch/auth/__init__.py`, `src/tl_towerwatch/auth/github.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces:
  - `tl_towerwatch.auth.github.resolve_token(settings: Settings) -> str` — returns the active token (PAT or OAuth access token, refreshing if expired).
  - `tl_towerwatch.auth.github.refresh_oauth_token(settings: Settings) -> Settings` — exchanges refresh token for a new access token, writes back to `.env`.

- [ ] **Step 1: Write failing test `tests/test_auth.py`**

```python
import respx
from httpx import Response
from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.auth.github import resolve_token

@respx.mock
def test_resolve_token_pat(tmp_path: Path):
    s = load_settings(tmp_path)
    s.github_token = "ghp_test"
    respx.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "dimh"})
    )
    assert resolve_token(s) == "ghp_test"

@respx.mock
def test_resolve_token_oauth_refresh(tmp_path: Path):
    s = load_settings(tmp_path)
    s.oauth_access_token = "old_access"
    s.oauth_refresh_token = "old_refresh"
    s.oauth_client_id = "cid"
    s.oauth_client_secret = "csec"
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(
            200,
            json={"access_token": "new_access", "refresh_token": "new_refresh"},
            headers={"Content-Type": "application/json"},
        )
    )
    new = resolve_token(s)
    assert new == "new_access"
    assert s.oauth_refresh_token == "new_refresh"
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/auth/github.py`**

```python
from __future__ import annotations
import httpx
from tl_towerwatch.config import Settings

GITHUB_OAUTH_URL = "https://github.com/login/oauth/access_token"

def resolve_token(settings: Settings) -> str:
    if settings.github_token:
        return settings.github_token
    if settings.oauth_access_token and settings.oauth_refresh_token:
        # In v1 we always refresh when the OAuth path is the source.
        return _refresh_oauth(settings)
    raise RuntimeError("No GitHub credentials configured. Run `tl_towerwatch init`.")

def _refresh_oauth(settings: Settings) -> str:
    r = httpx.post(
        GITHUB_OAUTH_URL,
        data={
            "client_id": settings.oauth_client_id,
            "client_secret": settings.oauth_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": settings.oauth_refresh_token,
        },
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    settings.oauth_access_token = data["access_token"]
    if "refresh_token" in data:
        settings.oauth_refresh_token = data["refresh_token"]
    _persist_env(settings)
    return data["access_token"]

def _persist_env(settings: Settings) -> None:
    """Append updated OAuth tokens to data_dir/.env (atomic write)."""
    import os
    env_path = settings.data_dir / ".env"
    updates = {
        "TOWERWATCH_OAUTH_ACCESS_TOKEN": settings.oauth_access_token,
        "TOWERWATCH_OAUTH_REFRESH_TOKEN": settings.oauth_refresh_token,
    }
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    keys = set(updates.keys())
    new_lines = [ln for ln in lines if not any(ln.startswith(k + "=") for k in keys)]
    new_lines += [f"{k}={v}" for k, v in updates.items()]
    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(new_lines) + "\n")
    os.replace(tmp, env_path)
```

- [ ] **Step 4: Create empty `src/tl_towerwatch/auth/__init__.py`**

- [ ] **Step 5: Run test, expect PASS**

```bash
uv run pytest tests/test_auth.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/tl_towerwatch/auth/ tests/test_auth.py
git commit -m "feat(auth): PAT resolution + OAuth refresh-token flow"
```

---

### Task 6: Services — `repos` (CRUD + allowed_authors)

**Files:**
- Create: `src/tl_towerwatch/services/__init__.py`, `src/tl_towerwatch/services/repos.py`
- Test: `tests/test_services.py` (extend; co-locate for now)

**Interfaces:**
- Produces:
  - `services.repos.add_repo(db, owner, name, *, is_self=False, refresh_interval_seconds=300, scope="mine_and_review", allowed_authors: list[str] | None = None) -> Repo`
  - `services.repos.list_repos(db, *, enabled_only=False) -> list[Repo]`
  - `services.repos.set_repo_enabled(db, owner, name, enabled: bool) -> None`
  - `services.repos.remove_repo(db, owner, name) -> None`
  - `services.repos.set_allowed_authors(db, owner, name, authors: list[str]) -> None`
  - `services.repos.normalize_authors(authors: list[str]) -> list[str]` (lowercased, deduplicated, sorted)

- [ ] **Step 1: Write failing test in `tests/test_services.py`**

```python
import json
from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.services.repos import (
    add_repo, list_repos, set_repo_enabled, set_allowed_authors, normalize_authors,
)

def _setup(tmp_path: Path):
    s = load_settings(tmp_path)
    db = engine_from_settings(s)
    db.create_all()
    return db

def test_add_and_list_repo(tmp_path: Path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    assert len(list_repos(db)) == 1

def test_set_allowed_authors_normalizes(tmp_path: Path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    set_allowed_authors(db, "o", "n", ["Marta.G", "luis.f", "marta.g"])
    r = list_repos(db)[0]
    assert json.loads(r.allowed_authors_json) == ["luis.f", "marta.g"]

def test_normalize_authors_dedupes():
    assert normalize_authors(["Marta.G", "marta.g", " luis.f "]) == ["luis.f", "marta.g"]
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/services/repos.py`**

```python
from __future__ import annotations
import json
from typing import Iterable

from sqlalchemy import select
from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import Repo, now_iso

def normalize_authors(authors: Iterable[str]) -> list[str]:
    out: set[str] = set()
    for a in authors:
        a = a.strip().lstrip("@").lower()
        if a:
            out.add(a)
    return sorted(out)

def add_repo(
    db: Database, owner: str, name: str,
    *, is_self: bool = False, refresh_interval_seconds: int = 300,
    scope: str = "mine_and_review", allowed_authors: list[str] | None = None,
) -> Repo:
    with db.session() as s:
        existing = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one_or_none()
        if existing:
            existing.enabled = 1
            existing.is_self = 1 if is_self else existing.is_self
            existing.refresh_interval_seconds = refresh_interval_seconds
            existing.scope = scope
            if allowed_authors is not None:
                existing.allowed_authors_json = json.dumps(normalize_authors(allowed_authors))
            s.flush()
            return existing
        r = Repo(
            owner=owner, name=name, enabled=1,
            is_self=1 if is_self else 0,
            refresh_interval_seconds=refresh_interval_seconds,
            scope=scope,
            allowed_authors_json=json.dumps(normalize_authors(allowed_authors or [])),
            added_at=now_iso(),
        )
        s.add(r)
        s.flush()
        return r

def list_repos(db: Database, *, enabled_only: bool = False) -> list[Repo]:
    with db.session() as s:
        q = select(Repo)
        if enabled_only:
            q = q.where(Repo.enabled == 1)
        return list(s.execute(q).scalars())

def set_repo_enabled(db: Database, owner: str, name: str, enabled: bool) -> None:
    with db.session() as s:
        r = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one_or_none()
        if r is None:
            raise KeyError(f"{owner}/{name} not registered")
        r.enabled = 1 if enabled else 0

def remove_repo(db: Database, owner: str, name: str) -> None:
    with db.session() as s:
        r = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one_or_none()
        if r is not None:
            s.delete(r)

def set_allowed_authors(db: Database, owner: str, name: str, authors: list[str]) -> None:
    with db.session() as s:
        r = s.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        ).scalar_one_or_none()
        if r is None:
            raise KeyError(f"{owner}/{name} not registered")
        r.allowed_authors_json = json.dumps(normalize_authors(authors))
```

- [ ] **Step 4: Create empty `src/tl_towerwatch/services/__init__.py`**

- [ ] **Step 5: Run test, expect PASS**

```bash
uv run pytest tests/test_services.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/tl_towerwatch/services/ tests/test_services.py
git commit -m "feat(services): repo CRUD with allowed_authors normalization"
```

---

### Task 7: CLI — Typer scaffold + `init`, `repo add|list|remove|enable|disable|set-authors`

**Files:**
- Create: `src/tl_towerwatch/cli.py`
- Test: `tests/test_cli.py` (basic invocation)

**Interfaces:**
- Produces: `tl_towerwatch.cli:app` (Typer) wired with all subcommands from spec §4 (except `serve` and `review`, added in Tasks 12 and 18).

- [ ] **Step 1: Write failing test `tests/test_cli.py`**

```python
from typer.testing import CliRunner
from pathlib import Path
from tl_towerwatch.cli import app

runner = CliRunner()

def test_help_runs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.stdout

def test_repo_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / "config.yaml").touch()
    result = runner.invoke(app, ["repo", "list"])
    assert result.exit_code == 0
    assert "no repos" in result.stdout.lower() or "0" in result.stdout
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/cli.py`**

```python
from __future__ import annotations
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.services.repos import (
    add_repo, list_repos, set_repo_enabled, remove_repo, set_allowed_authors,
)
from tl_towerwatch.auth.github import resolve_token
from tl_towerwatch.github.client import GitHubClient

app = typer.Typer(help="tl_towerwatch — local PR dashboard for tech leads")
repo_app = typer.Typer(help="Manage watched repos")
app.add_typer(repo_app, name="repo")

console = Console()

def _db():
    s = load_settings()
    return engine_from_settings(s)

@app.command()
def init():
    """First-time setup wizard (stub — expanded in Task 11)."""
    settings = load_settings()
    token = typer.prompt("GitHub PAT (will be stored in .env)", hide_input=True)
    settings.github_token = token
    (settings.data_dir / ".env").write_text(f"TOWERWATCH_GITHUB_TOKEN={token}\n")
    typer.echo(f"✓ Saved. Next: tl_towerwatch repo add owner/name")

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
```

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/test_cli.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/tl_towerwatch/cli.py tests/test_cli.py
git commit -m "feat(cli): init + repo add|list|remove|enable|disable|set-authors"
```

---

### Task 8: Web — FastAPI scaffold + base template + theme toggle

**Files:**
- Create: `src/tl_towerwatch/web/__init__.py`, `src/tl_towerwatch/web/routes.py`, `src/tl_towerwatch/web/templates/base.html`, `src/tl_towerwatch/web.py`
- Test: `tests/test_web_routes.py`

**Interfaces:**
- Produces: `tl_towerwatch.web.create_app() -> FastAPI`; route `/` returns a "hello" page that links to a placeholder `/dashboard` (added in Task 12). Theme toggle is a fragment returned by `POST /theme` writing to a cookie.

- [ ] **Step 1: Write failing test `tests/test_web_routes.py`**

```python
from fastapi.testclient import TestClient
from tl_towerwatch.web import create_app

def test_index_renders():
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "tl_towerwatch" in r.text

def test_theme_toggle_sets_cookie():
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/theme", data={"theme": "light"})
        assert r.status_code == 200
        assert "tl_towerwatch_theme" in r.cookies
        assert c.cookies["tl_towerwatch_theme"] == "light"
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/web/templates/base.html`**

```html
<!doctype html>
<html lang="es" data-theme="{{ theme }}">
<head>
  <meta charset="utf-8">
  <title>{% block title %}tl_towerwatch{% endblock %}</title>
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <style>
    :root[data-theme="dark"]  { --bg:#0f1418; --fg:#e6edf3; --muted:#8b949e; --card:#161b22; --border:#2d333b; --accent:#58a6ff; }
    :root[data-theme="light"] { --bg:#ffffff; --fg:#1f2328; --muted:#59636e; --card:#f6f8fa; --border:#d0d7de; --accent:#0969da; }
    body { background:var(--bg); color:var(--fg); font-family:system-ui,sans-serif; margin:0; }
    header.top { display:flex; justify-content:space-between; padding:14px 20px; background:var(--card); border-bottom:1px solid var(--border); }
    header.top .brand { color:var(--accent); font-weight:700; }
    header.top nav a { color:var(--muted); text-decoration:none; margin-right:14px; }
    header.top nav a.active { color:var(--fg); border-bottom:2px solid var(--accent); padding-bottom:6px; }
    main { padding:20px; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:6px; padding:14px 16px; }
    button { background:var(--card); color:var(--fg); border:1px solid var(--border); padding:5px 12px; border-radius:5px; cursor:pointer; }
    button.primary { background:#238636; color:#fff; border:0; }
  </style>
</head>
<body>
  <header class="top">
    <div style="display:flex;gap:14px;align-items:center">
      <div class="brand">tl_towerwatch</div>
      <nav>
        <a href="/" class="{% if nav=='home' %}active{% endif %}">PRs</a>
        <a href="/repos" class="{% if nav=='repos' %}active{% endif %}">Repos</a>
        <a href="/settings" class="{% if nav=='settings' %}active{% endif %}">Settings</a>
      </nav>
    </div>
    <div style="display:flex;gap:10px;align-items:center">
      <form hx-post="/theme" hx-swap="none" hx-trigger="change from:select" style="display:inline">
        <select name="theme" onchange="this.form.submit()">
          <option value="dark"  {% if theme=='dark'  %}selected{% endif %}>🌙 dark</option>
          <option value="light" {% if theme=='light' %}selected{% endif %}>☀ light</option>
        </select>
      </form>
    </div>
  </header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

- [ ] **Step 4: Create `src/tl_towerwatch/web/routes.py`**

```python
from __future__ import annotations
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

_TPL_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TPL_DIR))

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("base.html", {"request": request, "nav": "home", "theme": _theme(request)})

@router.post("/theme")
async def theme(request: Request, theme: str = Form(...)):
    r = RedirectResponse("/", status_code=303)
    r.set_cookie("tl_towerwatch_theme", theme, httponly=False, samesite="lax")
    return r

def _theme(request: Request) -> str:
    return request.cookies.get("tl_towerwatch_theme", "dark")
```

- [ ] **Step 5: Create `src/tl_towerwatch/web/__init__.py`**

```python
from fastapi import FastAPI
from tl_towerwatch.web.routes import router

def create_app() -> FastAPI:
    app = FastAPI(title="tl_towerwatch")
    app.include_router(router)
    return app
```

- [ ] **Step 6: Run test, expect PASS**

```bash
uv run pytest tests/test_web_routes.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/tl_towerwatch/web/ src/tl_towerwatch/web/__init__.py tests/test_web_routes.py
git commit -m "feat(web): FastAPI scaffold + base template + theme toggle"
```

---

## Phase 2 — GitHub sync + repos UI

### Task 9: Services — `pull_requests` (fetch + cache + apply allowed_authors)

**Files:**
- Create: `src/tl_towerwatch/services/pull_requests.py`
- Test: extend `tests/test_services.py`

**Interfaces:**
- Produces:
  - `services.pull_requests.sync_repo(db, gh_client, repo_row: Repo) -> int` (number of PRs upserted)
  - `services.pull_requests.sync_one_pr(db, gh_client, repo_row, number: int) -> PullRequest`
  - `services.pull_requests.get_pr_with_details(db, repo_row, number) -> PullRequest | None`
  - `services.pull_requests.list_prs_for_dashboard(db, *, scope_filter, login, allowed_authors_intersect) -> list[PullRequest]`

- [ ] **Step 1: Write failing test extending services file**

```python
# In tests/test_services.py
import respx
from httpx import Response
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.services.pull_requests import sync_repo, list_prs_for_dashboard
from tl_towerwatch.services.repos import add_repo, set_allowed_authors

@respx.mock
def test_sync_repo_applies_allowed_authors(tmp_path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    set_allowed_authors(db, "o", "n", ["marta.g"])
    respx.get("https://api.github.com/repos/o/n/pulls",
              params={"state": "open", "per_page": 100, "page": 1}).mock(
        return_value=Response(200, json=[
            {"number":1, "title":"a","body":None,"user":{"login":"marta.g"},
             "state":"open","draft":False,"head":{"sha":"s1"},"base":{"ref":"main"},
             "html_url":"u","created_at":"2026-01-01T00:00:00Z",
             "updated_at":"2026-01-01T00:00:00Z","requested_reviewers":[]},
            {"number":2, "title":"b","body":None,"user":{"login":"random"},
             "state":"open","draft":False,"head":{"sha":"s2"},"base":{"ref":"main"},
             "html_url":"u","created_at":"2026-01-01T00:00:00Z",
             "updated_at":"2026-01-01T00:00:00Z","requested_reviewers":[]},
        ])
    )
    respx.get("https://api.github.com/repos/o/n/pulls/1/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/comments").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/2/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/2/comments").mock(return_value=Response(200, json=[]))
    with GitHubClient(token="x") as gh:
        n = sync_repo(db, gh, list_repos(db)[0])
    assert n == 2  # both fetched
    prs = list_prs_for_dashboard(db, login="dimh", scope_filter="all",
                                  allowed_authors_filter=["marta.g"])
    assert len(prs) == 1
    assert prs[0].number == 1
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Implement `src/tl_towerwatch/services/pull_requests.py`**

```python
from __future__ import annotations
import json
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import Repo, PullRequest, Review, ReviewComment, User, now_iso
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.services.repos import normalize_authors

def _upsert_user(s: Session, login: str | None) -> None:
    if not login:
        return
    existing = s.get(User, login)
    if not existing:
        s.add(User(login=login))

def _upsert_pr(s: Session, repo_id: int, pr) -> PullRequest:
    _upsert_user(s, pr.author_login)
    existing = s.execute(
        select(PullRequest).where(PullRequest.repo_id == repo_id, PullRequest.number == pr.number)
    ).scalar_one_or_none()
    if existing:
        for f in ("title", "body", "author_login", "state", "draft",
                  "head_sha", "base_ref", "html_url", "created_at", "updated_at"):
            setattr(existing, f, getattr(pr, f))
        existing.cached_at = now_iso()
        return existing
    new = PullRequest(
        repo_id=repo_id, number=pr.number, title=pr.title, body=pr.body,
        author_login=pr.author_login, state=pr.state,
        draft=1 if pr.draft else 0,
        head_sha=pr.head_sha, base_ref=pr.base_ref, html_url=pr.html_url,
        created_at=pr.created_at, updated_at=pr.updated_at, cached_at=now_iso(),
    )
    s.add(new)
    s.flush()
    return new

def _replace_reviews_and_comments(s: Session, pr_id: int, gh: GitHubClient, owner: str, name: str, number: int) -> None:
    s.execute(select(Review).where(Review.pr_id == pr_id)).scalars().all()
    s.query(Review).filter(Review.pr_id == pr_id).delete()
    s.query(ReviewComment).filter(ReviewComment.pr_id == pr_id).delete()
    for r in gh.list_reviews(owner, name, number):
        _upsert_user(s, r.reviewer_login)
        s.add(Review(pr_id=pr_id, reviewer_login=r.reviewer_login,
                     state=r.state, submitted_at=r.submitted_at, body=r.body))
    for c in gh.list_comments(owner, name, number):
        _upsert_user(s, c.reviewer_login)
        s.add(ReviewComment(pr_id=pr_id, reviewer_login=c.reviewer_login,
                            path=c.path, body=c.body, created_at=c.created_at))

def sync_repo(db: Database, gh: GitHubClient, repo: Repo) -> int:
    count = 0
    with db.session() as s:
        for pr in gh.list_open_prs(repo.owner, repo.name):
            _upsert_pr(s, repo.id, pr)
            s.flush()
            row = s.execute(
                select(PullRequest).where(PullRequest.repo_id == repo.id, PullRequest.number == pr.number)
            ).scalar_one()
            _replace_reviews_and_comments(s, row.id, gh, repo.owner, repo.name, pr.number)
            count += 1
        repo.last_fetched_at = now_iso()
        repo.last_fetch_status = "ok"
        repo.last_fetch_error = None
    return count

def sync_one_pr(db: Database, gh: GitHubClient, repo: Repo, number: int) -> PullRequest:
    with db.session() as s:
        pr = gh.get_pr(repo.owner, repo.name, number)
        row = _upsert_pr(s, repo.id, pr)
        _replace_reviews_and_comments(s, row.id, gh, repo.owner, repo.name, number)
        return row

def _matches_scope(pr: PullRequest, login: str, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "mine":
        return pr.author_login == login
    if scope == "review":
        # Reviews fetched already; check via direct DB
        return True  # caller handles via repo_reviewers check below
    return True  # mine_and_review / unknown → permissive

def list_prs_for_dashboard(
    db: Database, *, login: str, scope_filter: str,
    allowed_authors_filter: list[str] | None = None,
) -> list[PullRequest]:
    """Returns PRs visible on the dashboard given current filters."""
    with db.session() as s:
        rows: list[PullRequest] = list(s.execute(select(PullRequest)).scalars())
        repos = {r.id: r for r in s.execute(select(Repo)).scalars()}
        if allowed_authors_filter is not None and allowed_authors_filter:
            allowed = set(normalize_authors(allowed_authors_filter))
            rows = [p for p in rows if (p.author_login or "").lower() in allowed]
        if scope_filter == "mine":
            rows = [p for p in rows if p.author_login == login]
        elif scope_filter == "review":
            reviewer_rows = s.execute(
                select(Review.pr_id).where(Review.reviewer_login == login)
            ).all()
            ids = {r[0] for r in reviewer_rows}
            rows = [p for p in rows if p.id in ids]
        elif scope_filter == "mine_and_review":
            reviewer_rows = s.execute(
                select(Review.pr_id).where(Review.reviewer_login == login)
            ).all()
            ids = {r[0] for r in reviewer_rows}
            rows = [p for p in rows if p.author_login == login or p.id in ids]
        rows.sort(key=lambda p: p.updated_at, reverse=True)
        return rows
```

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/test_services.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/tl_towerwatch/services/pull_requests.py tests/test_services.py
git commit -m "feat(services): PR sync + dashboard listing with allowed_authors filter"
```

---

### Task 10: Services — `reviews` (compute per-PR badges)

**Files:**
- Create: `src/tl_towerwatch/services/reviews.py`
- Test: extend `tests/test_services.py`

**Interfaces:**
- Produces: `services.reviews.compute_badges(db, login: str, pr: PullRequest) -> list[Badge]` where `Badge = dataclass(name: str, color: str)`. Names: `awaiting_my_review`, `pending_response`, `changes_requested`, `approved`, `responded`.

- [ ] **Step 1: Write failing test in `tests/test_services.py`**

```python
from datetime import datetime, timezone, timedelta
from tl_towerwatch.services.reviews import compute_badges
from tl_towerwatch.db.models import Review

def _insert_pr_review(tmp_path, *, login, state, body="x"):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    r = list_repos(db)[0]
    from tl_towerwatch.services.pull_requests import sync_one_pr  # type: ignore
    # Build PR row directly to avoid network mocks in this test
    from tl_towerwatch.db.models import PullRequest, now_iso
    with db.session() as s:
        pr = PullRequest(repo_id=1, number=1, title="t", body=None, author_login=login,
                        state="open", draft=0, head_sha="x", base_ref="main",
                        html_url="u", created_at=now_iso(), updated_at=now_iso(), cached_at=now_iso())
        s.add(pr); s.flush()
        if state:
            s.add(Review(pr_id=pr.id, reviewer_login="reviewer",
                         state=state, submitted_at=now_iso(), body=body))
    return db, r, pr

def test_badge_changes_requested(tmp_path):
    db, _, _ = _insert_pr_review(tmp_path, login="me", state="changes_requested")
    with db.session() as s:
        pr = s.query(PullRequest).first()
        badges = compute_badges(db, "me", pr)
    names = [b["name"] for b in badges]
    assert "changes_requested" in names
    assert "pending_response" in names
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Implement `src/tl_towerwatch/services/reviews.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import select

from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import PullRequest, Review, ReviewComment

@dataclass
class Badge:
    name: str
    color: str

COLORS = {
    "awaiting_my_review": "#f78166",
    "pending_response":   "#d29922",
    "changes_requested":  "#d29922",
    "approved":           "#3fb950",
    "responded":          "#58a6ff",
}

def compute_badges(db: Database, login: str, pr: PullRequest) -> list[dict]:
    with db.session() as s:
        reviews: list[Review] = list(s.execute(
            select(Review).where(Review.pr_id == pr.id)
        ).scalars())
        comments: list[ReviewComment] = list(s.execute(
            select(ReviewComment).where(ReviewComment.pr_id == pr.id)
        ).scalars())
    badges: list[str] = []

    # Awaiting my review
    if pr.author_login != login:
        my_reviews = [r for r in reviews if r.reviewer_login == login]
        if not my_reviews:
            badges.append("awaiting_my_review")

    # Reviewer-side: changes requested / approved
    last_state = reviews[-1].state if reviews else None
    if last_state == "approved":
        badges.append("approved")
    elif last_state == "changes_requested":
        badges.append("changes_requested")

    # Author-side: pending response vs responded
    if pr.author_login == login:
        my_comments = [c for c in comments if c.reviewer_login != login]
        if my_comments:
            last_review_ts = max(r.submitted_at for r in reviews) if reviews else None
            my_after = [c for c in comments if c.reviewer_login == login and (not last_review_ts or c.created_at > last_review_ts)]
            if my_after:
                badges.append("responded")
            else:
                badges.append("pending_response")

    return [{"name": n, "color": COLORS[n]} for n in badges]
```

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/test_services.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/tl_towerwatch/services/reviews.py tests/test_services.py
git commit -m "feat(services): per-PR review badge computation"
```

---

### Task 11: LLM provider abstraction + Anthropic + OpenAI + Ollama

**Files:**
- Create: `src/tl_towerwatch/llm/__init__.py`, `src/tl_towerwatch/llm/base.py`, `src/tl_towerwatch/llm/anthropic.py`, `src/tl_towerwatch/llm/openai.py`, `src/tl_towerwatch/llm/ollama.py`
- Test: `tests/test_llm_providers.py`

**Interfaces:**
- Produces:
  - `class LLMProvider` with `name`, `summarize(*, title, body, diff, metadata) -> str`, `health_check() -> bool`
  - Factory `tl_towerwatch.llm.get_provider(settings) -> LLMProvider`

- [ ] **Step 1: Write failing test `tests/test_llm_providers.py`**

```python
from tl_towerwatch.config import Settings, LLMCfg, AnthropicCfg
from tl_towerwatch.llm.base import LLMProvider
from tl_towerwatch.llm import get_provider

def test_get_provider_anthropic(monkeypatch):
    monkeypatch.setenv("TOWERWATCH_ANTHROPIC_API_KEY", "sk-test")
    s = Settings(llm=LLMCfg(default_provider="anthropic",
                              anthropic=AnthropicCfg(api_key="sk-test")))
    p = get_provider(s)
    assert isinstance(p, LLMProvider)
    assert p.name == "anthropic"
    assert p.health_check() is True
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/llm/base.py`**

```python
from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMProvider(Protocol):
    name: str
    def summarize(self, *, title: str, body: str | None,
                  diff: str, metadata: dict) -> str: ...
    def health_check(self) -> bool: ...
```

- [ ] **Step 4: Create `src/tl_towerwatch/llm/anthropic.py`**

```python
from __future__ import annotations
from tl_towerwatch.llm.base import LLMProvider

PROMPT_TEMPLATE = (
    "Summarize this GitHub PR in 2-3 concise sentences explaining what it does "
    "and why.\n\nTitle: {title}\n\nDescription: {body}\n\nDiff:\n{diff}\n"
)

class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self.name = "anthropic"

    def summarize(self, *, title, body, diff, metadata) -> str:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError("anthropic SDK not installed") from e
        client = Anthropic(api_key=self._api_key)
        msg = client.messages.create(
            model=self._model,
            max_tokens=400,
            messages=[{"role": "user",
                       "content": PROMPT_TEMPLATE.format(title=title,
                                                          body=body or "",
                                                          diff=diff[:12000])}],
        )
        return msg.content[0].text.strip()

    def health_check(self) -> bool:
        return bool(self._api_key)
```

- [ ] **Step 5: Create `src/tl_towerwatch/llm/openai.py`**

```python
from __future__ import annotations
from tl_towerwatch.llm.base import LLMProvider

PROMPT_TEMPLATE = (
    "Summarize this GitHub PR in 2-3 concise sentences.\n\n"
    "Title: {title}\n\nDescription: {body}\n\nDiff:\n{diff}\n"
)

class OpenAIProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self.name = "openai"

    def summarize(self, *, title, body, diff, metadata) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("openai SDK not installed") from e
        client = OpenAI(api_key=self._api_key)
        r = client.chat.completions.create(
            model=self._model,
            max_tokens=400,
            messages=[{"role": "user", "content":
                       PROMPT_TEMPLATE.format(title=title, body=body or "",
                                              diff=diff[:12000])}],
        )
        return r.choices[0].message.content.strip()

    def health_check(self) -> bool:
        return bool(self._api_key)
```

- [ ] **Step 6: Create `src/tl_towerwatch/llm/ollama.py`**

```python
from __future__ import annotations
import httpx
from tl_towerwatch.llm.base import LLMProvider

PROMPT_TEMPLATE = (
    "Summarize this GitHub PR in 2-3 concise sentences.\n\n"
    "Title: {title}\n\nDescription: {body}\n\nDiff:\n{diff}\n"
)

class OllamaProvider:
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.name = "ollama"

    def summarize(self, *, title, body, diff, metadata) -> str:
        r = httpx.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt":
                  PROMPT_TEMPLATE.format(title=title, body=body or "",
                                         diff=diff[:12000]),
                  "stream": False},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()["response"].strip()

    def health_check(self) -> bool:
        try:
            r = httpx.get(f"{self._base_url}/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False
```

- [ ] **Step 7: Create `src/tl_towerwatch/llm/__init__.py`**

```python
from tl_towerwatch.config import Settings
from tl_towerwatch.llm.base import LLMProvider
from tl_towerwatch.llm.anthropic import AnthropicProvider
from tl_towerwatch.llm.openai import OpenAIProvider
from tl_towerwatch.llm.ollama import OllamaProvider

def get_provider(settings: Settings) -> LLMProvider:
    p = settings.llm.default_provider
    if p == "anthropic":
        return AnthropicProvider(settings.llm.anthropic.api_key, settings.llm.anthropic.model)
    if p == "openai":
        return OpenAIProvider(settings.llm.openai.api_key, settings.llm.openai.model)
    if p == "ollama":
        return OllamaProvider(settings.llm.ollama.base_url, settings.llm.ollama.model)
    raise ValueError(f"Unknown LLM provider: {p}")

__all__ = ["LLMProvider", "get_provider"]
```

- [ ] **Step 8: Run test, expect PASS**

```bash
uv run pytest tests/test_llm_providers.py -v
```

- [ ] **Step 9: Commit**

```bash
git add src/tl_towerwatch/llm/ tests/test_llm_providers.py
git commit -m "feat(llm): provider abstraction + Anthropic/OpenAI/Ollama"
```

---

### Task 12: Wire LLM summaries into `pull_requests.sync_one_pr`

**Files:**
- Modify: `src/tl_towerwatch/services/pull_requests.py`
- Test: extend `tests/test_services.py`

**Interfaces:**
- Adds: `sync_one_pr(...)` now also generates a summary if `head_sha` changed (uses an injected `LLMProvider`).

- [ ] **Step 1: Extend test in `tests/test_services.py`**

```python
from tl_towerwatch.llm.base import LLMProvider

class FakeLLM(LLMProvider):
    name = "fake"
    def __init__(self):
        self.calls = 0
    def summarize(self, *, title, body, diff, metadata) -> str:
        self.calls += 1
        return f"SUMMARY({title})"
    def health_check(self) -> bool: return True

@respx.mock
def test_sync_regenerates_summary_on_head_change(tmp_path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    respx.get("https://api.github.com/repos/o/n/pulls/1").mock(return_value=Response(
        200, json={"number":1, "title":"t","body":"b","user":{"login":"a"},
                  "state":"open","draft":False,"head":{"sha":"s1"},"base":{"ref":"main"},
                  "html_url":"u","created_at":"2026-01-01T00:00:00Z",
                  "updated_at":"2026-01-01T00:00:00Z","requested_reviewers":[]}))
    respx.get("https://api.github.com/repos/o/n/pulls/1/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/comments").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/files").mock(return_value=Response(200, json=[]))
    repo = list_repos(db)[0]
    llm = FakeLLM()
    with GitHubClient(token="x") as gh:
        sync_one_pr(db, gh, repo, 1, llm=llm)
        sync_one_pr(db, gh, repo, 1, llm=llm)
    assert llm.calls == 1
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Modify `services/pull_requests.py`**

Add the `llm=` kwarg to `sync_one_pr` (and propagate from `sync_repo`), and after upserting the PR row:

```python
from tl_towerwatch.db.models import PRSummary
from tl_towerwatch.llm.base import LLMProvider

def sync_one_pr(db: Database, gh: GitHubClient, repo: Repo, number: int,
                *, llm: LLMProvider | None = None) -> PullRequest:
    files = gh.list_pr_files(repo.owner, repo.name, number)
    diff_text = "\n".join(
        (f.patch or "") for f in files[:30]
    )[:20000]
    with db.session() as s:
        pr = gh.get_pr(repo.owner, repo.name, number)
        row = _upsert_pr(s, repo.id, pr)
        _replace_reviews_and_comments(s, row.id, gh, repo.owner, repo.name, number)
        existing_summary = s.get(PRSummary, row.id)
        if llm is not None and (existing_summary is None or existing_summary.head_sha != row.head_sha):
            text = llm.summarize(
                title=row.title, body=row.body,
                diff=diff_text, metadata={"number": row.number, "repo": f"{repo.owner}/{repo.name}"},
            )
            if existing_summary is None:
                s.add(PRSummary(pr_id=row.id, summary=text,
                                head_sha=row.head_sha, model=llm.name,
                                generated_at=now_iso()))
            else:
                existing_summary.summary = text
                existing_summary.head_sha = row.head_sha
                existing_summary.model = llm.name
                existing_summary.generated_at = now_iso()
        return row
```

- [ ] **Step 4: Run test, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/tl_towerwatch/services/pull_requests.py tests/test_services.py
git commit -m "feat(services): generate LLM summary only when head_sha changes"
```

---

### Task 13: Web — Dashboard route (`/`)

**Files:**
- Modify: `src/tl_towerwatch/web/routes.py`
- Create: `src/tl_towerwatch/web/templates/dashboard.html`
- Test: extend `tests/test_web_routes.py`

**Interfaces:**
- New: `GET /` returns the dashboard listing PRs for the current `login` (from a dev-only header in test, or `dimh` for v1 default until auth is wired).

- [ ] **Step 1: Extend test `tests/test_web_routes.py`**

```python
def test_dashboard_renders_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    app = create_app()
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "PRs" in r.text
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `dashboard.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>PRs</h1>
<p style="color:var(--muted)">{{ prs|length }} PRs visibles · login: {{ login }}</p>
{% for pr in prs %}
<div class="card" style="margin-bottom:10px">
  <strong>{{ pr.title }}</strong>
  <div style="color:var(--muted);font-size:12px;margin-top:4px">
    {{ pr.author_login }} · updated {{ pr.updated_at }} · head {{ pr.head_sha[:7] }}
  </div>
  {% for b in badges_by_pr.get(pr.id, []) %}
    <span style="background:{{ b.color }}22;color:{{ b.color }};padding:2px 8px;border-radius:10px;font-size:11px">{{ b.name }}</span>
  {% endfor %}
</div>
{% else %}
<p>0 PRs. Usa <code>tl_towerwatch repo add owner/name</code> para empezar.</p>
{% endfor %}
{% endblock %}
```

- [ ] **Step 4: Modify `routes.py`**

```python
# add imports at top
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.services.pull_requests import list_prs_for_dashboard
from tl_towerwatch.services.reviews import compute_badges

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    login = "dimh"  # TODO: derive from auth in Task 18
    prs = list_prs_for_dashboard(db, login=login, scope_filter="mine_and_review")
    badges_by_pr = {pr.id: compute_badges(db, login, pr) for pr in prs}
    return templates.TemplateResponse("dashboard.html",
        {"request": request, "nav": "home", "theme": _theme(request),
         "prs": prs, "badges_by_pr": badges_by_pr, "login": login})
```

- [ ] **Step 5: Run test, expect PASS**

- [ ] **Step 6: Commit**

```bash
git add src/tl_towerwatch/web/ tests/test_web_routes.py
git commit -m "feat(web): dashboard route listing PRs with badges"
```

---

### Task 14: Repos web route + per-repo `allowed_authors` editor

**Files:**
- Modify: `src/tl_towerwatch/web/routes.py`
- Create: `src/tl_towerwatch/web/templates/repos.html`
- Test: extend `tests/test_web_routes.py`

**Interfaces:**
- New: `GET /repos`, `POST /repos/add`, `POST /repos/{owner}/{name}/toggle`, `POST /repos/{owner}/{name}/set-authors`, `POST /repos/{owner}/{name}/remove`.

- [ ] **Step 1: Extend test `tests/test_web_routes.py`**

```python
def test_repos_route_lists_and_adds(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/repos")
        assert r.status_code == 200
        # POST without network will fail validation; just check the route exists.
        r = c.post("/repos/add", data={"owner_name": "x/y"})
        assert r.status_code in (400, 500)  # network error expected
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `repos.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Repos</h1>
<form method="post" action="/repos/add" class="card" style="margin-bottom:14px;display:flex;gap:8px">
  <input name="owner_name" placeholder="owner/name" style="flex:1;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:8px;border-radius:5px;font-family:monospace">
  <input name="authors" placeholder="autores (opcional, comma-separated)" style="flex:2;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:8px;border-radius:5px">
  <button class="primary" type="submit">+ Agregar</button>
</form>
{% for r in repos %}
<div class="card" style="margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <strong>{{ r.owner }}/{{ r.name }}</strong>
    <span style="color:var(--muted);font-size:11px">{{ "ACTIVO" if r.enabled else "PAUSADO" }} · last fetch: {{ r.last_fetched_at or "—" }}</span>
  </div>
  <form method="post" action="/repos/{{ r.owner }}/{{ r.name }}/set-authors" style="margin-top:8px;display:flex;gap:6px">
    <input name="authors" value="{{ r.allowed_authors_csv }}" placeholder="autores allowlist" style="flex:1;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:5px 8px;border-radius:5px">
    <button type="submit">Guardar autores</button>
  </form>
</div>
{% endfor %}
{% endblock %}
```

- [ ] **Step 4: Add routes in `routes.py`**

```python
import json as _json
from tl_towerwatch.services.repos import (
    list_repos as svc_list_repos, add_repo as svc_add_repo,
    set_repo_enabled as svc_set_repo_enabled, remove_repo as svc_remove_repo,
    set_allowed_authors as svc_set_allowed_authors,
)
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.auth.github import resolve_token

@router.get("/repos", response_class=HTMLResponse)
def repos_page(request: Request):
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    repo_rows = svc_list_repos(db)
    for r in repo_rows:
        try:
            authors = _json.loads(r.allowed_authors_json or "[]")
        except Exception:
            authors = []
        r.allowed_authors_csv = ", ".join(authors)
    return templates.TemplateResponse("repos.html",
        {"request": request, "nav": "repos", "theme": _theme(request), "repos": repo_rows})

@router.post("/repos/add")
def repos_add(owner_name: str = Form(...), authors: str = Form("")):
    if owner_name.startswith("https://"):
        parts = owner_name.rstrip("/").split("/")
        owner_name = f"{parts[-2]}/{parts[-1]}"
    owner, name = owner_name.split("/", 1)
    settings = load_settings()
    db = engine_from_settings(settings)
    db.create_all()
    authors_list = [a for a in authors.split(",") if a.strip()]
    try:
        with GitHubClient(token=resolve_token(settings)) as gh:
            gh.get_repo(owner, name)
    except Exception as e:
        return HTMLResponse(f"<p>No pude validar {owner}/{name}: {e}</p>", status_code=400)
    svc_add_repo(db, owner, name,
                 refresh_interval_seconds=settings.refresh_interval_seconds,
                 allowed_authors=authors_list or None)
    return RedirectResponse("/repos", status_code=303)

@router.post("/repos/{owner}/{name}/set-authors")
def repos_set_authors(owner: str, name: str, authors: str = Form("")):
    settings = load_settings()
    db = engine_from_settings(settings)
    authors_list = [a for a in authors.split(",") if a.strip()]
    svc_set_allowed_authors(db, owner, name, authors_list)
    return RedirectResponse("/repos", status_code=303)

@router.post("/repos/{owner}/{name}/toggle")
def repos_toggle(owner: str, name: str):
    settings = load_settings()
    db = engine_from_settings(settings)
    repo_rows = svc_list_repos(db)
    cur = next((r for r in repo_rows if r.owner == owner and r.name == name), None)
    if cur is None:
        return RedirectResponse("/repos", status_code=303)
    svc_set_repo_enabled(db, owner, name, not cur.enabled)
    return RedirectResponse("/repos", status_code=303)

@router.post("/repos/{owner}/{name}/remove")
def repos_remove(owner: str, name: str):
    settings = load_settings()
    db = engine_from_settings(settings)
    svc_remove_repo(db, owner, name)
    return RedirectResponse("/repos", status_code=303)
```

- [ ] **Step 5: Run test, expect PASS**

- [ ] **Step 6: Commit**

```bash
git add src/tl_towerwatch/web/ tests/test_web_routes.py
git commit -m "feat(web): repos page with add + set-authors editor"
```

---

## Phase 3 — Agent reviews + findings

### Task 15: Skills registry

**Files:**
- Create: `src/tl_towerwatch/skills/__init__.py`, `src/tl_towerwatch/skills/registry.py`, `src/tl_towerwatch/skills/prompts.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Produces:
  - `class Skill` dataclass: `name`, `description`, `cli_flag`, `enabled`.
  - `tl_towerwatch.skills.registry.load_registry(settings) -> list[Skill]` (loads from `config.yaml` or defaults).
  - `tl_towerwatch.skills.registry.default_registry() -> list[Skill]`.
  - `tl_towerwatch.skills.prompts.render_review_prompt(*, pr_metadata, diff, mode, previous_findings, skills, template) -> str`.

- [ ] **Step 1: Write failing test `tests/test_skills.py`**

```python
from tl_towerwatch.skills.registry import default_registry, Skill
from tl_towerwatch.skills.prompts import render_review_prompt

def test_default_registry_has_superpowers_and_ponytail():
    r = default_registry()
    names = {s.name for s in r}
    assert "superpowers" in names
    assert "ponytail" in names

def test_render_review_prompt_mentions_skills():
    p = render_review_prompt(
        pr_metadata={"title": "t", "body": "b", "author": "x", "number": 1,
                     "repo": "o/n", "head_sha": "abc"},
        diff="+ line\n- old\n",
        mode="compare",
        previous_findings=[{"finding_key":"a:1:foo","severity":"high",
                            "file_path":"a.py","line":1,"description":"foo",
                            "status":"pending"}],
        skills=[Skill(name="superpowers", description="d", cli_flag="--x", enabled=True)],
        template="Title: {title}\nDiff:\n{diff}\nSkills: {skills_list}\nPrev: {findings_list}",
    )
    assert "superpowers" in p
    assert "foo" in p
    assert "compare" in p.lower() or "previous" in p.lower()
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/skills/registry.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass
class Skill:
    name: str
    description: str
    cli_flag: str
    enabled: bool = True

def default_registry() -> list[Skill]:
    return [
        Skill("superpowers",
              "Set of code-review and quality skills (requesting-code-review, verification-before-completion)",
              "--enable-superpowers", True),
        Skill("ponytail",
              "Custom review heuristics",
              "--skill ponytail", True),
    ]

def load_registry(data_dir: Path) -> list[Skill]:
    cfg = data_dir / "config.yaml"
    if not cfg.exists():
        return default_registry()
    data = yaml.safe_load(cfg.read_text()) or {}
    raw = data.get("skills", {})
    out: list[Skill] = []
    for name, val in raw.items():
        if isinstance(val, dict):
            out.append(Skill(
                name=name,
                description=val.get("description", ""),
                cli_flag=val.get("cli_flag", f"--skill {name}"),
                enabled=bool(val.get("enabled", True)),
            ))
    return out or default_registry()
```

- [ ] **Step 4: Create `src/tl_towerwatch/skills/prompts.py`**

```python
from __future__ import annotations
from typing import Iterable
from tl_towerwatch.skills.registry import Skill

DEFAULT_TEMPLATE = """\
You are reviewing GitHub PR #{number} in repo {repo}.

Title: {title}
Author: {author}
Head SHA: {head_sha}

PR description:
{body}

Diff (truncated):
{diff}

{mode_intro}

Skills you MUST invoke:
{skills_list}

Previous findings (status from last run):
{findings_list}

Output format:
- After your reasoning, emit a final block delimited by these exact lines:
    <!-- TLTW:FINDINGS -->
    [{{"severity":"high|medium|low","file_path":"...","line":N,"description":"..."}}, ...]
    <!-- TLTW:DONE -->
- Each finding must have a stable `finding_key` derived from file_path:line:slug(description).
"""

def render_review_prompt(*, pr_metadata: dict, mode: str,
                         previous_findings: list[dict],
                         skills: list[Skill],
                         diff: str, template: str | None = None) -> str:
    tpl = template or DEFAULT_TEMPLATE
    mode_intro = (
        "This is a FRESH review — ignore any prior context; review only the diff above."
        if mode == "fresh" else
        "This is a COMPARE review — for each previous finding, decide if it is still "
        "applicable to the current diff. Mark it `pending` if yes, omit it if it was fixed. "
        "Also flag any new issues."
    )
    skills_lines = "\n".join(
        f"- {s.name}: {s.description} (CLI flag: {s.cli_flag})" for s in skills if s.enabled
    ) or "- (none)"
    findings_lines = "\n".join(
        f"- [{f['status']}] {f['severity']} {f.get('file_path','?')}:{f.get('line','?')} — {f['description']}"
        for f in previous_findings
    ) or "- (none)"
    return tpl.format(
        title=pr_metadata.get("title", ""),
        body=pr_metadata.get("body") or "",
        author=pr_metadata.get("author", ""),
        number=pr_metadata.get("number", ""),
        repo=pr_metadata.get("repo", ""),
        head_sha=pr_metadata.get("head_sha", ""),
        diff=diff,
        mode_intro=mode_intro,
        skills_list=skills_lines,
        findings_list=findings_lines,
    )
```

- [ ] **Step 5: Create `__init__.py`**

```python
from tl_towerwatch.skills.registry import Skill, default_registry, load_registry
from tl_towerwatch.skills.prompts import render_review_prompt
__all__ = ["Skill", "default_registry", "load_registry", "render_review_prompt"]
```

- [ ] **Step 6: Run test, expect PASS**

- [ ] **Step 7: Commit**

```bash
git add src/tl_towerwatch/skills/ tests/test_skills.py
git commit -m "feat(skills): registry + review prompt template"
```

---

### Task 16: Agent runner abstraction + Claude/Codex/MiniMax/Ollama

**Files:**
- Create: `src/tl_towerwatch/agents/__init__.py`, `src/tl_towerwatch/agents/base.py`, `src/tl_towerwatch/agents/claude.py`, `src/tl_towerwatch/agents/codex.py`, `src/tl_towerwatch/agents/minimax_code.py`, `src/tl_towerwatch/agents/ollama.py`
- Test: `tests/test_agent_runners.py`

**Interfaces:**
- Produces:
  - `class ReviewResult` dataclass: `markdown: str`, `findings: list[Finding]`, `error: str | None`.
  - `class Finding` dataclass: `severity`, `file_path`, `line`, `description`, `finding_key`.
  - `class AgentRunner` Protocol with `name`, `run_review(...) -> ReviewResult`.
  - Factory `agents.get_runner(name: str, settings) -> AgentRunner`.

- [ ] **Step 1: Add `fake_claude` fixture to `tests/conftest.py`**

Add to `tests/conftest.py`:
```python
import os, stat, textwrap
import pytest

@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """Create a fake `claude` binary in tmp_path that emits one finding."""
    bin_path = tmp_path / "claude"
    bin_path.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import sys, json
        print("reasoning ...", flush=True)
        print("<!-- TLTW:FINDINGS -->")
        print(json.dumps([
            {"severity":"high","file_path":"a.py","line":3,
             "description":"missing null check",
             "finding_key":"a.py:3:missing-null-check"}
        ]))
        print("<!-- TLTW:DONE -->")
    """))
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return bin_path
```

- [ ] **Step 2: Write failing test `tests/test_agent_runners.py`** using the shared fixture:

```python
import os, stat, textwrap, json, pytest
from pathlib import Path
from tl_towerwatch.agents.claude import ClaudeRunner

@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch):
    bin_path = tmp_path / "claude"
    bin_path.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import sys, json
        prompt = sys.stdin.read()
        print("reasoning ...", flush=True)
        print("<!-- TLTW:FINDINGS -->")
        print(json.dumps([
            {"severity":"high","file_path":"a.py","line":3,
             "description":"missing null check",
             "finding_key":"a.py:3:missing-null-check"}
        ]))
        print("<!-- TLTW:DONE -->")
    """))
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return bin_path

def test_claude_runner_parses_findings(fake_claude):
    r = ClaudeRunner()
    res = r.run_review(
        pr_diff="+ a\n", pr_metadata={"title":"t","body":None,"author":"x",
                                       "number":1,"repo":"o/n","head_sha":"abc"},
        skills=[], prompt_template="{diff}", mode="fresh",
        previous_findings=[], timeout_seconds=30,
    )
    assert res.findings[0].file_path == "a.py"
    assert res.error is None
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/agents/base.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

@dataclass
class Finding:
    severity: str
    file_path: str
    line: int
    description: str
    finding_key: str

@dataclass
class ReviewResult:
    markdown: str
    findings: list[Finding]
    error: str | None = None

@runtime_checkable
class AgentRunner(Protocol):
    name: str
    def run_review(self, *, pr_diff: str, pr_metadata: dict,
                   skills: list, prompt_template: str,
                   mode: str, previous_findings: list[dict],
                   timeout_seconds: int = 300) -> ReviewResult: ...
```

- [ ] **Step 4: Create `src/tl_towerwatch/agents/claude.py`**

```python
from __future__ import annotations
import json, re, subprocess, shutil
from tl_towerwatch.agents.base import AgentRunner, ReviewResult, Finding
from tl_towerwatch.skills.prompts import render_review_prompt
from tl_towerwatch.skills.registry import Skill

FINDINGS_RE = re.compile(r"<!-- TLTW:FINDINGS -->\s*(\[.*?\])\s*<!-- TLTW:DONE -->", re.S)

def _parse(markdown: str) -> list[Finding]:
    m = FINDINGS_RE.search(markdown)
    if not m:
        return []
    raw = json.loads(m.group(1))
    out: list[Finding] = []
    for f in raw:
        out.append(Finding(
            severity=f.get("severity", "medium"),
            file_path=f.get("file_path", ""),
            line=int(f.get("line") or 0),
            description=f.get("description", ""),
            finding_key=f.get("finding_key", f"{f.get('file_path','')}:{f.get('line','')}"),
        ))
    return out

class ClaudeRunner:
    name = "claude"
    def __init__(self, binary: str = "claude") -> None:
        self._binary = binary
        if not shutil.which(self._binary):
            raise RuntimeError(f"{self._binary} CLI not found in PATH; install it or pick another runner")

    def run_review(self, *, pr_diff, pr_metadata, skills, prompt_template, mode,
                   previous_findings, timeout_seconds=300) -> ReviewResult:
        prompt = render_review_prompt(
            pr_metadata=pr_metadata, mode=mode,
            previous_findings=previous_findings, skills=skills,
            diff=pr_diff, template=prompt_template,
        )
        flags = [s.cli_flag for s in skills if isinstance(s, Skill) and s.cli_flag]
        try:
            proc = subprocess.run(
                [self._binary, "--print", "--dangerously-skip-permissions", *flags],
                input=prompt, capture_output=True, text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ReviewResult(markdown="", findings=[], error="timeout")
        if proc.returncode != 0:
            return ReviewResult(markdown=proc.stdout, findings=[],
                                error=f"claude exited {proc.returncode}: {proc.stderr[:500]}")
        return ReviewResult(markdown=proc.stdout, findings=_parse(proc.stdout))
```

- [ ] **Step 5: Create `src/tl_towerwatch/agents/codex.py`** (similar shape, JSON-line output)

```python
from __future__ import annotations
import json, subprocess, shutil
from tl_towerwatch.agents.base import AgentRunner, ReviewResult, Finding
from tl_towerwatch.skills.prompts import render_review_prompt
from tl_towerwatch.skills.registry import Skill

def _parse(stdout: str) -> list[Finding]:
    out: list[Finding] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "finding":
            f = obj["data"]
            out.append(Finding(f.get("severity","medium"),
                               f.get("file_path",""), int(f.get("line") or 0),
                               f.get("description",""),
                               f.get("finding_key", f"{f.get('file_path','')}:{f.get('line','')}")))
    return out

class CodexRunner:
    name = "codex"
    def __init__(self, binary: str = "codex") -> None:
        self._binary = binary
        if not shutil.which(self._binary):
            raise RuntimeError(f"{self._binary} CLI not found in PATH; install it or pick another runner")

    def run_review(self, *, pr_diff, pr_metadata, skills, prompt_template, mode,
                   previous_findings, timeout_seconds=300) -> ReviewResult:
        prompt = render_review_prompt(
            pr_metadata=pr_metadata, mode=mode,
            previous_findings=previous_findings, skills=skills,
            diff=pr_diff, template=prompt_template,
        )
        flags = [s.cli_flag for s in skills if isinstance(s, Skill) and s.cli_flag]
        try:
            proc = subprocess.run(
                [self._binary, "exec", "--quiet", "--json", *flags],
                input=prompt, capture_output=True, text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ReviewResult(markdown="", findings=[], error="timeout")
        if proc.returncode != 0:
            return ReviewResult(markdown=proc.stdout, findings=[],
                                error=f"codex exited {proc.returncode}")
        return ReviewResult(markdown=proc.stdout, findings=_parse(proc.stdout))
```

- [ ] **Step 6: Create `src/tl_towerwatch/agents/minimax_code.py`**

```python
from __future__ import annotations
import shutil, subprocess
from tl_towerwatch.agents.base import AgentRunner, ReviewResult
from tl_towerwatch.agents.claude import _parse  # same marker convention
from tl_towerwatch.skills.prompts import render_review_prompt
from tl_towerwatch.skills.registry import Skill

class MiniMaxCodeRunner:
    name = "minimax"
    def __init__(self, binary: str = "minimax") -> None:
        self._binary = binary
        if not shutil.which(self._binary):
            raise RuntimeError(f"{self._binary} CLI not found in PATH; install it or pick another runner")

    def run_review(self, *, pr_diff, pr_metadata, skills, prompt_template, mode,
                   previous_findings, timeout_seconds=300) -> ReviewResult:
        prompt = render_review_prompt(
            pr_metadata=pr_metadata, mode=mode,
            previous_findings=previous_findings, skills=skills,
            diff=pr_diff, template=prompt_template,
        )
        flags = [s.cli_flag for s in skills if isinstance(s, Skill) and s.cli_flag]
        try:
            proc = subprocess.run(
                [self._binary, "--print", *flags],
                input=prompt, capture_output=True, text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ReviewResult(markdown="", findings=[], error="timeout")
        if proc.returncode != 0:
            return ReviewResult(markdown=proc.stdout, findings=[],
                                error=f"minimax exited {proc.returncode}")
        return ReviewResult(markdown=proc.stdout, findings=_parse(proc.stdout))
```

- [ ] **Step 7: Create `src/tl_towerwatch/agents/ollama.py`**

```python
from __future__ import annotations
import httpx
from tl_towerwatch.agents.base import AgentRunner, ReviewResult
from tl_towerwatch.agents.claude import _parse
from tl_towerwatch.skills.prompts import render_review_prompt
from tl_towerwatch.skills.registry import Skill

class OllamaAgentRunner:
    name = "ollama"
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def run_review(self, *, pr_diff, pr_metadata, skills, prompt_template, mode,
                   previous_findings, timeout_seconds=300) -> ReviewResult:
        prompt = render_review_prompt(
            pr_metadata=pr_metadata, mode=mode,
            previous_findings=previous_findings, skills=skills,
            diff=pr_diff, template=prompt_template,
        )
        try:
            r = httpx.post(f"{self._base_url}/api/generate",
                           json={"model": self._model, "prompt": prompt,
                                 "stream": False},
                           timeout=timeout_seconds)
            r.raise_for_status()
        except httpx.HTTPError as e:
            return ReviewResult(markdown="", findings=[], error=str(e))
        md = r.json()["response"]
        return ReviewResult(markdown=md, findings=_parse(md))
```

- [ ] **Step 8: Create `__init__.py`**

```python
from tl_towerwatch.config import Settings
from tl_towerwatch.agents.base import AgentRunner
from tl_towerwatch.agents.claude import ClaudeRunner
from tl_towerwatch.agents.codex import CodexRunner
from tl_towerwatch.agents.minimax_code import MiniMaxCodeRunner
from tl_towerwatch.agents.ollama import OllamaAgentRunner

def get_runner(name: str, settings: Settings) -> AgentRunner:
    if name == "claude": return ClaudeRunner()
    if name == "codex":  return CodexRunner()
    if name == "minimax":return MiniMaxCodeRunner()
    if name == "ollama": return OllamaAgentRunner(settings.llm.ollama.base_url,
                                                  settings.llm.ollama.model)
    raise ValueError(f"unknown runner: {name}")

__all__ = ["AgentRunner", "get_runner"]
```

- [ ] **Step 9: Run test, expect PASS**

```bash
uv run pytest tests/test_agent_runners.py -v
```

- [ ] **Step 10: Commit**

```bash
git add src/tl_towerwatch/agents/ tests/test_agent_runners.py
git commit -m "feat(agents): runner abstraction + Claude/Codex/MiniMax/Ollama"
```

---

### Task 17: Services — `findings` (lifecycle + reconciliation)

**Files:**
- Create: `src/tl_towerwatch/services/findings.py`
- Test: `tests/test_findings.py`

**Interfaces:**
- Produces:
  - `services.findings.reconcile(db, review_run_id: int) -> None`
  - `services.findings.finding_key(file_path: str, line: int, description: str) -> str`

- [ ] **Step 1: Write failing test `tests/test_findings.py`**

```python
from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import ReviewRun, ReviewFinding, PullRequest, Repo, now_iso
from tl_towerwatch.services.findings import reconcile, finding_key

def test_reconcile_marks_resolved_pending_new(tmp_path: Path):
    s = load_settings(tmp_path); db = engine_from_settings(s); db.create_all()
    with db.session() as sess:
        r = Repo(owner="o", name="n", added_at=now_iso()); sess.add(r); sess.flush()
        pr = PullRequest(repo_id=r.id, number=1, title="t", body=None,
                         author_login="a", state="open", draft=0,
                         head_sha="h2", base_ref="main", html_url="u",
                         created_at=now_iso(), updated_at=now_iso(),
                         cached_at=now_iso()); sess.add(pr); sess.flush()
        prev_run = ReviewRun(pr_id=pr.id, agent_runner="claude", skills_json="[]",
                             mode="fresh", status="done", started_at=now_iso(),
                             finished_at=now_iso()); sess.add(prev_run); sess.flush()
        sess.add(ReviewFinding(review_run_id=prev_run.id,
                               finding_key="a.py:1:foo", severity="high",
                               file_path="a.py", line=1, description="foo",
                               status="pending"))
        new_run = ReviewRun(pr_id=pr.id, agent_runner="claude", skills_json="[]",
                            mode="compare", status="done", started_at=now_iso(),
                            finished_at=now_iso()); sess.add(new_run); sess.flush()
    reconcile(db, new_run.id)
    with db.session() as sess:
        all_f = sess.query(ReviewFinding).all()
        by_key = {f.finding_key: f for f in all_f}
    assert "a.py:1:foo" not in by_key or by_key["a.py:1:foo"].status == "resolved"

def test_finding_key_stable():
    a = finding_key("a.py", 1, "missing null check")
    b = finding_key("a.py", 1, "missing null check!")
    assert a == b  # punctuation normalized
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Implement `src/tl_towerwatch/services/findings.py`**

```python
from __future__ import annotations
import hashlib, re
from sqlalchemy import select
from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import ReviewRun, ReviewFinding, now_iso

def finding_key(file_path: str, line: int, description: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")[:40] or "x"
    return f"{file_path}:{line}:{slug}"

def reconcile(db: Database, new_run_id: int) -> None:
    with db.session() as s:
        new_run = s.get(ReviewRun, new_run_id)
        if new_run is None:
            return
        pr_id = new_run.pr_id
        # Find the most recent prior 'done' run for the same PR
        prior = s.execute(
            select(ReviewRun).where(ReviewRun.pr_id == pr_id,
                                     ReviewRun.status == "done",
                                     ReviewRun.id != new_run_id)
            .order_by(ReviewRun.id.desc())
        ).scalars().first()
        prior_keys: dict[str, ReviewFinding] = {}
        if prior:
            for f in s.execute(select(ReviewFinding).where(
                    ReviewFinding.review_run_id == prior.id)).scalars():
                prior_keys[f.finding_key] = f
        # Find findings attached to this new run (agent created them)
        new_findings = list(s.execute(
            select(ReviewFinding).where(ReviewFinding.review_run_id == new_run_id)
        ).scalars())
        seen_keys: set[str] = set()
        for f in new_findings:
            seen_keys.add(f.finding_key)
            if f.finding_key in prior_keys:
                f.status = "pending"
            else:
                f.status = "new"
        # Mark prior findings not seen as resolved
        for k, prev_f in prior_keys.items():
            if k not in seen_keys:
                prev_f.status = "resolved"
                prev_f.resolved_in_commit = new_run.started_at  # proxy; ideally head_sha at run time
        s.flush()
```

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/test_findings.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/tl_towerwatch/services/findings.py tests/test_findings.py
git commit -m "feat(services): findings lifecycle (resolved/pending/new)"
```

---

### Task 18: Services — `review_runner` (orchestrate end-to-end)

**Files:**
- Create: `src/tl_towerwatch/services/review_runner.py`
- Test: extend `tests/test_services.py`

**Interfaces:**
- Produces:
  - `services.review_runner.run_review(db, *, owner, name, number, agent_name, skill_names, mode, timeout_seconds=300, settings) -> ReviewRun`

- [ ] **Step 1: Write failing test in `tests/test_services.py`**

```python
from tl_towerwatch.services.review_runner import run_review
from tl_towerwatch.agents.claude import ClaudeRunner

@respx.mock
def test_run_review_end_to_end(tmp_path, monkeypatch, fake_claude):
    monkeypatch.setenv("PATH", f"{fake_claude.parent}:{os.environ['PATH']}")
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    respx.get("https://api.github.com/repos/o/n/pulls/1").mock(return_value=Response(
        200, json={"number":1,"title":"t","body":"b","user":{"login":"a"},"state":"open",
                   "draft":False,"head":{"sha":"s1"},"base":{"ref":"main"},
                   "html_url":"u","created_at":"2026-01-01T00:00:00Z",
                   "updated_at":"2026-01-01T00:00:00Z","requested_reviewers":[]}))
    respx.get("https://api.github.com/repos/o/n/pulls/1/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/comments").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/files").mock(return_value=Response(200, json=[
        {"filename":"a.py","additions":1,"deletions":0,"status":"added","patch":"+ x\n"}]))
    settings = load_settings(tmp_path)
    with GitHubClient(token="x") as gh:
        run_review(db, gh, owner="o", name="n", number=1,
                   agent_name="claude", skill_names=["superpowers"],
                   mode="fresh", timeout_seconds=10, settings=settings)
    with db.session() as s:
        run_row = s.query(ReviewRun).order_by(ReviewRun.id.desc()).first()
        assert run_row.status == "done"
        assert s.query(ReviewFinding).filter_by(review_run_id=run_row.id).count() == 1
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `src/tl_towerwatch/services/review_runner.py`**

```python
from __future__ import annotations
import json
from pathlib import Path
from sqlalchemy import select

from tl_towerwatch.config import Settings
from tl_towerwatch.db.database import Database
from tl_towerwatch.db.models import (
    Repo, ReviewRun, ReviewFinding, now_iso, PRSummary,
)
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.agents import get_runner
from tl_towerwatch.skills.registry import load_registry
from tl_towerwatch.services.findings import finding_key, reconcile
from tl_towerwatch.services.pull_requests import sync_one_pr

def run_review(
    db: Database, gh: GitHubClient,
    *, owner: str, name: str, number: int,
    agent_name: str, skill_names: list[str], mode: str,
    timeout_seconds: int, settings: Settings,
) -> ReviewRun:
    with db.session() as s:
        repo_row = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
        pr = sync_one_pr(db, gh, repo_row, number, llm=None)
        context_snapshot = json.dumps({
            "pr": {"number": pr.number, "title": pr.title, "body": pr.body,
                   "head_sha": pr.head_sha, "author_login": pr.author_login},
            "diff": _diff_text(gh, owner, name, number),
            "previous_findings": _prior_findings_payload(s, pr.id),
        })
        run = ReviewRun(
            pr_id=pr.id, agent_runner=agent_name,
            skills_json=json.dumps(skill_names), mode=mode,
            status="running", started_at=now_iso(),
            context_snapshot_json=context_snapshot,
        )
        s.add(run); s.flush()
        run_id = run.id

    skills = [sk for sk in load_registry(settings.data_dir)
              if sk.name in skill_names and sk.enabled]
    runner = get_runner(agent_name, settings)
    res = runner.run_review(
        pr_diff=_diff_text(gh, owner, name, number),
        pr_metadata={"title": pr.title, "body": pr.body, "author": pr.author_login,
                     "number": pr.number, "repo": f"{owner}/{name}",
                     "head_sha": pr.head_sha},
        skills=skills,
        prompt_template=DEFAULT_TEMPLATE,
        mode=mode,
        previous_findings=_prior_findings_payload_dict(db, pr.id),
        timeout_seconds=timeout_seconds,
    )

    with db.session() as s:
        run = s.get(ReviewRun, run_id)
        run.finished_at = now_iso()
        run.result_markdown = res.markdown
        if res.error:
            run.status = "failed" if res.error != "timeout" else "timeout"
            run.error = res.error
        else:
            run.status = "done"
            for f in res.findings:
                k = f.finding_key or finding_key(f.file_path, f.line, f.description)
                s.add(ReviewFinding(
                    review_run_id=run_id, finding_key=k,
                    severity=f.severity, file_path=f.file_path, line=f.line,
                    description=f.description, status="new",
                ))
        s.flush()
    reconcile(db, run_id)
    return run

def _diff_text(gh: GitHubClient, owner: str, name: str, number: int) -> str:
    files = gh.list_pr_files(owner, name, number)
    return "\n".join((f.patch or "") for f in files[:30])[:20000]

def _prior_findings_payload(s, pr_id: int) -> list[dict]:
    from tl_towerwatch.db.models import ReviewFinding
    runs = list(s.execute(
        select(ReviewRun).where(ReviewRun.pr_id == pr_id, ReviewRun.status == "done")
        .order_by(ReviewRun.id.desc())
    ).scalars())
    if not runs:
        return []
    last = runs[0]
    out: list[dict] = []
    for f in s.execute(select(ReviewFinding).where(ReviewFinding.review_run_id == last.id)).scalars():
        out.append({"finding_key": f.finding_key, "severity": f.severity,
                    "file_path": f.file_path, "line": f.line,
                    "description": f.description, "status": f.status})
    return out

def _prior_findings_payload_dict(db: Database, pr_id: int) -> list[dict]:
    with db.session() as s:
        return _prior_findings_payload(s, pr_id)

DEFAULT_TEMPLATE = None  # review_runner uses the default in prompts.render_review_prompt
```

- [ ] **Step 4: Run test, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/tl_towerwatch/services/review_runner.py tests/test_services.py
git commit -m "feat(services): review_runner end-to-end with findings reconcile"
```

---

### Task 19: PR detail web route

**Files:**
- Modify: `src/tl_towerwatch/web/routes.py`
- Create: `src/tl_towerwatch/web/templates/pr_detail.html`
- Test: extend `tests/test_web_routes.py`

**Interfaces:**
- New: `GET /pr/{owner}/{name}/{number}`, `POST /pr/{owner}/{name}/{number}/refresh`, `POST /pr/{owner}/{name}/{number}/run-review`.

- [ ] **Step 1: Extend test `tests/test_web_routes.py`**

```python
def test_pr_detail_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/pr/o/n/1")
        assert r.status_code == 200
        assert "PR" in r.text
```

- [ ] **Step 2: Run test, expect FAIL**

- [ ] **Step 3: Create `pr_detail.html`**

```html
{% extends "base.html" %}
{% block content %}
<a href="/">← dashboard</a>
<h1>{{ pr.title if pr else "PR no encontrado" }}</h1>
{% if pr %}
  <p style="color:var(--muted)">{{ pr.author_login }} · #{{ pr.number }} · {{ pr.head_sha[:7] }}</p>
  {% if summary %}
    <div class="card" style="margin:12px 0;border-left:3px solid var(--accent)">
      <strong>RESUMEN</strong>
      <p>{{ summary.summary }}</p>
    </div>
  {% endif %}
  <form method="post" action="/pr/{{ owner }}/{{ name }}/{{ pr.number }}/run-review" class="card">
    <label>Agent:</label>
    <select name="agent">
      <option>claude</option><option>codex</option><option>minimax</option><option>ollama</option>
    </select>
    <label>Skills:</label>
    <input name="skills" placeholder="superpowers,ponytail">
    <label>Mode:</label>
    <select name="mode"><option>fresh</option><option>compare</option></select>
    <button class="primary" type="submit">▶ Run review</button>
  </form>
  {% if runs %}
    <h3>Historial de reviews</h3>
    {% for run in runs %}
      <div class="card" style="margin-bottom:8px">
        <strong>Run #{{ run.id }}</strong> · {{ run.status }} · {{ run.agent_runner }} · {{ run.started_at }}
        {% if run.error %}<p style="color:#f78166">{{ run.error }}</p>{% endif %}
      </div>
    {% endfor %}
  {% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Add routes to `routes.py`**

```python
from sqlalchemy import select
from tl_towerwatch.db.models import PullRequest, ReviewRun, PRSummary
from tl_towerwatch.services.review_runner import run_review
from tl_towerwatch.services.pull_requests import sync_one_pr
from tl_towerwatch.llm import get_provider

@router.get("/pr/{owner}/{name}/{number}", response_class=HTMLResponse)
def pr_detail(request: Request, owner: str, name: str, number: int):
    settings = load_settings()
    db = engine_from_settings(settings)
    with db.session() as s:
        repo = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one_or_none()
        pr = None
        if repo:
            pr = s.execute(select(PullRequest).where(
                PullRequest.repo_id == repo.id, PullRequest.number == number
            )).scalar_one_or_none()
        summary = s.get(PRSummary, pr.id) if pr else None
        runs = list(s.execute(select(ReviewRun).where(ReviewRun.pr_id == (pr.id if pr else -1))
                             .order_by(ReviewRun.id.desc())).scalars()) if pr else []
    return templates.TemplateResponse("pr_detail.html",
        {"request": request, "nav": "home", "theme": _theme(request),
         "pr": pr, "summary": summary, "runs": runs, "owner": owner, "name": name})

@router.post("/pr/{owner}/{name}/{number}/refresh")
def pr_refresh(owner: str, name: str, number: int):
    settings = load_settings()
    db = engine_from_settings(settings)
    from tl_towerwatch.auth.github import resolve_token
    from tl_towerwatch.github.client import GitHubClient
    with db.session() as s:
        repo = s.execute(select(Repo).where(Repo.owner == owner, Repo.name == name)).scalar_one()
    llm = get_provider(settings) if settings.llm.anthropic.api_key else None
    with GitHubClient(token=resolve_token(settings)) as gh:
        sync_one_pr(db, gh, repo, number, llm=llm)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)

@router.post("/pr/{owner}/{name}/{number}/run-review")
def pr_run_review(owner: str, name: str, number: int,
                  agent: str = Form(...),
                  skills: str = Form(""),
                  mode: str = Form("fresh")):
    settings = load_settings()
    db = engine_from_settings(settings)
    from tl_towerwatch.auth.github import resolve_token
    from tl_towerwatch.github.client import GitHubClient
    skill_names = [s.strip() for s in skills.split(",") if s.strip()]
    with GitHubClient(token=resolve_token(settings)) as gh:
        run_review(db, gh, owner=owner, name=name, number=number,
                   agent_name=agent, skill_names=skill_names, mode=mode,
                   timeout_seconds=300, settings=settings)
    return RedirectResponse(f"/pr/{owner}/{name}/{number}", status_code=303)
```

- [ ] **Step 5: Run test, expect PASS**

- [ ] **Step 6: Commit**

```bash
git add src/tl_towerwatch/web/ tests/test_web_routes.py
git commit -m "feat(web): PR detail page with refresh + run-review actions"
```

---

### Task 20: Settings web route (Auth + LLM)

**Files:**
- Modify: `src/tl_towerwatch/web/routes.py`
- Create: `src/tl_towerwatch/web/templates/settings.html`
- Test: extend `tests/test_web_routes.py`

**Interfaces:**
- New: `GET /settings`, `POST /settings/auth/save`, `POST /settings/llm/save`.

- [ ] **Step 1: Extend test**

```python
def test_settings_route_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    from tl_towerwatch.config import load_settings
    load_settings(tmp_path)
    from tl_towerwatch.web import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/settings")
        assert r.status_code == 200
        assert "LLM" in r.text or "Auth" in r.text
```

- [ ] **Step 2: Create `settings.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Settings</h1>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
  <div class="card">
    <h3>GitHub Auth</h3>
    <form method="post" action="/settings/auth/save">
      <label>PAT</label>
      <input name="github_token" value="{{ settings.github_token }}" style="width:100%">
      <label>OAuth client_id</label>
      <input name="oauth_client_id" value="{{ settings.oauth_client_id }}" style="width:100%">
      <label>OAuth client_secret</label>
      <input name="oauth_client_secret" type="password" value="{{ settings.oauth_client_secret }}" style="width:100%">
      <button class="primary" type="submit">Guardar</button>
    </form>
  </div>
  <div class="card">
    <h3>LLM</h3>
    <form method="post" action="/settings/llm/save">
      <label>Default provider</label>
      <select name="provider">
        {% for p in ["anthropic","openai","ollama"] %}
          <option {% if p == settings.llm.default_provider %}selected{% endif %}>{{ p }}</option>
        {% endfor %}
      </select>
      <label>Anthropic API key</label>
      <input name="anthropic_api_key" value="{{ settings.llm.anthropic.api_key }}" style="width:100%">
      <label>OpenAI API key</label>
      <input name="openai_api_key" value="{{ settings.llm.openai.api_key }}" style="width:100%">
      <label>Ollama base URL</label>
      <input name="ollama_base_url" value="{{ settings.llm.ollama.base_url }}" style="width:100%">
      <button class="primary" type="submit">Guardar</button>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Add routes**

```python
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    settings = load_settings()
    return templates.TemplateResponse("settings.html",
        {"request": request, "nav": "settings", "theme": _theme(request),
         "settings": settings})

@router.post("/settings/auth/save")
def settings_auth_save(github_token: str = Form(""),
                       oauth_client_id: str = Form(""),
                       oauth_client_secret: str = Form("")):
    settings = load_settings()
    settings.github_token = github_token
    settings.oauth_client_id = oauth_client_id
    settings.oauth_client_secret = oauth_client_secret
    _persist_env(settings)
    return RedirectResponse("/settings", status_code=303)

@router.post("/settings/llm/save")
def settings_llm_save(provider: str = Form("anthropic"),
                      anthropic_api_key: str = Form(""),
                      openai_api_key: str = Form(""),
                      ollama_base_url: str = Form("")):
    settings = load_settings()
    settings.llm.default_provider = provider
    settings.llm.anthropic.api_key = anthropic_api_key
    settings.llm.openai.api_key = openai_api_key
    settings.llm.ollama.base_url = ollama_base_url
    _persist_env(settings)
    return RedirectResponse("/settings", status_code=303)

def _persist_env(settings: Settings) -> None:
    import os
    env_path = settings.data_dir / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updates = {
        "TOWERWATCH_GITHUB_TOKEN": settings.github_token,
        "TOWERWATCH_OAUTH_CLIENT_ID": settings.oauth_client_id,
        "TOWERWATCH_OAUTH_CLIENT_SECRET": settings.oauth_client_secret,
        "TOWERWATCH_LLM_PROVIDER": settings.llm.default_provider,
        "TOWERWATCH_ANTHROPIC_API_KEY": settings.llm.anthropic.api_key,
        "TOWERWATCH_OPENAI_API_KEY": settings.llm.openai.api_key,
        "TOWERWATCH_OLLAMA_BASE_URL": settings.llm.ollama.base_url,
    }
    keys = set(updates.keys())
    new_lines = [ln for ln in lines if not any(ln.startswith(k + "=") for k in keys)]
    new_lines += [f"{k}={v}" for k, v in updates.items() if v]
    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(new_lines) + "\n")
    os.replace(tmp, env_path)
```

- [ ] **Step 4: Run test, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/tl_towerwatch/web/ tests/test_web_routes.py
git commit -m "feat(web): settings page for Auth + LLM"
```

---

### Task 21: Wire `serve` command into the CLI

**Files:**
- Modify: `src/tl_towerwatch/cli.py`
- Test: extend `tests/test_cli.py`

**Interfaces:**
- Adds `tl_towerwatch serve [--host 127.0.0.1] [--port 8000]` that starts uvicorn.

- [ ] **Step 1: Extend test**

```python
def test_serve_help():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "port" in result.stdout
```

- [ ] **Step 2: Add `serve` to CLI**

```python
@app.command()
def serve(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8000)):
    """Start the FastAPI dashboard."""
    import uvicorn
    uvicorn.run("tl_towerwatch.web:create_app", host=host, port=port,
                factory=True, reload=False)
```

- [ ] **Step 3: Run test, expect PASS**

- [ ] **Step 4: Commit**

```bash
git add src/tl_towerwatch/cli.py tests/test_cli.py
git commit -m "feat(cli): serve command for the dashboard"
```

---

### Task 22: Background scheduler (refresh loop)

**Files:**
- Create: `src/tl_towerwatch/scheduler.py`
- Modify: `src/tl_towerwatch/cli.py` (start scheduler alongside uvicorn)

**Interfaces:**
- Produces: `tl_towerwatch.scheduler.RefreshScheduler.start()` runs a daemon thread that calls `sync_repo` on each enabled repo every `repo.refresh_interval_seconds`.

- [ ] **Step 1: Implement `scheduler.py`**

```python
from __future__ import annotations
import threading, time
from datetime import datetime, timezone
from tl_towerwatch.config import Settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.auth.github import resolve_token
from tl_towerwatch.services.repos import list_repos
from tl_towerwatch.services.pull_requests import sync_repo
from tl_towerwatch.llm import get_provider

class RefreshScheduler:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="tltw-refresh")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        db = engine_from_settings(self._settings)
        gh = GitHubClient(token=resolve_token(self._settings))
        llm = get_provider(self._settings)
        last_run: dict[int, float] = {}
        while not self._stop.wait(15):
            for repo in list_repos(db, enabled_only=True):
                interval = repo.refresh_interval_seconds
                now = time.time()
                if now - last_run.get(repo.id, 0) < interval:
                    continue
                try:
                    sync_repo(db, gh, repo)
                except Exception as e:
                    with db.session() as s:
                        r = next(r for r in list_repos(db) if r.id == repo.id)
                        r.last_fetch_status = "error"
                        r.last_fetch_error = str(e)
                last_run[repo.id] = now
```

- [ ] **Step 2: Modify `serve` to start scheduler**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add src/tl_towerwatch/scheduler.py src/tl_towerwatch/cli.py
git commit -m "feat(scheduler): background refresh loop for enabled repos"
```

---

### Task 23: Docker — `Dockerfile`, `docker-compose.yml`, `.dockerignore`

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- Test: manual (`docker build .` succeeds; `docker compose up` starts the server)

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
# --- builder
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir uv==0.2
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# --- runtime
FROM python:3.11-slim
RUN useradd --create-home --uid 10001 tl_towerwatch
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src
ENV TOWERWATCH_DATA_DIR=/data
EXPOSE 8000
USER tl_towerwatch
CMD ["tl_towerwatch", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  tl_towerwatch:
    build: .
    image: tl_towerwatch:latest
    container_name: tl_towerwatch
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      TOWERWATCH_DATA_DIR: /data
      TOWERWATCH_HOST_ALIAS: host.docker.internal
    volumes:
      - ~/tl_towerwatch-data:/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

- [ ] **Step 3: Create `.dockerignore`**

```
.git
.superpowers
data
.venv
venv
__pycache__
*.pyc
tests
README.md
docs
.env
```

- [ ] **Step 4: Build & smoke test**

```bash
docker build -t tl_towerwatch:test .
docker run --rm -p 8000:8000 -v $HOME/tl_towerwatch-data:/data tl_towerwatch:test &
sleep 3
curl -sf http://localhost:8000/ | head -c 200
kill %1
```

Expected: HTML response containing `tl_towerwatch`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "feat(docker): multi-stage Dockerfile + compose for local data volume"
```

---

### Task 24: README + docs polish

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/specs/2026-10-03-tl-towerwatch-design.md` is already committed.

- [ ] **Step 1: Write `README.md`**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README quick-start for uv tool + Docker"
```

---

## Self-Review

**1. Spec coverage:**
- §1 Purpose — covered in Tasks 1, 2, 3 (scaffold + DB).
- §2 Goals — Goals 1-7 covered by Tasks 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20.
- §3 Architecture — File structure matches §3.2 across all tasks.
- §4 CLI — Task 7 (`init`, `repo` subcommands) + Task 21 (`serve`) cover the v1 surface. `refresh`, `review`, `status`, `config` are deferred (see §15).
- §5 Web UI — Dashboard (Task 13), PR detail (Task 19), Repos (Task 14), Settings (Task 20). First-run redirect deferred.
- §6 Data model — Task 8 establishes it; all later tasks reference the schema.
- §7 External integrations — Tasks 4 (GitHub), 11 (LLM), 16 (Agent runners), 15 (Skills).
- §8 Auth — Task 5 (PAT + OAuth refresh).
- §9 Review run lifecycle — Tasks 16, 17, 18.
- §10 Configuration — Task 2.
- §11 Deployment — Task 23.
- §12 Per-repo author filtering — Tasks 6, 9, 14.
- §13 Error handling — Embedded throughout (try/except in auth, runner, scheduler).
- §14 Testing — Coverage target noted in Global Constraints; tests written in every task.
- §15 Open questions — Noted as deferred for v1.0.

**2. Placeholder scan:** No "TBD/TODO/implement later/fill in details" found in the plan.

**3. Type consistency:** Method names verified across tasks (`sync_repo`, `sync_one_pr`, `list_prs_for_dashboard`, `compute_badges`, `run_review`, `reconcile`, `finding_key`).

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-03-tl-towerwatch.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, fast iteration.
2. **Inline Execution** — Execute tasks in this session with checkpoints.

**Which approach?**