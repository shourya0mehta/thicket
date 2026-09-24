"""FastAPI app factory and server entry point.

``thicket.main:app`` is importable at module level for ``uvicorn``; it is
built lazily on first access, so importing this module reads no settings and
touches no files. Tests call :func:`create_app` with explicit settings.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from thicket.api.errors import install_error_handlers
from thicket.api.frontend import mount_frontend
from thicket.api.middleware import RequestMiddleware
from thicket.api.routes import api_router
from thicket.config import API_PORT, Settings, get_settings
from thicket.container import Container
from thicket.logging_setup import configure_logging

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        c = Container(settings)
        app.state.container = c
        c.startup(background=True)
        try:
            yield
        finally:
            c.shutdown()

    app = FastAPI(
        title="Thicket API",
        version=settings.app_version,
        description=(
            "Field audio in, transparent species detections, detection-derived metrics and "
            "exportable evidence out. Every error is an ErrorResponse with a typed error_code."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    install_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    mount_frontend(app, settings.serve_frontend_dir)

    app.add_middleware(RequestMiddleware, settings=settings)
    # Added last so it is outermost: CORS headers also go on 429/504/500 replies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
        expose_headers=["Content-Disposition", "Location", "Retry-After", "X-Request-ID"],
        max_age=600,
    )
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """Lazy ``app`` attribute (PEP 562) so ``uvicorn thicket.main:app`` works."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)


def run() -> None:
    """``thicket-api`` console script: one worker, because models load per worker."""
    import uvicorn

    uvicorn.run(
        "thicket.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=API_PORT,
        workers=1,
        log_config=None,
        access_log=False,
        proxy_headers=True,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
