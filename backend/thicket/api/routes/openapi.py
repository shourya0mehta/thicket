"""OpenAPI helpers for routes that parse multipart bodies themselves."""

from __future__ import annotations

from thicket.api.schemas import ErrorResponse

ERRORS: dict[int | str, dict] = {
    "4XX": {"model": ErrorResponse, "description": "Typed client error"},
    "5XX": {"model": ErrorResponse, "description": "Typed server error"},
}


def upload_body(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required or [],
                    }
                }
            },
        }
    }
