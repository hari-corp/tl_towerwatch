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