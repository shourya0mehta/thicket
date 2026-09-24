"""Data access. Every method opens and closes its own short session and
returns detached rows or plain dataclasses, so callers on any thread can use
the results without holding a session open."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from thicket.domain.consolidation import WindowDetection
from thicket.ids import new_id
from thicket.persistence.db import (
    AnalysisRow,
    Database,
    EventRefRow,
    EventReviewRow,
    ModelRunRow,
    RawDetectionRow,
    RecordingRow,
    SiteRow,
    utcnow,
)

TERMINAL = ("completed", "failed")


@dataclass
class AnalysisBundle:
    analysis: AnalysisRow
    recording: RecordingRow | None
    model_runs: list[ModelRunRow] = field(default_factory=list)
    raw: list[WindowDetection] = field(default_factory=list)
    reviews: dict[str, EventReviewRow] = field(default_factory=dict)


def _to_detection(r: RawDetectionRow) -> WindowDetection:
    return WindowDetection(
        id=r.detection_id,
        model_run_id=r.model_run_id,
        label_raw=r.label_raw,
        scientific_name=r.scientific_name,
        common_name=r.common_name,
        taxon=r.taxon,
        start_seconds=r.start_seconds,
        end_seconds=r.end_seconds,
        confidence=r.confidence,
        plausibility=r.plausibility,
    )


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------------- create
    def create_analysis(
        self,
        recording: RecordingRow,
        analysis: AnalysisRow,
    ) -> None:
        with self.db.session() as s:
            if recording.site_name:
                recording.site_id = self._site_id(
                    s, recording.site_name, recording.latitude, recording.longitude
                )
            s.add(recording)
            s.flush()
            s.add(analysis)

    @staticmethod
    def _site_id(s, name: str, lat: float | None, lon: float | None) -> str:  # type: ignore[no-untyped-def]
        row = s.execute(
            select(SiteRow).where(func.lower(SiteRow.name) == name.lower()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            row = SiteRow(id=new_id("site"), name=name, latitude=lat, longitude=lon)
            s.add(row)
            s.flush()
        elif row.latitude is None and lat is not None:
            row.latitude, row.longitude = lat, lon
        return row.id

    # ---------------------------------------------------------------- update
    def set_stage(self, analysis_id: str, stage: str, status: str = "processing") -> bool:
        with self.db.session() as s:
            res = s.execute(
                update(AnalysisRow)
                .where(AnalysisRow.id == analysis_id, AnalysisRow.status.not_in(TERMINAL))
                .values(stage=stage, status=status)
            )
            return res.rowcount > 0

    def set_spectrogram(self, analysis_id: str) -> None:
        with self.db.session() as s:
            s.execute(
                update(AnalysisRow)
                .where(AnalysisRow.id == analysis_id)
                .values(has_spectrogram=True)
            )

    def set_quality(self, analysis_id: str, quality: dict) -> None:
        with self.db.session() as s:
            s.execute(
                update(AnalysisRow).where(AnalysisRow.id == analysis_id).values(quality=quality)
            )

    def complete(
        self,
        analysis_id: str,
        *,
        quality: dict | None,
        indices: dict | None,
        warnings: list[str],
        timings: dict[str, int],
        model_runs: Sequence[ModelRunRow],
        detections: Sequence[WindowDetection],
        storage_uri: str | None,
    ) -> bool:
        """Persist results and mark completed. False if the analysis is gone or already final."""
        with self.db.session() as s:
            row = s.get(AnalysisRow, analysis_id, with_for_update=True)
            if row is None or row.status in TERMINAL:
                return False
            for run in model_runs:
                s.add(run)
            s.flush()
            if detections:
                s.execute(
                    RawDetectionRow.__table__.insert(),
                    [
                        {
                            "analysis_id": analysis_id,
                            "detection_id": d.id,
                            "model_run_id": d.model_run_id,
                            "label_raw": d.label_raw,
                            "scientific_name": d.scientific_name,
                            "common_name": d.common_name,
                            "taxon": d.taxon,
                            "start_seconds": d.start_seconds,
                            "end_seconds": d.end_seconds,
                            "confidence": d.confidence,
                            "plausibility": d.plausibility,
                        }
                        for d in detections
                    ],
                )
            row.quality = quality
            row.acoustic_indices = indices
            row.warnings = list(warnings)
            row.stage_timings = dict(timings)
            row.status = "completed"
            row.stage = "completed"
            row.completed_at = utcnow()
            if storage_uri:
                rec = s.get(RecordingRow, row.recording_id)
                if rec is not None:
                    rec.storage_uri = storage_uri
            return True

    def fail(
        self,
        analysis_id: str,
        code: str,
        message: str,
        timings: dict[str, int] | None = None,
        quality: dict | None = None,
    ) -> bool:
        with self.db.session() as s:
            row = s.get(AnalysisRow, analysis_id)
            if row is None or row.status in TERMINAL:
                return False
            row.status = "failed"
            row.stage = "failed"
            row.error_code = code
            row.error_message = message
            row.completed_at = utcnow()
            if timings is not None:
                row.stage_timings = dict(timings)
            if quality is not None:
                row.quality = quality
            return True

    def mark_interrupted(self) -> int:
        """Fail analyses left queued/processing by a previous process."""
        with self.db.session() as s:
            res = s.execute(
                update(AnalysisRow)
                .where(AnalysisRow.status.not_in(TERMINAL))
                .values(
                    status="failed",
                    stage="failed",
                    error_code="internal_error",
                    error_message="The analysis was interrupted by a server restart. Run it again.",
                    completed_at=utcnow(),
                )
            )
            return res.rowcount or 0

    # ------------------------------------------------------------------ read
    def get_analysis(self, analysis_id: str) -> AnalysisRow | None:
        with self.db.session() as s:
            return s.get(AnalysisRow, analysis_id)

    def load_bundle(self, analysis_id: str, with_detections: bool = True) -> AnalysisBundle | None:
        with self.db.session() as s:
            row = s.get(AnalysisRow, analysis_id)
            if row is None:
                return None
            return self._bundle(s, row, with_detections)

    def _bundle(self, s, row: AnalysisRow, with_detections: bool) -> AnalysisBundle:  # type: ignore[no-untyped-def]
        rec = s.get(RecordingRow, row.recording_id)
        runs = list(
            s.execute(
                select(ModelRunRow)
                .where(ModelRunRow.analysis_id == row.id)
                .order_by(ModelRunRow.position, ModelRunRow.id)
            ).scalars()
        )
        raw: list[WindowDetection] = []
        reviews: dict[str, EventReviewRow] = {}
        if with_detections and row.status == "completed":
            raw = [
                _to_detection(r)
                for r in s.execute(
                    select(RawDetectionRow)
                    .where(RawDetectionRow.analysis_id == row.id)
                    .order_by(RawDetectionRow.pk)
                ).scalars()
            ]
            reviews = {
                r.event_id: r
                for r in s.execute(
                    select(EventReviewRow).where(EventReviewRow.analysis_id == row.id)
                ).scalars()
            }
        return AnalysisBundle(
            analysis=row, recording=rec, model_runs=runs, raw=raw, reviews=reviews
        )

    def list_recent(self, limit: int = 20) -> list[AnalysisBundle]:
        with self.db.session() as s:
            rows = list(
                s.execute(
                    select(AnalysisRow)
                    .order_by(AnalysisRow.created_at.desc(), AnalysisRow.id)
                    .limit(limit)
                ).scalars()
            )
            return [self._bundle(s, r, True) for r in rows]

    # ---------------------------------------------------------------- delete
    def delete(self, analysis_id: str) -> tuple[bool, RecordingRow | None]:
        """Delete an analysis and everything derived from it.

        Returns (found, deleted recording row or None) for asset cleanup.
        """
        with self.db.session() as s:
            row = s.get(AnalysisRow, analysis_id)
            if row is None:
                return False, None
            rec = s.get(RecordingRow, row.recording_id)
            for table in (EventRefRow, EventReviewRow, RawDetectionRow, ModelRunRow):
                s.execute(delete(table).where(table.analysis_id == analysis_id))
            s.delete(row)
            s.flush()
            if rec is not None:
                others = s.execute(
                    select(func.count())
                    .select_from(AnalysisRow)
                    .where(AnalysisRow.recording_id == rec.id)
                ).scalar_one()
                if not others:
                    s.delete(rec)
                    return True, rec
            return True, None

    # --------------------------------------------------------------- reviews
    def register_event_refs(self, analysis_id: str, event_ids: Iterable[str]) -> None:
        ids = sorted(set(event_ids))
        if not ids:
            return
        for attempt in range(3):
            try:
                with self.db.session() as s:
                    existing = set(
                        s.execute(
                            select(EventRefRow.event_id).where(EventRefRow.event_id.in_(ids))
                        ).scalars()
                    )
                    missing = [i for i in ids if i not in existing]
                    if missing:
                        s.execute(
                            EventRefRow.__table__.insert(),
                            [{"event_id": i, "analysis_id": analysis_id} for i in missing],
                        )
                return
            except IntegrityError:
                if attempt == 2:
                    raise

    def event_analysis_id(self, event_id: str) -> str | None:
        with self.db.session() as s:
            return s.execute(
                select(EventRefRow.analysis_id).where(EventRefRow.event_id == event_id)
            ).scalar_one_or_none()

    def upsert_review(
        self,
        *,
        event_id: str,
        analysis_id: str,
        review_status: str,
        reviewed_label: str | None,
        review_note: str | None,
        resolved: tuple[str, str, str] | None,
        updated_at: datetime | None = None,
    ) -> None:
        with self.db.session() as s:
            row = s.get(EventReviewRow, event_id)
            if review_status == "unreviewed":
                if row is not None:
                    s.delete(row)
                return
            if row is None:
                row = EventReviewRow(event_id=event_id, analysis_id=analysis_id)
                s.add(row)
            row.review_status = review_status
            row.reviewed_label = reviewed_label
            row.review_note = review_note
            row.resolved_scientific_name, row.resolved_common_name, row.resolved_taxon = (
                resolved if resolved else (None, None, None)
            )
            row.updated_at = updated_at or utcnow()
