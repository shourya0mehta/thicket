"""Recording windows, and gaps measured inside them.

Field recorders rarely run around the clock: an AudioMoth set for the dawn
chorus records from 04:00 to 08:00 and sleeps the rest of the day. Measuring
gaps in wall-clock time would call every night a gap. So a deployment's
**active hours** (local hours of the day in which it records) come first:

* from ``schedule_description`` when it names time ranges such as
  ``04:00-08:00, 18:30-20:00`` (local time; a range may wrap midnight),
* otherwise learned from its recordings: every local hour that any recording
  starts in or runs through.

A gap between two consecutive recordings then counts only the minutes that
fall inside active hours, intervals are inferred from those active minutes,
and uptime compares recordings with the number expected inside active hours.

Gaps are only ever measured *between recordings*, never from "now": SD cards
arrive weeks after they were recorded, and backfilled data is not an outage.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

ALL_HOURS: frozenset[int] = frozenset(range(24))
MIN_INTERVALS_TO_INFER = 3
# "04:00-08:00", "4:30 to 6", "21h00-03h00". Minutes need a separator, so a date
# such as 2024-05-14 is never read as a time range.
_RANGE = re.compile(
    r"\b([01]?\d|2[0-3])(?:[:.h]([0-5]\d))?\s*(?:-|to)\s*([01]?\d|2[0-4])(?:[:.h]([0-5]\d))?\b"
)


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def parse_schedule_hours(text: str | None) -> frozenset[int] | None:
    """Local hours covered by ``HH:MM-HH:MM`` ranges in a schedule description.

    ``"04:00-08:00 and 18:30-20:00"`` gives {4, 5, 6, 7, 18, 19}; a range that
    wraps midnight (``21:00-03:00``) is understood. None when no range is named.
    """
    if not text:
        return None
    hours: set[int] = set()
    found = False
    for m in _RANGE.finditer(text):
        if m.group(2) is None and m.group(4) is None:
            continue  # "3-5" is not a time range
        found = True
        start = int(m.group(1)) * 60 + int(m.group(2) or 0)
        end = int(m.group(3)) * 60 + int(m.group(4) or 0)
        if end == start:
            return ALL_HOURS
        minute = start
        while True:
            hours.add((minute // 60) % 24)
            minute = (minute // 60 + 1) * 60
            if (end > start and minute >= end) or (end < start and minute >= end + 24 * 60):
                break
    return frozenset(hours) if found and hours else None


def learned_hours(recordings: Iterable[tuple[datetime, float]], tz: ZoneInfo) -> frozenset[int]:
    """Local hours any recording starts in or runs through ((start, seconds) pairs)."""
    hours: set[int] = set()
    for start, seconds in recordings:
        t = _aware(start)
        end = t + timedelta(seconds=max(float(seconds or 0.0), 0.0))
        hours.add(t.astimezone(tz).hour)
        # Every local hour boundary crossed before the end.
        probe = t
        while len(hours) < 24:
            local = probe.astimezone(tz)
            nxt = (
                local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            ).astimezone(UTC)
            if nxt <= probe:
                nxt = probe + timedelta(minutes=1)
            if nxt >= end:
                break
            hours.add(nxt.astimezone(tz).hour)
            probe = nxt
    return frozenset(hours)


def active_minutes(start: datetime, end: datetime, tz: ZoneInfo, hours: frozenset[int]) -> float:
    """Minutes of [start, end) that fall in the active local hours."""
    a, b = _aware(start), _aware(end)
    if b <= a or not hours:
        return 0.0
    if hours == ALL_HOURS:
        return (b - a).total_seconds() / 60.0
    total = 0.0
    t = a
    while t < b:
        local = t.astimezone(tz)
        boundary = (
            local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        ).astimezone(UTC)
        if boundary <= t:  # a clock change; move on a minute
            boundary = t + timedelta(minutes=1)
        seg_end = min(boundary, b)
        if local.hour in hours:
            total += (seg_end - t).total_seconds() / 60.0
        t = seg_end
    return total


@dataclass(frozen=True)
class Schedule:
    """Where a recorder is expected to record: its zone and active local hours."""

    tz: ZoneInfo
    hours: frozenset[int]
    source: str  # "declared" (schedule_description) or "learned" (recordings)

    def minutes(self, start: datetime, end: datetime) -> float:
        return active_minutes(start, end, self.tz, self.hours)

    def describe(self) -> str:
        if self.hours == ALL_HOURS:
            return "around the clock"
        return "local hours " + ", ".join(_spans(sorted(self.hours)))


def _spans(hours: Sequence[int]) -> list[str]:
    out: list[str] = []
    start = prev = hours[0]
    for h in [*hours[1:], None]:
        if h is not None and h == prev + 1:
            prev = h
            continue
        out.append(f"{start:02d}:00-{(prev + 1) % 24:02d}:00")
        if h is not None:
            start = prev = h
    return out


def schedule_for(
    recordings: Iterable[tuple[datetime, float]],
    tz_name: str | None,
    schedule_description: str | None = None,
) -> Schedule:
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
    declared = parse_schedule_hours(schedule_description)
    if declared:
        return Schedule(tz=tz, hours=declared, source="declared")
    learned = learned_hours(recordings, tz)
    return Schedule(tz=tz, hours=learned or ALL_HOURS, source="learned")


def active_intervals(times: Sequence[datetime], schedule: Schedule) -> list[float]:
    """Active minutes between consecutive recording starts (sorted times)."""
    return [schedule.minutes(a, b) for a, b in zip(times, times[1:], strict=False)]


def infer_interval(times: Sequence[datetime], schedule: Schedule) -> float | None:
    """Median active-minute interval; needs three positive intervals."""
    intervals = [i for i in active_intervals(times, schedule) if i > 0]
    if len(intervals) < MIN_INTERVALS_TO_INFER:
        return None
    return round(statistics.median(intervals), 3)


@dataclass(frozen=True)
class ActiveGap:
    start: datetime
    end: datetime
    active_hours: float
    expected_recordings: int
    index: int  # position of the recording that ends the gap


def find_active_gaps(
    times: Sequence[datetime],
    schedule: Schedule,
    *,
    interval_minutes: float | None,
    multiplier: float,
    min_hours: float,
) -> list[ActiveGap]:
    """Gaps between consecutive recordings, counted in active minutes only."""
    if len(times) < 2 or not interval_minutes or interval_minutes <= 0:
        return []
    limit = max(multiplier * interval_minutes, min_hours * 60.0)
    gaps: list[ActiveGap] = []
    for i, (a, b) in enumerate(zip(times, times[1:], strict=False), start=1):
        minutes = schedule.minutes(a, b)
        if minutes >= limit:
            gaps.append(
                ActiveGap(
                    start=a,
                    end=b,
                    active_hours=round(minutes / 60.0, 2),
                    expected_recordings=max(0, int(round(minutes / interval_minutes)) - 1),
                    index=i,
                )
            )
    return gaps


def expected_recordings(
    start: datetime, end: datetime, schedule: Schedule, interval_minutes: float
) -> int:
    """Recordings a schedule expects in [start, end], both ends included."""
    if interval_minutes <= 0 or end < start:
        return 0
    return int(schedule.minutes(start, end) / interval_minutes) + 1


def upload_events(created: Iterable[datetime], *, gap_minutes: float = 30.0) -> list[datetime]:
    """Times uploads arrived: recordings created within ``gap_minutes`` of the
    previous one belong to the same upload (a batch creates them in one go)."""
    events: list[datetime] = []
    last: datetime | None = None
    for t in sorted(_aware(x) for x in created):
        if last is None or (t - last).total_seconds() / 60.0 > gap_minutes:
            events.append(t)
        last = t
    return events
