"""Assemble the data bundle a report is rendered from.

The bundle is plain JSON (sorted keys, deterministic for the same inputs
and generation time) and is what ``GET /reports/{id}.json`` returns. Every
number in the PDF comes from it, and its SHA-256 is printed on every page.

Per recording the bundle carries the analysis derived at the report's
decision threshold (or each analysis's own when none is given) through the
same :func:`thicket.services.results.build_analysis` path as the API, so the
species table, events, metrics and ``counted_in_metrics`` flags agree with
the workspace. Aggregates (species across recordings, richness by day,
baseline) are computed here from those per-recording results.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from thicket import __version__
from thicket.api.platform_schemas import PLATFORM_SCHEMA_VERSION, ReportTemplateKey
from thicket.api.schemas import SCHEMA_VERSION, Analysis
from thicket.domain.metrics import shannon_index
from thicket.domain.timebuckets import local_date, zone
from thicket.persistence.db import OrganizationRow, ReportRow
from thicket.persistence.platform_repositories import PlatformRepository
from thicket.persistence.repositories import Repository
from thicket.reports.field_schema import fields_for, missing_fields
from thicket.services import results
from thicket.services.exports import CSV_COLUMNS
from thicket.services.rollups import recording_timestamp

CSV_DEFINITIONS = {
    "analysis_id": "Thicket analysis id the row belongs to.",
    "recording_filename": "Display name of the uploaded file.",
    "site_name": "Site the recording is assigned to.",
    "latitude": "Recorder latitude in decimal degrees (WGS84) when known.",
    "longitude": "Recorder longitude in decimal degrees (WGS84) when known.",
    "captured_at": "Recording start time (ISO 8601, with offset when known).",
    "timezone": "IANA time zone the recording time is expressed in.",
    "taxon": "Group the event counts under (bird, amphibian, insect, mammal, or a non-wildlife class).",
    "common_name": "Common name the event counts under.",
    "scientific_name": "Scientific name the event counts under.",
    "event_id": "Deterministic event id (hash of analysis, run, species and extent).",
    "start_seconds": "Event start within the recording.",
    "end_seconds": "Event end within the recording.",
    "max_confidence": "Highest model score among the event's windows.",
    "mean_confidence": "Mean model score over the event's windows.",
    "n_windows": "Number of analysis windows merged into the event.",
    "model": "Model name.",
    "model_version": "Model version.",
    "model_run_id": "Run id of the model within the analysis.",
    "decision_threshold": "Score at or above which windows became events.",
    "plausibility": "Range and season check of the detected label (birds only).",
    "review_status": "unreviewed, accepted, rejected or corrected.",
    "reviewed_label": "Label the reviewer typed for a correction.",
    "detected_taxon": "Group of the model's own label.",
    "detected_common_name": "Common name of the model's own label.",
    "detected_scientific_name": "Scientific name of the model's own label.",
    "counted_in_metrics": "true for events behind the species table and metrics.",
}

LIMITATIONS = [
    "Detection events are stretches of audio in which a species was detected. They are not "
    "animals: one bird can make many events and several can share one. Nothing in this report "
    "counts animals.",
    "No recall estimate exists for these recordings, so a species that was not detected is "
    "reported as not detected in this effort, with the minutes and threshold stated.",
    "The range and season plausibility check applies to birds only. Frog, insect and mammal "
    "labels from BirdNET are shown as unverified non-bird labels.",
    "Audio quality checks and the soundscape QC head were evaluated on curated clips, not on "
    "field recordings from these sites; treat quality flags as hints.",
    "Acoustic indices respond to weather, noise and insects as well as wildlife. They are "
    "soundscape index values for context only.",
    "Change between periods is reported for the same sites and season with effort noted. The "
    "report does not attribute change to any practice or cause.",
]

NOT_DISCLAIMER = results.ABUNDANCE_DISCLAIMER


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dumps(bundle: dict) -> str:
    return json.dumps(bundle, indent=2, sort_keys=True, default=_json_default) + "\n"


def _json_default(o: object) -> object:
    if isinstance(o, datetime | date):
        return o.isoformat()
    if hasattr(o, "value"):
        return o.value
    return str(o)


def _period_bounds(start: date, end: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = zone(tz_name)
    s = datetime.combine(start, datetime.min.time(), tzinfo=tz).astimezone(UTC)
    e = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=tz).astimezone(UTC)
    return s, e


def _analysis_entry(a: Analysis, rec, derived, tz_name: str, site_name: str | None) -> dict:  # type: ignore[no-untyped-def]
    captured, anchor = recording_timestamp(rec, tz_name)
    counted = [e for e in a.events if e.counted_in_metrics]
    reviews = Counter(e.review_status.value for e in a.events)
    return {
        "analysis_id": a.id,
        "recording_id": rec.id,
        "filename": rec.filename,
        "source_filename": rec.source_filename,
        "site_id": rec.site_id,
        "site_name": site_name,
        "deployment_id": rec.deployment_id,
        "recorder_id": rec.recorder_id,
        "captured_at": captured.isoformat() if captured else None,
        "captured_at_source": rec.captured_at_source,
        "local_date": local_date(anchor, tz_name).isoformat(),
        "timezone": rec.timezone,
        "latitude": rec.latitude,
        "longitude": rec.longitude,
        "duration_seconds": rec.duration_seconds,
        "sample_rate_hz": rec.sample_rate_hz,
        "channels": rec.channels,
        "bit_depth": rec.bit_depth,
        "byte_size": rec.byte_size,
        "checksum_sha256": rec.checksum_sha256,
        "format": rec.format,
        "recorder_type": rec.recorder_type,
        "telemetry": rec.telemetry,
        "decision_threshold": a.settings.decision_threshold,
        "settings": a.settings.model_dump(mode="json"),
        "model_runs": [m.model_dump(mode="json") for m in a.model_runs],
        "quality": a.quality.model_dump(mode="json") if a.quality else None,
        "metrics": a.metrics.model_dump(mode="json") if a.metrics else None,
        "acoustic_indices": a.acoustic_indices.model_dump(mode="json")
        if a.acoustic_indices
        else None,
        "species": [s.model_dump(mode="json") for s in a.species],
        "events": [e.model_dump(mode="json") for e in a.events],
        "counted_events": len(counted),
        "review_counts": dict(reviews),
        "warnings": [w for w in a.warnings if w != NOT_DISCLAIMER],
        "software_version": a.software_version,
        "created_at": a.created_at.isoformat(),
        "completed_at": a.completed_at.isoformat() if a.completed_at else None,
        "stage_timings_ms": a.stage_timings_ms,
    }


def _species_table(entries: Sequence[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for e in entries:
        seen_here: set[str] = set()
        for s in e["species"]:
            sci = s["scientific_name"]
            g = grouped.setdefault(
                sci,
                {
                    "scientific_name": sci,
                    "common_name": s["common_name"],
                    "taxon": s["taxon"],
                    "detection_events": 0,
                    "recordings_with_detection": 0,
                    "max_confidence": 0.0,
                    "first_detected_at": None,
                    "last_detected_at": None,
                    "plausibility": "unknown",
                    "reviewed_events": 0,
                    "accepted_events": 0,
                    "rejected_events": 0,
                    "site_ids": set(),
                },
            )
            g["detection_events"] += int(s["detection_event_count"])
            g["max_confidence"] = max(g["max_confidence"], float(s["max_confidence"]))
            if s["plausibility"] == "plausible":
                g["plausibility"] = "plausible"
            if sci not in seen_here:
                g["recordings_with_detection"] += 1
                seen_here.add(sci)
            if e["captured_at"]:
                g["first_detected_at"] = (
                    e["captured_at"]
                    if g["first_detected_at"] is None
                    else min(g["first_detected_at"], e["captured_at"])
                )
                g["last_detected_at"] = (
                    e["captured_at"]
                    if g["last_detected_at"] is None
                    else max(g["last_detected_at"], e["captured_at"])
                )
            if e["site_id"]:
                g["site_ids"].add(e["site_id"])
    # Second pass: review outcomes, once every counted species is known.
    for e in entries:
        for ev in e["events"]:
            g = grouped.get(ev["scientific_name"]) or grouped.get(ev["detected_scientific_name"])
            if g is None or ev["review_status"] == "unreviewed":
                continue
            g["reviewed_events"] += 1
            if ev["review_status"] == "accepted":
                g["accepted_events"] += 1
            elif ev["review_status"] == "rejected":
                g["rejected_events"] += 1
    out = []
    for g in grouped.values():
        g["site_ids"] = sorted(g["site_ids"])
        g["max_confidence"] = round(g["max_confidence"], 4)
        out.append(g)
    out.sort(key=lambda g: (-g["detection_events"], -g["max_confidence"], g["common_name"]))
    return out


def _by_day(entries: Sequence[dict]) -> list[dict]:
    days: dict[str, dict] = {}
    for e in entries:
        d = days.setdefault(
            e["local_date"],
            {
                "date": e["local_date"],
                "recordings": 0,
                "minutes": 0.0,
                "events": 0,
                "species": Counter(),
            },
        )
        d["recordings"] += 1
        d["minutes"] += float(e["duration_seconds"]) / 60.0
        for s in e["species"]:
            d["species"][s["scientific_name"]] += int(s["detection_event_count"])
            d["events"] += int(s["detection_event_count"])
    out = []
    for key in sorted(days):
        d = days[key]
        counts = list(d["species"].values())
        out.append(
            {
                "date": d["date"],
                "recordings": d["recordings"],
                "minutes": round(d["minutes"], 2),
                "detection_events": d["events"],
                "species_richness": len(d["species"]),
                "events_per_minute": round(d["events"] / d["minutes"], 3) if d["minutes"] else 0.0,
                "shannon_index": round(shannon_index(counts), 4) if counts else 0.0,
            }
        )
    return out


def _summary(entries: Sequence[dict], species: Sequence[dict]) -> dict:
    minutes = sum(float(e["duration_seconds"]) for e in entries) / 60.0
    events = sum(int(s["detection_events"]) for s in species)
    counts = [int(s["detection_events"]) for s in species]
    per_rec_richness = [int((e["metrics"] or {}).get("species_richness", 0)) for e in entries]
    quality = Counter((e["quality"] or {}).get("status", "unknown") for e in entries)
    return {
        "recordings": len(entries),
        "minutes_recorded": round(minutes, 2),
        "species_counted": len(species),
        "detection_events": events,
        "events_per_minute": round(events / minutes, 3) if minutes else 0.0,
        "shannon_index": round(shannon_index(counts), 4) if counts else 0.0,
        "richness_per_recording_median": statistics.median(per_rec_richness)
        if per_rec_richness
        else None,
        "quality_counts": dict(quality),
        "speech_flagged_recordings": sum(
            1 for e in entries if (e["quality"] or {}).get("speech_detected")
        ),
        "sites": sorted({e["site_id"] for e in entries if e["site_id"]}),
        "first_recording_at": min(
            (e["captured_at"] for e in entries if e["captured_at"]), default=None
        ),
        "last_recording_at": max(
            (e["captured_at"] for e in entries if e["captured_at"]), default=None
        ),
    }


def _bootstrap_ci(values: Sequence[float], n_boot: int = 500, seed: int = 7) -> dict | None:
    """Percentile bootstrap of the mean over recordings (deterministic seed)."""
    import random

    vals = [float(v) for v in values]
    if len(vals) < 3:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sample = [rng.choice(vals) for _ in vals]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(0.025 * (n_boot - 1))]
    hi = means[int(0.975 * (n_boot - 1))]
    return {
        "mean": round(sum(vals) / len(vals), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "n": len(vals),
    }


def _review_log(entries: Sequence[dict], reviewer_names: dict[str, str]) -> list[dict]:
    out = []
    for e in entries:
        for ev in e["events"]:
            if ev["review_status"] == "unreviewed":
                continue
            out.append(
                {
                    "event_id": ev["id"],
                    "analysis_id": e["analysis_id"],
                    "recording_filename": e["filename"],
                    "captured_at": e["captured_at"],
                    "start_seconds": ev["start_seconds"],
                    "model_label": ev["detected_common_name"],
                    "model_scientific_name": ev["detected_scientific_name"],
                    "max_confidence": ev["max_confidence"],
                    "review_status": ev["review_status"],
                    "reviewer_label": ev["reviewed_label"],
                    "review_note": ev["review_note"],
                    "counted_in_metrics": ev["counted_in_metrics"],
                }
            )
    return out


def build_bundle(
    repo: Repository,
    platform: PlatformRepository,
    report: ReportRow,
    org: OrganizationRow,
    *,
    generated_at: datetime | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(UTC)
    tz_name = org.timezone or "UTC"
    key = ReportTemplateKey(report.template)
    site_rows = {s.id: s for s in platform.list_sites(org.id)}
    site_ids = list(report.site_ids or []) or sorted(site_rows)
    start_dt, end_dt = _period_bounds(report.period_start, report.period_end, tz_name)
    pairs = platform.completed_analyses_for_period(
        org.id, site_ids=site_ids if report.site_ids else None, start=start_dt, end=end_dt
    )
    entries: list[dict] = []
    for a_row, rec in pairs:
        bundle = repo.load_bundle(a_row.id)
        if bundle is None:
            continue
        analysis, derived = results.build_analysis(bundle, report.decision_threshold)
        site = site_rows.get(rec.site_id or "")
        entries.append(
            _analysis_entry(analysis, rec, derived, tz_name, site.name if site else rec.site_name)
        )
    entries.sort(key=lambda e: (e["captured_at"] or "", e["analysis_id"]))

    baseline = None
    if report.baseline_start and report.baseline_end:
        b_start, b_end = _period_bounds(report.baseline_start, report.baseline_end, tz_name)
        b_pairs = platform.completed_analyses_for_period(
            org.id, site_ids=site_ids if report.site_ids else None, start=b_start, end=b_end
        )
        b_entries = []
        for a_row, rec in b_pairs:
            bundle = repo.load_bundle(a_row.id)
            if bundle is None:
                continue
            analysis, derived = results.build_analysis(bundle, report.decision_threshold)
            site = site_rows.get(rec.site_id or "")
            b_entries.append(
                _analysis_entry(
                    analysis, rec, derived, tz_name, site.name if site else rec.site_name
                )
            )
        b_species = _species_table(b_entries)
        baseline = {
            "period_start": report.baseline_start.isoformat(),
            "period_end": report.baseline_end.isoformat(),
            "summary": _summary(b_entries, b_species),
            "richness_by_day": _by_day(b_entries),
            "species": [
                {
                    k: v
                    for k, v in s.items()
                    if k
                    in (
                        "scientific_name",
                        "common_name",
                        "taxon",
                        "detection_events",
                        "recordings_with_detection",
                    )
                }
                for s in b_species
            ],
            "richness_per_recording": _bootstrap_ci(
                [int((e["metrics"] or {}).get("species_richness", 0)) for e in b_entries]
            ),
            "events_per_minute_per_recording": _bootstrap_ci(
                [float((e["metrics"] or {}).get("events_per_minute", 0.0)) for e in b_entries]
            ),
        }

    species = _species_table(entries)
    deployments = [
        d
        for d in platform.list_deployments(org.id)
        if (not report.site_ids or d.site_id in site_ids)
        and d.started_at < end_dt
        and (d.ended_at is None or d.ended_at >= start_dt)
    ]
    recorder_ids = {d.recorder_id for d in deployments} | {
        e["recorder_id"] for e in entries if e["recorder_id"]
    }
    recorders = [r for r in platform.list_recorders(org.id) if r.id in recorder_ids]
    reviewer_rows = platform.reviews_for_analyses([e["analysis_id"] for e in entries])
    reviewer_ids = {r.reviewed_by for r in reviewer_rows if r.reviewed_by}
    reviewer_names = {u.id: u.name for u in platform.users_by_ids(reviewer_ids).values()}
    models = {}
    for e in entries:
        for m in e["model_runs"]:
            models[(m["model"], m["version"], m["model_sha256"])] = {
                "model": m["model"],
                "version": m["version"],
                "model_sha256": m["model_sha256"],
                "adapter": m["adapter"],
                "window_seconds": m["window_seconds"],
                "experimental": m["experimental"],
            }
    fields = dict(report.fields or {})
    warnings: list[str] = []
    if not entries:
        warnings.append("No completed recordings fall in this period for the selected sites.")
    thresholds = sorted({e["decision_threshold"] for e in entries})
    if len(thresholds) > 1:
        warnings.append(
            "Recordings were analyzed at different decision thresholds ("
            + ", ".join(f"{t:g}" for t in thresholds)
            + "). Set a report threshold to compare them on one scale."
        )
    bundle = {
        "report": {
            "id": report.id,
            "template": key.value,
            "template_title": fields.get("report_title") or report.title,
            "title": report.title,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "baseline_start": report.baseline_start.isoformat() if report.baseline_start else None,
            "baseline_end": report.baseline_end.isoformat() if report.baseline_end else None,
            "site_ids": site_ids,
            "decision_threshold": report.decision_threshold,
            "include_review_log": bool(report.include_review_log),
            "include_raw_manifest": bool(report.include_raw_manifest),
            "generated_at": generated_at.isoformat(),
            "software_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "platform_schema_version": PLATFORM_SCHEMA_VERSION,
            "timezone": tz_name,
            "created_by": report.created_by,
        },
        "organization": {
            "id": org.id,
            "name": org.name,
            "kind": org.kind,
            "timezone": tz_name,
            "country": org.country,
            "region": org.region,
        },
        "fields": fields,
        "field_labels": {f.name: f.label for f in fields_for(key)},
        "missing_fields": missing_fields(key, fields),
        "sites": [
            {
                "id": s.id,
                "name": s.name,
                "latitude": s.latitude,
                "longitude": s.longitude,
                "habitat_type": s.habitat_type,
                "area_hectares": s.area_hectares,
                "fsa_field_number": s.fsa_field_number,
                "paddock_id": s.paddock_id,
                "notes": s.notes,
            }
            for s in site_rows.values()
            if s.id in site_ids
        ],
        "recorders": [
            {
                "id": r.id,
                "label": r.label,
                "make": r.make,
                "model": r.model,
                "serial": r.serial,
                "firmware": r.firmware,
            }
            for r in recorders
        ],
        "deployments": [
            {
                "id": d.id,
                "recorder_id": d.recorder_id,
                "site_id": d.site_id,
                "started_at": d.started_at.isoformat(),
                "ended_at": d.ended_at.isoformat() if d.ended_at else None,
                "mount_height_m": d.mount_height_m,
                "orientation": d.orientation,
                "gain_setting": d.gain_setting,
                "schedule_description": d.schedule_description,
                "expected_interval_minutes": d.expected_interval_minutes,
                "expected_clip_seconds": d.expected_clip_seconds,
            }
            for d in deployments
        ],
        "summary": _summary(entries, species),
        "species": species,
        "richness_by_day": _by_day(entries),
        "recordings": entries,
        "baseline": baseline,
        "review_log": _review_log(entries, reviewer_names) if report.include_review_log else [],
        "reviewers": sorted(reviewer_names.values()),
        "models": sorted(models.values(), key=lambda m: (m["model"], m["version"])),
        "manifest": [
            {
                "filename": e["filename"],
                "checksum_sha256": e["checksum_sha256"],
                "byte_size": e["byte_size"],
                "duration_seconds": e["duration_seconds"],
                "analysis_id": e["analysis_id"],
                "captured_at": e["captured_at"],
            }
            for e in entries
        ]
        if report.include_raw_manifest
        else [],
        "limitations": LIMITATIONS,
        "csv_columns": [{"name": c, "definition": CSV_DEFINITIONS.get(c, "")} for c in CSV_COLUMNS],
        "warnings": warnings,
    }
    return bundle


def site_day_lookup(bundle: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in bundle["recordings"]:
        out[e["local_date"]].append(e)
    return out
