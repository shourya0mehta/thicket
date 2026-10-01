"""Sign-in over HTTP in the three modes: disabled, dev and google (mocked)."""

from urllib.parse import parse_qs, urlsplit

import pytest
from tests.google_mock import CLIENT_ID, FakeGoogle
from tests.platform_helpers import CSRF, dev_login

from thicket.ids import LOCAL_ORG_ID, LOCAL_USER_ID
from thicket.services.auth import OAUTH_COOKIE, SESSION_COOKIE

API = "/api/v1"


def code(r):
    return r.json()["error_code"]


# ----------------------------------------------------------------- disabled


def test_disabled_mode_is_the_local_owner(make_platform_client):
    client = make_platform_client()
    cfg = client.get(f"{API}/auth/config").json()
    assert cfg == {
        "mode": "disabled",
        "google_client_id": None,
        "sign_in_url": None,
        "allowed_domains": [],
    }
    me = client.get(f"{API}/auth/me").json()
    assert me["user"]["id"] == LOCAL_USER_ID and me["auth_mode"] == "disabled"
    assert me["roles"] == {LOCAL_ORG_ID: "owner"}
    assert [o["id"] for o in me["organizations"]] == [LOCAL_ORG_ID]
    # No CSRF header needed and no cookie is ever set.
    r = client.post(f"{API}/orgs", json={"name": "Second farm"})
    assert r.status_code == 201 and SESSION_COOKIE not in r.cookies
    assert client.get(f"{API}/analyses").status_code == 200
    assert client.post(f"{API}/auth/dev", json={"email": "a@b.org"}).status_code == 404


def test_disabled_mode_logout_is_harmless(make_platform_client):
    client = make_platform_client()
    assert client.post(f"{API}/auth/logout").status_code == 204
    assert client.get(f"{API}/auth/me").status_code == 200


# ---------------------------------------------------------------------- dev


@pytest.fixture
def dev(make_platform_client):
    return make_platform_client(auth_mode="dev")


def test_dev_requires_sign_in(dev):
    r = dev.get(f"{API}/auth/me")
    assert r.status_code == 401 and code(r) == "unauthenticated"
    assert dev.get(f"{API}/orgs").status_code == 401
    assert dev.get(f"{API}/analyses").status_code == 401
    assert dev.get(f"{API}/auth/config").json()["mode"] == "dev"
    # Public routes stay public.
    assert dev.get(f"{API}/health").status_code == 200


def test_dev_login_sets_a_hardened_cookie(dev):
    r = dev.post(
        f"{API}/auth/dev", json={"email": "Jane@Example.org", "name": "Jane"}, headers=CSRF
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "jane@example.org" and body["organizations"] == []
    cookie = r.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE}=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "max-age=2592000" in cookie and "secure" not in cookie
    me = dev.get(f"{API}/auth/me").json()
    assert me["user"]["name"] == "Jane" and me["auth_mode"] == "dev"
    assert me["user"]["id"] != LOCAL_USER_ID


def test_secure_cookie_with_https_public_url(make_platform_client):
    client = make_platform_client(auth_mode="dev", public_base_url="https://thicket.example.org")
    r = client.post(f"{API}/auth/dev", json={"email": "a@example.org"}, headers=CSRF)
    assert "secure" in r.headers["set-cookie"].lower()


def test_csrf_header_required_for_mutations(dev):
    r = dev.post(f"{API}/auth/dev", json={"email": "a@example.org"})
    assert r.status_code == 403 and code(r) == "forbidden"
    dev_login(dev, "a@example.org")
    r = dev.post(f"{API}/orgs", json={"name": "Farm"})
    assert r.status_code == 403
    r = dev.post(f"{API}/orgs", json={"name": "Farm"}, headers={"X-Requested-With": "nope"})
    assert r.status_code == 403
    assert dev.post(f"{API}/orgs", json={"name": "Farm"}, headers=CSRF).status_code == 201
    # GET never needs it.
    assert dev.get(f"{API}/orgs").status_code == 200


def test_logout_revokes_the_session(dev):
    dev_login(dev, "a@example.org")
    token = dev.cookies.get(SESSION_COOKIE)
    r = dev.post(f"{API}/auth/logout", headers=CSRF)
    assert r.status_code == 204
    assert dev.get(f"{API}/auth/me").status_code == 401
    # Replaying the old cookie does not work either.
    dev.cookies.set(SESSION_COOKIE, token)
    assert dev.get(f"{API}/auth/me").status_code == 401


def test_rolling_session_refresh(dev):
    dev_login(dev, "a@example.org")
    auth = dev.app.state.container.auth
    real = auth.clock
    try:
        auth.clock = lambda: real() + 2 * 3600
        r = dev.get(f"{API}/auth/me")
    finally:
        auth.clock = real
    assert r.status_code == 200
    assert SESSION_COOKIE in r.headers.get("set-cookie", "")
    # A fresh session does not get a new cookie on every request.
    assert "set-cookie" not in dev.get(f"{API}/auth/me").headers


def test_logout_after_a_refresh_revokes_the_pre_refresh_cookie(dev):
    """A refresh keeps the session id, so logout also kills a copy taken before it."""
    dev_login(dev, "a@example.org")
    before = dev.cookies.get(SESSION_COOKIE)
    auth = dev.app.state.container.auth
    real = auth.clock
    try:
        auth.clock = lambda: real() + 2 * 3600
        assert dev.get(f"{API}/auth/me").status_code == 200
    finally:
        auth.clock = real
    after = dev.cookies.get(SESSION_COOKIE)
    assert after != before
    assert auth.read_session(after).session_id == auth.read_session(before).session_id
    assert dev.post(f"{API}/auth/logout", headers=CSRF).status_code == 204
    for token in (before, after):
        dev.cookies.clear()
        dev.cookies.set(SESSION_COOKIE, token)
        assert dev.get(f"{API}/auth/me").status_code == 401


def test_dev_login_domain_restriction(make_platform_client):
    client = make_platform_client(auth_mode="dev", allowed_signin_domains="farm.coop")
    r = client.post(f"{API}/auth/dev", json={"email": "x@gmail.com"}, headers=CSRF)
    assert r.status_code == 403
    assert client.get(f"{API}/auth/config").json()["allowed_domains"] == ["farm.coop"]


def test_cors_allows_credentials_and_the_csrf_header(make_platform_client):
    client = make_platform_client(auth_mode="dev")
    r = client.options(
        f"{API}/orgs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-requested-with,content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-credentials"] == "true"
    assert "x-requested-with" in r.headers["access-control-allow-headers"].lower()


# ------------------------------------------------------------------- google


@pytest.fixture
def google(make_platform_client):
    fake = FakeGoogle()
    client = make_platform_client(
        auth_mode="google",
        google_client_id=CLIENT_ID,
        google_client_secret="s",
        frontend_url="https://app.example.org",
    )
    client.app.state.container.auth._google = fake.oidc()
    return client, fake


def _start(client, fake, next_path="/sites"):
    r = client.get(f"{API}/auth/google/start", params={"next": next_path}, follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    fake.claims["nonce"] = q["nonce"][0]
    assert OAUTH_COOKIE in r.headers["set-cookie"]
    return q


def test_google_config(google):
    client, _ = google
    cfg = client.get(f"{API}/auth/config").json()
    assert cfg["mode"] == "google" and cfg["google_client_id"] == CLIENT_ID
    assert cfg["sign_in_url"] == "/api/v1/auth/google/start"


def test_google_start_redirects_with_pkce(google):
    client, fake = google
    q = _start(client, fake)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == [CLIENT_ID]
    assert q["redirect_uri"] == ["http://localhost:8000/api/v1/auth/google/callback"]


def test_google_callback_signs_in_and_redirects(google):
    client, fake = google
    q = _start(client, fake, "/alerts")
    r = client.get(
        f"{API}/auth/google/callback",
        params={"code": "auth-code", "state": q["state"][0]},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "https://app.example.org/#/alerts"
    assert SESSION_COOKIE in r.headers.get("set-cookie", "")
    me = client.get(f"{API}/auth/me").json()
    assert me["user"]["email"] == "farmer@example.org" and me["auth_mode"] == "google"
    assert me["user"]["picture_url"] == "https://example.org/p.png"


def test_google_callback_with_bad_state_or_token(google):
    client, fake = google
    q = _start(client, fake)
    r = client.get(
        f"{API}/auth/google/callback",
        params={"code": "c", "state": "forged"},
        follow_redirects=False,
    )
    assert r.status_code == 401 and code(r) == "unauthenticated"
    fake.next_id_token = fake.id_token(nonce=fake.claims["nonce"], aud="other-client")
    r = client.get(
        f"{API}/auth/google/callback",
        params={"code": "c", "state": q["state"][0]},
        follow_redirects=False,
    )
    assert r.status_code == 401
    fake.next_id_token = fake.id_token(nonce=fake.claims["nonce"], email_verified=False)
    r = client.get(
        f"{API}/auth/google/callback",
        params={"code": "c", "state": q["state"][0]},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert client.get(f"{API}/auth/me").status_code == 401


def test_google_mode_has_no_dev_login(google):
    client, _ = google
    r = client.post(f"{API}/auth/dev", json={"email": "a@example.org"}, headers=CSRF)
    assert r.status_code == 404


def test_google_start_refused_in_other_modes(dev):
    assert dev.get(f"{API}/auth/google/start", follow_redirects=False).status_code == 404
