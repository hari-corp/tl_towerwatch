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
        # Anything inbound (reviews or comments) from non-authors is something
        # the author may need to respond to.
        inbound_reviews = [r for r in reviews if r.reviewer_login != login]
        inbound_comments = [c for c in comments if c.reviewer_login != login]
        if inbound_reviews or inbound_comments:
            last_review_ts = max(r.submitted_at for r in reviews) if reviews else None
            my_after = [
                c for c in comments
                if c.reviewer_login == login
                and (not last_review_ts or c.created_at > last_review_ts)
            ]
            if my_after:
                badges.append("responded")
            else:
                badges.append("pending_response")

    return [{"name": n, "color": COLORS[n]} for n in badges]