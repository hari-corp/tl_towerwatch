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
