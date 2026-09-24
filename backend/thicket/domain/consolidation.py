"""Turn per-window model outputs into detection events.

A model emits one score per analysis window. Several adjacent windows usually
belong to one continuous call bout, so for each species (and model run) we
merge windows that overlap or sit within ``merge_gap_seconds`` of each other.

An event is a stretch of audio in which a species was detected. It is not an
individual animal: one animal can produce many events and several animals can
share one.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WindowDetection:
    """Canonical raw detection used by the domain layer."""

    id: str
    model_run_id: str
    label_raw: str
    scientific_name: str
    common_name: str
    taxon: str
    start_seconds: float
    end_seconds: float
    confidence: float
    plausibility: str = "unknown"


@dataclass
class Event:
    id: str
    scientific_name: str
    common_name: str
    taxon: str
    model_run_id: str
    start_seconds: float
    end_seconds: float
    max_confidence: float
    mean_confidence: float
    contributing_detection_ids: list[str] = field(default_factory=list)
    plausibility: str = "unknown"

    @property
    def n_windows(self) -> int:
        return len(self.contributing_detection_ids)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def event_id(
    analysis_id: str, model_run_id: str, scientific_name: str, start: float, end: float
) -> str:
    """Deterministic id: the same analysis + threshold always yields the same ids.

    That lets review decisions stick to an event across threshold changes when
    the event's extent is unchanged.
    """
    key = f"{analysis_id}|{model_run_id}|{scientific_name}|{start:.3f}|{end:.3f}"
    return "evt_" + hashlib.sha1(key.encode()).hexdigest()[:16]


def filter_by_threshold(dets: Iterable[WindowDetection], threshold: float) -> list[WindowDetection]:
    """Inclusive: a window at exactly the threshold is kept."""
    eps = 1e-9
    return [d for d in dets if d.confidence + eps >= threshold]


def consolidate(
    detections: Sequence[WindowDetection],
    threshold: float,
    merge_gap_seconds: float = 1.0,
    analysis_id: str = "",
) -> list[Event]:
    """Filter by ``threshold`` then merge per (model run, species).

    Two windows merge when ``next.start - current.end <= merge_gap_seconds``.
    Overlapping windows (negative gap) always merge. Events come back sorted by
    start time, then scientific name, so output is deterministic.
    """
    if merge_gap_seconds < 0:
        raise ValueError("merge_gap_seconds must be >= 0")
    groups: dict[tuple[str, str], list[WindowDetection]] = defaultdict(list)
    for d in filter_by_threshold(detections, threshold):
        groups[(d.model_run_id, d.scientific_name)].append(d)

    events: list[Event] = []
    for (run_id, sci), dets in groups.items():
        dets.sort(key=lambda d: (d.start_seconds, d.end_seconds, d.id))
        cluster: list[WindowDetection] = [dets[0]]
        cur_end = dets[0].end_seconds
        for d in dets[1:]:
            if d.start_seconds - cur_end <= merge_gap_seconds + 1e-9:
                cluster.append(d)
                cur_end = max(cur_end, d.end_seconds)
            else:
                events.append(_make_event(cluster, run_id, sci, analysis_id))
                cluster = [d]
                cur_end = d.end_seconds
        events.append(_make_event(cluster, run_id, sci, analysis_id))
    events.sort(key=lambda e: (e.start_seconds, e.scientific_name, e.model_run_id))
    return events


def _make_event(cluster: list[WindowDetection], run_id: str, sci: str, analysis_id: str) -> Event:
    start = min(d.start_seconds for d in cluster)
    end = max(d.end_seconds for d in cluster)
    confs = [d.confidence for d in cluster]
    plaus = {d.plausibility for d in cluster}
    plausibility = (
        "unlikely" if "unlikely" in plaus else ("plausible" if "plausible" in plaus else "unknown")
    )
    first = cluster[0]
    return Event(
        id=event_id(analysis_id, run_id, sci, start, end),
        scientific_name=sci,
        common_name=first.common_name,
        taxon=first.taxon,
        model_run_id=run_id,
        start_seconds=round(start, 3),
        end_seconds=round(end, 3),
        max_confidence=round(max(confs), 4),
        mean_confidence=round(sum(confs) / len(confs), 4),
        contributing_detection_ids=[d.id for d in cluster],
        plausibility=plausibility,
    )
