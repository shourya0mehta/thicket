"""Sites, recorders, deployments and recordings (local workspace)."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.platform_helpers import insert_analysis

from thicket.ids import LOCAL_ORG_ID

API = "/api/v1"
ORG = LOCAL_ORG_ID


@pytest.fixture
def client(make_platform_client):
    return make_platform_client()


def site(client, **kw):
    body = {"name": "North pasture", "latitude": 42.44, "longitude": -76.5, **kw}
    r = client.post(f"{API}/orgs/{ORG}/sites", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def recorder(client, **kw):
    r = client.post(
        f"{API}/orgs/{ORG}/recorders", json={"label": "AM-1", "make": "audiomoth", **kw}
    )
    assert r.status_code == 201, r.text
    return r.json()


def deployment(client, recorder_id, site_id, **kw):
    body = {
        "recorder_id": recorder_id,
        "site_id": site_id,
        "started_at": "2026-05-01T00:00:00Z",
        **kw,
    }
    r = client.post(f"{API}/orgs/{ORG}/deployments", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_site_crud(client):
    s = site(
        client, habitat_type="pasture", area_hectares=4.2, fsa_field_number="4", paddock_id="P4"
    )
    assert s["organization_id"] == ORG and s["habitat_type"] == "pasture"
    assert s["stats"] == {
        "recordings": 0,
        "minutes_recorded": 0.0,
        "first_recording_at": None,
        "last_recording_at": None,
        "species_counted": 0,
        "open_alerts": 0,
        "health": "unknown",
    }
    assert [x["id"] for x in client.get(f"{API}/orgs/{ORG}/sites").json()] == [s["id"]]
    r = client.patch(f"{API}/sites/{s['id']}", json={"name": "North pasture east", "notes": "gate"})
    assert r.status_code == 200 and r.json()["name"] == "North pasture east"
    assert client.get(f"{API}/sites/{s['id']}").json()["notes"] == "gate"
    assert client.delete(f"{API}/sites/{s['id']}").status_code == 204
    assert client.get(f"{API}/sites/{s['id']}").status_code == 404


def test_site_validation(client):
    r = client.post(f"{API}/orgs/{ORG}/sites", json={"name": "X", "latitude": 42.0})
    assert r.status_code == 422
    r = client.post(f"{API}/orgs/{ORG}/sites", json={"name": "X", "latitude": 95, "longitude": 0})
    assert r.status_code == 422
    r = client.post(f"{API}/orgs/{ORG}/sites", json={"name": "X", "habitat_type": "moon"})
    assert r.status_code == 422
    assert client.get(f"{API}/sites/site_nope").status_code == 404


def test_site_with_recordings_cannot_be_deleted(client):
    s = site(client)
    c = client.app.state.container
    insert_analysis(
        c, site_id=s["id"], captured_at=datetime.now(UTC), species={"Turdus migratorius": 2}
    )
    r = client.delete(f"{API}/sites/{s['id']}")
    assert r.status_code == 409 and r.json()["error_code"] == "conflict"
    assert r.json()["detail"] == {"recordings": 1}
    got = client.get(f"{API}/sites/{s['id']}").json()
    assert got["stats"]["recordings"] == 1 and got["stats"]["species_counted"] == 1
    assert got["stats"]["minutes_recorded"] == 1.0 and got["stats"]["health"] == "good"


def test_recorder_crud_and_conflict(client):
    rc = recorder(client, serial="24A1D5F3")
    assert (
        rc["make"] == "audiomoth"
        and rc["health"] == "unknown"
        and rc["active_deployment_id"] is None
    )
    r = client.patch(
        f"{API}/recorders/{rc['id']}", json={"firmware": "1.11.0", "make": "song_meter"}
    )
    assert r.json()["firmware"] == "1.11.0" and r.json()["make"] == "song_meter"
    s = site(client)
    insert_analysis(
        client.app.state.container,
        site_id=s["id"],
        recorder_id=rc["id"],
        captured_at=datetime.now(UTC),
    )
    assert client.delete(f"{API}/recorders/{rc['id']}").status_code == 409
    other = recorder(client, label="spare")
    assert client.delete(f"{API}/recorders/{other['id']}").status_code == 204
    assert client.get(f"{API}/recorders/{rc['id']}").json()["last_recording_at"] is not None


def test_deployments_and_active_filter(client):
    s = site(client)
    rc = recorder(client)
    now = datetime.now(UTC)
    current = deployment(
        client,
        rc["id"],
        s["id"],
        started_at=(now - timedelta(days=3)).isoformat(),
        expected_interval_minutes=10,
    )
    ended = deployment(
        client,
        rc["id"],
        s["id"],
        started_at=(now - timedelta(days=30)).isoformat(),
        ended_at=(now - timedelta(days=20)).isoformat(),
    )
    all_ = client.get(f"{API}/orgs/{ORG}/deployments").json()
    assert {d["id"] for d in all_} == {current["id"], ended["id"]}
    active = client.get(f"{API}/orgs/{ORG}/deployments?active=true").json()
    assert [d["id"] for d in active] == [current["id"]]
    inactive = client.get(f"{API}/orgs/{ORG}/deployments?active=false").json()
    assert [d["id"] for d in inactive] == [ended["id"]]
    assert client.get(f"{API}/recorders/{rc['id']}").json()["active_deployment_id"] == current["id"]
    r = client.patch(
        f"{API}/deployments/{current['id']}",
        json={"ended_at": now.isoformat(), "gain_setting": "high"},
    )
    assert r.status_code == 200 and r.json()["gain_setting"] == "high"
    assert client.delete(f"{API}/deployments/{ended['id']}").status_code == 204
    assert client.get(f"{API}/deployments/{ended['id']}").status_code == 404


def test_deployment_validation(client):
    s = site(client)
    rc = recorder(client)
    r = client.post(
        f"{API}/orgs/{ORG}/deployments",
        json={
            "recorder_id": rc["id"],
            "site_id": s["id"],
            "started_at": "2026-05-02T00:00:00Z",
            "ended_at": "2026-05-01T00:00:00Z",
        },
    )
    assert r.status_code == 422
    r = client.post(
        f"{API}/orgs/{ORG}/deployments",
        json={
            "recorder_id": "rcd_" + "0" * 24,
            "site_id": s["id"],
            "started_at": "2026-05-02T00:00:00Z",
        },
    )
    assert r.status_code == 422
    r = client.post(
        f"{API}/orgs/{ORG}/deployments",
        json={
            "recorder_id": rc["id"],
            "site_id": s["id"],
            "started_at": "2026-05-02T00:00:00Z",
            "expected_interval_minutes": 0,
        },
    )
    assert r.status_code == 422


def test_deployment_times_without_an_offset_are_utc_not_a_500(client):
    s = site(client)
    rc = recorder(client)
    r = client.post(
        f"{API}/orgs/{ORG}/deployments",
        json={
            "recorder_id": rc["id"],
            "site_id": s["id"],
            "started_at": "2026-05-01T00:00:00",
            "ended_at": "2026-06-01T00:00:00Z",
        },
    )
    assert r.status_code == 201, r.text
    dep = r.json()
    assert datetime.fromisoformat(dep["started_at"]) == datetime(2026, 5, 1, tzinfo=UTC)
    r = client.patch(f"{API}/deployments/{dep['id']}", json={"ended_at": "2026-04-01T00:00:00"})
    assert r.status_code == 422
    r = client.patch(f"{API}/deployments/{dep['id']}", json={"ended_at": "2026-07-01T00:00:00"})
    assert r.status_code == 200, r.text
    assert datetime.fromisoformat(r.json()["ended_at"]) == datetime(2026, 7, 1, tzinfo=UTC)


def test_site_and_recorder_health_follow_open_alerts(client):
    s = site(client)
    rc = recorder(client)
    c = client.app.state.container
    insert_analysis(
        c,
        site_id=s["id"],
        recorder_id=rc["id"],
        captured_at=datetime.now(UTC),
        telemetry={"battery_v": 3.1, "source": "audiomoth_comment"},
    )
    c.alerts.evaluate_org(ORG)
    got = client.get(f"{API}/sites/{s['id']}").json()["stats"]
    assert got["open_alerts"] == 1 and got["health"] == "attention"
    assert client.get(f"{API}/recorders/{rc['id']}").json()["health"] == "attention"
    alert = client.get(f"{API}/orgs/{ORG}/alerts").json()["items"][0]
    client.patch(f"{API}/alerts/{alert['id']}", json={"status": "resolved"})
    assert client.get(f"{API}/sites/{s['id']}").json()["stats"]["health"] == "good"


def test_deleting_recordings_updates_their_alerts(client):
    """Alerts that only pointed at deleted recordings no longer keep a site in attention."""
    s = site(client)
    rc = recorder(client)
    c = client.app.state.container
    _, low = insert_analysis(
        c,
        site_id=s["id"],
        recorder_id=rc["id"],
        captured_at=datetime.now(UTC) - timedelta(hours=1),
        telemetry={"battery_v": 3.1, "source": "audiomoth_comment"},
    )
    speech_aid, speech = insert_analysis(
        c, site_id=s["id"], captured_at=datetime.now(UTC), speech=True
    )
    c.alerts.evaluate_org(ORG)
    alerts = {a["kind"]: a for a in client.get(f"{API}/orgs/{ORG}/alerts").json()["items"]}
    assert alerts["battery_low"]["recording_ids"] == [low]
    assert alerts["speech_detected"]["recording_ids"] == [speech]
    assert client.get(f"{API}/sites/{s['id']}").json()["stats"]["health"] == "attention"
    assert client.delete(f"{API}/recordings/{low}").status_code == 204
    # Through the analysis route too (it removes the recording with its last analysis).
    assert client.delete(f"{API}/analyses/{speech_aid}").status_code == 204
    page = client.get(f"{API}/orgs/{ORG}/alerts").json()
    assert {a["kind"]: a["status"] for a in page["items"]} == {
        "battery_low": "resolved",
        "speech_detected": "resolved",
    }
    assert all(a["recording_ids"] == [] and a["note"] for a in page["items"])
    assert client.get(f"{API}/sites/{s['id']}").json()["stats"]["open_alerts"] == 0


def test_recordings_list_filters_and_delete(client):
    s1, s2 = site(client, name="A"), site(client, name="B")
    c = client.app.state.container
    t0 = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    _, r1 = insert_analysis(c, site_id=s1["id"], captured_at=t0, species={"Turdus migratorius": 1})
    insert_analysis(
        c, site_id=s1["id"], captured_at=t0 + timedelta(days=1), quality_status="not_usable"
    )
    insert_analysis(
        c, site_id=s2["id"], captured_at=t0 + timedelta(days=2), species={"Cyanocitta cristata": 2}
    )
    page = client.get(f"{API}/orgs/{ORG}/recordings").json()
    assert page["total"] == 3 and page["page"] == 1
    assert [i["captured_at"][:10] for i in page["items"]] == [
        "2026-05-16",
        "2026-05-15",
        "2026-05-14",
    ]
    assert client.get(f"{API}/orgs/{ORG}/recordings?site_id={s1['id']}").json()["total"] == 2
    assert client.get(f"{API}/orgs/{ORG}/recordings?quality=not_usable").json()["total"] == 1
    assert client.get(f"{API}/orgs/{ORG}/recordings?species=Blue Jay").json()["total"] == 1
    assert (
        client.get(f"{API}/orgs/{ORG}/recordings?species=Cyanocitta cristata").json()["total"] == 1
    )
    r = client.get(
        f"{API}/orgs/{ORG}/recordings", params={"from": "2026-05-15", "to": "2026-05-16"}
    )
    assert r.json()["total"] == 1
    paged = client.get(f"{API}/orgs/{ORG}/recordings?page=2&page_size=2").json()
    assert len(paged["items"]) == 1 and paged["total"] == 3
    assert client.get(f"{API}/orgs/{ORG}/recordings?quality=great").status_code == 422
    one = client.get(f"{API}/recordings/{r1}").json()
    assert (
        one["site_name"] == "A"
        and one["species_richness"] == 1
        and one["analysis_status"] == "completed"
    )
    assert one["captured_at_source"] == "user" and one["telemetry"]["source"] == "none"
    assert client.delete(f"{API}/recordings/{r1}").status_code == 204
    assert client.get(f"{API}/recordings/{r1}").status_code == 404
    assert client.get(f"{API}/orgs/{ORG}/recordings").json()["total"] == 2
    # The rollup for that day went with it.
    assert client.get(f"{API}/sites/{s1['id']}").json()["stats"]["species_counted"] == 0


def test_accumulation(client):
    s = site(client)
    c = client.app.state.container
    t0 = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    insert_analysis(
        c,
        site_id=s["id"],
        captured_at=t0,
        species={"Turdus migratorius": 1, "Cyanocitta cristata": 1},
    )
    insert_analysis(
        c, site_id=s["id"], captured_at=t0 + timedelta(hours=1), species={"Turdus migratorius": 3}
    )
    insert_analysis(
        c,
        site_id=s["id"],
        captured_at=t0 + timedelta(hours=2),
        species={"Dolichonyx oryzivorus": 1},
    )
    acc = client.get(f"{API}/sites/{s['id']}/accumulation").json()
    assert [p["cumulative_species"] for p in acc["points"]] == [2, 2, 3]
    assert [p["recording_index"] for p in acc["points"]] == [1, 2, 3]
    assert "not a completeness estimate" in acc["note"]
