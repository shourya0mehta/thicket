"""Periodic cleanup of temp files, expired previews and orphaned assets.

Runs every ``JANITOR_INTERVAL_SECONDS`` (10 minutes by default) in a daemon
thread. Deletes:

* ``<data>/tmp/<analysis_id>/`` directories older than ``TEMP_RETENTION_HOURS``
  that do not belong to a running job (jobs normally remove their own);
* previews past their expiry;
* spectrograms and retained audio whose analysis no longer exists, once older
  than the temp retention window.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from thicket.config import Settings
from thicket.persistence.repositories import Repository
from thicket.services.previews import PreviewService
from thicket.services.storage import Storage

log = logging.getLogger(__name__)


class Janitor:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        previews: PreviewService,
        repo: Repository,
        active_ids: Callable[[], set[str]],
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.previews = previews
        self.repo = repo
        self.active_ids = active_ids
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self, now: float | None = None) -> dict[str, int]:
        now = time.time() if now is None else now
        max_age = self.settings.temp_retention_hours * 3600.0
        active = self.active_ids()
        counts = {"temp_dirs": 0, "previews": 0, "orphan_assets": 0}
        if self.storage.tmp.is_dir():
            for d in self.storage.tmp.iterdir():
                if d.name in active:
                    continue
                try:
                    age = now - d.stat().st_mtime
                except OSError:
                    continue
                if age >= max_age:
                    if d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)
                    else:
                        d.unlink(missing_ok=True)
                    counts["temp_dirs"] += 1
        counts["previews"] = self.previews.purge_expired(datetime.fromtimestamp(now, UTC))
        for folder in (self.storage.spectrograms, self.storage.recordings):
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                aid = f.stem.split(".")[0]
                if aid in active:
                    continue
                try:
                    age = now - f.stat().st_mtime
                except OSError:
                    continue
                if age >= max_age and self.repo.get_analysis(aid) is None:
                    f.unlink(missing_ok=True)
                    counts["orphan_assets"] += 1
        if any(counts.values()):
            log.info("janitor cleanup", extra=counts)
        return counts

    def _loop(self) -> None:
        while not self._stop.wait(self.settings.janitor_interval_seconds):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - keep the janitor alive
                log.exception("janitor run failed")

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="thicket-janitor", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
