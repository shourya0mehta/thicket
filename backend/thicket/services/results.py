"""Derive-on-read: the one path from stored raw detections to what users see.

For a given decision threshold ``t``::

    raw detections (>= ingestion floor)
      -> consolidate(raw, t, merge_gap)         events (all taxa, all runs)
      -> apply reviews                          counting view of the events
      -> counted_events(view, rejected_ids)     the counted set
      -> species_summaries + compute_metrics    species table and metrics

Every endpoint (analysis view, list summaries, CSV, JSON, review responses)
goes through :func:`derive`, so the species table, events, charts and metrics
always come from the same post-threshold event set.

Review rules
------------
* ``rejected``: the event stays listed but is excluded from metrics.
* ``corrected``: the event no longer counts for the model's species. If the
  reviewer's label matches a known model label (scientific, common or raw
  name) it counts for that species instead; otherwise it is excluded.
* ``accepted``: counts as usual, and an accepted event overrides an
  ``unlikely`` range/season flag (a reviewer confirmed it).

Combined runs
-------------
Each adapter has its own ``model_run_id`` and consolidation never merges
across runs, so two models detecting the same species yield separate events,
each keeping its ``model_run_id``. The species table groups by scientific name
and lists every contributing run in ``model_run_ids``; its event count is the
sum over runs. Nothing is deduplicated across models.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime

from thicket.api.schemas import (
    BIODIVERSITY_TAXA,
    AcousticIndices,
    Analysis,
    AnalysisSettings,
    AnalysisStatus,
    AnalysisSummary,
    Assets,
    DetectionEvent,
    ErrorCode,
    Metrics,
    ModelRun,
    QualityReport,
    RawDetection,
    RecordingInfo,
    ReviewStatus,
    SpeciesRef,
    SpeciesSummary,
)
from thicket.domain.consolidation import Event, WindowDetection, consolidate
from thicket.domain.metrics import (
    MetricSet,
    SpeciesStats,
    compute_metrics,
    counted_events,
    species_summaries,
)
from thicket.errors import invalid_parameter
from thicket.persistence.db import EventReviewRow, ModelRunRow, RecordingRow
from thicket.persistence.repositories import AnalysisBundle
from thicket.services.spectrogram import MAX_HZ, MIN_HZ

API_PREFIX = "/api/v1"
ABUNDANCE_DISCLAIMER = (
    "Metrics are based on acoustic detection events and do not estimate individual abundance."
)


def validate_threshold(value: float | None, raw_floor: float, default: float) -> float:
    if value is None:
        return default
    if not math.isfinite(value) or value < raw_floor - 1e-9 or value > 1.0:
        raise invalid_parameter(
            f"threshold must be between {raw_floor:.2f} and 1.0. Scores below "
            f"{raw_floor:.2f} (the ingestion floor) are not stored, so lower thresholds "
            "cannot be applied.",
            field="threshold",
        )
    return round(float(value), 4)


def format_threshold(t: float) -> str:
    return f"{t:g}"


@dataclass
class Derived:
    threshold: float
    events: list[Event]
    counted: list[Event]
    species: list[SpeciesStats]
    metrics: MetricSet
    rejected_ids: set[str]
    unlikely_excluded: list[Event]
    non_biodiversity: list[Event]


def apply_reviews(
    events: list[Event], reviews: dict[str, EventReviewRow]
) -> tuple[list[Event], set[str]]:
    """Return (counting view of events, ids excluded by review)."""
    view: list[Event] = []
    excluded: set[str] = set()
    for e in events:
        r = reviews.get(e.id)
        status = r.review_status if r else ReviewStatus.unreviewed.value
        if status == ReviewStatus.rejected.value:
            excluded.add(e.id)
            view.append(e)
        elif status == ReviewStatus.corrected.value:
            if r is not None and r.resolved_scientific_name and r.resolved_taxon:
                view.append(
                    replace(
                        e,
                        scientific_name=r.resolved_scientific_name,
                        common_name=r.resolved_common_name or r.resolved_scientific_name,
                        taxon=r.resolved_taxon,
                        plausibility="plausible",
                    )
                )
            else:
                excluded.add(e.id)
                view.append(e)
        elif status == ReviewStatus.accepted.value and e.plausibility == "unlikely":
            view.append(replace(e, plausibility="plausible"))
        else:
            view.append(e)
    return view, excluded


def derive(
    raw: list[WindowDetection],
    *,
    threshold: float,
    merge_gap_seconds: float,
    analysis_id: str,
    duration_seconds: float,
    reviews: dict[str, EventReviewRow],
) -> Derived:
    events = consolidate(raw, threshold, merge_gap_seconds, analysis_id)
    view, excluded = apply_reviews(events, reviews)
    counted = counted_events(view, rejected_ids=excluded)
    counted_ids = {e.id for e in counted}
    unlikely = [
        e
        for e in view
        if e.id not in counted_ids
        and e.id not in excluded
        and e.taxon in BIODIVERSITY_TAXA
        and e.plausibility == "unlikely"
    ]
    non_bio = [e for e in view if e.taxon not in BIODIVERSITY_TAXA and e.id not in excluded]
    return Derived(
        threshold=threshold,
        events=events,
        counted=counted,
        species=species_summaries(counted, raw),
        metrics=compute_metrics(counted, duration_seconds),
        rejected_ids=excluded,
        unlikely_excluded=unlikely,
        non_biodiversity=non_bio,
    )


def derive_bundle(bundle: AnalysisBundle, threshold: float) -> Derived:
    a = bundle.analysis
    duration = bundle.recording.duration_seconds if bundle.recording else 0.0
    return derive(
        bundle.raw,
        threshold=threshold,
        merge_gap_seconds=a.merge_gap_seconds,
        analysis_id=a.id,
        duration_seconds=duration,
        reviews=bundle.reviews,
    )


def _plural(n: int, word: str) -> str:
    # "species" is its own plural.
    return f"{n} {word}" if n == 1 or word.endswith("species") else f"{n} {word}s"


def derived_warnings(d: Derived) -> list[str]:
    out: list[str] = []
    if d.unlikely_excluded:
        species = sorted({e.common_name for e in d.unlikely_excluded})
        out.append(
            f"{_plural(len(d.unlikely_excluded), 'detection event')} of "
            f"{_plural(len(species), 'species')} unlikely at this location and time of year "
            f"({', '.join(species[:5])}{', ...' if len(species) > 5 else ''}) "
            f"{'is' if len(d.unlikely_excluded) == 1 else 'are'} listed but not counted in metrics."
        )
    if d.non_biodiversity:
        counts = Counter(e.common_name for e in d.non_biodiversity)
        parts = ", ".join(f"{name} ({_plural(n, 'event')})" for name, n in sorted(counts.items()))
        out.append(f"Non-wildlife sounds were detected and are not counted as species: {parts}.")
    if d.rejected_ids:
        out.append(
            f"{_plural(len(d.rejected_ids), 'event')} rejected in review, or corrected to a label "
            f"the models do not know, {'is' if len(d.rejected_ids) == 1 else 'are'} excluded from metrics."
        )
    return out


# ---------------------------------------------------------------- converters


def recording_info(rec: RecordingRow) -> RecordingInfo:
    captured = None
    if rec.captured_at:
        try:
            captured = datetime.fromisoformat(rec.captured_at)
        except ValueError:
            captured = None
    return RecordingInfo(
        id=rec.id,
        filename=rec.filename,
        content_type=rec.content_type,
        byte_size=rec.byte_size,
        checksum_sha256=rec.checksum_sha256,
        format=rec.format,
        duration_seconds=rec.duration_seconds,
        sample_rate_hz=rec.sample_rate_hz,
        channels=rec.channels,
        bit_depth=rec.bit_depth,
        captured_at=captured,
        timezone=rec.timezone,
        latitude=rec.latitude,
        longitude=rec.longitude,
        site_name=rec.site_name,
        recorder_type=rec.recorder_type,
        notes=rec.notes,
    )


def model_run(row: ModelRunRow) -> ModelRun:
    return ModelRun(
        id=row.id,
        adapter=row.adapter,
        model=row.model,
        version=row.version,
        model_sha256=row.model_sha256,
        taxa=list(row.taxa),
        experimental=row.experimental,
        required_sample_rate_hz=row.required_sample_rate_hz,
        window_seconds=row.window_seconds,
        hop_seconds=row.hop_seconds,
        raw_threshold=row.raw_threshold,
        configuration=dict(row.configuration or {}),
        runtime_ms=row.runtime_ms,
        n_windows=row.n_windows,
    )


def detection_event(e: Event, review: EventReviewRow | None) -> DetectionEvent:
    return DetectionEvent(
        id=e.id,
        scientific_name=e.scientific_name,
        common_name=e.common_name,
        taxon=e.taxon,
        model_run_id=e.model_run_id,
        start_seconds=e.start_seconds,
        end_seconds=e.end_seconds,
        max_confidence=e.max_confidence,
        mean_confidence=e.mean_confidence,
        n_windows=e.n_windows,
        contributing_detection_ids=list(e.contributing_detection_ids),
        plausibility=e.plausibility,  # type: ignore[arg-type]
        review_status=ReviewStatus(review.review_status) if review else ReviewStatus.unreviewed,
        reviewed_label=review.reviewed_label if review else None,
        review_note=review.review_note if review else None,
    )


def species_summary(s: SpeciesStats) -> SpeciesSummary:
    return SpeciesSummary(
        scientific_name=s.scientific_name,
        common_name=s.common_name,
        taxon=s.taxon,
        model_run_ids=s.model_run_ids,
        detection_event_count=s.detection_event_count,
        raw_detection_count=s.raw_detection_count,
        max_confidence=s.max_confidence,
        mean_confidence=s.mean_confidence,
        total_event_duration_seconds=s.total_event_duration_seconds,
        first_detection_seconds=s.first_detection_seconds,
        last_detection_seconds=s.last_detection_seconds,
        plausibility=s.plausibility,  # type: ignore[arg-type]
    )


def metrics_model(m: MetricSet) -> Metrics:
    return Metrics(
        species_richness=m.species_richness,
        shannon_index=m.shannon_index,
        pielou_evenness=m.pielou_evenness,
        simpson_diversity=m.simpson_diversity,
        total_detection_events=m.total_detection_events,
        raw_detection_count=m.raw_detection_count,
        events_per_minute=m.events_per_minute,
        dominant_species=SpeciesRef(
            scientific_name=m.dominant_species[0], common_name=m.dominant_species[1]
        )
        if m.dominant_species
        else None,
        events_by_taxon=m.events_by_taxon,
    )


def raw_detection(d: WindowDetection) -> RawDetection:
    return RawDetection(
        id=d.id,
        model_run_id=d.model_run_id,
        label_raw=d.label_raw,
        scientific_name=d.scientific_name,
        common_name=d.common_name,
        taxon=d.taxon,
        start_seconds=d.start_seconds,
        end_seconds=d.end_seconds,
        confidence=d.confidence,
        plausibility=d.plausibility,  # type: ignore[arg-type]
    )


def assets(bundle: AnalysisBundle, threshold: float) -> Assets:
    aid = bundle.analysis.id
    t = format_threshold(threshold)
    base = f"{API_PREFIX}/analyses/{aid}"
    retained = bool(bundle.recording and bundle.recording.storage_uri)
    return Assets(
        audio_url=f"{base}/audio" if retained else None,
        spectrogram_url=f"{base}/spectrogram.png" if bundle.analysis.has_spectrogram else None,
        spectrogram_min_hz=MIN_HZ,
        spectrogram_max_hz=MAX_HZ,
        csv_url=f"{base}/export.csv?threshold={t}",
        json_url=f"{base}/export.json?threshold={t}",
    )


def build_analysis(
    bundle: AnalysisBundle, threshold: float | None = None
) -> tuple[Analysis, Derived | None]:
    """The full Analysis at ``threshold`` (default: the analysis's own threshold)."""
    a = bundle.analysis
    t = validate_threshold(threshold, a.raw_threshold, a.decision_threshold)
    status = AnalysisStatus(a.status)
    derived: Derived | None = None
    warnings: list[str] = []
    if status == AnalysisStatus.completed:
        derived = derive_bundle(bundle, t)
        warnings = [ABUNDANCE_DISCLAIMER, *list(a.warnings or []), *derived_warnings(derived)]
    else:
        warnings = list(a.warnings or [])
    analysis = Analysis(
        id=a.id,
        status=status,
        stage=a.stage,
        recording=recording_info(bundle.recording) if bundle.recording else None,
        quality=QualityReport.model_validate(a.quality) if a.quality else None,
        settings=AnalysisSettings(
            decision_threshold=t,
            raw_threshold=a.raw_threshold,
            merge_gap_seconds=a.merge_gap_seconds,
            hop_seconds=a.hop_seconds,
            requested_models=list(a.requested_models),
            location_filter=a.location_filter,
            location_filter_threshold=a.location_filter_threshold,
        ),
        model_runs=[model_run(r) for r in bundle.model_runs],
        metrics=metrics_model(derived.metrics) if derived else None,
        acoustic_indices=AcousticIndices.model_validate(a.acoustic_indices)
        if a.acoustic_indices
        else None,
        species=[species_summary(s) for s in derived.species] if derived else [],
        events=[detection_event(e, bundle.reviews.get(e.id)) for e in derived.events]
        if derived
        else [],
        raw_detections=[raw_detection(d) for d in bundle.raw] if derived else [],
        assets=assets(bundle, t),
        warnings=warnings,
        error_code=ErrorCode(a.error_code) if a.error_code else None,
        error_message=a.error_message,
        software_version=a.software_version,
        created_at=a.created_at,
        completed_at=a.completed_at,
        stage_timings_ms={k: int(v) for k, v in (a.stage_timings or {}).items()},
    )
    return analysis, derived


def summary(bundle: AnalysisBundle) -> AnalysisSummary:
    a = bundle.analysis
    derived = derive_bundle(bundle, a.decision_threshold) if a.status == "completed" else None
    return AnalysisSummary(
        id=a.id,
        status=AnalysisStatus(a.status),
        filename=bundle.recording.filename if bundle.recording else None,
        site_name=bundle.recording.site_name if bundle.recording else None,
        created_at=a.created_at,
        duration_seconds=bundle.recording.duration_seconds if bundle.recording else None,
        species_richness=derived.metrics.species_richness if derived else None,
        total_detection_events=derived.metrics.total_detection_events if derived else None,
        decision_threshold=a.decision_threshold,
        top_species=[s.common_name for s in derived.species[:3]] if derived else [],
    )
