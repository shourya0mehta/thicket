"""Local dates, ISO weeks and hour buckets (dawn, day, dusk, night).

Baselines compare like with like: a dawn chorus recording against other
dawn recordings. With site coordinates the buckets follow the sun
(``astral``): dawn is one hour before sunrise to two hours after, dusk one
hour either side of sunset, day in between, night the rest. Without
coordinates (or at polar latitudes where the sun does not rise or set) fixed
local hours apply: 04 to 09 dawn, 09 to 17 day, 17 to 21 dusk, 21 to 04 night.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HourBucket = str  # "dawn" | "day" | "dusk" | "night"
BUCKETS = ("dawn", "day", "dusk", "night")


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_local(ts: datetime, tz_name: str | None) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(zone(tz_name))


def local_date(ts: datetime, tz_name: str | None) -> date:
    return to_local(ts, tz_name).date()


def iso_week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return iso[0], iso[1]


def fixed_bucket(hour: int) -> HourBucket:
    if 4 <= hour < 9:
        return "dawn"
    if 9 <= hour < 17:
        return "day"
    if 17 <= hour < 21:
        return "dusk"
    return "night"


@lru_cache(maxsize=4096)
def _sun_times(lat: float, lon: float, day: date, tz_name: str) -> tuple[datetime, datetime] | None:
    try:
        from astral import Observer
        from astral.sun import sun
    except ImportError:  # pragma: no cover - astral is a declared dependency
        return None
    try:
        s = sun(Observer(latitude=lat, longitude=lon), date=day, tzinfo=zone(tz_name))
        return s["sunrise"], s["sunset"]
    except (ValueError, TypeError):
        return None


def hour_bucket(
    local_ts: datetime, latitude: float | None = None, longitude: float | None = None
) -> HourBucket:
    """Bucket for a timezone-aware local timestamp (sun-based when coordinates exist)."""
    if latitude is None or longitude is None or local_ts.tzinfo is None:
        return fixed_bucket(local_ts.hour)
    tz_name = getattr(local_ts.tzinfo, "key", None) or "UTC"
    times = _sun_times(round(latitude, 3), round(longitude, 3), local_ts.date(), tz_name)
    if times is None:
        return fixed_bucket(local_ts.hour)
    sunrise, sunset = times
    dawn_start, dawn_end = sunrise - timedelta(hours=1), sunrise + timedelta(hours=2)
    dusk_start, dusk_end = sunset - timedelta(hours=1), sunset + timedelta(hours=1)
    if dawn_start <= local_ts < dawn_end:
        return "dawn"
    if dusk_start <= local_ts < dusk_end:
        return "dusk"
    if dawn_end <= local_ts < dusk_start:
        return "day"
    return "night"


SEASON_HALF_WIDTH_DAYS = 21


def season_distance_days(a: date, b: date) -> int:
    """Days between two dates' places in the year, on a 365-day circle.

    15 December and 5 January are 21 days apart whatever the years, so a season
    window around New Year is as wide as any other (ISO week numbers modulo 53
    made it lopsided in 52-week years). 29 February counts as 28 February.
    """

    def place(d: date) -> int:
        return date(2001, d.month, min(d.day, 28) if d.month == 2 else d.day).timetuple().tm_yday

    gap = abs(place(a) - place(b))
    return min(gap, 365 - gap)


def in_season_window(a: date, b: date, half_width_days: int = SEASON_HALF_WIDTH_DAYS) -> bool:
    return season_distance_days(a, b) <= half_width_days


def season_weeks(center: tuple[int, int], half_width: int = 3) -> set[int]:
    """ISO week numbers within ``half_width`` of the center week, wrapping the year.

    Kept for callers that still think in weeks; baselines use
    :func:`in_season_window`, which does not skew at the turn of the year."""
    _, week = center
    return {((week - 1 + k) % 53) + 1 for k in range(-half_width, half_width + 1)}
