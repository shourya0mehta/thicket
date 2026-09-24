"""Exception handlers: every error leaves the API as an ``ErrorResponse``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from thicket.api.schemas import ErrorCode, ErrorResponse
from thicket.errors import ThicketError

log = logging.getLogger(__name__)


def error_body(code: ErrorCode, message: str, detail: dict | None = None) -> dict:
    return ErrorResponse(error_code=code, message=message, detail=detail).model_dump(mode="json")


def error_response(
    code: ErrorCode,
    message: str,
    status_code: int,
    detail: dict | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    return JSONResponse(error_body(code, message, detail), status_code=status_code, headers=headers)


async def _thicket_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ThicketError)
    return error_response(exc.code, exc.message, exc.status_code, exc.detail)


def _loc(loc: tuple | list) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "request"


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"field": _loc(e.get("loc", ())), "message": str(e.get("msg", "invalid value"))}
        for e in exc.errors()
    ]
    first = errors[0] if errors else {"field": "request", "message": "invalid value"}
    return error_response(
        ErrorCode.invalid_parameter,
        f"Invalid {first['field']}: {first['message']}.",
        422,
        {"errors": errors[:10]},
    )


_HTTP_CODES = {
    404: (ErrorCode.not_found, "Not found."),
    405: (ErrorCode.invalid_parameter, "This method is not allowed on this path."),
    413: (ErrorCode.file_too_large, "The request is too large."),
    415: (ErrorCode.unsupported_file_type, "Unsupported media type."),
}


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = _HTTP_CODES.get(
        exc.status_code,
        (
            ErrorCode.invalid_parameter
            if 400 <= exc.status_code < 500
            else ErrorCode.internal_error,
            "The request could not be processed."
            if exc.status_code < 500
            else "An internal error occurred.",
        ),
    )
    return error_response(code, message, exc.status_code, headers=getattr(exc, "headers", None))


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ThicketError, _thicket_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
