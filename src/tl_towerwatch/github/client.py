from __future__ import annotations

from typing import Any

import httpx

from tl_towerwatch.github.models import (
    CommentData,
    CommitData,
    FileData,
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