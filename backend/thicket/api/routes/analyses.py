"""Analyses: create, list, read at a threshold, delete, assets and exports."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from thicket.api.deps import check_content_length, container
from thicket.api.routes.openapi import ERRORS, upload_body
from thicket.api.schemas import Analysis, AnalysisExport, AnalysisList, AnalysisStatus, ErrorCode
from thicket.container import Container
from thicket.errors import ThicketError, analysis_not_found, invalid_parameter, not_found
from thicket.ids import new_id
from thicket.services.exports import csv_text, export_filename, json_export
from thicket.services.intake import StoredUpload, clean_text, parse_multipart_upload
from thicket.services.params import ANALYSIS_FIELDS, AnalysisParams, parse_analysis_params

router = APIRouter(tags=["analyses"])

THRESHOLD_QUERY = Query(
    None,
    description="Decision threshold for events, species and metrics. Defaults to the analysis's own.",
)

_FORM = {
    "file": {"type": "string", "format": "binary", "description": ".wav .mp3 .m4a .flac or .ogg"},
    "preview_id": {"type": "string", "description": "Reuse a preview's upload instead of a file."},
    "models": {
        "type": "string",
        "description": 'JSON array or comma list of model keys. Default ["birdnet"].',
    },
    "threshold": {"type": "number", "description": "Decision threshold, default 0.60."},
    "latitude": {"type": "number", "minimum": -90, "maximum": 90},
    "longitude": {"type": "number", "minimum": -180, "maximum": 180},
    "captured_at": {"type": "string", "format": "date-time"},
    "timezone": {"type": "string", "description": "IANA name, e.g. America/New_York"},
    "site_name": {"type": "string"},
    "notes": {"type": "string"},
    "recorder_type": {"type": "string"},
}


def _create_and_submit(
    c: Container, analysis_id: str, upload: StoredUpload, params: AnalysisParams, tmp: Path
) -> None:
    job = c.analysis.create(analysis_id, upload, params, tmp)
    c.analysis.submit(job)


@router.post(
    "/analyses",
    status_code=202,
    response_model=Analysis,
    responses={201: {"model": Analysis, "description": "Completed (wait=true)"}, **ERRORS},
    openapi_extra=upload_body(_FORM),
)
async def create_analysis(
    request: Request,
    wait: bool = Query(
        False, description="Run synchronously and return the completed analysis (201)."
    ),
) -> JSONResponse:
    """Upload a recording (or reuse a preview) and start an analysis.

    Returns 202 with the queued analysis (poll ``GET /analyses/{id}``), or 201
    with the completed analysis when ``wait=true``.
    """
    c = container(request)
    check_content_length(request, c.settings.max_upload_bytes)
    analysis_id = new_id("ana")
    tmp = c.storage.analysis_tmp(analysis_id)
    tmp.mkdir(parents=True)
    handed_off = False
    try:
        fields, upload = await parse_multipart_upload(
            request.headers.get("content-type"),
            request.stream(),
            tmp,
            max_bytes=c.settings.max_upload_bytes,
            allowed_fields=ANALYSIS_FIELDS,
        )
        params = parse_analysis_params(fields, c.settings, c.registry)
        preview_id = clean_text(fields.get("preview_id"), 64, "preview_id")
        if upload is not None and preview_id:
            raise invalid_parameter(
                "Send either a file or a preview_id, not both.", field="preview_id"
            )
        if upload is None:
            if not preview_id:
                raise invalid_parameter(
                    "Attach an audio file in the 'file' field or pass a preview_id.", field="file"
                )
            upload = await run_in_threadpool(c.previews.materialize, preview_id, tmp)
        await run_in_threadpool(_create_and_submit, c, analysis_id, upload, params, tmp)
        handed_off = True
    finally:
        if not handed_off:
            shutil.rmtree(tmp, ignore_errors=True)

    location = {"Location": f"/api/v1/analyses/{analysis_id}"}
    if wait:
        await run_in_threadpool(c.analysis.wait, analysis_id, None)
        analysis = await run_in_threadpool(c.analysis.view, analysis_id, None)
        if analysis.status == AnalysisStatus.failed:
            raise ThicketError(
                analysis.error_code or ErrorCode.internal_error,
                analysis.error_message or "The analysis failed.",
                detail={"analysis_id": analysis_id},
            )
        return JSONResponse(analysis.model_dump(mode="json"), status_code=201, headers=location)
    analysis = await run_in_threadpool(c.analysis.view, analysis_id, None)
    return JSONResponse(analysis.model_dump(mode="json"), status_code=202, headers=location)


@router.get("/analyses", response_model=AnalysisList, responses=ERRORS)
def list_analyses(request: Request, limit: int = Query(20, ge=1, le=100)) -> AnalysisList:
    """Most recent analyses first."""
    return container(request).analysis.list_recent(limit)


@router.get("/analyses/{analysis_id}", response_model=Analysis, responses=ERRORS)
def get_analysis(
    analysis_id: str, request: Request, threshold: float | None = THRESHOLD_QUERY
) -> Analysis:
    """The full analysis, with events, species and metrics recomputed at ``threshold``."""
    return container(request).analysis.view(analysis_id, threshold)


@router.delete("/analyses/{analysis_id}", status_code=204, responses=ERRORS)
def delete_analysis(analysis_id: str, request: Request) -> Response:
    """Delete the analysis, its detections, reviews, spectrogram and any retained audio."""
    container(request).analysis.delete(analysis_id)
    return Response(status_code=204)


@router.get(
    "/analyses/{analysis_id}/spectrogram.png",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}, **ERRORS},
)
def analysis_spectrogram(analysis_id: str, request: Request) -> FileResponse:
    c = container(request)
    path = c.storage.spectrogram_path(analysis_id)  # validates the id
    row = c.repo.get_analysis(analysis_id)
    if row is None:
        raise analysis_not_found()
    if not row.has_spectrogram or not path.is_file():
        raise not_found("The spectrogram is not ready yet.")
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"}
    )


@router.get(
    "/analyses/{analysis_id}/audio",
    response_class=FileResponse,
    responses={200: {"content": {"audio/wav": {}}}, **ERRORS},
)
def analysis_audio(analysis_id: str, request: Request) -> FileResponse:
    """Normalized audio (48 kHz mono WAV). Only when the server retains audio."""
    c = container(request)
    path = c.storage.audio_path(analysis_id)
    bundle = c.repo.load_bundle(analysis_id, with_detections=False)
    if bundle is None:
        raise analysis_not_found()
    uri = bundle.recording.storage_uri if bundle.recording else None
    stored = c.storage.resolve_uri(uri)
    if stored is None or stored != path or not path.is_file():
        raise not_found("Audio is not retained on this server (RETAIN_AUDIO=false).")
    return FileResponse(
        path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"}
    )


@router.get(
    "/analyses/{analysis_id}/export.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}, **ERRORS},
)
def export_csv(
    analysis_id: str, request: Request, threshold: float | None = THRESHOLD_QUERY
) -> Response:
    analysis = container(request).analysis.view(analysis_id, threshold)
    _require_completed(analysis)
    return Response(
        csv_text(analysis),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(analysis, "csv")}"'
        },
    )


@router.get("/analyses/{analysis_id}/export.json", response_model=AnalysisExport, responses=ERRORS)
def export_json(
    analysis_id: str, request: Request, threshold: float | None = THRESHOLD_QUERY
) -> JSONResponse:
    analysis = container(request).analysis.view(analysis_id, threshold)
    _require_completed(analysis)
    return JSONResponse(
        json_export(analysis).model_dump(mode="json"),
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(analysis, "json")}"'
        },
    )


def _require_completed(analysis: Analysis) -> None:
    if analysis.status != AnalysisStatus.completed:
        raise invalid_parameter(
            f"The analysis is {analysis.status.value}; exports are available once it completes."
        )
