"""CSV and JSON exports of one analysis at one decision threshold.

Both are rendered from the same :class:`~thicket.api.schemas.Analysis` the
API returns, so exports can never disagree with what the user saw.

CSV: one row per consolidated detection event at the threshold (every
taxon, every model run). ``counted_in_metrics`` (``true``/``false``) marks the
rows behind the species table and metrics: filter on it and group by
``scientific_name`` to reproduce them. ``taxon``, ``common_name`` and
``scientific_name`` are the species a row counts under; ``detected_*`` keep
the model's label, which differs only for events a reviewer corrected to
another known label (``reviewed_label`` holds the reviewer's text).
Plausibility and review status explain why a row is not counted. Text cells
that start with ``= + - @`` are prefixed with ``'`` to defuse spreadsheet
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
    "reviewed_label",
    "detected_taxon",
    "detected_common_name",
    "detected_scientific_name",
    "counted_in_metrics",
]

EXPORT_NOTE = (
    "Metrics are based on acoustic detection events and do not estimate individual abundance. "
    "Species, events and metrics come from consolidated detection events at or above the "
    "decision threshold. Every event is listed; counted_in_metrics marks the ones behind the "
    "species and metrics. The others were excluded in review, flagged unlikely for the "
    "location and date, or are non-wildlife sounds."
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
                    e.detected_taxon,
                    e.detected_common_name,
                    e.detected_scientific_name,
                    "true" if e.counted_in_metrics else "false",
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
