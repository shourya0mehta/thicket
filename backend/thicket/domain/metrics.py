"""Detection-derived biodiversity metrics.

All metrics are computed from one collection: consolidated detection events
above the decision threshold, restricted to biodiversity taxa (birds,
amphibians, insects, mammals) and excluding events a reviewer rejected.

Let n_i be the event count for species i, N = sum(n_i), p_i = n_i / N.

* richness S = number of species with at least one event
* Shannon H' = -sum(p_i * ln p_i), natural log, 0 when N = 0
* Pielou J' = H' / ln(S) when S > 1, else 0
* Gini-Simpson D = 1 - sum(p_i^2), 0 when N = 0

These describe how detection events are distributed across species. They are
not estimates of abundance: loud, frequent callers produce more events than
quiet species, and detectability varies with distance, weather and season.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .consolidation import Event, WindowDetection

BIODIVERSITY_TAXA = frozenset({"bird", "amphibian", "insect", "mammal"})


def shannon_index(counts: Sequence[int]) -> float:
    n = sum(counts)
    if n <= 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / n
            h -= p * math.log(p)
    return h


def pielou_evenness(counts: Sequence[int]) -> float:
    s = sum(1 for c in counts if c > 0)
    if s <= 1:
        return 0.0
    return shannon_index(counts) / math.log(s)


def gini_simpson(counts: Sequence[int]) -> float:
    n = sum(counts)
    if n <= 0:
        return 0.0
    return 1.0 - sum((c / n) ** 2 for c in counts)


@dataclass
class SpeciesStats:
    scientific_name: str
    common_name: str
    taxon: str
    model_run_ids: list[str]
    detection_event_count: int
    raw_detection_count: int
    max_confidence: float
    mean_confidence: float
    total_event_duration_seconds: float
    first_detection_seconds: float
    last_detection_seconds: float
    plausibility: str


@dataclass
class MetricSet:
    species_richness: int
    shannon_index: float
    pielou_evenness: float
    simpson_diversity: float
    total_detection_events: int
    raw_detection_count: int
    events_per_minute: float
    dominant_species: tuple[str, str] | None
    events_by_taxon: dict[str, int]


def counted_events(
    events: Iterable[Event],
    rejected_ids: set[str] | None = None,
    include_unlikely: bool = False,
) -> list[Event]:
    """The one event collection every metric, table and chart is built from.

    Excludes non-biodiversity labels (human, noise, engines...), events a
    reviewer rejected, and, unless ``include_unlikely``, events whose species
    failed the range/season plausibility check.
    """
    rejected_ids = rejected_ids or set()
    return [
        e
        for e in events
        if e.taxon in BIODIVERSITY_TAXA
        and e.id not in rejected_ids
        and (include_unlikely or e.plausibility != "unlikely")
    ]


def species_summaries(
    events: Sequence[Event], raw: Sequence[WindowDetection]
) -> list[SpeciesStats]:
    by_species: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        by_species[e.scientific_name].append(e)
    raw_ids = {d.id: d for d in raw}
    out: list[SpeciesStats] = []
    for sci, evs in by_species.items():
        contributing = [
            raw_ids[i] for e in evs for i in e.contributing_detection_ids if i in raw_ids
        ]
        confs = [d.confidence for d in contributing] or [e.max_confidence for e in evs]
        plaus = {e.plausibility for e in evs}
        out.append(
            SpeciesStats(
                scientific_name=sci,
                common_name=evs[0].common_name,
                taxon=evs[0].taxon,
                model_run_ids=sorted({e.model_run_id for e in evs}),
                detection_event_count=len(evs),
                raw_detection_count=len(contributing),
                max_confidence=round(max(e.max_confidence for e in evs), 4),
                mean_confidence=round(sum(confs) / len(confs), 4),
                total_event_duration_seconds=round(sum(e.duration_seconds for e in evs), 3),
                first_detection_seconds=min(e.start_seconds for e in evs),
                last_detection_seconds=max(e.end_seconds for e in evs),
                plausibility="unlikely"
                if "unlikely" in plaus
                else ("plausible" if "plausible" in plaus else "unknown"),
            )
        )
    out.sort(key=lambda s: (-s.detection_event_count, -s.max_confidence, s.common_name))
    return out


def compute_metrics(events: Sequence[Event], duration_seconds: float) -> MetricSet:
    """``events`` must already be the counted set (see :func:`counted_events`)."""
    counts = Counter(e.scientific_name for e in events)
    names = {e.scientific_name: e.common_name for e in events}
    values = list(counts.values())
    dominant = None
    if counts:
        # Ties break on max confidence, then name, so the choice is deterministic.
        best_conf: dict[str, float] = defaultdict(float)
        for e in events:
            best_conf[e.scientific_name] = max(best_conf[e.scientific_name], e.max_confidence)
        sci = sorted(counts, key=lambda s: (-counts[s], -best_conf[s], s))[0]
        dominant = (sci, names[sci])
    minutes = duration_seconds / 60.0 if duration_seconds > 0 else 0.0
    by_taxon = Counter(e.taxon for e in events)
    return MetricSet(
        species_richness=len(counts),
        shannon_index=round(shannon_index(values), 4),
        pielou_evenness=round(pielou_evenness(values), 4),
        simpson_diversity=round(gini_simpson(values), 4),
        total_detection_events=len(events),
        raw_detection_count=sum(e.n_windows for e in events),
        events_per_minute=round(len(events) / minutes, 3) if minutes else 0.0,
        dominant_species=dominant,
        events_by_taxon=dict(sorted(by_taxon.items())),
    )
