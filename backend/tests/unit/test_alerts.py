"""Alert engine: every kind fires on a synthetic deployment built to trigger it,
nothing fires without a baseline, repeats are deduplicated, and every detail
states the observed value, the baseline and the sample size."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from tests.platform_helpers import insert_analysis

from thicket.api.platform_schemas import AlertRules

A, B = "Turdus migratorius", "Cyanocitta cristata"
FIVE = {
    "Turdus migratorius": 1,
    "Cyanocitta cristata": 1,
    "Haemorhous mexicanus": 1,
    "Poecile atricapillus": 1,
    "Pseudacris crucifer": 1,
}
T0 = datetime(2026, 5, 1, 6, 0, tzinfo=UTC)  # 06:00 UTC: "dawn" with the fixed buckets


@pytest.fixture
def env(container):
    c = container
    org = c.platform.local_org_id()
    site = c.platform.create_site(org, {"name": "North pasture"})
    rec = c.platform.create_recorder(org, {"label": "AM-1", "make": "audiomoth"})
    dep = c.platform.create_deployment(
        org, {"recorder_id": rec.id, "site_id": site.id, "started_at": T0 - timedelta(days=30)}
    )
    return c, org, site, rec, dep


def add(env, when, **kw):
    c, org, site, rec, dep = env
    kw.setdefault("species", FIVE)
    return insert_analysis(
        c, site_id=site.id, recorder_id=rec.id, deployment_id=dep.id, captured_at=when, **kw
    )


def baseline(env, n=10, **kw):
    return [add(env, T0 + timedelta(days=i), **kw) for i in range(n)]


def kinds(rows):
    return sorted({r.kind for r in rows})


def evaluate(env, aid):
    return env[0].alerts.evaluate_analysis(aid)


def assert_plain_detail(row):
    d = row.detail
    assert d.startswith("Observed") or "Observed" in d, d
    assert "baseline" in d and re.search(r"n = \d+", d), d
    assert "\u2014" not in d and "\u2014" not in row.title
    for word in ("individuals", "population", "abundance"):
        assert word not in d.lower() and word not in row.title.lower()
    ev = row.evidence
    assert "n" in ev and ("observed" in ev or "observed_gap_hours" in ev)


# ----------------------------------------------------------------- ecology


def test_richness_and_activity_drop_need_consecutive_recordings(env):
    baseline(env)
    later = T0 + timedelta(days=10)
    low = {A: 1}
    aid1, _ = add(env, later, species=low)
    assert not {"richness_drop", "activity_drop"} & set(kinds(evaluate(env, aid1)))
    add(env, later + timedelta(days=1), species=low)
    aid3, _ = add(env, later + timedelta(days=2), species=low)
    rows = evaluate(env, aid3)
    by_kind = {r.kind: r for r in rows}
    drop = by_kind["richness_drop"]
    assert drop.category == "ecology" and drop.severity == "watch"  # z = -4, warning at -4.5
    assert drop.evidence["observed"] == [1.0, 1.0, 1.0] and drop.evidence["baseline_median"] == 5
    assert drop.evidence["n"] == 12 and "dawn" in drop.detail
    assert len(drop.recording_ids) == 3
    act = by_kind["activity_drop"]
    assert act.severity == "warning"  # 1 vs 5 per minute with a 0.05 floor
    for r in rows:
        assert_plain_detail(r)


def test_no_baseline_fires_no_ecology_or_recorder_alert(env):
    for i in range(3):
        aid, _ = add(env, T0 + timedelta(days=i), species={A: 1}, profile={"rms_dbfs": -80.0})
    rows = evaluate(env, aid)
    assert rows == []
    assert env[0].alerts.nightly(env[1]) == []


def test_new_species_for_site(env):
    baseline(env, species={A: 1})
    aid, _ = add(env, T0 + timedelta(days=11), species={A: 1, "Dolichonyx oryzivorus": 1})
    rows = [r for r in evaluate(env, aid) if r.kind == "new_species_for_site"]
    assert len(rows) == 1
    r = rows[0]
    assert r.species_scientific_name == "Dolichonyx oryzivorus" and r.severity == "info"
    assert "first time" in r.detail and r.evidence["n"] == 10
    assert_plain_detail(r)


def test_priority_species_needs_no_baseline(env):
    c, org, *_ = env
    c.alerts.put_rules(org, AlertRules(priority_species=["Dolichonyx oryzivorus"]))
    aid, _ = add(env, T0, species={"Dolichonyx oryzivorus": 2})
    rows = evaluate(env, aid)
    assert kinds(rows) == ["priority_species_detected"]
    assert rows[0].species_common_name == "Bobolink" and rows[0].evidence["observed"] == 2
    assert_plain_detail(rows[0])


def test_species_surge(env):
    baseline(env, species={A: 2})
    aid, _ = add(env, T0 + timedelta(days=11), species={A: 8})
    rows = [r for r in evaluate(env, aid) if r.kind == "species_surge"]
    assert len(rows) == 1 and rows[0].evidence["observed"] == 8
    assert rows[0].evidence["baseline_median"] == 2 and rows[0].evidence["robust_z"] == 6.0
    assert_plain_detail(rows[0])


def test_expected_species_missing(env):
    c, org, *_ = env
    baseline(env, species={A: 1, B: 1})
    for i in range(6):
        add(env, T0 + timedelta(days=10 + i), species={B: 1})
    rows = c.alerts.nightly(org)
    missing = [r for r in rows if r.kind == "expected_species_missing"]
    assert len(missing) == 1 and missing[0].species_scientific_name == A
    assert "Not detected in this effort" in missing[0].detail
    assert missing[0].evidence["baseline_presence_fraction"] == 1.0
    assert_plain_detail(missing[0])


# ----------------------------------------------------------------- quality


def test_speech_detected(env):
    aid, _ = add(env, T0, speech=True)
    rows = evaluate(env, aid)
    assert kinds(rows) == ["speech_detected"] and rows[0].category == "quality"
    assert_plain_detail(rows[0])


def test_low_quality_streak(env):
    add(env, T0, quality_status="not_usable")
    aid2, _ = add(env, T0 + timedelta(hours=1), quality_status="not_usable")
    assert "low_quality_streak" not in kinds(evaluate(env, aid2))
    aid3, _ = add(env, T0 + timedelta(hours=2), quality_status="not_usable")
    rows = [r for r in evaluate(env, aid3) if r.kind == "low_quality_streak"]
    assert len(rows) == 1 and rows[0].severity == "warning" and len(rows[0].recording_ids) == 3
    assert_plain_detail(rows[0])


# ---------------------------------------------------------------- recorder


def test_muffled_audio(env):
    baseline(env)
    muffled = {
        "band_fraction_0_1k": 0.80,
        "band_fraction_1_4k": 0.15,
        "band_fraction_4_8k": 0.03,
        "band_fraction_8k_plus": 0.02,
        "spectral_centroid_hz": 600.0,
    }
    later = T0 + timedelta(days=10)
    for i in range(2):
        aid, _ = add(env, later + timedelta(hours=i), profile=muffled)
        assert "muffled_audio" not in kinds(evaluate(env, aid))
    aid, _ = add(env, later + timedelta(hours=2), profile=muffled)
    rows = [r for r in evaluate(env, aid) if r.kind == "muffled_audio"]
    assert len(rows) == 1
    r = rows[0]
    assert r.category == "recorder" and r.severity == "warning"
    assert r.suggested_action == (
        "Check the windscreen and microphone port for water, debris or spider webs, and "
        "confirm the recorder has not been turned toward a wall or into vegetation."
    )
    assert r.evidence["observed"]["high_band_fraction"] == 0.05
    assert r.evidence["baseline_median"]["spectral_centroid_hz"] == 2500.0
    assert "600 Hz" in r.detail and "2500 Hz" in r.detail
    assert_plain_detail(r)


@pytest.mark.parametrize("rms, severity", [(-50.0, "watch"), (-55.0, "warning"), (-31.0, "watch")])
def test_level_drift(env, rms, severity):
    baseline(env)
    aid, _ = add(env, T0 + timedelta(days=11), profile={"rms_dbfs": rms})
    rows = [r for r in evaluate(env, aid) if r.kind == "level_drift"]
    assert len(rows) == 1 and rows[0].severity == severity
    assert rows[0].evidence["baseline_median"] == -40.0
    assert_plain_detail(rows[0])


def test_small_level_change_does_not_fire(env):
    baseline(env)
    aid, _ = add(env, T0 + timedelta(days=11), profile={"rms_dbfs": -44.0})
    assert "level_drift" not in kinds(evaluate(env, aid))


def test_clipping_increase(env):
    baseline(env)
    for i in range(3):
        aid, _ = add(env, T0 + timedelta(days=10, hours=i), profile={"clipping_fraction": 0.02})
    rows = [r for r in evaluate(env, aid) if r.kind == "clipping_increase"]
    assert len(rows) == 1 and rows[0].evidence["observed"] == [0.02, 0.02, 0.02]
    assert_plain_detail(rows[0])


def test_channel_imbalance_and_dc_offset(env):
    aid, _ = add(
        env, T0, channels=2, profile={"channel_rms_dbfs": [-40.0, -60.0], "dc_offset": 0.05}
    )
    rows = evaluate(env, aid)
    assert kinds(rows) == ["channel_imbalance", "dc_offset"]
    imb = next(r for r in rows if r.kind == "channel_imbalance")
    assert imb.evidence["observed"] == 20.0
    for r in rows:
        assert_plain_detail(r)


@pytest.mark.parametrize(
    "make, volts, fires",
    [
        ("audiomoth", 3.4, True),
        ("audiomoth", 3.7, False),
        ("song_meter", 4.5, True),
        ("song_meter", 4.7, False),
    ],
)
def test_battery_low_per_make(env, make, volts, fires):
    c, org, site, rec, dep = env
    c.platform.update_recorder(rec.id, {"make": make})
    aid, _ = add(env, T0, telemetry={"battery_v": volts, "source": "audiomoth_comment"})
    rows = [r for r in evaluate(env, aid) if r.kind == "battery_low"]
    assert bool(rows) is fires
    if rows:
        assert rows[0].evidence["make"] == make
        assert_plain_detail(rows[0])


def test_temperature_extreme(env):
    aid, _ = add(env, T0, telemetry={"temperature_c": 55.0, "source": "guano"})
    rows = [r for r in evaluate(env, aid) if r.kind == "temperature_extreme"]
    assert len(rows) == 1 and rows[0].evidence["observed"] == 55.0
    assert_plain_detail(rows[0])


def test_recording_gap(env):
    c, org, site, rec, dep = env
    now = datetime.now(UTC).replace(microsecond=0)
    start = now - timedelta(hours=8)
    for i in range(12):
        add(env, start + timedelta(minutes=10 * i))  # last one 6 h 10 min ago
    rows = [r for r in c.alerts.nightly(org) if r.kind == "recording_gap"]
    assert len(rows) == 1
    r = rows[0]
    assert r.severity == "warning" and r.deployment_id == dep.id
    assert r.evidence["baseline_median_interval_minutes"] == 10.0 and r.evidence["n"] == 11
    assert 6.0 < r.evidence["observed_gap_hours"] < 6.5 and r.evidence["limit_hours"] == 2.0
    assert_plain_detail(r)


def test_no_gap_when_recent(env):
    c, org, *_ = env
    now = datetime.now(UTC)
    for i in range(6):
        add(env, now - timedelta(minutes=10 * (6 - i)))
    assert [r for r in c.alerts.nightly(org) if r.kind == "recording_gap"] == []


def test_schedule_deviation(env):
    c, org, site, rec, dep = env
    c.platform.update_deployment(dep.id, {"expected_interval_minutes": 10.0})
    for i in range(10):
        add(env, T0 + timedelta(minutes=10 * i))
    aid, _ = add(env, T0 + timedelta(minutes=90 + 30))
    rows = [r for r in evaluate(env, aid) if r.kind == "schedule_deviation"]
    assert len(rows) == 1 and rows[0].evidence == {"observed": 30.0, "baseline": 10.0, "n": 1}
    assert_plain_detail(rows[0])


def test_clock_suspect_for_a_batch(env):
    c, org, site, rec, dep = env
    job = c.platform.create_job(
        org,
        site_id=site.id,
        deployment_id=dep.id,
        recorder_id=rec.id,
        settings={},
        filenames=["a_1.wav", "a_2.wav", "a_3.wav", "a_4.wav"],
        created_by=None,
    )
    times = [
        T0,
        T0 - timedelta(hours=1),
        T0 - timedelta(hours=1),
        datetime.now(UTC) + timedelta(days=30),
    ]
    for i, t in enumerate(times):
        c.platform.update_item(
            job.id,
            i,
            {"captured_at": t, "status": "completed", "captured_at_source": "file_metadata"},
        )
    rows = c.alerts.evaluate_batch(job.id)
    assert kinds(rows) == ["clock_suspect"]
    obs = rows[0].evidence["observed"]
    assert obs == {"out_of_order": 1, "duplicates": 1, "future": 1}
    assert_plain_detail(rows[0])


def test_clean_batch_has_no_clock_alert(env):
    c, org, site, *_ = env
    job = c.platform.create_job(
        org,
        site_id=site.id,
        deployment_id=None,
        recorder_id=None,
        settings={},
        filenames=["1.wav", "2.wav"],
        created_by=None,
    )
    for i in range(2):
        c.platform.update_item(job.id, i, {"captured_at": T0 + timedelta(hours=i)})
    assert c.alerts.evaluate_batch(job.id) == []


# ------------------------------------------------------- lifecycle and rules


def test_dedupe_updates_the_open_alert(env):
    c, org, *_ = env
    aid, _ = add(env, T0, speech=True)
    first = evaluate(env, aid)[0]
    aid2, _ = add(env, T0 + timedelta(hours=1), speech=True)
    second = evaluate(env, aid2)[0]
    assert second.id == first.id and second.occurrences == 2
    assert set(second.recording_ids) == {first.recording_ids[0], second.recording_ids[-1]}
    rows, total, by_status, _ = c.platform.list_alerts(org)
    assert total == 1 and by_status == {"open": 1}
    # Once resolved, a new occurrence opens a new alert.
    c.platform.update_alert(first.id, {"status": "resolved"})
    aid3, _ = add(env, T0 + timedelta(hours=2), speech=True)
    third = evaluate(env, aid3)[0]
    assert third.id != first.id and third.occurrences == 1


def test_disabled_rules_and_setting(env):
    c, org, *_ = env
    c.alerts.put_rules(org, AlertRules(enabled=False))
    aid, _ = add(env, T0, speech=True)
    assert evaluate(env, aid) == []
    c.alerts.put_rules(org, AlertRules())
    c.alerts.settings = c.alerts.settings.model_copy(update={"alerts_enabled": False})
    assert evaluate(env, aid) == []


def test_corrupt_stored_rules_fall_back_to_defaults(env):
    c, org, *_ = env
    c.platform.put_alert_rules(org, {"min_baseline_recordings": "lots"})
    assert c.alerts.rules(org) == AlertRules()


def test_snoozed_alerts_reopen_when_due(env):
    c, org, *_ = env
    aid, _ = add(env, T0, speech=True)
    row = evaluate(env, aid)[0]
    c.platform.update_alert(
        row.id, {"status": "snoozed", "snoozed_until": datetime.now(UTC) - timedelta(minutes=1)}
    )
    assert c.platform.unsnooze_due() == 1
    assert c.platform.get_alert(row.id).status == "open"


def test_evaluate_org_runs_over_recent_recordings(env):
    c, org, *_ = env
    add(env, T0, telemetry={"battery_v": 3.0, "source": "audiomoth_comment"})
    rows = c.alerts.evaluate_org(org)
    assert "battery_low" in kinds(rows)
    assert c.alerts.evaluate_org(org) and c.platform.list_alerts(org)[1] == 1
