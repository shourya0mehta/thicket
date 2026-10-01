"""Organizations, members, roles and invites (AUTH_MODE=dev, several users)."""

import pytest
from tests.platform_helpers import CSRF, create_org, dev_login

API = "/api/v1"


@pytest.fixture
def client(make_platform_client):
    return make_platform_client(auth_mode="dev", frontend_url="https://app.example.org")


def invite(client, org_id, email, role="viewer"):
    r = client.post(
        f"{API}/orgs/{org_id}/invites", json={"email": email, "role": role}, headers=CSRF
    )
    assert r.status_code == 201, r.text
    return r.json()


def join(client, org_id, owner_email, email, role):
    """Invite ``email`` as ``role`` (signed in as the owner) and accept it as that user."""
    dev_login(client, owner_email)
    inv = invite(client, org_id, email, role)
    token = inv["accept_url"].rsplit("/", 1)[-1]
    dev_login(client, email)
    r = client.post(f"{API}/invites/{token}/accept", headers=CSRF)
    assert r.status_code == 200, r.text
    return r.json()


def test_create_and_read_org(client):
    dev_login(client, "owner@example.org")
    org = create_org(client, "Hilltop Farm", kind="ranch", timezone="America/Denver", region="CO")
    assert org["slug"] == "hilltop-farm" and org["kind"] == "ranch"
    assert org["timezone"] == "America/Denver" and org["member_count"] == 1
    assert create_org(client, "Hilltop Farm")["slug"] == "hilltop-farm-2"
    assert len(client.get(f"{API}/orgs").json()) == 2
    me = client.get(f"{API}/auth/me").json()
    assert me["roles"][org["id"]] == "owner"
    got = client.get(f"{API}/orgs/{org['id']}").json()
    assert got["id"] == org["id"] and got["site_count"] == 0


def test_org_validation(client):
    dev_login(client, "owner@example.org")
    r = client.post(f"{API}/orgs", json={"name": "X", "timezone": "Mars/Base"}, headers=CSRF)
    assert r.status_code == 422 and r.json()["error_code"] == "invalid_parameter"
    r = client.post(f"{API}/orgs", json={"name": ""}, headers=CSRF)
    assert r.status_code == 422
    r = client.post(f"{API}/orgs", json={"name": "X", "bogus": 1}, headers=CSRF)
    assert r.status_code == 422


def test_update_and_delete_need_roles(client):
    dev_login(client, "owner@example.org")
    org = create_org(client)
    oid = org["id"]
    join(client, oid, "owner@example.org", "mgr@example.org", "manager")
    r = client.patch(f"{API}/orgs/{oid}", json={"name": "Renamed"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    r = client.delete(f"{API}/orgs/{oid}", headers=CSRF)
    assert r.status_code == 403 and r.json()["error_code"] == "forbidden"
    join(client, oid, "owner@example.org", "viewer@example.org", "viewer")
    assert client.patch(f"{API}/orgs/{oid}", json={"name": "No"}, headers=CSRF).status_code == 403
    dev_login(client, "owner@example.org")
    assert client.delete(f"{API}/orgs/{oid}", headers=CSRF).status_code == 204
    assert client.get(f"{API}/orgs/{oid}").status_code == 403  # no longer a member
    assert client.get(f"{API}/orgs").json() == []


def test_non_member_gets_403_and_unknown_org_404(client):
    dev_login(client, "owner@example.org")
    org = create_org(client)
    dev_login(client, "stranger@example.org")
    r = client.get(f"{API}/orgs/{org['id']}")
    assert r.status_code == 403
    assert client.get(f"{API}/orgs/org_{'f' * 24}").status_code == 403
    assert client.get(f"{API}/orgs/not-an-id").status_code == 404


def test_invite_flow(client):
    dev_login(client, "owner@example.org")
    org = create_org(client)
    inv = invite(client, org["id"], "New@Example.org", "reviewer")
    assert inv["email"] == "new@example.org" and inv["role"] == "reviewer"
    assert inv["accept_url"].startswith("https://app.example.org/#/invite/")
    listed = client.get(f"{API}/orgs/{org['id']}/invites").json()
    assert len(listed) == 1 and listed[0]["accept_url"] is None  # token shown only once
    token = inv["accept_url"].rsplit("/", 1)[-1]
    dev_login(client, "new@example.org")
    r = client.post(f"{API}/invites/{token}/accept", headers=CSRF)
    assert r.status_code == 200 and r.json()["id"] == org["id"]
    assert client.get(f"{API}/auth/me").json()["roles"][org["id"]] == "reviewer"
    r = client.post(f"{API}/invites/{token}/accept", headers=CSRF)
    assert r.status_code == 409 and r.json()["error_code"] == "conflict"


def test_revoking_invites(client):
    dev_login(client, "owner@example.org")
    oid = create_org(client)["id"]
    unused = invite(client, oid, "maybe@example.org")
    used = invite(client, oid, "joined@example.org")
    boss = invite(client, oid, "boss@example.org", "owner")
    used_token = used["accept_url"].rsplit("/", 1)[-1]
    dev_login(client, "joined@example.org")
    assert client.post(f"{API}/invites/{used_token}/accept", headers=CSRF).status_code == 200
    join(client, oid, "owner@example.org", "mgr@example.org", "manager")
    # A manager revokes an unused invite; its link stops working.
    r = client.delete(f"{API}/orgs/{oid}/invites/{unused['id']}", headers=CSRF)
    assert r.status_code == 204
    ids = {i["id"] for i in client.get(f"{API}/orgs/{oid}/invites").json()}
    assert unused["id"] not in ids and used["id"] in ids
    dev_login(client, "maybe@example.org")
    token = unused["accept_url"].rsplit("/", 1)[-1]
    assert client.post(f"{API}/invites/{token}/accept", headers=CSRF).status_code == 404
    dev_login(client, "mgr@example.org")
    # Accepted invites are history; owner invites need an owner; unknown ids are 404.
    r = client.delete(f"{API}/orgs/{oid}/invites/{used['id']}", headers=CSRF)
    assert r.status_code == 409 and r.json()["error_code"] == "conflict"
    assert client.delete(f"{API}/orgs/{oid}/invites/{boss['id']}", headers=CSRF).status_code == 403
    assert client.delete(f"{API}/orgs/{oid}/invites/inv_nope", headers=CSRF).status_code == 404
    dev_login(client, "owner@example.org")
    assert client.delete(f"{API}/orgs/{oid}/invites/{boss['id']}", headers=CSRF).status_code == 204
    # Another organization's invite is not found from here; viewers cannot revoke.
    other = create_org(client, "Other")["id"]
    theirs = invite(client, other, "x@example.org")
    assert (
        client.delete(f"{API}/orgs/{oid}/invites/{theirs['id']}", headers=CSRF).status_code == 404
    )
    dev_login(client, "joined@example.org")  # a viewer of oid
    again = client.delete(f"{API}/orgs/{other}/invites/{theirs['id']}", headers=CSRF)
    assert again.status_code == 403


def test_invite_for_another_email_and_bad_tokens(client):
    dev_login(client, "owner@example.org")
    org = create_org(client)
    token = invite(client, org["id"], "right@example.org")["accept_url"].rsplit("/", 1)[-1]
    dev_login(client, "wrong@example.org")
    assert client.post(f"{API}/invites/{token}/accept", headers=CSRF).status_code == 422
    assert client.post(f"{API}/invites/garbage/accept", headers=CSRF).status_code == 404


def test_expired_invite(client):
    dev_login(client, "owner@example.org")
    org = create_org(client)
    inv = invite(client, org["id"], "late@example.org")
    from datetime import UTC, datetime, timedelta

    from thicket.persistence.db import InviteRow

    db = client.app.state.container.db
    with db.session() as s:
        s.get(InviteRow, inv["id"]).expires_at = datetime.now(UTC) - timedelta(days=1)
    dev_login(client, "late@example.org")
    r = client.post(f"{API}/invites/{inv['accept_url'].rsplit('/', 1)[-1]}/accept", headers=CSRF)
    assert r.status_code == 409 and "expired" in r.json()["message"]


def test_invite_needs_manager_and_owner_for_owner_invites(client):
    dev_login(client, "owner@example.org")
    org = create_org(client)
    join(client, org["id"], "owner@example.org", "mgr@example.org", "manager")
    r = client.post(
        f"{API}/orgs/{org['id']}/invites",
        json={"email": "x@example.org", "role": "owner"},
        headers=CSRF,
    )
    assert r.status_code == 422
    assert invite(client, org["id"], "x@example.org", "viewer")["role"] == "viewer"
    join(client, org["id"], "owner@example.org", "v@example.org", "viewer")
    r = client.post(
        f"{API}/orgs/{org['id']}/invites", json={"email": "y@example.org"}, headers=CSRF
    )
    assert r.status_code == 403
    assert client.get(f"{API}/orgs/{org['id']}/invites").status_code == 403


def test_members_roles_and_last_owner(client):
    dev_login(client, "owner@example.org")
    org = create_org(client)
    oid = org["id"]
    join(client, oid, "owner@example.org", "a@example.org", "viewer")
    dev_login(client, "owner@example.org")
    members = client.get(f"{API}/orgs/{oid}/members").json()
    assert {m["user"]["email"]: m["role"] for m in members} == {
        "owner@example.org": "owner",
        "a@example.org": "viewer",
    }
    owner_id = next(m["user"]["id"] for m in members if m["role"] == "owner")
    a_id = next(m["user"]["id"] for m in members if m["role"] == "viewer")
    r = client.patch(f"{API}/orgs/{oid}/members/{a_id}", json={"role": "manager"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["role"] == "manager"
    r = client.patch(f"{API}/orgs/{oid}/members/{owner_id}", json={"role": "viewer"}, headers=CSRF)
    assert r.status_code == 409
    r = client.delete(f"{API}/orgs/{oid}/members/{owner_id}", headers=CSRF)
    assert r.status_code == 409
    # A manager cannot change roles; anyone can leave.
    dev_login(client, "a@example.org")
    r = client.patch(f"{API}/orgs/{oid}/members/{owner_id}", json={"role": "viewer"}, headers=CSRF)
    assert r.status_code == 403
    assert client.delete(f"{API}/orgs/{oid}/members/{owner_id}", headers=CSRF).status_code == 403
    assert client.delete(f"{API}/orgs/{oid}/members/{a_id}", headers=CSRF).status_code == 204
    assert client.get(f"{API}/orgs/{oid}").status_code == 403


def test_removed_members_lose_the_orgs_notifications(client):
    """In-app notifications embed the whole alert, and digests mail them out later."""
    from datetime import UTC, datetime

    from tests.platform_helpers import insert_analysis

    dev_login(client, "owner@example.org")
    oid = create_org(client)["id"]
    join(client, oid, "owner@example.org", "a@example.org", "viewer")
    a_id = client.get(f"{API}/auth/me").json()["user"]["id"]
    r = client.put(
        f"{API}/me/notification-prefs",
        json={"email_enabled": True, "email_digest": "daily", "min_severity": "info"},
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    c = client.app.state.container
    insert_analysis(
        c,
        org_id=oid,
        captured_at=datetime.now(UTC),
        telemetry={"battery_v": 2.0, "source": "audiomoth_comment"},
    )
    c.alerts.evaluate_org(oid)
    assert client.get(f"{API}/me/notifications").json()["unread"] >= 1
    assert c.platform.pending_email_notifications("daily")
    dev_login(client, "owner@example.org")
    assert client.delete(f"{API}/orgs/{oid}/members/{a_id}", headers=CSRF).status_code == 204
    dev_login(client, "a@example.org")
    page = client.get(f"{API}/me/notifications").json()
    assert page["items"] == [] and page["unread"] == 0
    assert all(u.id != a_id for _, _, u in c.platform.pending_email_notifications("daily"))


def test_alert_rules_get_put(client):
    dev_login(client, "owner@example.org")
    org = create_org(client)
    rules = client.get(f"{API}/orgs/{org['id']}/alert-rules").json()
    assert rules["min_baseline_recordings"] == 8 and rules["enabled"]
    rules["priority_species"] = ["Dolichonyx oryzivorus"]
    rules["min_baseline_recordings"] = 5
    r = client.put(f"{API}/orgs/{org['id']}/alert-rules", json=rules, headers=CSRF)
    assert r.status_code == 200
    assert client.get(f"{API}/orgs/{org['id']}/alert-rules").json()["min_baseline_recordings"] == 5
    rules["min_baseline_recordings"] = 1
    assert (
        client.put(f"{API}/orgs/{org['id']}/alert-rules", json=rules, headers=CSRF).status_code
        == 422
    )


def test_local_workspace_cannot_be_deleted(make_platform_client):
    client = make_platform_client()
    from thicket.ids import LOCAL_ORG_ID

    assert client.delete(f"{API}/orgs/{LOCAL_ORG_ID}").status_code == 403


def test_two_owners_demoting_or_removing_each_other_keep_one_owner(container, monkeypatch):
    """The owner count is checked inside the UPDATE/DELETE, not read beforehand."""
    import pytest

    from thicket.api.platform_schemas import Role
    from thicket.errors import ThicketError

    c = container
    a = c.platform.upsert_user(email="a@example.org", name="A")
    b = c.platform.upsert_user(email="b@example.org", name="B")
    org = c.platform.create_org(
        a.id, name="Two", kind="farm", timezone="UTC", country=None, region=None
    )
    c.platform.add_member(org.id, b.id, "owner")
    # Both requests read "two owners" before either wrote: the race the old check lost.
    monkeypatch.setattr(c.platform, "owner_count", lambda org_id: 2)
    c.services.set_role(org.id, a.id, Role.viewer)
    with pytest.raises(ThicketError) as e:
        c.services.set_role(org.id, b.id, Role.viewer)
    assert e.value.code.value == "conflict"
    with pytest.raises(ThicketError) as e:
        c.services.remove_member(org.id, b.id)
    assert e.value.code.value == "conflict"
    assert c.platform.role_in_org(b.id, org.id) == "owner"
    # Promoting is never blocked, and then either owner may leave.
    c.services.set_role(org.id, a.id, Role.owner)
    c.services.remove_member(org.id, b.id)
    assert c.platform.role_in_org(b.id, org.id) is None
    with pytest.raises(ThicketError) as e:
        c.services.remove_member(org.id, "user_" + "5" * 24)
    assert e.value.code.value == "not_found"
