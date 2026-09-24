"""The analysis pipeline: one domain path from upload to stored evidence.

Stages (``analysis.stage`` while running, with per-stage milliseconds in
``stage_timings_ms``)::

    queued -> normalizing -> quality -> spectrogram -> model:<key> ...
           -> consolidating -> metrics -> completed | failed

* ``normalizing``: decode to 48 kHz mono (capped at the maximum duration)
  and stream native-rate level statistics.
* ``quality``: signal QC (see :mod:`thicket.domain.quality`).
* ``spectrogram``: the canonical PNG (see :mod:`thicket.services.spectrogram`).
* ``model:<key>``: each requested adapter, each with its own
  ``model_run_id``. An adapter that declares ``embedding_source`` (the
  frog/insect head) reuses that source's embeddings when the source ran in
  the same analysis, so BirdNET runs once.
* ``consolidating``: detection ids are renumbered ``det_0..det_N`` across
  runs (unique per analysis), QC is finalized with BirdNET's "Human vocal"
  score and the optional QC head, and events are consolidated at the
  requested threshold. Events are never deduplicated across model runs.
* ``metrics``: acoustic indices; species metrics are derived on read.

Jobs run on a bounded thread pool (``WORKER_CONCURRENCY``). Each job has a
deadline (``ANALYSIS_TIMEOUT_SECONDS``) checked between stages, plus a timer
that marks the analysis failed with ``analysis_timeout`` if a stage hangs.
The per-analysis temp directory is removed in ``finally`` on success and on
failure; normalized audio is kept only when ``RETAIN_AUDIO`` is true.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

from thicket.api.schemas import (
    Analysis,
    AnalysisList,
    ErrorCode,
    EventReviewUpdate,
    QualityReport,
    QualityStatus,
    ReviewStatus,
)
from thicket.config import Settings
from thicket.domain.acoustic_indices import compute_indices
from thicket.domain.consolidation import WindowDetection, consolidate
from thicket.domain.quality import apply_qc_head, assess_quality, finalize_quality
from thicket.errors import (
    ThicketError,
    analysis_not_found,
    event_not_found,
    from_adapter_error,
    invalid_parameter,
)
from thicket.ids import is_valid_event_id, is_valid_id, model_run_id, new_id
from thicket.models.base import AdapterError, AdapterOutput, AnalysisContext
from thicket.models.registry import ModelRegistry
from thicket.persistence.db import AnalysisRow, ModelRunRow, RecordingRow
from thicket.persistence.repositories import Repository
from thicket.services import results
from thicket.services.audio_io import AudioDecodeError, AudioProbe, decode, probe, write_wav
from thicket.services.audio_stats import native_level_stats
from thicket.services.intake import StoredUpload, clean_text
from thicket.services.params import AnalysisParams
from thicket.services.spectrogram import write_png
from thicket.services.storage import Storage

log = logging.getLogger(__name__)

TARGET_SR = 48_000
MIN_SAMPLE_RATE_HZ = 16_000


class AnalysisCancelled(Exception):
    """The analysis was deleted or timed out while running."""


def decode_failed() -> ThicketError:
    return ThicketError(
        ErrorCode.audio_decode_failed,
        "This file could not be decoded as audio. It may be damaged or use an unsupported codec.",
    )


def check_probe(pr: AudioProbe, settings: Settings) -> None:
    """Reject files that cannot be analyzed, before any model runs."""
    if pr.sample_rate_hz <= 0 or pr.channels <= 0:
        raise decode_failed()
    if pr.duration_seconds > settings.max_audio_duration_seconds:
        raise audio_too_long(pr.duration_seconds, settings)
    if 0 < pr.duration_seconds < settings.min_audio_duration_seconds:
        raise audio_too_short(pr.duration_seconds, settings)
    if pr.sample_rate_hz < MIN_SAMPLE_RATE_HZ:
        raise ThicketError(
            ErrorCode.unsupported_audio,
            f"The sample rate of {pr.sample_rate_hz} Hz is too low: content above "
            f"{pr.sample_rate_hz / 2000:.1f} kHz is missing. Record at 32 kHz or more "
            f"(at least {MIN_SAMPLE_RATE_HZ} Hz is required).",
            detail={"sample_rate_hz": pr.sample_rate_hz},
        )


def audio_too_long(duration: float, settings: Settings) -> ThicketError:
    return ThicketError(
        ErrorCode.audio_too_long,
        f"The recording is {duration:.0f} s long; the limit is "
        f"{settings.max_audio_duration_seconds:.0f} s. Trim it and try again.",
        detail={
            "duration_seconds": round(duration, 3),
            "max_seconds": settings.max_audio_duration_seconds,
        },
    )


def audio_too_short(duration: float, settings: Settings) -> ThicketError:
    return ThicketError(
        ErrorCode.audio_too_short,
        f"The recording is {duration:.2f} s long; at least "
        f"{settings.min_audio_duration_seconds:.1f} s is needed.",
        detail={
            "duration_seconds": round(duration, 3),
            "min_seconds": settings.min_audio_duration_seconds,
        },
    )


DURATION_MISMATCH_SECONDS = 1.0


def duration_mismatch_warning(declared: float, decoded: float) -> str | None:
    """Warn when the container's declared duration disagrees with the decoded audio.

    Truncated files (and some VBR MP3s) declare more audio than they hold.
    Results, rates and time axes use the decoded duration.
    """
    if declared <= 0 or abs(declared - decoded) <= DURATION_MISMATCH_SECONDS:
        return None
    return (
        f"The file declares {declared:.1f} s of audio but {decoded:.1f} s could be decoded; "
        f"it may be truncated or damaged. Results cover the decoded {decoded:.1f} s."
    )


def probe_upload(path: Path) -> AudioProbe:
    try:
        return probe(path)
    except AudioDecodeError as exc:
        raise decode_failed() from exc


def format_label(upload: StoredUpload, pr: AudioProbe) -> str:
    return f"{upload.kind} ({pr.codec})" if pr.codec else upload.kind


def _jsonable(obj: object) -> object:
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


@dataclass
class Job:
    analysis_id: str
    upload: StoredUpload
    params: AnalysisParams
    probe: AudioProbe
    tmp_dir: Path
    created: float = field(default_factory=time.monotonic)
    cancel: threading.Event = field(default_factory=threading.Event)
    timings: dict[str, int] = field(default_factory=dict)
    deadline: float = float("inf")
    future: Future | None = None
    stage: str = "queued"


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        repo: Repository,
        registry: ModelRegistry,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.repo = repo
        self.registry = registry
        self._pool: ThreadPoolExecutor | None = None
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=self.settings.worker_concurrency, thread_name_prefix="thicket-worker"
            )

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel.set()
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=True)
            self._pool = None

    def active_ids(self) -> set[str]:
        with self._lock:
            return set(self._jobs)

    # -------------------------------------------------------------- create
    def create(
        self, analysis_id: str, upload: StoredUpload, params: AnalysisParams, tmp_dir: Path
    ) -> Job:
        """Probe, validate and persist a queued analysis. Raises typed errors."""
        pr = probe_upload(upload.path)
        check_probe(pr, self.settings)
        rec = RecordingRow(
            id=new_id("rec"),
            filename=upload.filename,
            content_type=upload.content_type,
            byte_size=upload.byte_size,
            checksum_sha256=upload.sha256,
            format=format_label(upload, pr),
            duration_seconds=round(pr.duration_seconds, 3),
            sample_rate_hz=pr.sample_rate_hz,
            channels=pr.channels,
            bit_depth=pr.bit_depth,
            captured_at=params.captured_at.isoformat() if params.captured_at else None,
            timezone=params.timezone,
            latitude=params.latitude,
            longitude=params.longitude,
            site_name=params.site_name,
            recorder_type=params.recorder_type,
            notes=params.notes,
        )
        row = AnalysisRow(
            id=analysis_id,
            recording_id=rec.id,
            status="queued",
            stage="queued",
            requested_models=list(params.models),
            decision_threshold=params.threshold,
            raw_threshold=self.settings.raw_threshold,
            merge_gap_seconds=self.settings.merge_gap_seconds,
            hop_seconds=self.settings.hop_seconds,
            location_filter=self.settings.location_filter,
            location_filter_threshold=self.settings.location_filter_threshold,
            warnings=[],
            software_version=self.settings.app_version,
            stage_timings={},
            has_spectrogram=False,
        )
        self.repo.create_analysis(rec, row)
        job = Job(analysis_id=analysis_id, upload=upload, params=params, probe=pr, tmp_dir=tmp_dir)
        with self._lock:
            self._jobs[analysis_id] = job
        log.info(
            "analysis queued",
            extra={
                "analysis_id": analysis_id,
                "models": params.models,
                "byte_size": upload.byte_size,
                "duration_seconds": round(pr.duration_seconds, 2),
            },
        )
        return job

    def submit(self, job: Job) -> Future:
        self.start()
        assert self._pool is not None
        try:
            job.future = self._pool.submit(self._execute, job)
        except RuntimeError as exc:
            self._finish(job)
            self.repo.fail(
                job.analysis_id, ErrorCode.internal_error.value, "The server is shutting down."
            )
            raise ThicketError(
                ErrorCode.internal_error, "The server is shutting down. Try again."
            ) from exc
        return job.future

    def run_sync(self, job: Job) -> None:
        """Run a job in the calling thread (CLI)."""
        self._execute(job)

    def wait(self, analysis_id: str, timeout: float | None = None) -> None:
        with self._lock:
            job = self._jobs.get(analysis_id)
        if job is not None and job.future is not None:
            job.future.result(timeout=timeout)

    # ------------------------------------------------------------ pipeline
    def _check(self, job: Job) -> None:
        if job.cancel.is_set():
            raise AnalysisCancelled()
        if time.monotonic() > job.deadline:
            raise self._timeout_error()

    def _timeout_error(self) -> ThicketError:
        return ThicketError(
            ErrorCode.analysis_timeout,
            f"The analysis took longer than the {self.settings.analysis_timeout_seconds:.0f} s limit "
            "and was stopped. Try a shorter recording.",
        )

    @contextmanager
    def _stage(self, job: Job, name: str) -> Iterator[None]:
        self._check(job)
        if not self.repo.set_stage(job.analysis_id, name):
            raise AnalysisCancelled()
        job.stage = name
        t0 = time.perf_counter()
        try:
            yield
        finally:
            job.timings[name] = int(round((time.perf_counter() - t0) * 1000))

    def _on_timeout(self, job: Job) -> None:
        if job.cancel.is_set():
            return
        job.cancel.set()
        err = self._timeout_error()
        if self.repo.fail(job.analysis_id, err.code.value, err.message, job.timings):
            log.warning(
                "analysis timed out",
                extra={
                    "analysis_id": job.analysis_id,
                    "stage": job.stage,
                    "stage_timings_ms": job.timings,
                },
            )

    def _ordered_models(self, keys: list[str]) -> list[str]:
        """Embedding sources first, otherwise the requested order."""
        sources = {getattr(self.registry.lookup(k), "embedding_source", None) for k in keys}
        return sorted(keys, key=lambda k: (0 if k in sources else 1, keys.index(k)))

    def _execute(self, job: Job) -> None:
        aid = job.analysis_id
        timeout = self.settings.analysis_timeout_seconds
        job.timings["queued"] = int(round((time.monotonic() - job.created) * 1000))
        job.deadline = time.monotonic() + timeout
        timer = threading.Timer(timeout, self._on_timeout, args=(job,))
        timer.daemon = True
        timer.start()
        report: QualityReport | None = None
        retained: Path | None = None
        try:
            params = job.params
            with self._stage(job, "normalizing"):
                max_s = self.settings.max_audio_duration_seconds
                mono, sr = decode(
                    job.upload.path, target_sr=TARGET_SR, mono=True, max_seconds=max_s + 1.0
                )
                duration = mono.size / float(sr)
                if duration > max_s + 0.05:
                    raise audio_too_long(duration, self.settings)
                if duration < self.settings.min_audio_duration_seconds:
                    raise audio_too_short(duration, self.settings)
                levels = native_level_stats(job.upload.path, job.probe.channels)

            with self._stage(job, "quality"):
                report = assess_quality(
                    duration_seconds=duration,
                    sample_rate_hz=job.probe.sample_rate_hz,
                    levels=levels,
                    mono=mono,
                    mono_sample_rate=sr,
                    min_duration_seconds=self.settings.min_audio_duration_seconds,
                    max_duration_seconds=self.settings.max_audio_duration_seconds,
                )
                self.repo.set_quality(aid, report.model_dump(mode="json"))

            with self._stage(job, "spectrogram"):
                path = self.storage.spectrogram_path(aid)
                write_png(mono, path)
                if job.cancel.is_set():
                    path.unlink(missing_ok=True)
                    raise AnalysisCancelled()
                self.repo.set_spectrogram(aid)

            outputs: dict[str, AdapterOutput] = {}
            contexts: dict[str, AnalysisContext] = {}
            order = self._ordered_models(params.models)
            for key in order:
                with self._stage(job, f"model:{key}"):
                    remaining = max(0.0, job.deadline - time.monotonic())
                    adapter = self.registry.require_ready(key, timeout=remaining)
                    ctx = AnalysisContext(
                        analysis_id=aid,
                        model_run_id=model_run_id(aid, key),
                        latitude=params.latitude,
                        longitude=params.longitude,
                        recording_date=params.recording_date,
                        raw_threshold=self.settings.raw_threshold,
                        hop_seconds=self.settings.hop_seconds,
                        location_filter=self.settings.location_filter,
                        location_filter_threshold=self.settings.location_filter_threshold,
                    )
                    source = getattr(adapter, "embedding_source", None)
                    shared = outputs.get(source) if source else None
                    if (
                        shared is not None
                        and shared.embeddings is not None
                        and shared.window_starts is not None
                        and hasattr(adapter, "analyze_embeddings")
                    ):
                        out = adapter.analyze_embeddings(  # type: ignore[attr-defined]
                            shared.embeddings, shared.window_starts, duration, ctx
                        )
                        out.configuration["embeddings_from_run"] = contexts[source].model_run_id  # type: ignore[index]
                    else:
                        out = adapter.analyze(mono, sr, ctx)
                    outputs[key] = out
                    contexts[key] = ctx

            with self._stage(job, "consolidating"):
                detections: list[WindowDetection] = []
                for key in order:
                    detections.extend(outputs[key].detections)
                detections = [replace(d, id=f"det_{i}") for i, d in enumerate(detections)]
                speech = [
                    float(o.extras["human_vocal_max"])
                    for o in outputs.values()
                    if "human_vocal_max" in o.extras
                ]
                report = finalize_quality(report, max(speech) if speech else None)
                embeddings = next(
                    (
                        o.embeddings
                        for o in outputs.values()
                        if o.embeddings is not None and len(o.embeddings)
                    ),
                    None,
                )
                backbone = (
                    self.registry.lookup("birdnet").model_sha256()
                    if "birdnet" in self.registry
                    else None
                )
                report = apply_qc_head(report, embeddings, backbone)
                events = consolidate(
                    detections, params.threshold, self.settings.merge_gap_seconds, aid
                )

            with self._stage(job, "metrics"):
                indices = compute_indices(mono, sr).as_dict()
                warnings = self._pipeline_warnings(params, report)
                mismatch = duration_mismatch_warning(job.probe.duration_seconds, duration)
                if mismatch:
                    warnings.append(mismatch)

            if self.settings.retain_audio:
                retained = self.storage.audio_path(aid)
                write_wav(retained, mono, sr)

            self._check(job)
            runs = [
                self._run_row(aid, pos, key, contexts[key], outputs[key])
                for pos, key in enumerate(order)
            ]
            job.timings["total"] = int(sum(v for k, v in job.timings.items() if k != "queued"))
            ok = self.repo.complete(
                aid,
                quality=report.model_dump(mode="json"),
                indices=indices,
                warnings=warnings,
                timings=job.timings,
                model_runs=runs,
                detections=detections,
                storage_uri=self.storage.storage_uri(retained) if retained else None,
                duration_seconds=round(duration, 3),
            )
            if not ok:
                raise AnalysisCancelled()
            self.repo.register_event_refs(aid, {e.id: e.contributing_detection_ids for e in events})
            log.info(
                "analysis completed",
                extra={
                    "analysis_id": aid,
                    "stage_timings_ms": job.timings,
                    "n_raw_detections": len(detections),
                    "n_events": len(events),
                    "models": order,
                },
            )
        except AnalysisCancelled:
            self._discard(retained)
            log.info("analysis cancelled", extra={"analysis_id": aid, "stage": job.stage})
        except ThicketError as exc:
            self._discard(retained)
            self._fail(job, exc.code, exc.message, report)
        except AdapterError as exc:
            self._discard(retained)
            err = from_adapter_error(exc)
            self._fail(
                job, err.code, err.message, report, exc_info=err.code == ErrorCode.internal_error
            )
        except AudioDecodeError:
            self._discard(retained)
            err = decode_failed()
            self._fail(job, err.code, err.message, report)
        except Exception:  # noqa: BLE001 - last resort, never leak internals
            self._discard(retained)
            if job.cancel.is_set():
                log.info("analysis cancelled", extra={"analysis_id": aid, "stage": job.stage})
            else:
                self._fail(
                    job,
                    ErrorCode.internal_error,
                    "The analysis failed because of an internal error.",
                    report,
                    exc_info=True,
                )
        finally:
            timer.cancel()
            self._finish(job)

    def _finish(self, job: Job) -> None:
        shutil.rmtree(job.tmp_dir, ignore_errors=True)
        with self._lock:
            self._jobs.pop(job.analysis_id, None)

    @staticmethod
    def _discard(path: Path | None) -> None:
        if path is not None:
            path.unlink(missing_ok=True)

    def _fail(
        self,
        job: Job,
        code: ErrorCode,
        message: str,
        report: QualityReport | None,
        exc_info: bool = False,
    ) -> None:
        self.repo.fail(
            job.analysis_id,
            code.value,
            message,
            job.timings,
            report.model_dump(mode="json") if report else None,
        )
        log.warning(
            "analysis failed",
            extra={
                "analysis_id": job.analysis_id,
                "error_code": code.value,
                "stage": job.stage,
                "stage_timings_ms": job.timings,
            },
            exc_info=exc_info,
        )

    def _run_row(
        self, aid: str, pos: int, key: str, ctx: AnalysisContext, out: AdapterOutput
    ) -> ModelRunRow:
        adapter = self.registry.lookup(key)
        return ModelRunRow(
            id=ctx.model_run_id,
            analysis_id=aid,
            position=pos,
            adapter=key,
            model=getattr(adapter, "model_name", adapter.name),
            version=adapter.version,
            model_sha256=adapter.model_sha256(),
            taxa=list(adapter.taxon_scope),
            experimental=adapter.experimental,
            required_sample_rate_hz=adapter.required_sample_rate_hz,
            window_seconds=adapter.window_seconds,
            hop_seconds=ctx.hop_seconds,
            raw_threshold=ctx.raw_threshold,
            configuration=_jsonable(out.configuration),  # type: ignore[arg-type]
            runtime_ms=int(out.runtime_ms),
            n_windows=int(out.n_windows),
        )

    def _pipeline_warnings(self, params: AnalysisParams, report: QualityReport) -> list[str]:
        out: list[str] = []
        for key in params.models:
            adapter = self.registry.lookup(key)
            if adapter.experimental:
                out.append(
                    f"{adapter.name} is an experimental model that has not been validated. "
                    "Treat its detections as unverified and review them."
                )
        if "birdnet" in params.models:
            if params.latitude is None:
                out.append(
                    "No coordinates were provided, so detections were not checked against "
                    "species ranges and seasons."
                )
            elif not self.settings.location_filter:
                out.append("The range and season plausibility check is turned off on this server.")
            elif params.captured_at is None:
                out.append(
                    "No recording date was provided, so the range check used year-round occurrence."
                )
        if report.status == QualityStatus.not_usable:
            out.append(
                "Audio quality checks failed, so these detections may be unreliable. "
                "See the quality report."
            )
        return out

    # ---------------------------------------------------------------- reads
    def _bundle(self, analysis_id: str):  # type: ignore[no-untyped-def]
        if not is_valid_id(analysis_id, "ana"):
            raise analysis_not_found()
        bundle = self.repo.load_bundle(analysis_id)
        if bundle is None:
            raise analysis_not_found()
        return bundle

    def view(self, analysis_id: str, threshold: float | None = None) -> Analysis:
        bundle = self._bundle(analysis_id)
        analysis, derived = results.build_analysis(bundle, threshold)
        if derived is not None:
            self.repo.register_event_refs(
                analysis_id, {e.id: e.contributing_detection_ids for e in derived.events}
            )
        return analysis

    def list_recent(self, limit: int = 20) -> AnalysisList:
        return AnalysisList(items=[results.summary(b) for b in self.repo.list_recent(limit)])

    # --------------------------------------------------------------- writes
    def delete(self, analysis_id: str) -> None:
        if not is_valid_id(analysis_id, "ana"):
            raise analysis_not_found()
        with self._lock:
            job = self._jobs.get(analysis_id)
        if job is not None:
            job.cancel.set()
        found, rec = self.repo.delete(analysis_id)
        if not found:
            raise analysis_not_found()
        self.storage.spectrogram_path(analysis_id).unlink(missing_ok=True)
        self.storage.audio_path(analysis_id).unlink(missing_ok=True)
        if rec is not None and rec.storage_uri:
            p = self.storage.resolve_uri(rec.storage_uri)
            if p is not None:
                p.unlink(missing_ok=True)
        if job is None:
            shutil.rmtree(self.storage.analysis_tmp(analysis_id), ignore_errors=True)
        log.info("analysis deleted", extra={"analysis_id": analysis_id})

    def _event_windows(
        self, analysis_id: str, event_id: str, threshold: float | None
    ) -> list[str] | None:
        """Raw detection ids of an event registered before schema 2 (no ids stored).

        Looks for the event at the requested threshold, then at the analysis's
        own. None when it cannot be found; the review then applies by id only.
        """
        bundle = self.repo.load_bundle(analysis_id)
        if bundle is None or bundle.analysis.status != "completed":
            return None
        a = bundle.analysis
        candidates = [a.decision_threshold]
        if threshold is not None:
            candidates.insert(0, results.validate_threshold(threshold, a.raw_threshold, 0.0))
        for t in candidates:
            for e in results.derive_bundle(bundle, t).events:
                if e.id == event_id:
                    return list(e.contributing_detection_ids)
        return None

    def review(self, event_id: str, update: EventReviewUpdate, threshold: float | None) -> Analysis:
        if not is_valid_event_id(event_id):
            raise event_not_found()
        ref = self.repo.event_ref(event_id)
        if ref is None:
            raise event_not_found()
        analysis_id, detection_ids = ref
        if detection_ids is None:
            detection_ids = self._event_windows(analysis_id, event_id, threshold)
        label = clean_text(update.reviewed_label, 200, "reviewed_label")
        note = clean_text(update.review_note, 2000, "review_note")
        resolved = None
        if update.review_status == ReviewStatus.corrected:
            if not label:
                raise invalid_parameter(
                    "reviewed_label is required when review_status is 'corrected'.",
                    field="reviewed_label",
                )
            lab = self.registry.resolve_label(label)
            if lab is not None:
                resolved = (lab.scientific_name, lab.common_name, lab.taxon)
        self.repo.upsert_review(
            event_id=event_id,
            analysis_id=analysis_id,
            review_status=update.review_status.value,
            reviewed_label=label,
            review_note=note,
            resolved=resolved,
            detection_ids=detection_ids,
        )
        log.info(
            "event reviewed",
            extra={
                "analysis_id": analysis_id,
                "event_id": event_id,
                "review_status": update.review_status.value,
            },
        )
        return self.view(analysis_id, threshold)
