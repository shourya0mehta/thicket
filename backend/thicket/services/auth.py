"""Accounts and sign-in.

Three modes (``AUTH_MODE``):

* ``disabled``: every request is the implicit local owner (``user_local``) of
  the implicit organization (``org_local``). No cookies, no CSRF header.
* ``dev``: an email-only form (``POST /auth/dev``) creates or finds a user and
  sets the session cookie. Refused in production.
* ``google``: OpenID Connect authorization code flow with PKCE. The ID token
  is verified against Google's JWKS (signature, ``aud``, ``iss``, ``exp``,
  ``nonce``) and ``email_verified`` must be true. ``ALLOWED_SIGNIN_DOMAINS``
  restricts who can sign in at all.

Sessions are stateless signed cookies (itsdangerous, ``SESSION_SECRET``):
``{sid, uid, iat}``, 30 days, re-signed on use once older than an hour
(rolling). Logout puts the ``sid`` on a server-side revocation list that is
pruned once the cookie itself would have expired. Cookies are HttpOnly,
SameSite=Lax and Secure when ``PUBLIC_BASE_URL`` is https.

The OAuth ``state``, PKCE verifier and ``nonce`` travel in a separate signed
cookie that lives ten minutes.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from itsdangerous import BadSignature, URLSafeTimedSerializer

from thicket.api.platform_schemas import AuthConfig, AuthMode, Role
from thicket.config import Settings
from thicket.errors import forbidden, invalid_parameter, not_found, unauthenticated
from thicket.ids import LOCAL_ORG_ID, LOCAL_USER_ID, is_valid_id, new_id
from thicket.persistence.db import UserRow
from thicket.persistence.platform_repositories import (
    PlatformRepository,
    normalize_email,
    role_at_least,
)

log = logging.getLogger(__name__)

SESSION_COOKIE = "thicket_session"
OAUTH_COOKIE = "thicket_oauth"
SESSION_MAX_AGE = 30 * 24 * 3600
SESSION_REFRESH_AFTER = 3600
OAUTH_MAX_AGE = 600
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "thicket"
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SECRET_FILE = "session_secret"


# ---------------------------------------------------------------- secrets


def load_session_secret(settings: Settings) -> str:
    """``SESSION_SECRET`` or a random secret persisted under the data dir."""
    if settings.session_secret:
        return settings.session_secret
    path = settings.data_dir / SECRET_FILE
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    except OSError:
        pass
    secret = secrets.token_urlsafe(48)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(secret, encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(path)
    except OSError:
        log.warning("could not persist the session secret; sessions end with the process")
    if settings.is_production and settings.auth_enabled:
        log.warning(
            "SESSION_SECRET is unset; a generated secret was written under the data dir. "
            "Set SESSION_SECRET so sessions survive redeploys across hosts."
        )
    return secret


# -------------------------------------------------------------- principal


@dataclass
class SessionInfo:
    session_id: str
    user_id: str
    issued_at: float
    expires_at: datetime
    refresh: bool = False


@dataclass
class Principal:
    user: UserRow
    roles: dict[str, str] = field(default_factory=dict)
    session: SessionInfo | None = None
    is_local: bool = False

    @property
    def user_id(self) -> str:
        return self.user.id

    def role_in(self, org_id: str) -> str | None:
        return self.roles.get(org_id)

    def has_role(self, org_id: str, minimum: str | Role) -> bool:
        role = self.roles.get(org_id)
        return role is not None and role_at_least(role, str(minimum))


# ----------------------------------------------------------- Google OIDC


class GoogleOIDC:
    """Discovery, authorization URL, code exchange and ID token verification.

    ``client`` is any :class:`httpx.Client`; tests pass one with a
    ``MockTransport``. Discovery and JWKS are cached for an hour.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        client: httpx.Client | None = None,
        discovery_url: str = GOOGLE_DISCOVERY_URL,
        clock=time.time,  # type: ignore[no-untyped-def]
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.client = client or httpx.Client(timeout=10.0)
        self.discovery_url = discovery_url
        self.clock = clock
        self._discovery: dict | None = None
        self._discovery_at = 0.0
        self._jwks: dict | None = None
        self._jwks_at = 0.0
        self.cache_seconds = 3600.0

    def discovery(self) -> dict:
        if self._discovery is None or self.clock() - self._discovery_at > self.cache_seconds:
            r = self.client.get(self.discovery_url)
            r.raise_for_status()
            self._discovery = r.json()
            self._discovery_at = self.clock()
        return self._discovery

    def jwks(self, force: bool = False) -> dict:
        if force or self._jwks is None or self.clock() - self._jwks_at > self.cache_seconds:
            r = self.client.get(self.discovery()["jwks_uri"])
            r.raise_for_status()
            self._jwks = r.json()
            self._jwks_at = self.clock()
        return self._jwks

    @staticmethod
    def pkce_pair() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    def authorization_url(
        self, *, state: str, code_challenge: str, nonce: str, login_hint: str | None = None
    ) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self.discovery()['authorization_endpoint']}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> dict:
        r = self.client.post(
            self.discovery()["token_endpoint"],
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            raise unauthenticated("Google did not accept the sign-in code. Try again.")
        return r.json()

    def verify_id_token(self, token: str, nonce: str | None) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise unauthenticated("The sign-in token could not be read.") from exc
        kid = header.get("kid")
        key = self._key_for(kid)
        if key is None:
            key = self._key_for(kid, force=True)
        if key is None:
            raise unauthenticated("The sign-in token was signed with an unknown key.")
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=list(GOOGLE_ISSUERS),
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
                leeway=60,
            )
        except jwt.ExpiredSignatureError as exc:
            raise unauthenticated("The sign-in token has expired. Try again.") from exc
        except jwt.PyJWTError as exc:
            raise unauthenticated("The sign-in token is not valid.") from exc
        if nonce is not None and claims.get("nonce") != nonce:
            raise unauthenticated("The sign-in response did not match this browser.")
        if not claims.get("email"):
            raise unauthenticated("Google did not return an email address.")
        if claims.get("email_verified") is not True:
            raise forbidden("Only verified Google email addresses can sign in.")
        return claims

    def _key_for(self, kid: str | None, force: bool = False):  # type: ignore[no-untyped-def]
        for jwk_dict in self.jwks(force=force).get("keys", []):
            if kid is None or jwk_dict.get("kid") == kid:
                try:
                    return jwt.PyJWK(jwk_dict, algorithm="RS256").key
                except jwt.PyJWTError:
                    continue
        return None


# ------------------------------------------------------------ the service


class AuthService:
    def __init__(
        self,
        settings: Settings,
        repo: PlatformRepository,
        *,
        secret: str | None = None,
        google: GoogleOIDC | None = None,
        clock=time.time,  # type: ignore[no-untyped-def]
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.clock = clock
        self.mode = AuthMode(settings.auth_mode)
        self._secret = secret
        self._serializer: URLSafeTimedSerializer | None = None
        self._google = google

    # -- wiring ---------------------------------------------------------
    @property
    def serializer(self) -> URLSafeTimedSerializer:
        if self._serializer is None:
            if self._secret is None:
                self._secret = load_session_secret(self.settings)
            self._serializer = URLSafeTimedSerializer(self._secret, salt="thicket.session")
        return self._serializer

    @property
    def google(self) -> GoogleOIDC:
        if self._google is None:
            assert self.settings.google_client_id and self.settings.google_client_secret
            self._google = GoogleOIDC(
                self.settings.google_client_id,
                self.settings.google_client_secret,
                self.settings.google_redirect_uri,
            )
        return self._google

    @property
    def enabled(self) -> bool:
        return self.mode != AuthMode.disabled

    def cookie_params(self, max_age: int) -> dict[str, Any]:
        return {
            "max_age": max_age,
            "httponly": True,
            "samesite": "lax",
            "secure": self.settings.cookie_secure,
            "path": "/",
        }

    def config(self) -> AuthConfig:
        return AuthConfig(
            mode=self.mode,
            google_client_id=self.settings.google_client_id
            if self.mode == AuthMode.google
            else None,
            sign_in_url="/api/v1/auth/google/start" if self.mode == AuthMode.google else None,
            allowed_domains=list(self.settings.allowed_signin_domains),
        )

    # -- sessions -------------------------------------------------------
    def issue_session(self, user_id: str) -> tuple[str, SessionInfo]:
        sid = new_id("ses")
        now = self.clock()
        token = self.serializer.dumps({"sid": sid, "uid": user_id, "iat": int(now)})
        info = SessionInfo(
            session_id=sid,
            user_id=user_id,
            issued_at=now,
            expires_at=datetime.fromtimestamp(now + SESSION_MAX_AGE, UTC),
        )
        return token, info

    def read_session(self, cookie: str | None) -> SessionInfo | None:
        if not cookie:
            return None
        try:
            data = self.serializer.loads(cookie, max_age=SESSION_MAX_AGE)
        except BadSignature:
            return None
        sid, uid, iat = data.get("sid"), data.get("uid"), data.get("iat")
        if not (is_valid_id(sid, "ses") and is_valid_id(uid, "user") and isinstance(iat, int)):
            return None
        if self.repo.is_session_revoked(sid):
            return None
        now = self.clock()
        return SessionInfo(
            session_id=sid,
            user_id=uid,
            issued_at=float(iat),
            expires_at=datetime.fromtimestamp(iat + SESSION_MAX_AGE, UTC),
            refresh=(now - iat) > SESSION_REFRESH_AFTER,
        )

    def revoke(self, session: SessionInfo) -> None:
        self.repo.revoke_session(session.session_id, session.user_id, session.expires_at)

    # -- principals -----------------------------------------------------
    def local_principal(self) -> Principal:
        user = self.repo.get_user(LOCAL_USER_ID)
        if user is None:  # pragma: no cover - created at startup
            raise unauthenticated("The local workspace is not initialized.")
        roles = self.repo.roles_for_user(LOCAL_USER_ID)
        roles.setdefault(LOCAL_ORG_ID, "owner")
        return Principal(user=user, roles=roles, session=None, is_local=True)

    def principal_from_cookie(self, cookie: str | None) -> Principal | None:
        """The signed-in principal, or None. Disabled mode always yields the local owner."""
        if not self.enabled:
            return self.local_principal()
        session = self.read_session(cookie)
        if session is None:
            return None
        user = self.repo.get_user(session.user_id)
        if user is None or user.id == LOCAL_USER_ID:
            return None
        return Principal(user=user, roles=self.repo.roles_for_user(user.id), session=session)

    # -- sign-in flows --------------------------------------------------
    def check_domain(self, email: str) -> None:
        allowed = self.settings.allowed_signin_domains
        if not allowed:
            return
        domain = email.rsplit("@", 1)[-1].lower()
        if domain not in allowed:
            raise forbidden(
                "This Thicket instance only accepts sign-ins from "
                + ", ".join(allowed)
                + " addresses."
            )

    def dev_login(self, email: str, name: str | None) -> UserRow:
        if self.mode != AuthMode.dev:
            raise not_found("Email sign-in is only available when AUTH_MODE=dev.")
        email = normalize_email(email)
        if "@" not in email or len(email) > 320 or " " in email:
            raise invalid_parameter("Enter a valid email address.", field="email")
        self.check_domain(email)
        return self.repo.upsert_user(email=email, name=(name or "").strip() or None)

    def start_google(self, next_path: str | None) -> tuple[str, str]:
        """Return (redirect URL to Google, signed state cookie value)."""
        if self.mode != AuthMode.google:
            raise not_found("Google sign-in is not enabled on this server.")
        verifier, challenge = GoogleOIDC.pkce_pair()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        url = self.google.authorization_url(state=state, code_challenge=challenge, nonce=nonce)
        cookie = self.serializer.dumps(
            {
                "state": state,
                "verifier": verifier,
                "nonce": nonce,
                "next": safe_next(next_path),
                "t": int(self.clock()),
            }
        )
        return url, cookie

    def finish_google(
        self, *, code: str | None, state: str | None, error: str | None, oauth_cookie: str | None
    ) -> tuple[UserRow, str]:
        """Validate state, exchange the code, verify the ID token; return (user, next path)."""
        if self.mode != AuthMode.google:
            raise not_found("Google sign-in is not enabled on this server.")
        if error:
            raise unauthenticated("Google sign-in was cancelled or refused.")
        try:
            saved = self.serializer.loads(oauth_cookie or "", max_age=OAUTH_MAX_AGE)
        except BadSignature as exc:
            raise unauthenticated(
                "The sign-in attempt expired or did not start in this browser. Try again."
            ) from exc
        if not code or not state or not secrets.compare_digest(str(saved.get("state")), state):
            raise unauthenticated("The sign-in response did not match this browser. Try again.")
        tokens = self.google.exchange_code(code, str(saved.get("verifier", "")))
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise unauthenticated("Google did not return an identity token.")
        claims = self.google.verify_id_token(id_token, str(saved.get("nonce")))
        email = normalize_email(str(claims["email"]))
        self.check_domain(email)
        user = self.repo.upsert_user(
            email=email,
            name=str(claims.get("name") or "").strip() or None,
            picture_url=str(claims["picture"]) if claims.get("picture") else None,
            google_sub=str(claims["sub"]),
        )
        log.info("user signed in", extra={"user_id": user.id, "method": "google"})
        return user, str(saved.get("next") or "/")

    def post_login_redirect(self, next_path: str) -> str:
        base = self.settings.frontend_url
        path = safe_next(next_path)
        return f"{base}/#{path}" if path.startswith("/") else f"{base}/#/"


def safe_next(value: str | None) -> str:
    """Only same-app paths (``/...``), never another origin."""
    if not value:
        return "/"
    text = value.strip()
    if text.startswith("#"):
        text = text[1:]
    if not text.startswith("/") or text.startswith("//") or "\\" in text:
        return "/"
    parts = urlsplit(text)
    if parts.scheme or parts.netloc:
        return "/"
    return text[:500]


def secret_path(data_dir: Path) -> Path:
    return data_dir / SECRET_FILE
