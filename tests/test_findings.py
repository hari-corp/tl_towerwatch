from pathlib import Path
from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings
from tl_towerwatch.db.models import ReviewRun, ReviewFinding, PullRequest, Repo, User, now_iso
from tl_towerwatch.services.findings import reconcile, finding_key

def test_reconcile_marks_resolved_pending_new(tmp_path: Path):
    s = load_settings(tmp_path); db = engine_from_settings(s); db.create_all()
    with db.session() as sess:
        r = Repo(owner="o", name="n", added_at=now_iso()); sess.add(r); sess.flush()
        if sess.get(User, "a") is None:
            sess.add(User(login="a")); sess.flush()
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