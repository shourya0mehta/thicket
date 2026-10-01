"""A member of organization A cannot see or change organization B's resources,
even with their ids. Resource routes answer 404 (existence does not leak),
org-scoped routes answer 403."""

import io
from datetime import UTC, datetime

import pytest
from PIL import Image
from tests.platform_helpers import CSRF, create_org, dev_login, insert_analysis

API = "/api/v1"


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (55, 113, 87)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def world(make_platform_client):
    client = make_platform_client(auth_mode="dev")
    c = client.app.state.container
    dev_login(client, "bob@farm-b.org")
    org_b = create_org(client, "Farm B")
    b = org_b["id"]
    site = client.post(f"{API}/orgs/{b}/sites", json={"name": "B pasture"}, headers=CSRF).json()
    rec = client.post(
        f"{API}/orgs/{b}/recorders", json={"label": "B-1", "make": "audiomoth"}, headers=CSRF
    ).json()
    dep = client.post(
        f"{API}/orgs/{b}/deployments",
        json={
            "recorder_id": rec["id"],
            "site_id": site["id"],
            "started_at": "2026-05-01T00:00:00Z",
        },
        headers=CSRF,
    ).json()
    aid, rid = insert_analysis(
        c,
        org_id=b,
        site_id=site["id"],
        recorder_id=rec["id"],
        captured_at=datetime.now(UTC),
        species={"Turdus migratorius": 2},
        telemetry={"battery_v": 3.0, "source": "audiomoth_comment"},
    )
    c.alerts.evaluate_org(b)
    alert = client.get(f"{API}/orgs/{b}/alerts").json()["items"][0]
    f = client.post(
        f"{API}/orgs/{b}/files", files={"file": ("map.png", png_bytes(), "image/png")}, headers=CSRF
    ).json()
    report = client.post(
        f"{API}/orgs/{b}/reports",
        json={
            "template": "evidence",
            "title": "B report",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        },
        headers=CSRF,
    ).json()
    job = c.platform.create_job(
        b,
        site_id=site["id"],
        deployment_id=None,
        recorder_id=None,
        settings={},
        filenames=["x.wav"],
        created_by=None,
    )
    event_id = client.get(f"{API}/analyses/{aid}").json()["events"][0]["id"]
    dev_login(client, "alice@farm-a.org")
    org_a = create_org(client, "Farm A")
    return {
        "client": client,
        "a": org_a["id"],
        "b": b,
        "site": site["id"],
        "recorder": rec["id"],
        "deployment": dep["id"],
        "analysis": aid,
        "recording": rid,
        "alert": alert["id"],
        "file": f["id"],
        "report": report["id"],
        "job": job.id,
        "event": event_id,
    }


@pytest.mark.parametrize(
    "path",
    [
        "/sites/{site}",
        "/sites/{site}/accumulation",
        "/recorders/{recorder}",
        "/recorders/{recorder}/health",
        "/deployments/{deployment}",
        "/recordings/{recording}",
        "/uploads/{job}",
        "/files/{file}",
        "/reports/{report}",
        "/reports/{report}.pdf",
        "/reports/{report}.json",
    ],
)
def test_resource_reads_are_404(world, path):
    r = world["client"].get(API + path.format(**world))
    assert r.status_code == 404, (path, r.status_code, r.text)


def test_analysis_routes_are_404(world):
    client, aid = world["client"], world["analysis"]
    for path in ("", "/export.csv", "/export.json", "/spectrogram.png", "/audio"):
        r = client.get(f"{API}/analyses/{aid}{path}")
        assert r.status_code == 404, path
    assert client.delete(f"{API}/analyses/{aid}", headers=CSRF).status_code == 404
    r = client.patch(
        f"{API}/events/{world['event']}", json={"review_status": "rejected"}, headers=CSRF
    )
    assert r.status_code == 404 and r.json()["error_code"] == "event_not_found"
    assert client.get(f"{API}/analyses").json()["items"] == []


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("patch", "/sites/{site}", {"name": "mine"}),
        ("delete", "/sites/{site}", None),
        ("patch", "/recorders/{recorder}", {"label": "mine"}),
        ("delete", "/recorders/{recorder}", None),
        ("patch", "/deployments/{deployment}", {"notes": "mine"}),
        ("delete", "/deployments/{deployment}", None),
        ("delete", "/recordings/{recording}", None),
        ("patch", "/alerts/{alert}", {"status": "resolved"}),
        ("delete", "/reports/{report}", None),
    ],
)
def test_resource_writes_are_404(world, method, path, body):
    client = world["client"]
    kwargs = {"headers": CSRF}
    if body is not None:
        kwargs["json"] = body
    r = getattr(client, method)(API + path.format(**world), **kwargs)
    assert r.status_code == 404, (path, r.text)


@pytest.mark.parametrize(
    "path",
    [
        "/orgs/{b}",
        "/orgs/{b}/members",
        "/orgs/{b}/sites",
        "/orgs/{b}/recorders",
        "/orgs/{b}/deployments",
        "/orgs/{b}/recordings",
        "/orgs/{b}/uploads",
        "/orgs/{b}/alerts",
        "/orgs/{b}/alert-rules",
        "/orgs/{b}/dashboard",
        "/orgs/{b}/sites/compare",
        "/orgs/{b}/reports",
    ],
)
def test_org_routes_are_403(world, path):
    r = world["client"].get(API + path.format(**world))
    assert r.status_code == 403, path


def test_cannot_link_foreign_ids_into_own_org(world):
    client, a = world["client"], world["a"]
    r = client.post(
        f"{API}/orgs/{a}/deployments",
        json={
            "recorder_id": world["recorder"],
            "site_id": world["site"],
            "started_at": "2026-05-01T00:00:00Z",
        },
        headers=CSRF,
    )
    assert r.status_code == 422
    r = client.post(
        f"{API}/orgs/{a}/reports",
        json={
            "template": "evidence",
            "title": "x",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
            "site_ids": [world["site"]],
        },
        headers=CSRF,
    )
    assert r.status_code == 422
    r = client.post(
        f"{API}/orgs/{a}/reports",
        json={
            "template": "nrcs",
            "title": "x",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
            "fields": {"tract_map_image": world["file"]},
        },
        headers=CSRF,
    )
    assert r.status_code == 422
    r = client.get(f"{API}/orgs/{a}/dashboard", params={"site_id": world["site"]})
    assert r.status_code == 404


def test_owner_of_b_still_sees_everything(world):
    client = world["client"]
    dev_login(client, "bob@farm-b.org")
    assert client.get(f"{API}/sites/{world['site']}").status_code == 200
    assert client.get(f"{API}/recordings/{world['recording']}").status_code == 200
    assert client.get(f"{API}/analyses/{world['analysis']}").status_code == 200
    assert client.get(f"{API}/files/{world['file']}").headers["content-type"] == "image/png"
    assert len(client.get(f"{API}/analyses").json()["items"]) == 1
