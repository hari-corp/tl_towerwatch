from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import ReviewRun, ReviewFinding, PullRequest, Repo, User, now_iso
from tl_towerwatch.services.findings import reconcile, finding_key

NEW_HEAD_SHA = "new_head_sha_here"

def _bootstrap(tmp_path: Path):
    """Create DB, repo, user, PR with NEW_HEAD_SHA, and one prior run."""
    s = load_settings(tmp_path); db = engine_from_settings(s); db.create_all()
    with db.session() as sess:
        r = Repo(owner="o", name="n", added_at=now_iso()); sess.add(r); sess.flush()
        if sess.get(User, "a") is None:
            sess.add(User(login="a")); sess.flush()
        pr = PullRequest(repo_id=r.id, number=1, title="t", body=None,
                         author_login="a", state="open", draft=0,
                         head_sha=NEW_HEAD_SHA, base_ref="main", html_url="u",
                         created_at=now_iso(), updated_at=now_iso(),
                         cached_at=now_iso()); sess.add(pr); sess.flush()
        prev_run = ReviewRun(pr_id=pr.id, agent_runner="claude", skills_json="[]",
                             mode="fresh", status="done", started_at=now_iso(),
                             finished_at=now_iso()); sess.add(prev_run); sess.flush()
    return db, prev_run.id

def test_reconcile_marks_resolved_pending_new(tmp_path: Path):
    db, prev_run_id = _bootstrap(tmp_path)
    with db.session() as sess:
        sess.add(ReviewFinding(review_run_id=prev_run_id,
                               finding_key="a.py:1:foo", severity="high",
                               file_path="a.py", line=1, description="foo",
                               status="pending"))
        new_run = ReviewRun(pr_id=1, agent_runner="claude", skills_json="[]",
                            mode="compare", status="done", started_at=now_iso(),
                            finished_at=now_iso()); sess.add(new_run); sess.flush()
        new_run_id = new_run.id
    reconcile(db, new_run_id)
    with db.session() as sess:
        all_f = sess.query(ReviewFinding).all()
        by_key = {f.finding_key: f for f in all_f}
    # Prior finding is still present (not deleted) and is resolved with the
    # new PR's head_sha (not the run's started_at timestamp).
    assert "a.py:1:foo" in by_key
    resolved = by_key["a.py:1:foo"]
    assert resolved.status == "resolved"
    assert resolved.resolved_in_commit == NEW_HEAD_SHA

def test_reconcile_marks_pending_when_finding_present_in_both_runs(tmp_path: Path):
    db, prev_run_id = _bootstrap(tmp_path)
    SHARED_KEY = "a.py:1:foo"
    with db.session() as sess:
        sess.add(ReviewFinding(review_run_id=prev_run_id,
                               finding_key=SHARED_KEY, severity="high",
                               file_path="a.py", line=1, description="foo",
                               status="pending"))
        new_run = ReviewRun(pr_id=1, agent_runner="claude", skills_json="[]",
                            mode="compare", status="done", started_at=now_iso(),
                            finished_at=now_iso()); sess.add(new_run); sess.flush()
        sess.add(ReviewFinding(review_run_id=new_run.id,
                               finding_key=SHARED_KEY, severity="high",
                               file_path="a.py", line=1, description="foo",
                               status="new"))
        new_run_id = new_run.id
    reconcile(db, new_run_id)
    with db.session() as sess:
        all_f = sess.query(ReviewFinding).filter_by(review_run_id=new_run_id).all()
        by_key = {f.finding_key: f for f in all_f}
    assert SHARED_KEY in by_key
    assert by_key[SHARED_KEY].status == "pending"

def test_reconcile_marks_new_when_finding_only_in_new_run(tmp_path: Path):
    db, _prev_run_id = _bootstrap(tmp_path)
    NEW_KEY = "b.py:2:bar"
    with db.session() as sess:
        new_run = ReviewRun(pr_id=1, agent_runner="claude", skills_json="[]",
                            mode="compare", status="done", started_at=now_iso(),
                            finished_at=now_iso()); sess.add(new_run); sess.flush()
        sess.add(ReviewFinding(review_run_id=new_run.id,
                               finding_key=NEW_KEY, severity="medium",
                               file_path="b.py", line=2, description="bar",
                               status="new"))
        new_run_id = new_run.id
    reconcile(db, new_run_id)
    with db.session() as sess:
        all_f = sess.query(ReviewFinding).filter_by(review_run_id=new_run_id).all()
        by_key = {f.finding_key: f for f in all_f}
    assert NEW_KEY in by_key
    new_f = by_key[NEW_KEY]
    assert new_f.status == "new"
    assert new_f.resolved_in_commit is None

def test_reconcile_resolved_in_commit_uses_head_sha(tmp_path: Path):
    """Pin FIX #1: resolved findings record the new PR's head_sha, not the
    run's started_at timestamp."""
    db, prev_run_id = _bootstrap(tmp_path)
    with db.session() as sess:
        sess.add(ReviewFinding(review_run_id=prev_run_id,
                               finding_key="a.py:1:foo", severity="high",
                               file_path="a.py", line=1, description="foo",
                               status="pending"))
        new_run = ReviewRun(pr_id=1, agent_runner="claude", skills_json="[]",
                            mode="compare", status="done",
                            started_at="not-a-real-sha", finished_at=now_iso())
        sess.add(new_run); sess.flush()
        new_run_id = new_run.id
    reconcile(db, new_run_id)
    with db.session() as sess:
        resolved = sess.query(ReviewFinding).filter_by(
            review_run_id=prev_run_id,
            finding_key="a.py:1:foo",
        ).one()
    assert resolved.status == "resolved"
    assert resolved.resolved_in_commit == NEW_HEAD_SHA
    assert resolved.resolved_in_commit != "not-a-real-sha"

def test_finding_key_stable():
    a = finding_key("a.py", 1, "missing null check")
    b = finding_key("a.py", 1, "missing null check!")
    assert a == b  # punctuation normalized