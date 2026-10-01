"""Nightly jobs in one scheduler: rollup rebuild, gap detection and expected
species, email digests (daily every night, weekly on Mondays), session
revocation pruning and the janitor's cleanup.

The scheduler sleeps until the next ``NIGHTLY_JOBS_HOUR_UTC`` on a daemon
thread. ``run_once`` does one full pass and is what tests and
``python -m thicket.cli nightly`` call; ``clock`` and ``sleeper`` are
injectable so a test can drive the loop without waiting.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from thicket.config import Settings

log = logging.getLogger(__name__)


class NightlyScheduler:
    def __init__(
        self,
        settings: Settings,
        *,
        rollups,  # type: ignore[no-untyped-def]
        alerts,  # type: ignore[no-untyped-def]
        notify,  # type: ignore[no-untyped-def]
        janitor,  # type: ignore[no-untyped-def]
        platform,  # type: ignore[no-untyped-def]
        auth=None,  # type: ignore[no-untyped-def]
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.rollups = rollups
        self.alerts = alerts
        self.notify = notify
        self.janitor = janitor
        self.platform = platform
        self.auth = auth
        self.clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run: dict | None = None

    # -- scheduling -----------------------------------------------------------
    def next_run(self, now: datetime | None = None) -> datetime:
        now = now or self.clock()
        target = now.replace(
            hour=self.settings.nightly_jobs_hour_utc, minute=0, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return target

    def run_once(self, now: datetime | None = None) -> dict:
        now = now or self.clock()
        summary: dict = {"started_at": now.isoformat()}
        steps: list[tuple[str, Callable[[], object]]] = [
            ("rollups", lambda: self.rollups.rebuild()),
            ("gaps_and_species", self._alerts_pass),
            ("digest_daily", lambda: self.notify.send_digests("daily")),
            (
                "digest_weekly",
                lambda: self.notify.send_digests("weekly") if now.weekday() == 0 else 0,
            ),
            ("sessions_pruned", lambda: self.platform.prune_revoked_sessions(now)),
            ("janitor", lambda: self.janitor.run_once()),
        ]
        for name, step in steps:
            try:
                summary[name] = step()
            except Exception:  # noqa: BLE001 - one failing step must not stop the others
                log.exception("nightly step failed", extra={"step": name})
                summary[name] = "failed"
        summary["finished_at"] = self.clock().isoformat()
        self.last_run = summary
        log.info("nightly jobs finished", extra={k: str(v)[:200] for k, v in summary.items()})
        return summary

    def _alerts_pass(self) -> int:
        if not self.settings.alerts_enabled:
            return 0
        n = 0
        for org_id in self.platform.all_org_ids():
            n += len(self.alerts.nightly(org_id))
        return n

    # -- thread ---------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            wait = max(1.0, (self.next_run() - self.clock()).total_seconds())
            if self._stop.wait(wait):
                return
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("nightly run failed")

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="thicket-nightly", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
