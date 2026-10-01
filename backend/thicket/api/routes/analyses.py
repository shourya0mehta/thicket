"""Analyses: create, list, read at a threshold, delete, assets and exports.

Tenancy (schema 3): every recording belongs to an organization. ``POST
/analyses`` takes ``organization_id`` (defaulting to the caller's only
organization, or the local workspace when sign-in is disabled) and needs the
manager role there; reads need membership of the recording's organization
and a foreign id answers 404. With ``AUTH_MODE=disabled`` the implicit local
owner satisfies all of this, so the single-recording workspace works as before.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from thicket.api.deps import authorize_resource, check_content_length, container, current_user
from thicket.api.platform_schemas import Role
from thicket.api.routes.openapi import ERRORS, upload_body
from thicket.api.schemas import Analysis, AnalysisExport, AnalysisList, AnalysisStatus, ErrorCode
from thicket.container import Container
from thicket.errors import (
    ThicketError,
    analysis_not_found,
    forbidden,
    invalid_parameter,
    not_found,
)
from thicket.ids import LOCAL_ORG_ID, is_valid_id, new_id
from thicket.services.auth import Principal
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
    "organization_id": {"type": "string", "description": "Defaults to your only organization."},
    "site_id": {"type": "string"},
    "deployment_id": {"type": "string"},
    "recorder_id": {"type": "string"},
}


def _create_and_submit(
    c: Container, analysis_id: str, upload: StoredUpload, params: AnalysisParams, tmp: Path
) -> None:
    job = c.analysis.create(analysis_id, upload, params, tmp)
    c.analysis.submit(job)


def resolve_tenancy(c: Container, p: Principal, params: AnalysisParams) -> AnalysisParams:
    """Pick the organization, check the manager role and that linked ids belong to it."""
    org_id = params.organization_id
    if org_id is None:
        if p.is_local:
            org_id = LOCAL_ORG_ID
        elif not p.roles:
            raise forbidden("Create or join an organization before uploading recordings.")
        elif len(p.roles) == 1:
            org_id = next(iter(p.roles))
        else:
            raise invalid_parameter(
                "organization_id is required when you belong to more than one organization.",
                field="organization_id",
            )
    if p.role_in(org_id) is None:
        raise forbidden("You are not a member of that organization.")
    if not p.has_role(org_id, Role.manager):
        raise forbidden("Starting an analysis needs the manager role in the organization.")
    site_id, deployment_id, recorder_id = params.site_id, params.deployment_id, params.recorder_id
    if deployment_id:
        dep = c.platform.get_deployment(deployment_id)
        if dep is None or dep.organization_id != org_id:
            raise invalid_parameter(
                "deployment_id does not belong to this organization.", field="deployment_id"
            )
        site_id = site_id or dep.site_id
        recorder_id = recorder_id or dep.recorder_id
    if site_id:
        site = c.platform.get_site(site_id)
        if site is None or site.organization_id != org_id:
            raise invalid_parameter(
                "site_id does not belong to this organization.", field="site_id"
            )
    if recorder_id:
        rec = c.platform.get_recorder(recorder_id)
        if rec is None or rec.organization_id != org_id:
            raise invalid_parameter(
                "recorder_id does not belong to this organization.", field="recorder_id"
            )
    return replace(
        params,
        organization_id=org_id,
        site_id=site_id,
        deployment_id=deployment_id,
        recorder_id=recorder_id,
    )


def authorize_analysis(request: Request, analysis_id: str, p: Principal, minimum: Role) -> None:
    """404 for unknown or foreign analyses; 403 for too low a role."""
    if not is_valid_id(analysis_id, "ana"):
        raise analysis_not_found()
    org_id = container(request).platform.org_of_analysis(analysis_id)
    if org_id is None:
        raise analysis_not_found()
    if p.role_in(org_id) is None:
        raise analysis_not_found()
    authorize_resource(p, org_id, minimum)


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
    p: Principal = Depends(current_user),
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
        params = resolve_tenancy(c, p, parse_analysis_params(fields, c.settings, c.registry))
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
        params = replace(params, source_filename=upload.filename)
        await run_in_threadpool(_create_and_submit, c, analysis_id, upload, params, tmp)
        handed_off = True
    finally:
        if not handed_off:
            shutil.rmtree(tmp, ignore_errors=True)
    if preview_id and not c.settings.retain_audio:
        # The analysis has its own copy; do not keep the upload for the preview TTL.
        await run_in_threadpool(c.previews.release_audio, preview_id)

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
def list_analyses(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    p: Principal = Depends(current_user),
) -> AnalysisList:
    """Most recent analyses first, across the caller's organizations."""
    c = container(request)
    if p.is_local:
        # The implicit local owner sees the whole local database.
        return c.analysis.list_recent(limit)
    return c.analysis.list_recent(limit, org_ids=list(p.roles))


@router.get("/analyses/{analysis_id}", response_model=Analysis, responses=ERRORS)
def get_analysis(
    analysis_id: str,
    request: Request,
    threshold: float | None = THRESHOLD_QUERY,
    p: Principal = Depends(current_user),
) -> Analysis:
    """The full analysis, with events, species and metrics recomputed at ``threshold``."""
    authorize_analysis(request, analysis_id, p, Role.viewer)
    return container(request).analysis.view(analysis_id, threshold)


@router.delete("/analyses/{analysis_id}", status_code=204, responses=ERRORS)
def delete_analysis(
    analysis_id: str, request: Request, p: Principal = Depends(current_user)
) -> Response:
    """Delete the analysis, its detections, reviews, spectrogram and any retained audio."""
    authorize_analysis(request, analysis_id, p, Role.manager)
    c = container(request)
    recording_id = c.platform.recording_id_for_analysis(analysis_id)
    c.analysis.delete(analysis_id)
    if recording_id:
        c.rollups.remove_recording(recording_id)
    return Response(status_code=204)


@router.get(
    "/analyses/{analysis_id}/spectrogram.png",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}, **ERRORS},
)
def analysis_spectrogram(
    analysis_id: str, request: Request, p: Principal = Depends(current_user)
) -> FileResponse:
    authorize_analysis(request, analysis_id, p, Role.viewer)
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
def analysis_audio(
    analysis_id: str, request: Request, p: Principal = Depends(current_user)
) -> FileResponse:
    """Normalized audio (48 kHz mono WAV). Only when the server retains audio."""
    authorize_analysis(request, analysis_id, p, Role.viewer)
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
    analysis_id: str,
    request: Request,
    threshold: float | None = THRESHOLD_QUERY,
    p: Principal = Depends(current_user),
) -> Response:
    authorize_analysis(request, analysis_id, p, Role.viewer)
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
    analysis_id: str,
    request: Request,
    threshold: float | None = THRESHOLD_QUERY,
    p: Principal = Depends(current_user),
) -> JSONResponse:
    authorize_analysis(request, analysis_id, p, Role.viewer)
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
