"""Serve the built frontend (``SERVE_FRONTEND_DIR``) at ``/`` with SPA fallback.

Existing files are served as-is (hashed ``assets/`` with a long cache);
every other non-API path returns ``index.html`` so client-side routes work.
``/api/...`` paths are never shadowed.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from thicket.errors import not_found


def mount_frontend(app: FastAPI, root: Path | None) -> None:
    if root is None or not (root / "index.html").is_file():

        @app.get("/", include_in_schema=False)
        def api_root() -> JSONResponse:
            return JSONResponse({"name": "Thicket API", "api": "/api/v1", "docs": "/api/docs"})

        return

    root = root.resolve()
    index = root / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise not_found()
        if full_path:
            candidate = (root / full_path).resolve()
            if root in candidate.parents and candidate.is_file():
                immutable = candidate.parent.name == "assets"
                return FileResponse(
                    candidate,
                    headers={
                        "Cache-Control": "public, max-age=31536000, immutable"
                        if immutable
                        else "public, max-age=300"
                    },
                )
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
