"""CSV and JSON exports of one analysis at one decision threshold.

Both are rendered from the same :class:`~thicket.api.schemas.Analysis` the
API returns, so exports can never disagree with what the user saw.

CSV: one row per consolidated detection event at the threshold (every
taxon, every model run), with plausibility and review status so rows that
do not count toward metrics are visible and filterable. Text cells that
start with ``= + - @`` are prefixed with ``'`` to defuse spreadsheet
formulas.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from thicket.api.schemas import SCHEMA_VERSION, Analysis, AnalysisExport, ExportMetadata

CSV_COLUMNS = [
    "analysis_id",
    "recording_filename",
    "site_name",
    "latitude",
    "longitude",
    "captured_at",
    "timezone",
    "taxon",
    "common_name",
    "scientific_name",
    "event_id",
    "start_seconds",
    "end_seconds",
    "max_confidence",
    "mean_confidence",
    "n_windows",
    "model",
    "model_version",
    "model_run_id",
    "decision_threshold",
    "plausibility",
    "review_status",
    # The reviewer's label for a "corrected" event; the row keeps the model's names.
    "reviewed_label",
]

EXPORT_NOTE = (
    "Metrics are based on acoustic detection events and do not estimate individual abundance. "
    "Species, events and metrics come from consolidated detection events at or above the "
    "decision threshold. Events excluded from metrics (rejected in review, unlikely for the "
    "location and date, or non-wildlife sounds) are listed with their status."
)


def _safe(value: object) -> object:
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value  # enums
    return _safe(value)


def csv_text(a: Analysis) -> str:
    runs = {r.id: r for r in a.model_runs}
    rec = a.recording
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for e in a.events:
        run = runs.get(e.model_run_id)
        w.writerow(
            [
                _cell(v)
                for v in (
                    a.id,
                    rec.filename if rec else None,
                    rec.site_name if rec else None,
                    rec.latitude if rec else None,
                    rec.longitude if rec else None,
                    rec.captured_at if rec else None,
                    rec.timezone if rec else None,
                    e.taxon,
                    e.common_name,
                    e.scientific_name,
                    e.id,
                    e.start_seconds,
                    e.end_seconds,
                    e.max_confidence,
                    e.mean_confidence,
                    e.n_windows,
                    run.model if run else None,
                    run.version if run else None,
                    e.model_run_id,
                    a.settings.decision_threshold,
                    e.plausibility,
                    e.review_status,
                    e.reviewed_label,
                )
            ]
        )
    return buf.getvalue()


def json_export(a: Analysis) -> AnalysisExport:
    return AnalysisExport(
        **a.model_dump(),
        export_metadata=ExportMetadata(
            exported_at=datetime.now(UTC),
            software_version=a.software_version,
            schema_version=SCHEMA_VERSION,
            decision_threshold=a.settings.decision_threshold,
            note=EXPORT_NOTE,
        ),
    )


def export_filename(a: Analysis, ext: str) -> str:
    return f"thicket_{a.id}_t{a.settings.decision_threshold:.2f}.{ext}"
