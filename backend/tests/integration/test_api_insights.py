"""Dashboard, phenology, comparison, alerts and notifications over HTTP."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.platform_helpers import CSRF, create_org, dev_login, insert_analysis

from thicket.ids import LOCAL_ORG_ID

API = "/api/v1"
ORG = LOCAL_ORG_ID
A = "Turdus migratorius"


@pytest.fixture
def client(make_platform_client):
    client = make_platform_client()
    c = client.app.state.container
    site = c.platform.create_site(ORG, {"name": "Dash"})
    now = datetime.now(UTC).replace(microsecond=0)
    for i in range(3):
        insert_analysis(c, site_id=site.id, captured_at=now - timedelta(days=i), species={A: i + 1})
    insert_analysis(c, site_id=site.id, captured_at=now - timedelta(days=200), species={A: 1})
    client.site_id = site.id  # type: ignore[attr-defined]
    return client


def test_dashboard_default_period(client):
    d = client.get(f"{API}/orgs/{ORG}/dashboard").json()
    assert (
        datetime.fromisoformat(d["period_end"]) - datetime.fromisoformat(d["period_start"])
    ).days == 89
    assert d["recordings"] == 3 and d["detection_events"] == 6 and d["species_counted"] == 1
    assert d["quality"] == {"usable": 3, "usable_with_warnings": 0, "not_usable": 0}
    assert d["species"][0]["presence_fraction"] == 1.0
    r = client.get(f"{API}/orgs/{ORG}/dashboard", params={"from": "2024-01-01", "to": "2028-01-01"})
    assert r.json()["recordings"] == 4
    r = client.get(f"{API}/orgs/{ORG}/dashboard", params={"site_id": client.site_id})
    assert r.json()["site_ids"] == [client.site_id]
    assert (
        client.get(
            f"{API}/orgs/{ORG}/dashboard", params={"from": "2026-02-01", "to": "2026-01-01"}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{API}/orgs/{ORG}/dashboard", params={"site_id": "site_" + "1" * 24}
        ).status_code
        == 404
    )


def test_phenology_and_compare(client):
    r = client.get(f"{API}/orgs/{ORG}/phenology", params={"scientific_name": A, "years": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["species"]["common_name"] == "American Robin"
    assert sum(cell["recordings_with_detection"] for cell in body["cells"]) == 4
    assert (
        client.get(
            f"{API}/orgs/{ORG}/phenology", params={"scientific_name": "Nobody here"}
        ).status_code
        == 404
    )
    assert client.get(f"{API}/orgs/{ORG}/phenology").status_code == 422
    comp = client.get(f"{API}/orgs/{ORG}/sites/compare").json()
    assert (
        comp["rows"][0]["recordings"] == 3
        and comp["rows"][0]["top_species"][0]["scientific_name"] == A
    )


def test_alert_list_update_and_evaluate(client):
    c = client.app.state.container
    insert_analysis(
        c,
        site_id=client.site_id,
        captured_at=datetime.now(UTC),
        speech=True,
    )
    r = client.post(f"{API}/orgs/{ORG}/alerts/evaluate")
    assert r.status_code == 200
    page = r.json()
    assert page["total"] == 1 and page["items"][0]["kind"] == "speech_detected"
    assert page["counts_by_status"] == {"open": 1} and page["counts_by_category"] == {"quality": 1}
    alert = page["items"][0]
    assert client.get(f"{API}/orgs/{ORG}/alerts?category=recorder").json()["total"] == 0
    assert client.get(f"{API}/orgs/{ORG}/alerts?kind=speech_detected").json()["total"] == 1
    assert client.get(f"{API}/orgs/{ORG}/alerts?site_id={client.site_id}").json()["total"] == 1
    assert client.get(f"{API}/orgs/{ORG}/alerts?status=bogus").status_code == 422
    r = client.patch(
        f"{API}/alerts/{alert['id']}", json={"status": "acknowledged", "note": "seen it"}
    )
    body = r.json()
    assert (
        body["status"] == "acknowledged" and body["note"] == "seen it" and body["acknowledged_by"]
    )
    r = client.patch(f"{API}/alerts/{alert['id']}", json={"status": "snoozed"})
    assert r.status_code == 422
    until = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    r = client.patch(
        f"{API}/alerts/{alert['id']}", json={"status": "snoozed", "snoozed_until": until}
    )
    assert r.json()["status"] == "snoozed" and r.json()["snoozed_until"]
    r = client.patch(f"{API}/alerts/{alert['id']}", json={"status": "open"})
    assert r.json()["acknowledged_by"] is None and r.json()["snoozed_until"] is None
    assert client.patch(f"{API}/alerts/alr_nope", json={"status": "open"}).status_code == 404


def test_alert_roles(make_platform_client):
    client = make_platform_client(auth_mode="dev")
    dev_login(client, "owner@example.org")
    org = create_org(client)
    c = client.app.state.container
    insert_analysis(c, org_id=org["id"], captured_at=datetime.now(UTC), speech=True)
    assert client.post(f"{API}/orgs/{org['id']}/alerts/evaluate", headers=CSRF).status_code == 200
    alert_id = client.get(f"{API}/orgs/{org['id']}/alerts").json()["items"][0]["id"]
    token = (
        client.post(
            f"{API}/orgs/{org['id']}/invites",
            json={"email": "v@example.org", "role": "viewer"},
            headers=CSRF,
        )
        .json()["accept_url"]
        .rsplit("/", 1)[-1]
    )
    dev_login(client, "v@example.org")
    client.post(f"{API}/invites/{token}/accept", headers=CSRF)
    assert client.get(f"{API}/orgs/{org['id']}/alerts").json()["total"] == 1
    r = client.patch(f"{API}/alerts/{alert_id}", json={"status": "resolved"}, headers=CSRF)
    assert r.status_code == 403
    assert client.post(f"{API}/orgs/{org['id']}/alerts/evaluate", headers=CSRF).status_code == 403


def test_notifications_api(client):
    c = client.app.state.container
    insert_analysis(c, site_id=client.site_id, captured_at=datetime.now(UTC), speech=True)
    rec = c.platform.create_recorder(ORG, {"label": "low", "make": "audiomoth"})
    insert_analysis(
        c, recorder_id=rec.id, captured_at=datetime.now(UTC), telemetry={"battery_v": 2.0}
    )
    client.post(f"{API}/orgs/{ORG}/alerts/evaluate")
    page = client.get(f"{API}/me/notifications").json()
    assert page["unread"] == 1 and page["items"][0]["alert"]["kind"] == "battery_low"
    assert page["items"][0]["channel"] == "in_app"
    assert client.get(f"{API}/auth/me").json()["unread_notifications"] == 1
    assert client.post(f"{API}/me/notifications/read", json={}).status_code == 422
    nid = page["items"][0]["id"]
    assert client.post(f"{API}/me/notifications/read", json={"ids": [nid]}).status_code == 204
    assert client.get(f"{API}/me/notifications?unread_only=true").json() == {
        "items": [],
        "unread": 0,
    }
    assert client.post(f"{API}/me/notifications/read", json={"all": True}).status_code == 204
    prefs = client.get(f"{API}/me/notification-prefs").json()
    assert prefs == {
        "email_enabled": False,
        "email_digest": "daily",
        "min_severity": "watch",
        "categories": ["ecology", "quality", "recorder"],
    }
    prefs.update(email_enabled=True, email_digest="weekly", categories=["recorder"])
    assert client.put(f"{API}/me/notification-prefs", json=prefs).json()["email_digest"] == "weekly"
    assert client.get(f"{API}/me/notification-prefs").json()["categories"] == ["recorder"]
    bad = dict(prefs, email_digest="hourly")
    assert client.put(f"{API}/me/notification-prefs", json=bad).status_code == 422
