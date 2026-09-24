"""Service wiring shared by the API and the CLI.

``Container(settings)`` builds everything without side effects;
``startup()`` creates directories and tables, fails analyses interrupted by
a previous process, starts model loading, the worker pool and the janitor;
``shutdown()`` stops them.
"""

from __future__ import annotations

import logging

from thicket.config import Settings
from thicket.models.registry import ModelRegistry, build_registry
from thicket.persistence.db import Database
from thicket.persistence.repositories import Repository
from thicket.services.analysis import AnalysisService
from thicket.services.audio_io import ffmpeg_available
from thicket.services.janitor import Janitor
from thicket.services.previews import PreviewService
from thicket.services.storage import Storage

log = logging.getLogger(__name__)


class Container:
    def __init__(self, settings: Settings, registry: ModelRegistry | None = None) -> None:
        self.settings = settings
        self.storage = Storage(settings.data_dir)
        assert settings.database_url is not None
        self.db = Database(settings.database_url)
        self.repo = Repository(self.db)
        self.registry = registry or build_registry(settings)
        self.analysis = AnalysisService(settings, self.storage, self.repo, self.registry)
        self.previews = PreviewService(settings, self.storage)
        self.janitor = Janitor(
            settings, self.storage, self.previews, self.repo, self.analysis.active_ids
        )
        self.ffmpeg = False

    def startup(self, background: bool = True) -> None:
        self.storage.ensure()
        self.db.create_all()
        interrupted = self.repo.mark_interrupted()
        if interrupted:
            log.warning("marked interrupted analyses as failed", extra={"count": interrupted})
        self.ffmpeg = ffmpeg_available()
        if not self.ffmpeg:
            log.warning("ffmpeg not found; MP3/M4A support depends on libsndfile")
        self.registry.start_loading(background=background)
        self.analysis.start()
        if background:
            self.janitor.start()
        log.info(
            "thicket started",
            extra={
                "version": self.settings.app_version,
                "environment": self.settings.environment,
                "models": self.registry.keys(),
                "worker_concurrency": self.settings.worker_concurrency,
            },
        )

    def shutdown(self) -> None:
        self.janitor.stop()
        self.analysis.shutdown(wait=False)
        self.db.dispose()
