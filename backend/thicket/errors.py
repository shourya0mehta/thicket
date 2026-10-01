"""Typed application errors.

Every failure a client can see is a :class:`ThicketError` carrying an
:class:`~thicket.api.schemas.ErrorCode` and an HTTP status. The API turns
them into ``ErrorResponse`` bodies; the CLI prints them. Messages are written
for end users: plain language, no internals.
"""

from __future__ import annotations

from typing import Any

from thicket.api.schemas import ErrorCode
from thicket.models.base import AdapterError, ModelUnavailable, UnsupportedAudio

# Default HTTP status per error code.
HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.unsupported_file_type: 415,
    ErrorCode.file_too_large: 413,
    ErrorCode.audio_too_long: 422,
    ErrorCode.audio_decode_failed: 422,
    ErrorCode.audio_too_short: 422,
    ErrorCode.unsupported_audio: 422,
    ErrorCode.model_unavailable: 503,
    ErrorCode.unknown_model: 422,
    ErrorCode.invalid_parameter: 422,
    ErrorCode.analysis_not_found: 404,
    ErrorCode.event_not_found: 404,
    ErrorCode.not_found: 404,
    ErrorCode.analysis_timeout: 504,
    ErrorCode.request_timeout: 504,
    ErrorCode.rate_limited: 429,
    ErrorCode.internal_error: 500,
    ErrorCode.unauthenticated: 401,
    ErrorCode.forbidden: 403,
    ErrorCode.conflict: 409,
}


class ThicketError(Exception):
    """An error with a stable, typed code that is safe to show to users."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = ErrorCode(code)
        self.message = message
        self.status_code = status_code or HTTP_STATUS.get(self.code, 500)
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ThicketError({self.code.value!r}, {self.message!r})"


def invalid_parameter(message: str, *, field: str | None = None) -> ThicketError:
    return ThicketError(
        ErrorCode.invalid_parameter, message, detail={"field": field} if field else None
    )


def not_found(message: str = "Not found.") -> ThicketError:
    return ThicketError(ErrorCode.not_found, message)


def analysis_not_found() -> ThicketError:
    return ThicketError(ErrorCode.analysis_not_found, "No analysis with that id exists.")


def event_not_found() -> ThicketError:
    return ThicketError(
        ErrorCode.event_not_found,
        "No detection event with that id exists. Load the analysis first, then review its events.",
    )


def unauthenticated(message: str = "Sign in to continue.") -> ThicketError:
    return ThicketError(ErrorCode.unauthenticated, message)


def forbidden(message: str = "You do not have permission to do this.") -> ThicketError:
    return ThicketError(ErrorCode.forbidden, message)


def conflict(message: str, *, detail: dict[str, Any] | None = None) -> ThicketError:
    return ThicketError(ErrorCode.conflict, message, detail=detail)


def from_adapter_error(exc: AdapterError) -> ThicketError:
    """Map a model adapter's typed error onto the API error codes."""
    if isinstance(exc, ModelUnavailable):
        return ThicketError(ErrorCode.model_unavailable, str(exc) or "The model is unavailable.")
    if isinstance(exc, UnsupportedAudio):
        return ThicketError(
            ErrorCode.unsupported_audio, str(exc) or "This audio is not supported by the model."
        )
    return ThicketError(ErrorCode.internal_error, "The model failed while analyzing this audio.")
