"""Smoke test verifying the v1.1 performance indexes are present on every
expected table. `create_all` builds the schema from the ORM metadata, so
inspecting the resulting tables is enough to prove the indexes survived.
"""
from sqlalchemy import inspect

from tl_towerwatch.config import load_settings
from tl_towerwatch.db.database import engine_from_settings


def test_db_has_perf_indexes(tmp_path):
    s = load_settings(tmp_path)
    db = engine_from_settings(s)
    db.create_all()
    insp = inspect(db.engine)
    for tbl, expected in [
        ("pull_requests", ["idx_pr_repo"]),
        ("reviews", ["idx_reviews_pr"]),
        ("review_comments", ["idx_comments_pr"]),
        ("review_findings", ["idx_findings_run", "idx_findings_key"]),
    ]:
        idx = [i["name"] for i in insp.get_indexes(tbl)]
        for e in expected:
            assert e in idx, f"missing {e} on {tbl}"