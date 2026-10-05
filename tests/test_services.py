import json
import os
from pathlib import Path

import pytest
import respx
from httpx import Response

from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import ReviewFinding, ReviewRun
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.services.pull_requests import (
    get_pr_with_details,
    list_prs_for_dashboard,
    save_manual_description,
    save_manual_notes,
    sync_one_pr,
    sync_repo,
)
from tl_towerwatch.services.repos import (
    add_allowed_author,
    add_repo,
    clear_allowed_authors,
    list_repos,
    normalize_authors,
    remove_allowed_author,
    set_allowed_authors,
)
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

def test_repo_add_remove_clear_author(tmp_path):
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    add_allowed_author(db, "o", "n", "marta.g")
    assert json.loads(list_repos(db)[0].allowed_authors_json) == ["marta.g"]
    add_allowed_author(db, "o", "n", "luis.f")
    assert json.loads(list_repos(db)[0].allowed_authors_json) == ["luis.f", "marta.g"]
    remove_allowed_author(db, "o", "n", "luis.f")
    assert json.loads(list_repos(db)[0].allowed_authors_json) == ["marta.g"]
    clear_allowed_authors(db, "o", "n")
    assert json.loads(list_repos(db)[0].allowed_authors_json) == []


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
    respx.get("https://api.github.com/repos/o/n/issues/1/comments").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/2/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/2/comments").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/issues/2/comments").mock(return_value=Response(200, json=[]))
    with GitHubClient(token="x") as gh:
        n = sync_repo(db, gh, list_repos(db)[0])
    assert n == 2  # both fetched
    prs = list_prs_for_dashboard(
        db, login="dimh", scope_filter="all", allowed_authors_filter=["marta.g"]
    )
    assert len(prs) == 1
    assert prs[0].number == 1


@respx.mock
def test_sync_repo_populates_user_avatar_and_display_name(tmp_path: Path):
    """Regression: v1.1 populates User.avatar_url and User.display_name from
    the GitHub PR author payload. Confirm the row is enriched after sync.
    """
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    respx.get("https://api.github.com/repos/o/n/pulls",
              params={"state": "open", "per_page": 100, "page": 1}).mock(
        return_value=Response(200, json=[
            {"number": 1, "title": "a", "body": None,
              "user": {"login": "marta.g", "avatar_url": "https://x/m.png", "name": "Marta G"},
              "state": "open", "draft": False, "head": {"sha": "s1"}, "base": {"ref": "main"},
              "html_url": "u", "created_at": "2026-01-01T00:00:00Z",
              "updated_at": "2026-01-01T00:00:00Z", "requested_reviewers": []},
        ])
    )
    respx.get("https://api.github.com/repos/o/n/pulls/1/reviews").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/comments").mock(return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/issues/1/comments").mock(return_value=Response(200, json=[]))
    repo_row = list_repos(db)[0]
    with GitHubClient(token="x") as gh:
        sync_repo(db, gh, repo_row)
    with db.session() as s:
        from tl_towerwatch.db.models import User
        u = s.get(User, "marta.g")
        assert u is not None
        assert u.avatar_url == "https://x/m.png"
        assert u.display_name == "Marta G"


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
    respx.get("https://api.github.com/repos/o/n/issues/1/comments").mock(return_value=Response(200, json=[]))
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
            {"id": 10, "user": {"login": "luis.f"}, "path": "x.py", "body": "nit",
             "created_at": "2026-02-02T00:00:00Z"}
        ])
    )
    respx.get("https://api.github.com/repos/o/n/issues/7/comments").mock(return_value=Response(200, json=[]))
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
    respx.get("https://api.github.com/repos/o/n/issues/7/comments").mock(return_value=Response(200, json=[]))
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



@respx.mock
def test_assemble_review_prompt_truncates_huge_diff(tmp_path, monkeypatch):
    """v1.3.0: ``assemble_review_prompt`` must cap the diff block at
    ``max_lines=2000`` so a 5000-file / 5M-line PR doesn't blow the
    user's external LLM's context window. Same regression test as v1.1's
    sync_one_pr truncation — just relocated to the new code path."""
    from tl_towerwatch.config_io import save_config_yaml
    from tl_towerwatch.services.prompt_assembly import assemble_review_prompt
    cfg = tmp_path / "config.yaml"
    save_config_yaml(cfg, {"prompts": {
        "review": "{title} | {diff}",
        "post_review": "{findings}",
        "check_resolved": "{findings}",
    }})
    respx.get("https://api.github.com/repos/o/n/pulls/1").mock(return_value=Response(
        200, json={"number": 1, "title": "big pr", "body": "b",
                   "user": {"login": "a"}, "state": "open", "draft": False,
                   "head": {"sha": "s1"}, "base": {"ref": "main"},
                   "html_url": "u",
                   "created_at": "2026-01-01T00:00:00Z",
                   "updated_at": "2026-01-01T00:00:00Z",
                   "requested_reviewers": []}))
    # 5000 files × 1000 lines each.
    huge_files = [
        {"filename": f"f{i}.py", "additions": 1, "deletions": 0,
         "status": "modified", "patch": "x\n" * 1000}
        for i in range(5000)
    ]
    respx.get("https://api.github.com/repos/o/n/pulls/1/files").mock(
        return_value=Response(200, json=huge_files))
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    with GitHubClient(token="x") as gh:
        out = assemble_review_prompt(
            gh, data_dir=tmp_path, owner="o", name="n", number=1,
            slot="review", mode="fresh",
        )
    # The diff portion stays under the 2000-line cap.
    assert out.count("\n") < 2500
    assert "truncated" in out
    assert "big pr" in out


@respx.mock
def test_assemble_review_prompt_uses_user_prompts(tmp_path, monkeypatch):
    """v1.3.0 (revised): the prompt template comes from the global
    ``prompts.<slot>`` block in config.yaml. Setting ``review`` to a
    custom template must produce that template in the rendered output."""
    from tl_towerwatch.config_io import save_config_yaml
    from tl_towerwatch.services.prompt_assembly import assemble_review_prompt
    cfg = tmp_path / "config.yaml"
    save_config_yaml(cfg, {"prompts": {
        "review": "CUSTOM({title})",
        "post_review": "",
        "check_resolved": "",
    }})
    respx.get("https://api.github.com/repos/o/n/pulls/1").mock(return_value=Response(
        200, json={"number": 1, "title": "feat", "body": "",
                   "user": {"login": "a"}, "state": "open", "draft": False,
                   "head": {"sha": "s1"}, "base": {"ref": "main"},
                   "html_url": "u",
                   "created_at": "2026-01-01T00:00:00Z",
                   "updated_at": "2026-01-01T00:00:00Z",
                   "requested_reviewers": []}))
    respx.get("https://api.github.com/repos/o/n/pulls/1/files").mock(
        return_value=Response(200, json=[]))
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    with GitHubClient(token="x") as gh:
        out = assemble_review_prompt(
            gh, data_dir=tmp_path, owner="o", name="n", number=1,
            slot="review", mode="fresh",
        )
    assert "CUSTOM(feat)" in out


@respx.mock
def test_assemble_review_prompt_fills_number_and_repo(tmp_path, monkeypatch):
    """v1.3.x: ``{number}`` and ``{repo}`` are filled from the GitHub
    payload + the ``owner/name`` arguments so the user can reference
    them in the prompt template.
    """
    from tl_towerwatch.config_io import save_config_yaml
    from tl_towerwatch.services.prompt_assembly import assemble_review_prompt
    save_config_yaml(tmp_path / "config.yaml", {"prompts": {
        "review": "PR #{number} in {repo}: {title}",
        "post_review": "",
        "check_resolved": "",
    }})
    respx.get("https://api.github.com/repos/o/n/pulls/42").mock(return_value=Response(
        200, json={"number": 42, "title": "feat", "body": "",
                   "user": {"login": "a"}, "state": "open", "draft": False,
                   "head": {"sha": "s1"}, "base": {"ref": "main"},
                   "html_url": "u",
                   "created_at": "2026-01-01T00:00:00Z",
                   "updated_at": "2026-01-01T00:00:00Z",
                   "requested_reviewers": []}))
    respx.get("https://api.github.com/repos/o/n/pulls/42/files").mock(
        return_value=Response(200, json=[]))
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_path))
    with GitHubClient(token="x") as gh:
        out = assemble_review_prompt(
            gh, data_dir=tmp_path, owner="o", name="n", number=42,
            slot="review", mode="fresh",
        )
    assert "PR #42 in o/n: feat" in out


@respx.mock
def test_save_manual_description_persists(tmp_path):
    from tl_towerwatch.db.models import PullRequest
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    repo = list_repos(db)[0]
    respx.get("https://api.github.com/repos/o/n/pulls/1").mock(return_value=Response(
        200, json={"number": 1, "title": "t", "body": "b",
                   "user": {"login": "a"}, "state": "open", "draft": False,
                   "head": {"sha": "s1"}, "base": {"ref": "main"},
                   "html_url": "u",
                   "created_at": "2026-01-01T00:00:00Z",
                   "updated_at": "2026-01-01T00:00:00Z",
                   "requested_reviewers": []}))
    respx.get("https://api.github.com/repos/o/n/pulls/1/reviews").mock(
        return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/comments").mock(
        return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/issues/1/comments").mock(return_value=Response(200, json=[]))
    with GitHubClient(token="x") as gh:
        sync_one_pr(db, gh, repo, 1)
    save_manual_description(db, repo, 1, "TL;DR for reviewers")
    with db.session() as s:
        pr = s.execute(__import__("sqlalchemy").select(PullRequest).where(
            PullRequest.repo_id == repo.id, PullRequest.number == 1
        )).scalar_one()
        assert pr.manual_description == "TL;DR for reviewers"
    # Empty save clears the field.
    save_manual_description(db, repo, 1, "")
    with db.session() as s:
        pr = s.execute(__import__("sqlalchemy").select(PullRequest).where(
            PullRequest.repo_id == repo.id, PullRequest.number == 1
        )).scalar_one()
        assert pr.manual_description is None


@respx.mock
def test_save_manual_notes_persists(tmp_path):
    from tl_towerwatch.db.models import PullRequest
    db = _setup(tmp_path)
    add_repo(db, "o", "n")
    repo = list_repos(db)[0]
    respx.get("https://api.github.com/repos/o/n/pulls/1").mock(return_value=Response(
        200, json={"number": 1, "title": "t", "body": "b",
                   "user": {"login": "a"}, "state": "open", "draft": False,
                   "head": {"sha": "s1"}, "base": {"ref": "main"},
                   "html_url": "u",
                   "created_at": "2026-01-01T00:00:00Z",
                   "updated_at": "2026-01-01T00:00:00Z",
                   "requested_reviewers": []}))
    respx.get("https://api.github.com/repos/o/n/pulls/1/reviews").mock(
        return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/pulls/1/comments").mock(
        return_value=Response(200, json=[]))
    respx.get("https://api.github.com/repos/o/n/issues/1/comments").mock(return_value=Response(200, json=[]))
    with GitHubClient(token="x") as gh:
        sync_one_pr(db, gh, repo, 1)
    save_manual_notes(db, repo, 1, "release notes")
    with db.session() as s:
        pr = s.execute(__import__("sqlalchemy").select(PullRequest).where(
            PullRequest.repo_id == repo.id, PullRequest.number == 1
        )).scalar_one()
        assert pr.manual_notes == "release notes"
