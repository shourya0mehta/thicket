"""Rollups: per-recording stats, site-day and species-day tables.

Three tables, all derived from the stored raw detections through
:func:`thicket.services.results.derive_bundle` at each analysis's own
recorded threshold, so the counted-event rule stays the single source of
truth:

* ``recording_stats``: one row per completed analysis (richness, events,
  events per minute, Shannon, quality status, species map, local date, hour
  bucket). Alerts and recorder health read this instead of re-deriving.
* ``site_day_stats``: per site and local date (organization timezone):
  recordings, minutes, richness and Shannon over the union of counted events
  across that day's analyses, events per minute, usable fraction, mean
  acoustic indices, quality counts and an hour-of-day activity map.
* ``species_day_stats``: per site, local date and species: events,
  recordings with a detection, max confidence, first and last detection.

``on_analysis_completed`` refreshes the recording's row and its site-day
after each completed analysis (and after a review, because reviews change
the counted set); ``rebuild`` recomputes everything (nightly). Recordings
without a site get a stats row (so recorder health works) but no site-day.
Local date falls back to the upload time when a recording has no timestamp.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime

from thicket.domain.metrics import shannon_index
from thicket.domain.timebuckets import hour_bucket, iso_week, to_local, zone
from thicket.persistence.db import OrganizationRow, RecordingRow, RecordingStatsRow, SiteRow
from thicket.persistence.platform_repositories import PlatformRepository
from thicket.persistence.repositories import AnalysisBundle, Repository
from thicket.services import results

log = logging.getLogger(__name__)

INDEX_KEYS = (
    "acoustic_complexity_index",
    "acoustic_diversity_index",
    "acoustic_evenness_index",
    "bioacoustic_index",
    "ndsi",
    "spectral_entropy",
    "temporal_entropy",
)
USABLE_STATUSES = ("usable", "usable_with_warnings")


def recording_timestamp(rec: RecordingRow, org_tz: str | None) -> tuple[datetime | None, datetime]:
    """(captured_at as a UTC instant or None, the instant used for the local date)."""
    captured = rec.captured_at_utc
    if captured is None and rec.captured_at:
        try:
            dt = datetime.fromisoformat(rec.captured_at)
        except ValueError:
            dt = None
        if dt is not None:
            if dt.tzinfo is None:
                # A naive timestamp is on the recorder's declared clock, else the org's.
                dt = dt.replace(tzinfo=zone(rec.timezone or org_tz or "UTC"))
            captured = dt.astimezone(UTC)
    if captured is not None and captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    created = rec.created_at if rec.created_at.tzinfo else rec.created_at.replace(tzinfo=UTC)
    return captured, captured or created


class RollupService:
    def __init__(self, repo: Repository, platform: PlatformRepository) -> None:
        self.repo = repo
        self.platform = platform
        self._org_cache: dict[str, OrganizationRow | None] = {}
        self._site_cache: dict[str, SiteRow | None] = {}

    # -------------------------------------------------------------- helpers
    def _org(self, org_id: str | None) -> OrganizationRow | None:
        if not org_id:
            return None
        if org_id not in self._org_cache:
            self._org_cache[org_id] = self.platform.get_org(org_id)
        return self._org_cache[org_id]

    def _site(self, site_id: str | None) -> SiteRow | None:
        if not site_id:
            return None
        if site_id not in self._site_cache:
            self._site_cache[site_id] = self.platform.get_site(site_id)
        return self._site_cache[site_id]

    def reset_cache(self) -> None:
        self._org_cache.clear()
        self._site_cache.clear()

    # --------------------------------------------------- per-recording stats
    def stats_values(self, bundle: AnalysisBundle) -> dict | None:
        a, rec = bundle.analysis, bundle.recording
        if rec is None or a.status != "completed":
            return None
        org = self._org(rec.organization_id)
        tz = org.timezone if org else "UTC"
        site = self._site(rec.site_id)
        captured, anchor = recording_timestamp(rec, tz)
        local = to_local(anchor, tz)
        lat = rec.latitude if rec.latitude is not None else (site.latitude if site else None)
        lon = rec.longitude if rec.longitude is not None else (site.longitude if site else None)
        derived = results.derive_bundle(bundle, a.decision_threshold)
        species: dict[str, list] = {}
        for s in derived.species:
            species[s.scientific_name] = [
                s.common_name,
                s.taxon,
                int(s.detection_event_count),
                float(s.max_confidence),
                s.plausibility,
            ]
        quality = a.quality or {}
        year, week = iso_week(local.date())
        minutes = float(rec.duration_seconds or 0.0) / 60.0
        return {
            "recording_id": rec.id,
            "analysis_id": a.id,
            "organization_id": rec.organization_id or "",
            "site_id": rec.site_id,
            "recorder_id": rec.recorder_id,
            "deployment_id": rec.deployment_id,
            "captured_at": captured,
            "local_date": local.date(),
            "local_hour": local.hour,
            "hour_bucket": hour_bucket(local, lat, lon),
            "iso_year": year,
            "iso_week": week,
            "minutes": round(minutes, 4),
            "richness": int(derived.metrics.species_richness),
            "events": int(derived.metrics.total_detection_events),
            "events_per_minute": float(derived.metrics.events_per_minute),
            "shannon": float(derived.metrics.shannon_index),
            "quality_status": quality.get("status"),
            "speech_detected": bool(quality.get("speech_detected", False)),
            "decision_threshold": float(a.decision_threshold),
            "species": species,
            "indices": dict(a.acoustic_indices) if a.acoustic_indices else None,
        }

    def on_analysis_completed(self, analysis_id: str) -> None:
        bundle = self.repo.load_bundle(analysis_id)
        if bundle is None or bundle.recording is None:
            return
        previous = self.platform.get_recording_stats(bundle.recording.id)
        values = self.stats_values(bundle)
        if values is None:
            return
        self.platform.upsert_recording_stats(values)
        org_id = values["organization_id"]
        days: set[tuple[str, date]] = set()
        if values["site_id"]:
            days.add((values["site_id"], values["local_date"]))
        if previous is not None and previous.site_id:
            days.add((previous.site_id, previous.local_date))
        for site_id, day in days:
            self.recompute_site_day(site_id, day, org_id)

    def remove_recording(self, recording_id: str) -> None:
        previous = self.platform.delete_recording_stats(recording_id)
        if previous is not None and previous.site_id:
            self.recompute_site_day(previous.site_id, previous.local_date, previous.organization_id)

    # ----------------------------------------------------------- site days
    def recompute_site_day(self, site_id: str, day: date, org_id: str) -> None:
        rows = self.platform.stats_for_site_day(site_id, day)
        if not rows:
            self.platform.replace_site_day(site_id, day, org_id, None, [])
            return
        day_values, species = aggregate_site_day(rows)
        self.platform.replace_site_day(site_id, day, org_id, day_values, species)

    def rebuild(self, org_id: str | None = None) -> dict[str, int]:
        """Recompute every recording's stats and every site-day from scratch."""
        self.reset_cache()
        self.platform.clear_rollups(org_id)
        days: set[tuple[str, date, str]] = set()
        n = 0
        for aid in self.platform.completed_analysis_ids(org_id):
            bundle = self.repo.load_bundle(aid)
            if bundle is None:
                continue
            values = self.stats_values(bundle)
            if values is None:
                continue
            if bundle.recording is not None and bundle.recording.captured_at_utc is None:
                captured = values["captured_at"]
                if captured is not None:
                    self.platform.attach_recording(
                        bundle.recording.id, {"captured_at_utc": captured}
                    )
            self.platform.upsert_recording_stats(values)
            n += 1
            if values["site_id"]:
                days.add((values["site_id"], values["local_date"], values["organization_id"]))
        for site_id, day, oid in sorted(days):
            self.recompute_site_day(site_id, day, oid)
        log.info("rollups rebuilt", extra={"recordings": n, "site_days": len(days)})
        return {"recordings": n, "site_days": len(days)}


def aggregate_site_day(rows: Iterable[RecordingStatsRow]) -> tuple[dict, list[dict]]:
    rows = list(rows)
    n = len(rows)
    minutes = sum(float(r.minutes or 0.0) for r in rows)
    events_by_species: Counter[str] = Counter()
    names: dict[str, tuple[str, str]] = {}
    with_detection: Counter[str] = Counter()
    max_conf: dict[str, float] = defaultdict(float)
    first: dict[str, datetime | None] = {}
    last: dict[str, datetime | None] = {}
    plaus: dict[str, set[str]] = defaultdict(set)
    quality_counts: Counter[str] = Counter()
    usable = 0
    rated = 0
    index_sums: dict[str, list[float]] = defaultdict(list)
    activity: dict[str, list[float]] = {}
    for r in rows:
        for sci, info in (r.species or {}).items():
            common, taxon, events, conf, pl = (list(info) + [None] * 5)[:5]
            events_by_species[sci] += int(events or 0)
            names[sci] = (str(common or sci), str(taxon or "bird"))
            with_detection[sci] += 1
            max_conf[sci] = max(max_conf[sci], float(conf or 0.0))
            plaus[sci].add(str(pl or "unknown"))
            ts = r.captured_at
            if ts is not None:
                first[sci] = ts if first.get(sci) is None else min(first[sci], ts)  # type: ignore[type-var]
                last[sci] = ts if last.get(sci) is None else max(last[sci], ts)  # type: ignore[type-var]
            else:
                first.setdefault(sci, None)
                last.setdefault(sci, None)
        if r.quality_status:
            rated += 1
            quality_counts[r.quality_status] += 1
            if r.quality_status in USABLE_STATUSES:
                usable += 1
        for k in INDEX_KEYS:
            v = (r.indices or {}).get(k)
            if isinstance(v, int | float):
                index_sums[k].append(float(v))
        hour = str(int(r.local_hour))
        cell = activity.setdefault(hour, [0, 0, 0.0])
        cell[0] += 1
        cell[1] += int(r.events or 0)
        cell[2] = round(cell[2] + float(r.minutes or 0.0), 4)
    total_events = int(sum(events_by_species.values()))
    day = {
        "recordings": n,
        "minutes": round(minutes, 4),
        "richness": len(events_by_species),
        "events": total_events,
        "events_per_minute": round(total_events / minutes, 4) if minutes > 0 else 0.0,
        "shannon": round(shannon_index(list(events_by_species.values())), 4)
        if events_by_species
        else 0.0,
        "usable_fraction": round(usable / rated, 4) if rated else None,
        "indices": {k: round(sum(v) / len(v), 6) for k, v in index_sums.items()} or None,
        "quality_counts": dict(quality_counts),
        "activity": activity,
    }
    species = [
        {
            "scientific_name": sci,
            "common_name": names[sci][0],
            "taxon": names[sci][1],
            "events": int(events_by_species[sci]),
            "recordings_with_detection": int(with_detection[sci]),
            "max_confidence": round(max_conf[sci], 4),
            "first_detected_at": first.get(sci),
            "last_detected_at": last.get(sci),
            "plausibility": "plausible" if "plausible" in plaus[sci] else "unknown",
        }
        for sci in sorted(events_by_species)
    ]
    return day, species
