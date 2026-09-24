"""POST /previews, GET /previews/{id}, GET /previews/{id}/spectrogram.png."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from thicket.api.deps import check_content_length, container
from thicket.api.routes.openapi import ERRORS, upload_body
from thicket.api.schemas import Preview
from thicket.errors import invalid_parameter
from thicket.services.intake import parse_multipart_upload

router = APIRouter(tags=["previews"])


@router.post(
    "/previews",
    status_code=201,
    response_model=Preview,
    responses=ERRORS,
    openapi_extra=upload_body({"file": {"type": "string", "format": "binary"}}, required=["file"]),
)
async def create_preview(request: Request) -> JSONResponse:
    """Decode, inspect, QC and render a spectrogram without running a model.

    The file is kept until ``expires_at`` so an analysis can reuse it with
    ``preview_id``.
    """
    c = container(request)
    check_content_length(request, c.settings.max_upload_bytes)
    preview_id, folder = c.previews.new_dir()
    try:
        _, upload = await parse_multipart_upload(
            request.headers.get("content-type"),
            request.stream(),
            folder,
            max_bytes=c.settings.max_upload_bytes,
            allowed_fields={"file"},
        )
        if upload is None:
            raise invalid_parameter("Attach an audio file in the 'file' field.", field="file")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    preview = await run_in_threadpool(c.previews.create, preview_id, upload)
    return JSONResponse(
        preview.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/api/v1/previews/{preview_id}"},
    )


@router.get("/previews/{preview_id}", response_model=Preview, responses=ERRORS)
def get_preview(preview_id: str, request: Request) -> Preview:
    return container(request).previews.get(preview_id)


@router.get(
    "/previews/{preview_id}/spectrogram.png",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}, **ERRORS},
)
def preview_spectrogram(preview_id: str, request: Request) -> FileResponse:
    path = container(request).previews.spectrogram_path(preview_id)
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )
