"""Dashboard, phenology, species accumulation and site comparison.

Everything here reads the rollup tables (``site_day_stats``,
``species_day_stats``, ``recording_stats``) that
:mod:`thicket.services.rollups` maintains, so numbers agree with the
per-analysis views: a day's richness is the number of distinct species with
counted events across that day's analyses, each at its own threshold.

Across several sites a day's richness is the union of the sites' species
(exact, from ``species_day_stats``), events per minute is total events over
total minutes, and Shannon is computed over the summed per-species events.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from thicket.api.platform_schemas import (
    Accumulation,
    AccumulationPoint,
    Dashboard,
    DayPoint,
    HeatCell,
    IndexPoint,
    Phenology,
    PhenologyCell,
    Site,
    SiteComparison,
    SiteComparisonRow,
    SpeciesRollup,
    TaxonCount,
)
from thicket.api.schemas import SpeciesRef, Taxon
from thicket.domain.metrics import shannon_index
from thicket.domain.timebuckets import iso_week, local_date
from thicket.errors import invalid_parameter, not_found
from thicket.persistence.db import SiteDayStatsRow, SpeciesDayStatsRow
from thicket.persistence.platform_repositories import PlatformRepository

DEFAULT_DASHBOARD_DAYS = 90
QUALITY_KEYS = ("usable", "usable_with_warnings", "not_usable")


def _taxon(value: str) -> Taxon:
    try:
        return Taxon(value)
    except ValueError:
        return Taxon.bird


def parse_period(
    start: date | None, end: date | None, default_days: int = DEFAULT_DASHBOARD_DAYS
) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    end = end or today
    start = start or (end - timedelta(days=default_days - 1))
    if start > end:
        raise invalid_parameter("from must not be after to.", field="from")
    if (end - start).days > 366 * 5:
        raise invalid_parameter("The period may span at most five years.", field="from")
    return start, end


def baseline_note(platform: PlatformRepository, org_id: str, recordings: int) -> str:
    first = platform.first_date_with_data(org_id)
    if first is None or recordings == 0:
        return (
            "No recordings yet. Baselines and alerts start once eight comparable recordings "
            "exist for a site."
        )
    span = (datetime.now(UTC).date() - first).days
    if span < 60:
        return (
            f"History starts {first.isoformat()} ({span} days). Seasonal baselines need at "
            "least one earlier season; until then alerts compare against the last eight weeks."
        )
    return (
        f"History starts {first.isoformat()} ({span} days). Baselines use the same site, hour "
        "bucket and season window (plus or minus three ISO weeks) across years."
    )


def _day_points(
    days: Sequence[SiteDayStatsRow],
    species: Sequence[SpeciesDayStatsRow],
    *,
    per_site: bool,
) -> list[DayPoint]:
    if per_site:
        return [
            DayPoint(
                date=d.local_date,
                site_id=d.site_id,
                recordings=d.recordings,
                minutes=round(d.minutes, 2),
                species_richness=d.richness,
                detection_events=d.events,
                events_per_minute=round(d.events_per_minute, 3),
                shannon_index=d.shannon,
                usable_fraction=d.usable_fraction,
            )
            for d in sorted(days, key=lambda r: (r.local_date, r.site_id))
        ]
    by_date: dict[date, list[SiteDayStatsRow]] = defaultdict(list)
    for d in days:
        by_date[d.local_date].append(d)
    sp_by_date: dict[date, Counter[str]] = defaultdict(Counter)
    for s in species:
        sp_by_date[s.local_date][s.scientific_name] += s.events
    out: list[DayPoint] = []
    for day in sorted(by_date):
        rows = by_date[day]
        minutes = sum(r.minutes for r in rows)
        events = sum(r.events for r in rows)
        rated = [r for r in rows if r.usable_fraction is not None]
        usable = (
            sum(r.usable_fraction * r.recordings for r in rated) / sum(r.recordings for r in rated)  # type: ignore[operator]
            if rated and sum(r.recordings for r in rated)
            else None
        )
        counts = list(sp_by_date[day].values())
        out.append(
            DayPoint(
                date=day,
                site_id=rows[0].site_id if len(rows) == 1 else None,
                recordings=sum(r.recordings for r in rows),
                minutes=round(minutes, 2),
                species_richness=len(sp_by_date[day]),
                detection_events=events,
                events_per_minute=round(events / minutes, 3) if minutes > 0 else 0.0,
                shannon_index=round(shannon_index(counts), 4) if counts else 0.0,
                usable_fraction=round(usable, 4) if usable is not None else None,
            )
        )
    return out


def _species_rollups(
    species: Sequence[SpeciesDayStatsRow],
    recordings_total: int,
    priority: set[str],
) -> list[SpeciesRollup]:
    grouped: dict[str, list[SpeciesDayStatsRow]] = defaultdict(list)
    for s in species:
        grouped[s.scientific_name].append(s)
    out: list[SpeciesRollup] = []
    for sci, rows in grouped.items():
        with_det = sum(r.recordings_with_detection for r in rows)
        firsts = [r.first_detected_at for r in rows if r.first_detected_at is not None]
        lasts = [r.last_detected_at for r in rows if r.last_detected_at is not None]
        out.append(
            SpeciesRollup(
                scientific_name=sci,
                common_name=rows[0].common_name,
                taxon=_taxon(rows[0].taxon),
                detection_events=sum(r.events for r in rows),
                recordings_with_detection=with_det,
                recordings_total=recordings_total,
                presence_fraction=round(with_det / recordings_total, 4)
                if recordings_total
                else 0.0,
                max_confidence=round(max(r.max_confidence for r in rows), 4),
                first_detected_at=min(firsts) if firsts else None,
                last_detected_at=max(lasts) if lasts else None,
                site_ids=sorted({r.site_id for r in rows}),
                is_priority=sci in priority,
                plausibility="plausible"
                if any(r.plausibility == "plausible" for r in rows)
                else "unknown",
            )
        )
    out.sort(key=lambda s: (-s.detection_events, -s.max_confidence, s.common_name))
    return out


def _weighted_index(rows: Sequence[SiteDayStatsRow], key: str) -> float | None:
    """Recording-weighted mean of one acoustic index over several site-days."""
    vals = [(r.indices or {}).get(key) for r in rows]
    if not vals or any(v is None for v in vals):
        return None
    weights = sum(r.recordings for r in rows) or 1
    return round(sum(float(v) * r.recordings for v, r in zip(vals, rows, strict=True)) / weights, 6)  # type: ignore[arg-type]


def build_dashboard(
    platform: PlatformRepository,
    org_id: str,
    *,
    start: date | None,
    end: date | None,
    site_id: str | None,
    priority_species: Sequence[str] = (),
) -> Dashboard:
    start, end = parse_period(start, end)
    site_ids = [site_id] if site_id else None
    days = platform.site_days(org_id, start=start, end=end, site_ids=site_ids)
    species = platform.species_days(org_id, start=start, end=end, site_ids=site_ids)
    recordings = sum(d.recordings for d in days)
    minutes = sum(d.minutes for d in days)
    events = sum(d.events for d in days)
    quality: Counter[str] = Counter()
    heat: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0, 0, 0.0])
    for d in days:
        for k, v in (d.quality_counts or {}).items():
            quality[k] += int(v)
        weekday = d.local_date.weekday()
        for hour, cell in (d.activity or {}).items():
            agg = heat[(weekday, int(hour))]
            agg[0] += int(cell[0])
            agg[1] += int(cell[1])
            agg[2] += float(cell[2])
    heatmap = [
        HeatCell(
            weekday=wd,
            hour=h,
            recordings=int(c[0]),
            events_per_minute=round(c[1] / c[2], 3) if c[2] > 0 else 0.0,
        )
        for (wd, h), c in sorted(heat.items())
    ]
    indices: list[IndexPoint] = []
    by_date: dict[date, list[SiteDayStatsRow]] = defaultdict(list)
    for d in days:
        by_date[d.local_date].append(d)
    for day in sorted(by_date):
        rows = [r for r in by_date[day] if r.indices]
        if not rows:
            continue
        indices.append(
            IndexPoint(
                date=day,
                site_id=rows[0].site_id if len(rows) == 1 else None,
                acoustic_complexity_index=_weighted_index(rows, "acoustic_complexity_index"),
                acoustic_diversity_index=_weighted_index(rows, "acoustic_diversity_index"),
                bioacoustic_index=_weighted_index(rows, "bioacoustic_index"),
                ndsi=_weighted_index(rows, "ndsi"),
            )
        )
    species_rollups = _species_rollups(species, recordings, set(priority_species))
    taxa: dict[str, tuple[int, set[str]]] = {}
    for s in species_rollups:
        ev, names = taxa.get(s.taxon.value, (0, set()))
        names.add(s.scientific_name)
        taxa[s.taxon.value] = (ev + s.detection_events, names)
    by_taxon = [
        TaxonCount(taxon=_taxon(t), detection_events=ev, species=len(names))
        for t, (ev, names) in sorted(taxa.items())
    ]
    open_alerts = sum(
        sum(sev.values())
        for key, sev in platform.open_alert_counts(org_id).items()
        if site_id is None or key == site_id
    )
    return Dashboard(
        organization_id=org_id,
        period_start=start,
        period_end=end,
        site_ids=sorted({d.site_id for d in days}) if not site_id else [site_id],
        recordings=recordings,
        minutes_recorded=round(minutes, 2),
        species_counted=len(species_rollups),
        detection_events=events,
        richness_by_day=_day_points(days, species, per_site=False),
        species=species_rollups,
        by_taxon=by_taxon,
        activity_heatmap=heatmap,
        indices_by_day=indices,
        quality={k: int(quality.get(k, 0)) for k in QUALITY_KEYS},
        open_alerts=int(open_alerts),
        baseline_note=baseline_note(platform, org_id, recordings),
        generated_at=datetime.now(UTC),
    )


def build_phenology(
    platform: PlatformRepository,
    org_id: str,
    *,
    scientific_name: str,
    site_id: str | None,
    years: int,
) -> Phenology:
    today = datetime.now(UTC).date()
    start = date(today.year - max(1, years) + 1, 1, 1)
    site_ids = [site_id] if site_id else None
    days = platform.site_days(org_id, start=start, end=today, site_ids=site_ids)
    species = platform.species_days(
        org_id, start=start, end=today, site_ids=site_ids, scientific_name=scientific_name
    )
    if not species:
        # Still a valid answer: no detections of that species in the window.
        any_rows = platform.species_days(org_id, scientific_name=scientific_name)
        if not any_rows:
            raise not_found(f"No detections of {scientific_name} in this organization.")
        common, taxon = any_rows[0].common_name, any_rows[0].taxon
    else:
        common, taxon = species[0].common_name, species[0].taxon
    weeks: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    for d in days:
        key = iso_week(d.local_date)
        cell = weeks[key]
        cell[0] += d.recordings
        cell[3] += d.minutes
    first_by_year: dict[int, date] = {}
    last_by_year: dict[int, date] = {}
    for s in species:
        key = iso_week(s.local_date)
        cell = weeks[key]
        cell[1] += s.recordings_with_detection
        cell[2] += s.events
        y = s.local_date.year
        first_by_year[y] = min(first_by_year.get(y, s.local_date), s.local_date)
        last_by_year[y] = max(last_by_year.get(y, s.local_date), s.local_date)
    cells = [
        PhenologyCell(
            year=y,
            iso_week=w,
            recordings=int(c[0]),
            recordings_with_detection=int(c[1]),
            presence_fraction=round(c[1] / c[0], 4) if c[0] else 0.0,
            events_per_minute=round(c[2] / c[3], 4) if c[3] > 0 else 0.0,
        )
        for (y, w), c in sorted(weeks.items())
        if c[0] > 0
    ]
    return Phenology(
        organization_id=org_id,
        site_ids=sorted({d.site_id for d in days}),
        species=SpeciesRef(
            scientific_name=species[0].scientific_name if species else scientific_name,
            common_name=common,
        ),
        taxon=_taxon(taxon),
        cells=cells,
        first_detection_by_year=first_by_year,
        last_detection_by_year=last_by_year,
    )


def build_accumulation(platform: PlatformRepository, org_id: str, site_id: str) -> Accumulation:
    rows = platform.stats_query(org_id, site_id=site_id)
    seen: set[str] = set()
    points: list[AccumulationPoint] = []
    for i, r in enumerate(rows, start=1):
        seen.update((r.species or {}).keys())
        points.append(
            AccumulationPoint(
                recording_index=i, captured_at=r.captured_at, cumulative_species=len(seen)
            )
        )
    return Accumulation(site_id=site_id, points=points)


def build_site_comparison(
    platform: PlatformRepository,
    org_id: str,
    sites: Sequence[Site],
    *,
    start: date | None,
    end: date | None,
) -> SiteComparison:
    start, end = parse_period(start, end)
    days = platform.site_days(org_id, start=start, end=end)
    species = platform.species_days(org_id, start=start, end=end)
    by_site_days: dict[str, list[SiteDayStatsRow]] = defaultdict(list)
    for d in days:
        by_site_days[d.site_id].append(d)
    by_site_species: dict[str, Counter[str]] = defaultdict(Counter)
    names: dict[str, str] = {}
    for s in species:
        by_site_species[s.site_id][s.scientific_name] += s.events
        names[s.scientific_name] = s.common_name
    rows: list[SiteComparisonRow] = []
    for site in sites:
        d_rows = by_site_days.get(site.id, [])
        minutes = sum(r.minutes for r in d_rows)
        events = sum(r.events for r in d_rows)
        counts = by_site_species.get(site.id, Counter())
        rated = [r for r in d_rows if r.usable_fraction is not None]
        n_rated = sum(r.recordings for r in rated)
        usable = (
            round(sum(r.usable_fraction * r.recordings for r in rated) / n_rated, 4)  # type: ignore[operator]
            if n_rated
            else None
        )
        top = [
            SpeciesRef(scientific_name=sci, common_name=names.get(sci, sci))
            for sci, _ in counts.most_common(3)
        ]
        rows.append(
            SiteComparisonRow(
                site=site,
                recordings=sum(r.recordings for r in d_rows),
                minutes=round(minutes, 2),
                species_richness=len(counts),
                events_per_minute=round(events / minutes, 3) if minutes > 0 else 0.0,
                shannon_index=round(shannon_index(list(counts.values())), 4) if counts else None,
                top_species=top,
                usable_fraction=usable,
            )
        )
    return SiteComparison(period_start=start, period_end=end, rows=rows)


def local_today(tz_name: str | None) -> date:
    return local_date(datetime.now(UTC), tz_name)
