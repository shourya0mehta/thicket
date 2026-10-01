"""Hour buckets (fixed and sun-based), local dates and season windows."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from thicket.domain.timebuckets import (
    fixed_bucket,
    hour_bucket,
    iso_week,
    local_date,
    season_weeks,
)

NY = ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    "hour, bucket",
    [
        (3, "night"),
        (4, "dawn"),
        (8, "dawn"),
        (9, "day"),
        (16, "day"),
        (17, "dusk"),
        (20, "dusk"),
        (21, "night"),
        (0, "night"),
    ],
)
def test_fixed_buckets(hour, bucket):
    assert fixed_bucket(hour) == bucket
    assert hour_bucket(datetime(2026, 5, 14, hour, 0, tzinfo=NY)) == bucket


def test_sun_based_buckets_in_ithaca_in_may():
    # Sunrise is about 05:40 and sunset about 20:20 local time.
    def b(h, m=0):
        return hour_bucket(datetime(2026, 5, 14, h, m, tzinfo=NY), 42.44, -76.50)

    assert b(4, 0) == "night"
    assert b(5, 0) == "dawn"
    assert b(7, 30) == "dawn"
    assert b(8, 0) == "day"
    assert b(19, 30) == "dusk"
    assert b(21, 0) == "dusk"
    assert b(22, 0) == "night"


def test_polar_day_falls_back_to_fixed_hours():
    oslo = ZoneInfo("Europe/Oslo")
    ts = datetime(2026, 6, 21, 6, 0, tzinfo=oslo)
    assert hour_bucket(ts, 78.2, 15.6) == fixed_bucket(6)


def test_local_date_uses_the_zone():
    ts = datetime(2026, 5, 15, 2, 30, tzinfo=UTC)  # 22:30 on the 14th in New York
    assert local_date(ts, "America/New_York") == date(2026, 5, 14)
    assert local_date(ts, "UTC") == date(2026, 5, 15)
    assert local_date(ts, "Not/AZone") == date(2026, 5, 15)


def test_iso_week_and_season_window_wraps():
    assert iso_week(date(2026, 1, 1)) == (2026, 1)
    assert season_weeks((2026, 20)) == {17, 18, 19, 20, 21, 22, 23}
    assert season_weeks((2026, 1)) == {51, 52, 53, 1, 2, 3, 4}


def test_season_window_is_symmetric_around_new_year():
    """ISO week numbers modulo 53 dropped 3 weeks back from week 1 in a 52-week year."""
    from thicket.domain.timebuckets import in_season_window, season_distance_days

    new_year = date(2026, 1, 1)  # ISO week 1 of 2026; 2025 has 52 weeks
    assert season_distance_days(date(2025, 12, 11), new_year) == 21  # ISO week 50
    assert in_season_window(date(2025, 12, 11), new_year)
    assert not in_season_window(date(2025, 12, 10), new_year)
    christmas_eve = date(2025, 12, 24)  # ISO week 52
    assert in_season_window(date(2025, 1, 14), christmas_eve)  # ISO week 3, a year earlier
    assert season_distance_days(date(2024, 2, 29), date(2025, 2, 28)) == 0
    assert season_distance_days(date(2026, 7, 1), date(2020, 7, 1)) == 0
    assert season_distance_days(date(2026, 1, 1), date(2026, 7, 2)) == 182


def test_alert_baselines_use_the_same_window_across_new_year():
    from datetime import UTC, datetime

    from thicket.persistence.db import RecordingStatsRow
    from thicket.services.alerts import AlertEngine

    def row(d: date) -> RecordingStatsRow:
        y, w = d.isocalendar()[0], d.isocalendar()[1]
        return RecordingStatsRow(
            recording_id=f"rec_{d.isoformat()}",
            hour_bucket="dawn",
            local_date=d,
            iso_year=y,
            iso_week=w,
            captured_at=datetime(d.year, d.month, d.day, 6, tzinfo=UTC),
        )

    current = row(date(2026, 1, 1))
    # A year back, so the eight-week fallback cannot pick them: ISO weeks 50, 50 and 4.
    history = [row(date(2024, 12, 11)), row(date(2024, 12, 15)), row(date(2025, 1, 20))]
    history.append(row(date(2024, 11, 30)))  # 32 days off: outside
    picked, description = AlertEngine.comparable(history, current, 3)
    assert {r.local_date for r in picked} == {
        date(2024, 12, 11),
        date(2024, 12, 15),
        date(2025, 1, 20),
    }
    assert "within 21 days of 01 January across years" in description
