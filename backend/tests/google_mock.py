"""A fake Google OpenID provider for tests: discovery, JWKS and token endpoint
served by ``httpx.MockTransport``, ID tokens signed with a throwaway RSA key."""

from __future__ import annotations

import json
import time
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from thicket.services.auth import GoogleOIDC

ISSUER = "https://accounts.google.com"
CLIENT_ID = "test-client.apps.googleusercontent.com"
CLIENT_SECRET = "test-secret"
KID = "test-key-1"


class FakeGoogle:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
        self.jwks = {"keys": [jwk]}
        self.claims: dict = {}
        self.token_status = 200
        self.requests: list[httpx.Request] = []
        self.next_id_token: str | None = None

    def id_token(self, *, key=None, kid: str = KID, **overrides) -> str:  # type: ignore[no-untyped-def]
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "1234567890",
            "email": "farmer@example.org",
            "email_verified": True,
            "name": "Jane Farmer",
            "picture": "https://example.org/p.png",
            "iat": now,
            "exp": now + 3600,
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key or self.key, algorithm="RS256", headers={"kid": kid})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                },
            )
        if url == "https://www.googleapis.com/oauth2/v3/certs":
            return httpx.Response(200, json=self.jwks)
        if url == "https://oauth2.googleapis.com/token":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"]
            assert form["code_verifier"][0]
            token = self.next_id_token or self.id_token(nonce=self.claims.get("nonce"))
            return httpx.Response(200, json={"id_token": token, "access_token": "at"})
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def oidc(
        self, redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    ) -> GoogleOIDC:
        return GoogleOIDC(CLIENT_ID, CLIENT_SECRET, redirect_uri, client=self.client())
