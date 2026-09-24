"""Request middleware: rate limiting, request timeouts, error safety net and
structured access logs, in one pure ASGI layer.

* Rate limit: an in-memory token bucket per client IP applied to POST
  requests (``RATE_LIMIT_PER_MINUTE``; 0 disables). Over the limit returns
  429 ``rate_limited`` with ``Retry-After``. Behind a reverse proxy, run
  uvicorn with ``--proxy-headers`` so the client IP is the real one.
* Timeout: ``REQUEST_TIMEOUT_SECONDS`` per request, plus
  ``ANALYSIS_TIMEOUT_SECONDS`` for ``?wait=true``. A timed-out request gets
  504 ``request_timeout`` if nothing was sent yet.
* Unhandled exceptions become 500 ``internal_error`` without internals.
* Access log: method, path, status, duration and request id. Never query
  bodies, filenames, notes or client IPs.
"""

from __future__ import annotations

import logging
import math
import secrets
import threading
import time
from urllib.parse import parse_qs

import anyio
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from thicket.api.errors import error_response
from thicket.api.schemas import ErrorCode
from thicket.config import Settings

log = logging.getLogger("thicket.access")


class TokenBucketLimiter:
    """``capacity`` requests per minute per key, refilled continuously."""

    def __init__(self, per_minute: int, clock=time.monotonic, max_keys: int = 10_000) -> None:  # type: ignore[no-untyped-def]
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.clock = clock
        self.max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        """Return (allowed, seconds until the next token)."""
        if self.capacity <= 0:
            return True, 0.0
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                allowed, wait = True, 0.0
            else:
                self._buckets[key] = (tokens, now)
                allowed, wait = False, (1.0 - tokens) / self.rate
            if len(self._buckets) > self.max_keys:
                self._prune(now)
        return allowed, wait

    def _prune(self, now: float) -> None:
        full_after = self.capacity / self.rate
        for k, (_, last) in list(self._buckets.items()):
            if now - last > full_after:
                del self._buckets[k]


SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
]


class RequestMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.limiter = TokenBucketLimiter(settings.rate_limit_per_minute)

    def _timeout(self, scope: Scope) -> float:
        timeout = self.settings.request_timeout_seconds
        qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        if qs.get("wait", ["false"])[-1].lower() in ("1", "true", "yes"):
            timeout += self.settings.analysis_timeout_seconds
        return timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        method = scope.get("method", "GET")
        path = scope.get("path", "")
        request_id = secrets.token_hex(8)
        state = {"started": False, "status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["started"] = True
                state["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers.append("x-request-id", request_id)
                for k, v in SECURITY_HEADERS:
                    if k.decode() not in headers:
                        headers.append(k.decode(), v.decode())
            await send(message)

        try:
            if method == "POST" and path.startswith("/api/"):
                client = scope.get("client")
                allowed, wait = self.limiter.allow(client[0] if client else "unknown")
                if not allowed:
                    retry = max(1, math.ceil(wait))
                    resp = error_response(
                        ErrorCode.rate_limited,
                        f"Too many requests. Try again in {retry} s.",
                        429,
                        {"retry_after_seconds": retry},
                        headers={"Retry-After": str(retry)},
                    )
                    await resp(scope, receive, send_wrapper)
                    return
            with anyio.move_on_after(self._timeout(scope)) as scope_cancel:
                await self.app(scope, receive, send_wrapper)
            if scope_cancel.cancelled_caught and not state["started"]:
                resp = error_response(
                    ErrorCode.request_timeout, "The request took too long and was stopped.", 504
                )
                await resp(scope, receive, send_wrapper)
        except Exception:  # noqa: BLE001 - last-resort safety net
            log.exception("unhandled error", extra={"request_id": request_id, "path": path})
            if not state["started"]:
                resp = error_response(ErrorCode.internal_error, "An internal error occurred.", 500)
                await resp(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status": state["status"],
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                },
            )
