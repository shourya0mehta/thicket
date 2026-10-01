"""Service wiring shared by the API and the CLI.

``Container(settings)`` builds everything without side effects;
``startup()`` creates directories and tables, fails analyses interrupted by
a previous process, starts model loading, the worker pool, the janitor and
the nightly scheduler; ``shutdown()`` stops them.
"""

from __future__ import annotations

import logging

from thicket.config import Settings
from thicket.models.registry import ModelRegistry, build_registry
from thicket.persistence.db import Database
from thicket.persistence.platform_repositories import PlatformRepository
from thicket.persistence.repositories import Repository
from thicket.services.alerts import AlertEngine
from thicket.services.analysis import AnalysisService
from thicket.services.audio_io import ffmpeg_available
from thicket.services.auth import AuthService
from thicket.services.ingest import IngestService
from thicket.services.janitor import Janitor
from thicket.services.nightly import NightlyScheduler
from thicket.services.notify import NotificationService
from thicket.services.platform import PlatformService
from thicket.services.previews import PreviewService
from thicket.services.recorder_health import RecorderHealthService
from thicket.services.reports import ReportService
from thicket.services.rollups import RollupService
from thicket.services.storage import Storage

log = logging.getLogger(__name__)


class Container:
    def __init__(self, settings: Settings, registry: ModelRegistry | None = None) -> None:
        self.settings = settings
        self.storage = Storage(settings.data_dir)
        assert settings.database_url is not None
        self.db = Database(settings.database_url)
        self.repo = Repository(self.db)
        self.platform = PlatformRepository(self.db)
        self.registry = registry or build_registry(settings)
        self.analysis = AnalysisService(settings, self.storage, self.repo, self.registry)
        self.previews = PreviewService(settings, self.storage)
        self.janitor = Janitor(
            settings, self.storage, self.previews, self.repo, self.analysis.active_ids
        )
        self.auth = AuthService(settings, self.platform)
        self.rollups = RollupService(self.repo, self.platform)
        self.notify = NotificationService(settings, self.platform, self.storage)
        self.alerts = AlertEngine(settings, self.platform, self.notify)
        self.health = RecorderHealthService(settings, self.platform, self.alerts)
        self.ingest = IngestService(settings, self.storage, self.repo, self.platform, self.analysis)
        self.reports = ReportService(
            settings, self.storage, self.repo, self.platform, self.analysis
        )
        self.services = PlatformService(settings, self.repo, self.platform, self.analysis)
        self.nightly = NightlyScheduler(
            settings,
            rollups=self.rollups,
            alerts=self.alerts,
            notify=self.notify,
            janitor=self.janitor,
            platform=self.platform,
            auth=self.auth,
        )
        self.ffmpeg = False
        self.ingest.alerts = self.alerts
        self.analysis.completion_hooks.append(self._after_analysis)
        self.analysis.failure_hooks.append(self.ingest.on_analysis_finished)
        self.analysis.review_hooks.append(self._after_review)

    # -- hooks ------------------------------------------------------------
    def _after_analysis(self, analysis_id: str) -> None:
        self.ingest.on_analysis_finished(analysis_id)
        self.rollups.on_analysis_completed(analysis_id)
        if self.settings.alerts_enabled:
            self.alerts.evaluate_analysis(analysis_id)

    def _after_review(self, analysis_id: str) -> None:
        self.rollups.on_analysis_completed(analysis_id)

    # -- lifecycle --------------------------------------------------------
    def startup(self, background: bool = True) -> None:
        self.storage.ensure()
        migrated_from = self.db.create_all()
        if migrated_from is not None and migrated_from < 3:
            # Analyses from the single-user build get their rollups once, right away.
            summary = self.rollups.rebuild()
            log.info("database upgraded", extra={"from_version": migrated_from, **summary})
        interrupted = self.repo.mark_interrupted()
        if interrupted:
            log.warning("marked interrupted analyses as failed", extra={"count": interrupted})
        self.platform.mark_interrupted_jobs()
        self.platform.mark_interrupted_reports()
        self.ffmpeg = ffmpeg_available()
        if not self.ffmpeg:
            log.warning("ffmpeg not found; MP3/M4A support depends on libsndfile")
        self.registry.start_loading(background=background)
        self.analysis.start()
        if background:
            self.janitor.start()
            self.nightly.start()
        log.info(
            "thicket started",
            extra={
                "version": self.settings.app_version,
                "environment": self.settings.environment,
                "models": self.registry.keys(),
                "worker_concurrency": self.settings.worker_concurrency,
                "auth_mode": self.settings.auth_mode,
            },
        )

    def shutdown(self) -> None:
        self.nightly.stop()
        self.janitor.stop()
        # Running analyses see their cancel flag at the next stage; a report
        # render finishes. Bounded so a stuck stage cannot hold the process.
        self.analysis.shutdown(wait=True, timeout=30.0)
        self.db.dispose()
