"""Recorder health: gaps, intervals, uptime, series and checks."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.platform_helpers import insert_analysis

from thicket.services.recorder_health import find_gaps, infer_interval_minutes

NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def test_find_gaps_and_expected_recordings():
    t = [NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=8), NOW + timedelta(hours=9)]
    gaps = find_gaps(t, interval_minutes=60, multiplier=3, min_hours=2)
    assert len(gaps) == 1
    g = gaps[0]
    assert g.hours == 7.0 and g.expected_recordings == 6 and g.start == t[1] and g.end == t[2]
    # The minimum gap length wins over the multiplier for short intervals.
    t2 = [NOW + timedelta(minutes=5 * i) for i in range(4)] + [NOW + timedelta(minutes=15 + 90)]
    assert find_gaps(t2, interval_minutes=5, multiplier=3, min_hours=2) == []
    assert find_gaps(t, interval_minutes=None, multiplier=3, min_hours=2) == []


def test_infer_interval():
    t = [NOW + timedelta(minutes=10 * i) for i in range(5)]
    assert infer_interval_minutes(t) == 10.0
    assert infer_interval_minutes(t[:3]) is None  # needs three intervals
    t_dup = [
        NOW,
        NOW,
        NOW + timedelta(minutes=10),
        NOW + timedelta(minutes=20),
        NOW + timedelta(minutes=30),
    ]
    assert infer_interval_minutes(t_dup) == 10.0


@pytest.fixture
def deployed(container):
    c = container
    org = c.platform.local_org_id()
    site = c.platform.create_site(org, {"name": "Health site"})
    rec = c.platform.create_recorder(org, {"label": "AM-H", "make": "audiomoth"})
    dep = c.platform.create_deployment(
        org,
        {
            "recorder_id": rec.id,
            "site_id": site.id,
            "started_at": NOW - timedelta(days=10),
            "expected_interval_minutes": 60.0,
        },
    )
    return c, org, site, rec, dep


def health(c, rec, dep, days=30):
    return c.health.build(
        c.platform.get_recorder(rec.id),
        c.services.recorder_model(c.platform.get_recorder(rec.id)),
        c.services.deployment_model(dep) if dep else None,
        dep,
        days=days,
    )


def test_health_series_gaps_and_uptime(deployed):
    c, org, site, rec, dep = deployed
    hours = [h for h in range(48, 0, -1) if not 20 <= h <= 25]  # a 7 hour gap
    for h in hours:
        insert_analysis(
            c,
            site_id=site.id,
            recorder_id=rec.id,
            deployment_id=dep.id,
            captured_at=NOW - timedelta(hours=h),
            telemetry={"battery_v": 4.1, "temperature_c": 15.0, "source": "audiomoth_comment"},
        )
    h = health(c, rec, dep)
    assert len(h.level_dbfs) == len(h.battery) == len(h.high_band_fraction) == 42
    assert h.high_band_fraction[0].v == pytest.approx(0.3)
    assert h.median_interval_minutes == 60.0 and h.expected_last_7d == 168
    assert h.recordings_last_7d == 42 and h.uptime_fraction_7d == pytest.approx(0.25)
    assert len(h.gaps) == 1 and h.gaps[0].hours == 7.0 and h.gaps[0].expected_recordings == 6
    checks = {c_.name: c_ for c_ in h.checks}
    assert checks["gaps"].status == "attention" and checks["uptime_7d"].status == "attention"
    assert checks["battery"].status == "good" and checks["battery"].baseline == 3.6
    assert checks["level_dbfs"].status == "good" and checks["level_dbfs"].baseline == -40.0
    assert checks["temperature"].status == "good"
    assert h.status == "attention" and h.last_recording_at == NOW - timedelta(hours=1)
    assert "Declared interval 60 min" in h.baseline_note


def test_health_flags_a_muffled_latest_recording(deployed):
    c, org, site, rec, dep = deployed
    for i in range(10, 1, -1):
        insert_analysis(
            c,
            recorder_id=rec.id,
            deployment_id=dep.id,
            site_id=site.id,
            captured_at=NOW - timedelta(hours=i),
        )
    insert_analysis(
        c,
        recorder_id=rec.id,
        deployment_id=dep.id,
        site_id=site.id,
        captured_at=NOW - timedelta(hours=1),
        profile={
            "band_fraction_4_8k": 0.02,
            "band_fraction_8k_plus": 0.01,
            "spectral_centroid_hz": 400.0,
            "rms_dbfs": -60.0,
        },
    )
    checks = {c_.name: c_ for c_ in health(c, rec, dep).checks}
    assert checks["high_band_fraction"].status == "attention"
    assert checks["spectral_centroid_hz"].status == "attention"
    assert checks["level_dbfs"].status == "attention"


def test_health_without_recordings_or_interval(container):
    c = container
    rec = c.platform.create_recorder(c.platform.local_org_id(), {"label": "idle"})
    h = health(c, rec, None)
    assert h.status == "unknown" and h.checks[0].name == "recordings"
    assert h.uptime_fraction_7d is None and h.median_interval_minutes is None
    assert "No timestamped recordings" in h.baseline_note


def test_inferred_interval_is_used_when_none_is_declared(container):
    c = container
    org = c.platform.local_org_id()
    rec = c.platform.create_recorder(org, {"label": "inferred", "make": "song_meter"})
    for i in range(6, 0, -1):
        insert_analysis(
            c,
            recorder_id=rec.id,
            captured_at=NOW - timedelta(minutes=30 * i),
            telemetry={"battery_v": 4.5},
        )
    h = health(c, rec, None)
    assert h.median_interval_minutes == 30.0 and h.expected_last_7d == 336
    battery = next(x for x in h.checks if x.name == "battery")
    assert battery.status == "attention" and battery.baseline == 4.6
    assert "Inferred interval 30 min" in h.baseline_note


def test_health_endpoint(make_platform_client):
    client = make_platform_client()
    c = client.app.state.container
    org = c.platform.local_org_id()
    rec = c.platform.create_recorder(org, {"label": "api"})
    for i in range(5, 0, -1):
        insert_analysis(c, recorder_id=rec.id, captured_at=NOW - timedelta(hours=i))
    r = client.get(f"/api/v1/recorders/{rec.id}/health?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recorder"]["id"] == rec.id and body["deployment"] is None
    assert body["median_interval_minutes"] == 60.0 and len(body["level_dbfs"]) == 5
    assert client.get(f"/api/v1/recorders/{rec.id}/health?days=0").status_code == 422
