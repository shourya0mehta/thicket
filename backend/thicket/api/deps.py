"""Request-scoped access to the service container."""

from __future__ import annotations

from fastapi import Request

from thicket.container import Container
from thicket.errors import invalid_parameter
from thicket.services.intake import file_too_large

MULTIPART_OVERHEAD_BYTES = 1024 * 1024


def container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def check_content_length(request: Request, max_bytes: int) -> None:
    """Reject obviously oversized uploads before reading the body."""
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        size = int(raw)
    except ValueError as exc:
        raise invalid_parameter("Invalid Content-Length header.") from exc
    if size > max_bytes + MULTIPART_OVERHEAD_BYTES:
        raise file_too_large(max_bytes)
