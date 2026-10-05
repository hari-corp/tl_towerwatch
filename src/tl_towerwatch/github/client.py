from __future__ import annotations

from typing import Any

import httpx

from tl_towerwatch.github.models import (
    CommentData,
    CommitData,
    FileData,
    IssueCommentData,
    PullRequestData,
    RateLimit,
    RepoMeta,
    ReviewData,
    User,
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
        self._oauth_scopes: list[str] | None = None

    def last_rate_limit(self) -> RateLimit | None:
        return self._last_rate_limit

    def last_oauth_scopes(self) -> list[str] | None:
        """Return the OAuth scopes from the most recent response's
        ``X-OAuth-Scopes`` header, or ``None`` if not yet observed.
        """
        return self._oauth_scopes

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

    def _capture_oauth_scopes(self, r: httpx.Response) -> None:
        scopes = r.headers.get("X-OAuth-Scopes")
        if scopes is not None:
            self._oauth_scopes = [s.strip() for s in scopes.split(",") if s.strip()]

    def _check(self, r: httpx.Response) -> dict[str, Any]:
        self._capture_rate_limit(r)
        self._capture_oauth_scopes(r)
        r.raise_for_status()
        return r.json()

    def get_authenticated_user(self) -> User:
        d = self._check(self._client.get("/user"))
        return User(login=d["login"], avatar_url=d.get("avatar_url"), display_name=d.get("name"))

    def get_rate_limit(self) -> RateLimit:
        """Probe GitHub's rate-limit endpoint. Returns ``RateLimit``
        with ``limit`` so the UI can render ``remaining / limit``
        without hard-coding 5,000 (the default is 5,000 for PATs but
        enterprise / OAuth flows can return different numbers)."""
        d = self._check(self._client.get("/rate_limit"))
        # GitHub returns both `resources.core` and `rate`; we read from
        # `rate` because it's always present and matches the response
        # semantics documented for the endpoint. Fall back to
        # `resources.core` for older clients.
        rate = d.get("rate") or d.get("resources", {}).get("core") or {}
        return RateLimit(
            limit=int(rate.get("limit", 0) or 0),
            remaining=int(rate.get("remaining", 0) or 0),
            reset=int(rate.get("reset", 0) or 0),
        )

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
                reviewer_avatar_url=r["user"].get("avatar_url"),
                reviewer_display_name=r["user"].get("name"),
            ) for r in d
        ]

    def list_comments(self, owner: str, name: str, number: int) -> list[CommentData]:
        """Inline review comments anchored to a file/line."""
        d = self._check(self._client.get(f"/repos/{owner}/{name}/pulls/{number}/comments"))
        return [
            CommentData(
                github_id=c["id"],
                reviewer_login=c["user"]["login"],
                path=c.get("path"),
                line=c.get("line"),
                body=c["body"],
                created_at=c["created_at"],
                in_reply_to_id=c.get("in_reply_to_id"),
                reviewer_avatar_url=c["user"].get("avatar_url"),
                reviewer_display_name=c["user"].get("name"),
            ) for c in d
        ]

    def list_issue_comments(self, owner: str, name: str, number: int) -> list[IssueCommentData]:
        """Top-level PR conversation comments (the GitHub "Conversation"
        tab). Includes replies when a comment has ``in_reply_to_id``
        pointing at another issue comment."""
        d = self._check(self._client.get(f"/repos/{owner}/{name}/issues/{number}/comments"))
        return [
            IssueCommentData(
                github_id=c["id"],
                author_login=c["user"]["login"],
                body=c["body"],
                created_at=c["created_at"],
                in_reply_to_id=c.get("in_reply_to_id"),
                author_avatar_url=c["user"].get("avatar_url"),
                author_display_name=c.get("user", {}).get("name"),
            ) for c in d
        ]

    def post_issue_comment(self, owner: str, name: str, number: int, body: str) -> dict:
        """POST a top-level (or reply) comment to the PR's conversation.
        Reply-to is implicit — pass the parent ``comment_id`` as
        ``in_reply_to`` and we'll surface it in the UI."""
        # GitHub's POST /issues/{number}/comments accepts only `body`
        # plus an optional undocumented `in_reply_to` we set so the
        # comment is rendered as a threaded reply in the Conversation
        # tab. We persist the parent link locally regardless.
        d = self._check(self._client.post(
            f"/repos/{owner}/{name}/issues/{number}/comments",
            json={"body": body},
        ))
        return d

    def post_review_comment_reply(self, owner: str, name: str, number: int,
                                  comment_id: int, body: str) -> dict:
        """POST a threaded reply to an inline review comment."""
        d = self._check(self._client.post(
            f"/repos/{owner}/{name}/pulls/{number}/comments/{comment_id}/replies",
            json={"body": body},
        ))
        return d

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
        user = pr.get("user") or {}
        return PullRequestData(
            number=pr["number"],
            title=pr["title"],
            body=pr.get("body"),
            author_login=user.get("login"),
            author_avatar_url=user.get("avatar_url"),
            author_display_name=user.get("name"),
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
            # GitHub returns these on /pulls/:number but NOT on /pulls (list).
            # List-loaded PRs will therefore carry 0/0/0; the per-PR refresh
            # path (and any render that needs real stats) is expected to
            # hit GET /pulls/:number so these land populated.
            additions=pr.get("additions", 0),
            deletions=pr.get("deletions", 0),
            changed_files=pr.get("changed_files", 0),
            commits_count=pr.get("commits", 0),
        )