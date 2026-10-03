import json
import os
from pathlib import Path

import respx
from httpx import Response

from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import ReviewFinding, ReviewRun
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.llm.base import LLMProvider
from tl_towerwatch.services.pull_requests import (
    get_pr_with_details,
    list_prs_for_dashboard,
    sync_one_pr,
    sync_repo,
)
from tl_towerwatch.services.repos import (
    add_repo,
    list_repos,
    normalize_authors,
    set_allowed_authors,
)
from tl_towerwatch.services.review_runner import run_review
from tl_towerwatch.services.reviews import compute_badges


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


@respx.mock
def test_sync_repo_applies_allowed_authors(tmp_path: Path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    set_allowed_authors(db, "o", "n", ["marta.g"])
    respx.get("https://api.github.com/repos/o/n/pulls",
              params={"state": "open", "per_page": 100, "page": 1}).mock(
        return_value=Response(200, json=[
            {"number": 1, "title": "a", "body": None, "user": {"login": "marta.g"},
             "state": "open", "draft": False, "head": {"sha": "s1"}, "base": {"ref": "main"},
             "html_url": "u", "created_at": "2026-01-01T00:00:00Z",
             "updated_at": "2026-01-01T00:00:00Z", "requested_reviewers": []},
            {"number": 2, "title": "b", "body": None, "user": {"login": "random"},
             "state": "open", "draft": False, "head": {"sha": "s2"}, "base": {"ref": "main"},
             "html_url": "u", "created_at": "2026-01-01T00:00:00Z",
             "updated_at": "2026-01-01T00:00:00Z", "requested_reviewers": []},
        ])
    )
    respx.get("https://api.github.com/repos/o/n/pulls/1/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/comments").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/2/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/2/comments").mock(return_value=Response(200, json=[]))
    with GitHubClient(token="x") as gh:
        n = sync_repo(db, gh, list_repos(db)[0])
    assert n == 2  # both fetched
    prs = list_prs_for_dashboard(
        db, login="dimh", scope_filter="all", allowed_authors_filter=["marta.g"]
    )
    assert len(prs) == 1
    assert prs[0].number == 1


@respx.mock
def test_sync_repo_persists_last_fetch_metadata(tmp_path: Path):
    """Regression: `sync_repo` must persist `last_fetched_at` / `last_fetch_status`
    / `last_fetch_error` on the Repo row even when the caller passes a detached
    instance (e.g. one returned by an earlier `list_repos(db)` call in a
    previous session).
    """
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    respx.get("https://api.github.com/repos/o/n/pulls",
              params={"state": "open", "per_page": 100, "page": 1}).mock(
        return_value=Response(200, json=[
            {"number": 1, "title": "a", "body": None, "user": {"login": "marta.g"},
             "state": "open", "draft": False, "head": {"sha": "s1"}, "base": {"ref": "main"},
             "html_url": "u", "created_at": "2026-01-01T00:00:00Z",
             "updated_at": "2026-01-01T00:00:00Z", "requested_reviewers": []},
        ])
    )
    respx.get("https://api.github.com/repos/o/n/pulls/1/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/comments").mock(return_value=Response(200, json=[]))
    repo_row = list_repos(db)[0]
    with GitHubClient(token="x") as gh:
        n = sync_repo(db, gh, repo_row)
    assert n == 1
    # Fresh session: re-read the repo and verify fetch metadata was committed.
    fresh = list_repos(db)[0]
    assert fresh.last_fetched_at is not None
    assert fresh.last_fetch_status == "ok"
    assert fresh.last_fetch_error is None


@respx.mock
def test_sync_one_pr_upserts_and_refreshes(tmp_path: Path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    respx.get("https://api.github.com/repos/o/n/pulls/7").mock(
        return_value=Response(200, json={
            "number": 7, "title": "first", "body": "hi", "user": {"login": "marta.g"},
            "state": "open", "draft": False, "head": {"sha": "s7"}, "base": {"ref": "main"},
            "html_url": "u7", "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z", "requested_reviewers": [],
        })
    )
    respx.get("https://api.github.com/repos/o/n/pulls/7/reviews").mock(
        return_value=Response(200, json=[
            {"user": {"login": "luis.f"}, "state": "APPROVED",
             "submitted_at": "2026-02-02T00:00:00Z", "body": "lgtm"}
        ])
    )
    respx.get("https://api.github.com/repos/o/n/pulls/7/comments").mock(
        return_value=Response(200, json=[
            {"user": {"login": "luis.f"}, "path": "x.py", "body": "nit",
             "created_at": "2026-02-02T00:00:00Z"}
        ])
    )
    repo_row = list_repos(db)[0]
    with GitHubClient(token="x") as gh:
        pr = sync_one_pr(db, gh, repo_row, 7)
    assert pr.number == 7
    assert pr.author_login == "marta.g"
    # Second call: refresh should update the title
    respx.get("https://api.github.com/repos/o/n/pulls/7").mock(
        return_value=Response(200, json={
            "number": 7, "title": "updated", "body": "hi", "user": {"login": "marta.g"},
            "state": "open", "draft": False, "head": {"sha": "s7b"}, "base": {"ref": "main"},
            "html_url": "u7", "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-03T00:00:00Z", "requested_reviewers": [],
        })
    )
    respx.get("https://api.github.com/repos/o/n/pulls/7/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/7/comments").mock(return_value=Response(200, json=[]))
    with GitHubClient(token="x") as gh:
        pr2 = sync_one_pr(db, gh, repo_row, 7)
    assert pr2.id == pr.id
    assert pr2.title == "updated"
    assert pr2.head_sha == "s7b"
    # get_pr_with_details returns the same row
    got = get_pr_with_details(db, repo_row, 7)
    assert got is not None
    assert got.number == 7
    assert got.title == "updated"


def test_list_prs_for_dashboard_scopes(tmp_path: Path):
    db = _setup(tmp_path)
    r = add_repo(db, "o", "n")
    # Create two PRs directly
    from tl_towerwatch.db.models import PullRequest, Review, User
    iso = lambda s: s
    with db.session() as s:
        for login in ("dimh", "alice"):
            if s.get(User, login) is None:
                s.add(User(login=login))
        s.flush()
        s.add(PullRequest(repo_id=r.id, number=1, title="mine",
                          body=None, author_login="dimh", state="open",
                          draft=0, head_sha="a", base_ref="main",
                          html_url="u", created_at=iso("2026-01-01T00:00:00Z"),
                          updated_at=iso("2026-01-02T00:00:00Z"), cached_at=iso("2026-01-02T00:00:00Z")))
        s.add(PullRequest(repo_id=r.id, number=2, title="other",
                          body=None, author_login="alice", state="open",
                          draft=0, head_sha="b", base_ref="main",
                          html_url="u", created_at=iso("2026-01-01T00:00:00Z"),
                          updated_at=iso("2026-01-03T00:00:00Z"), cached_at=iso("2026-01-03T00:00:00Z")))
        s.flush()
        mine_pr = s.execute(__import__("sqlalchemy").select(PullRequest).where(PullRequest.number == 1)).scalar_one()
        s.add(Review(pr_id=mine_pr.id, reviewer_login="dimh",
                     state="COMMENTED", submitted_at="2026-01-04T00:00:00Z", body=None))
    # scope=all
    all_prs = list_prs_for_dashboard(db, login="dimh", scope_filter="all")
    assert {p.number for p in all_prs} == {1, 2}
    # scope=mine
    mine = list_prs_for_dashboard(db, login="dimh", scope_filter="mine")
    assert {p.number for p in mine} == {1}
    # scope=review (dimh reviewed pr 1)
    review = list_prs_for_dashboard(db, login="dimh", scope_filter="review")
    assert {p.number for p in review} == {1}
    # scope=mine_and_review
    mr = list_prs_for_dashboard(db, login="dimh", scope_filter="mine_and_review")
    assert {p.number for p in mr} == {1}
    # allowed_authors_filter
    only_alice = list_prs_for_dashboard(
        db, login="dimh", scope_filter="all", allowed_authors_filter=["alice"]
    )
    assert {p.number for p in only_alice} == {2}
    # sort by updated_at desc
    sorted_prs = list_prs_for_dashboard(db, login="dimh", scope_filter="all")
    assert sorted_prs[0].number == 2  # updated 2026-01-03


def _insert_pr_review(tmp_path, *, login, state, body="x"):
    from tl_towerwatch.db.models import PullRequest, Review, User, now_iso
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    r = list_repos(db)[0]
    with db.session() as s:
        for u_login in (login, "reviewer"):
            if s.get(User, u_login) is None:
                s.add(User(login=u_login))
        s.flush()
        pr = PullRequest(
            repo_id=1, number=1, title="t", body=None, author_login=login,
            state="open", draft=0, head_sha="x", base_ref="main",
            html_url="u", created_at=now_iso(), updated_at=now_iso(),
            cached_at=now_iso(),
        )
        s.add(pr)
        s.flush()
        if state:
            s.add(Review(
                pr_id=pr.id, reviewer_login="reviewer",
                state=state, submitted_at=now_iso(), body=body,
            ))
    return db, r, pr


def test_badge_changes_requested(tmp_path):
    from tl_towerwatch.db.models import PullRequest
    db, _, _ = _insert_pr_review(tmp_path, login="me", state="changes_requested")
    with db.session() as s:
        pr = s.query(PullRequest).first()
        badges = compute_badges(db, "me", pr)
    names = [b["name"] for b in badges]
    assert "changes_requested" in names
    assert "pending_response" in names


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