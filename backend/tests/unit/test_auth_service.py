"""Sessions, principals and Google ID token verification (mocked provider)."""

import time
from urllib.parse import parse_qs, urlsplit

import pytest
from tests.google_mock import CLIENT_ID, FakeGoogle
from tests.helpers import make_settings

from thicket.errors import ThicketError
from thicket.ids import LOCAL_ORG_ID, LOCAL_USER_ID
from thicket.persistence.db import Database
from thicket.persistence.platform_repositories import PlatformRepository
from thicket.services.auth import (
    SESSION_MAX_AGE,
    AuthService,
    GoogleOIDC,
    safe_next,
)


class Clock:
    def __init__(self, t: float | None = None) -> None:
        self.t = t or time.time()

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def repo(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'a.sqlite3'}")
    db.create_all()
    yield PlatformRepository(db)
    db.dispose()


def service(tmp_path, repo, mode="dev", clock=None, google=None, **kw):
    extra = {"auth_mode": mode, **kw}
    if mode == "google":
        extra.setdefault("google_client_id", CLIENT_ID)
        extra.setdefault("google_client_secret", "s")
    return AuthService(
        make_settings(tmp_path, **extra),
        repo,
        secret="unit-test-secret-" + "x" * 32,
        google=google,
        clock=clock or Clock(),
    )


def test_disabled_mode_is_the_local_owner(tmp_path, repo):
    auth = service(tmp_path, repo, mode="disabled")
    p = auth.principal_from_cookie(None)
    assert p.is_local and p.user_id == LOCAL_USER_ID
    assert p.has_role(LOCAL_ORG_ID, "owner")
    assert auth.config().mode.value == "disabled" and auth.config().sign_in_url is None


def test_session_round_trip_and_revocation(tmp_path, repo):
    auth = service(tmp_path, repo)
    user = auth.dev_login("Farmer@Example.org", "Jane")
    assert user.email == "farmer@example.org" and user.name == "Jane"
    token, info = auth.issue_session(user.id)
    p = auth.principal_from_cookie(token)
    assert p.user_id == user.id and not p.is_local and p.session.session_id == info.session_id
    auth.revoke(p.session)
    assert auth.principal_from_cookie(token) is None


def test_tampered_and_garbage_cookies_are_rejected(tmp_path, repo):
    auth = service(tmp_path, repo)
    user = auth.dev_login("a@example.org", None)
    token, _ = auth.issue_session(user.id)
    assert auth.principal_from_cookie(token[:-2] + "xx") is None
    assert auth.principal_from_cookie("garbage") is None
    assert auth.principal_from_cookie(None) is None
    other = AuthService(auth.settings, repo, secret="another-secret-" + "y" * 32)
    assert other.principal_from_cookie(token) is None


def test_session_expires_after_30_days_and_refreshes_after_an_hour(tmp_path, repo):
    clock = Clock(1_800_000_000.0)
    auth = service(tmp_path, repo, clock=clock)
    user = auth.dev_login("a@example.org", None)
    token, _ = auth.issue_session(user.id)
    assert not auth.read_session(token).refresh
    clock.t += 2 * 3600
    assert auth.read_session(token).refresh
    # itsdangerous checks age against the real clock; sign an old token by moving its iat.
    old = auth.serializer.dumps({"sid": "ses_" + "1" * 24, "uid": user.id, "iat": 1})
    import itsdangerous

    real = itsdangerous.timed.TimestampSigner.get_timestamp
    try:
        itsdangerous.timed.TimestampSigner.get_timestamp = lambda self: (
            int(time.time()) - SESSION_MAX_AGE - 10
        )  # type: ignore[method-assign]
        expired = auth.serializer.dumps({"sid": "ses_" + "2" * 24, "uid": user.id, "iat": 1})
    finally:
        itsdangerous.timed.TimestampSigner.get_timestamp = real  # type: ignore[method-assign]
    assert auth.read_session(expired) is None
    assert auth.read_session(old) is not None  # signature is fresh, iat only drives refresh


def test_local_user_cannot_sign_in_by_cookie(tmp_path, repo):
    auth = service(tmp_path, repo)
    token, _ = auth.issue_session(LOCAL_USER_ID)
    assert auth.principal_from_cookie(token) is None


def test_dev_login_validation_and_domains(tmp_path, repo):
    auth = service(tmp_path, repo, allowed_signin_domains="example.org")
    with pytest.raises(ThicketError) as e:
        auth.dev_login("not-an-email", None)
    assert e.value.code.value == "invalid_parameter"
    with pytest.raises(ThicketError) as e:
        auth.dev_login("someone@gmail.com", None)
    assert e.value.code.value == "forbidden"
    assert auth.dev_login("ok@example.org", None).email == "ok@example.org"


def test_dev_login_refused_outside_dev_mode(tmp_path, repo):
    auth = service(tmp_path, repo, mode="disabled")
    with pytest.raises(ThicketError) as e:
        auth.dev_login("a@example.org", None)
    assert e.value.code.value == "not_found"


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, "/"),
        ("/sites/1", "/sites/1"),
        ("#/alerts", "/alerts"),
        ("//evil.example", "/"),
        ("https://evil.example/x", "/"),
        ("/\\evil", "/"),
        ("sites", "/"),
    ],
)
def test_safe_next(value, expected):
    assert safe_next(value) == expected


# ----------------------------------------------------------- Google


@pytest.fixture
def fake():
    return FakeGoogle()


def test_pkce_pair_is_s256():
    import base64
    import hashlib

    verifier, challenge = GoogleOIDC.pkce_pair()
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert 43 <= len(verifier) <= 128


def test_authorization_url_carries_pkce_state_and_nonce(fake):
    url = fake.oidc().authorization_url(state="st", code_challenge="ch", nonce="no")
    q = parse_qs(urlsplit(url).query)
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"] == ["ch"]
    assert q["state"] == ["st"] and q["nonce"] == ["no"] and q["client_id"] == [CLIENT_ID]
    assert q["scope"] == ["openid email profile"] and q["response_type"] == ["code"]


def test_valid_id_token(fake):
    claims = fake.oidc().verify_id_token(fake.id_token(nonce="n1"), "n1")
    assert claims["email"] == "farmer@example.org" and claims["sub"] == "1234567890"


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"aud": "someone-else"}, "unauthenticated"),
        ({"iss": "https://evil.example"}, "unauthenticated"),
        ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}, "unauthenticated"),
        ({"email_verified": False}, "forbidden"),
        ({"email": None}, "unauthenticated"),
        ({"nonce": "other"}, "unauthenticated"),
    ],
)
def test_invalid_id_tokens(fake, overrides, code):
    token = fake.id_token(**{"nonce": "n1", **overrides})
    with pytest.raises(ThicketError) as e:
        fake.oidc().verify_id_token(token, "n1")
    assert e.value.code.value == code


def test_token_signed_by_another_key_is_rejected(fake):
    with pytest.raises(ThicketError):
        fake.oidc().verify_id_token(fake.id_token(key=fake.other_key), None)
    with pytest.raises(ThicketError):
        fake.oidc().verify_id_token(fake.id_token(kid="unknown-kid"), None)
    with pytest.raises(ThicketError):
        fake.oidc().verify_id_token("not.a.jwt", None)


def test_full_google_flow_through_the_service(tmp_path, repo, fake):
    auth = service(tmp_path, repo, mode="google", google=fake.oidc())
    url, cookie = auth.start_google("/sites")
    q = parse_qs(urlsplit(url).query)
    fake.claims["nonce"] = q["nonce"][0]
    user, next_path = auth.finish_google(
        code="abc", state=q["state"][0], error=None, oauth_cookie=cookie
    )
    assert user.email == "farmer@example.org" and user.google_sub == "1234567890"
    assert next_path == "/sites"
    assert auth.post_login_redirect(next_path) == "http://localhost:5173/#/sites"
    # The token endpoint got the PKCE verifier.
    token_req = [r for r in fake.requests if "oauth2.googleapis.com/token" in str(r.url)][0]
    assert b"code_verifier=" in token_req.content


def test_google_flow_rejects_wrong_state_missing_cookie_and_errors(tmp_path, repo, fake):
    auth = service(tmp_path, repo, mode="google", google=fake.oidc())
    url, cookie = auth.start_google(None)
    state = parse_qs(urlsplit(url).query)["state"][0]
    for kw in (
        {"code": "c", "state": "wrong", "error": None, "oauth_cookie": cookie},
        {"code": "c", "state": state, "error": None, "oauth_cookie": None},
        {"code": None, "state": state, "error": "access_denied", "oauth_cookie": cookie},
    ):
        with pytest.raises(ThicketError) as e:
            auth.finish_google(**kw)
        assert e.value.code.value == "unauthenticated"
    fake.token_status = 400
    with pytest.raises(ThicketError):
        auth.finish_google(code="c", state=state, error=None, oauth_cookie=cookie)


def test_oauth_and_session_cookies_are_not_interchangeable(tmp_path, repo, fake):
    """Both are signed with the same secret, but with different salts."""
    auth = service(tmp_path, repo, mode="google", google=fake.oidc())
    _url, oauth_cookie = auth.start_google(None)
    assert auth.read_session(oauth_cookie) is None
    user = repo.upsert_user(email="a@example.org", name=None)
    session_cookie, _ = auth.issue_session(user.id)
    forged = auth.serializer.dumps({"state": "s", "verifier": "v", "nonce": "n", "next": "/"})
    for cookie in (session_cookie, forged):
        with pytest.raises(ThicketError) as e:
            auth.finish_google(code="c", state="s", error=None, oauth_cookie=cookie)
        assert e.value.code.value == "unauthenticated"


def test_google_domain_restriction(tmp_path, repo, fake):
    auth = service(
        tmp_path, repo, mode="google", google=fake.oidc(), allowed_signin_domains="farm.coop"
    )
    url, cookie = auth.start_google(None)
    q = parse_qs(urlsplit(url).query)
    fake.claims["nonce"] = q["nonce"][0]
    with pytest.raises(ThicketError) as e:
        auth.finish_google(code="c", state=q["state"][0], error=None, oauth_cookie=cookie)
    assert e.value.code.value == "forbidden"


def test_jwks_refetched_on_unknown_kid(fake):
    oidc = fake.oidc()
    oidc.verify_id_token(fake.id_token(), None)
    import json as _json

    import jwt as _jwt

    jwk = _json.loads(_jwt.algorithms.RSAAlgorithm.to_jwk(fake.other_key.public_key()))
    jwk.update({"kid": "rotated", "alg": "RS256"})
    fake.jwks["keys"].append(jwk)
    assert oidc.verify_id_token(fake.id_token(key=fake.other_key, kid="rotated"), None)["sub"]
