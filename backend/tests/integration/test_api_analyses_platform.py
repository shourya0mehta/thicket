"""The single-recording path in the platform: tenancy fields, signal profile,
rollups and alerts after completion, roles on analyses and reviews, rate limits."""

from datetime import UTC, datetime

import pytest
from tests.platform_helpers import CSRF, create_org, dev_login, write_wav

from thicket.ids import LOCAL_ORG_ID

API = "/api/v1"


def post(client, path, *, headers=None, **data):
    with open(path, "rb") as fh:
        return client.post(
            f"{API}/analyses?wait=true",
            data=data,
            files={"file": (path.name, fh)},
            headers=headers or {},
        )


@pytest.fixture
def tone(tmp_path):
    return write_wav(tmp_path / "tone.wav", 6.0, 2000)


def test_disabled_mode_analysis_attaches_to_the_local_org(make_platform_client, tone):
    client = make_platform_client()
    c = client.app.state.container
    site = client.post(
        f"{API}/orgs/{LOCAL_ORG_ID}/sites",
        json={"name": "Field 4", "latitude": 42.4, "longitude": -76.5},
    ).json()
    r = post(
        client,
        tone,
        site_id=site["id"],
        captured_at="2026-05-14T06:30:00",
        timezone="America/New_York",
    )
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["recording"]["site_name"] == "Field 4" and a["recording"]["latitude"] == 42.4
    assert [s["common_name"] for s in a["species"]] == ["Black-capped Chickadee"]
    rid = a["recording"]["id"]
    view = c.platform.get_recording(rid)
    rec = view.recording
    assert rec.organization_id == LOCAL_ORG_ID and rec.site_id == site["id"]
    assert rec.captured_at_source == "user" and rec.source_filename == "tone.wav"
    assert rec.captured_at_utc == datetime(2026, 5, 14, 10, 30, tzinfo=UTC)
    prof = rec.signal_profile
    assert prof["band_fraction_1_4k"] > 0.98 and abs(prof["spectral_centroid_hz"] - 2000) < 100
    assert prof["channel_rms_dbfs"] == [pytest.approx(-13.5, abs=0.2)]
    # The completion hook built the rollup.
    st = c.platform.get_recording_stats(rid)
    assert st.richness == 1 and st.local_date.isoformat() == "2026-05-14"
    summary = client.get(f"{API}/recordings/{rid}").json()
    assert summary["species_richness"] == 1 and summary["analysis_status"] == "completed"
    assert client.get(f"{API}/sites/{site['id']}").json()["stats"]["species_counted"] == 1
    # Deleting the analysis removes the rollup and frees the explicit site of recordings.
    assert client.delete(f"{API}/analyses/{a['id']}").status_code == 204
    assert c.platform.get_recording_stats(rid) is None
    assert client.get(f"{API}/sites/{site['id']}").status_code == 200  # explicit sites stay


def test_site_name_creates_an_implicit_site_in_the_org(make_platform_client, tone):
    client = make_platform_client()
    a = post(client, tone, site_name="Sapsucker Woods").json()
    sites = client.get(f"{API}/orgs/{LOCAL_ORG_ID}/sites").json()
    assert [s["name"] for s in sites] == ["Sapsucker Woods"]
    client.delete(f"{API}/analyses/{a['id']}")
    assert client.get(f"{API}/orgs/{LOCAL_ORG_ID}/sites").json() == []  # implicit site removed


def test_stereo_file_records_both_channels(make_platform_client, tmp_path):
    client = make_platform_client()
    path = write_wav(tmp_path / "st.wav", 6.0, 2000, channels=2, channel_gains=[1.0, 0.1])
    a = post(client, path).json()
    prof = client.app.state.container.platform.get_recording(
        a["recording"]["id"]
    ).recording.signal_profile
    left, right = prof["channel_rms_dbfs"]
    assert left - right == pytest.approx(20.0, abs=0.3)


def test_completion_hook_opens_alerts(make_platform_client, tmp_path):
    client = make_platform_client()
    path = write_wav(tmp_path / "dc.wav", 6.0, 2000, dc=0.1)
    post(client, path)
    kinds = {x["kind"] for x in client.get(f"{API}/orgs/{LOCAL_ORG_ID}/alerts").json()["items"]}
    assert "dc_offset" in kinds


def test_dev_mode_tenancy_rules(make_platform_client, tone):
    client = make_platform_client(auth_mode="dev")
    r = post(client, tone, headers=CSRF)
    assert r.status_code == 401
    dev_login(client, "a@example.org")
    r = post(client, tone, headers=CSRF)
    assert r.status_code == 403  # member of nothing, and not of the local workspace
    org1 = create_org(client, "One")
    r = post(client, tone, headers=CSRF)
    assert (
        r.status_code == 201
        and client.get(f"{API}/analyses").json()["items"][0]["id"] == r.json()["id"]
    )
    org2 = create_org(client, "Two")
    r = post(client, tone, headers=CSRF)
    assert r.status_code == 422 and r.json()["detail"]["field"] == "organization_id"
    r = post(client, tone, headers=CSRF, organization_id=org2["id"])
    assert r.status_code == 201
    site1 = client.post(f"{API}/orgs/{org1['id']}/sites", json={"name": "S1"}, headers=CSRF).json()
    r = post(client, tone, headers=CSRF, organization_id=org2["id"], site_id=site1["id"])
    assert r.status_code == 422
    r = post(client, tone, headers=CSRF, organization_id=LOCAL_ORG_ID)
    assert r.status_code == 403
    r = post(client, tone, headers=CSRF, organization_id="nonsense")
    assert r.status_code == 422


def test_roles_on_analyses_and_reviews(make_platform_client, tone):
    client = make_platform_client(auth_mode="dev")
    dev_login(client, "owner@example.org")
    org = create_org(client)
    a = post(client, tone, headers=CSRF).json()
    event_id = a["events"][0]["id"]
    for email, role in (("rev@example.org", "reviewer"), ("view@example.org", "viewer")):
        dev_login(client, "owner@example.org")
        token = (
            client.post(
                f"{API}/orgs/{org['id']}/invites", json={"email": email, "role": role}, headers=CSRF
            )
            .json()["accept_url"]
            .rsplit("/", 1)[-1]
        )
        dev_login(client, email)
        client.post(f"{API}/invites/{token}/accept", headers=CSRF)
    # Viewer: read yes, review and upload no.
    assert client.get(f"{API}/analyses/{a['id']}").status_code == 200
    assert client.get(f"{API}/analyses/{a['id']}/export.csv").status_code == 200
    r = client.patch(f"{API}/events/{event_id}", json={"review_status": "rejected"}, headers=CSRF)
    assert r.status_code == 403
    assert post(client, tone, headers=CSRF).status_code == 403
    assert client.delete(f"{API}/analyses/{a['id']}", headers=CSRF).status_code == 403
    # Reviewer: review yes, and the reviewer is recorded.
    dev_login(client, "rev@example.org")
    r = client.patch(f"{API}/events/{event_id}", json={"review_status": "accepted"}, headers=CSRF)
    assert r.status_code == 200
    me = client.get(f"{API}/auth/me").json()["user"]["id"]
    from thicket.persistence.db import EventReviewRow

    with client.app.state.container.db.session() as s:
        assert s.get(EventReviewRow, event_id).reviewed_by == me


def test_rate_limit_applies_to_platform_posts(make_platform_client):
    client = make_platform_client(rate_limit_per_minute=2)
    for _ in range(2):
        assert client.post(f"{API}/orgs", json={"name": "X"}).status_code == 201
    r = client.post(f"{API}/orgs", json={"name": "X"})
    assert r.status_code == 429 and r.json()["error_code"] == "rate_limited"
    assert "retry-after" in r.headers
    assert client.get(f"{API}/orgs").status_code == 200  # reads are not limited
