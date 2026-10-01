"""Batch uploads, recordings and uploaded images."""

from __future__ import annotations

import hashlib
import secrets
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from thicket.api.deps import (
    OrgContext,
    authorize_resource,
    check_content_length,
    container,
    current_user,
    require_org_role,
)
from thicket.api.platform_schemas import (
    BatchJob,
    RecordingPage,
    RecordingSummary,
    Role,
    UploadedFile,
)
from thicket.api.routes.openapi import ERRORS, upload_body
from thicket.api.schemas import ErrorCode
from thicket.errors import ThicketError, invalid_parameter, not_found
from thicket.ids import is_valid_id, new_id
from thicket.services.auth import Principal
from thicket.services.ingest import parse_multipart_batch
from thicket.services.intake import sanitize_filename
from thicket.services.params import parse_captured_at
from thicket.services.storage import IMAGE_EXTENSIONS

router = APIRouter(tags=["uploads"])

_BATCH_FORM = {
    "files": {
        "type": "array",
        "items": {"type": "string", "format": "binary"},
        "description": "Audio files, zips, Song Meter *_Summary.txt, AudioMoth CONFIG.TXT",
    },
    "site_id": {"type": "string"},
    "deployment_id": {"type": "string"},
    "recorder_id": {"type": "string"},
    "timezone": {"type": "string", "description": "IANA zone of the recorder's clock (required)."},
    "models": {"type": "string"},
    "threshold": {"type": "number"},
    "last_modified": {
        "type": "array",
        "items": {"type": "string"},
        "description": "ms since epoch per file, same order as files",
    },
    "captured_at_override": {"type": "string", "format": "date-time"},
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_SIGNATURES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}


@router.post(
    "/orgs/{org}/uploads",
    status_code=202,
    response_model=BatchJob,
    responses=ERRORS,
    openapi_extra=upload_body(_BATCH_FORM, required=["files", "site_id", "timezone"]),
)
async def create_batch(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.manager))
) -> JSONResponse:
    """Upload many files (and zips). Returns the job to poll at ``GET /uploads/{job_id}``."""
    c = container(request)
    check_content_length(request, c.settings.max_batch_bytes)
    staging_id = new_id("job")
    staging = c.storage.job_tmp(staging_id)
    staging.mkdir(parents=True)
    handed_off = False
    try:
        fields, files = await parse_multipart_batch(
            request.headers.get("content-type"),
            request.stream(),
            staging,
            per_file_max=c.settings.max_upload_bytes,
            max_total_bytes=c.settings.max_batch_bytes,
            max_files=c.settings.max_batch_files,
        )
        if not files:
            raise invalid_parameter("Attach at least one file in the 'files' field.", field="files")
        req = c.ingest.parse_request(ctx.org_id, fields, c.registry, ctx.user_id)
        job = await run_in_threadpool(c.ingest.start, req, files, staging)
        handed_off = True
    finally:
        if not handed_off:
            shutil.rmtree(staging, ignore_errors=True)
    found = c.platform.get_job(job.id)
    assert found is not None
    body = c.ingest.job_model(*found)
    return JSONResponse(
        body.model_dump(mode="json"),
        status_code=202,
        headers={"Location": f"/api/v1/uploads/{job.id}"},
    )


@router.get("/uploads/{job_id}", response_model=BatchJob, responses=ERRORS)
def get_batch(job_id: str, request: Request, p: Principal = Depends(current_user)) -> BatchJob:
    c = container(request)
    found = c.platform.get_job(job_id) if is_valid_id(job_id, "job") else None
    if found is None:
        raise not_found("No upload job with that id exists.")
    job, items = found
    authorize_resource(p, job.organization_id, Role.viewer)
    return c.ingest.job_model(job, items)


@router.get("/orgs/{org}/uploads", response_model=list[BatchJob], responses=ERRORS)
def list_batches(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    ctx: OrgContext = Depends(require_org_role(Role.viewer)),
) -> list[BatchJob]:
    c = container(request)
    return [c.ingest.job_model(j, None) for j in c.platform.list_jobs(ctx.org_id, limit)]


# ------------------------------------------------------------ recordings


def _dt(value: str | None, field: str, tz: str | None) -> datetime | None:
    if value is None:
        return None
    dt = parse_captured_at(value, tz)
    if dt is not None and dt.tzinfo is None:
        from zoneinfo import ZoneInfo

        dt = dt.replace(tzinfo=ZoneInfo(tz or "UTC"))
    return dt


@router.get("/orgs/{org}/recordings", response_model=RecordingPage, responses=ERRORS)
def list_recordings(
    request: Request,
    site_id: str | None = Query(None),
    recorder_id: str | None = Query(None),
    deployment_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    quality: str | None = Query(None),
    species: str | None = Query(None),
    ctx: OrgContext = Depends(require_org_role(Role.viewer)),
) -> RecordingPage:
    c = container(request)
    org = c.platform.get_org(ctx.org_id)
    tz = org.timezone if org else "UTC"
    if quality is not None and quality not in ("usable", "usable_with_warnings", "not_usable"):
        raise invalid_parameter(
            "quality must be usable, usable_with_warnings or not_usable.", field="quality"
        )
    return c.services.recordings_page(
        ctx.org_id,
        site_id=site_id,
        recorder_id=recorder_id,
        deployment_id=deployment_id,
        since=_dt(from_, "from", tz),
        until=_dt(to, "to", tz),
        page=page,
        page_size=page_size,
        quality=quality,
        species=species,
    )


@router.get("/recordings/{recording_id}", response_model=RecordingSummary, responses=ERRORS)
def get_recording(
    recording_id: str, request: Request, p: Principal = Depends(current_user)
) -> RecordingSummary:
    c = container(request)
    view = c.platform.get_recording(recording_id) if is_valid_id(recording_id, "rec") else None
    if view is None:
        raise not_found("No recording with that id exists.")
    authorize_resource(p, view.recording.organization_id, Role.viewer)
    return c.services.recording_model(view)


@router.delete("/recordings/{recording_id}", status_code=204, responses=ERRORS)
def delete_recording(
    recording_id: str, request: Request, p: Principal = Depends(current_user)
) -> Response:
    """Removes the recording, its analyses, reviews, spectrograms and retained audio."""
    c = container(request)
    view = c.platform.get_recording(recording_id) if is_valid_id(recording_id, "rec") else None
    if view is None:
        raise not_found("No recording with that id exists.")
    authorize_resource(p, view.recording.organization_id, Role.manager)
    c.services.delete_recording(view, c.rollups)
    return Response(status_code=204)


# ----------------------------------------------------------------- files


@router.post(
    "/orgs/{org}/files",
    status_code=201,
    response_model=UploadedFile,
    responses=ERRORS,
    openapi_extra=upload_body({"file": {"type": "string", "format": "binary"}}, required=["file"]),
)
async def upload_file(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.manager))
) -> JSONResponse:
    """Upload a png or jpg (10 MB) for deployment photos and tract maps in reports."""
    c = container(request)
    check_content_length(request, MAX_IMAGE_BYTES)
    tmp = c.storage.files / f"tmp_{secrets.token_hex(8)}"
    tmp.mkdir(parents=True)
    try:
        upload = await _parse_image(request, tmp)
        with open(upload.path, "rb") as fh:
            head = fh.read(8)
        content_type = next(
            (ct for sig, ct in IMAGE_SIGNATURES.items() if head.startswith(sig)), None
        )
        if content_type is None or content_type not in IMAGE_EXTENSIONS:
            raise ThicketError(ErrorCode.unsupported_file_type, "Upload a png or jpg image.")
        file_id = new_id("file")
        dest = c.storage.uploaded_file_path(file_id, content_type)
        shutil.move(str(upload.path), dest)
        row = c.platform.create_file(
            {
                "organization_id": ctx.org_id,
                "filename": upload.filename,
                "content_type": content_type,
                "byte_size": upload.size,
                "checksum_sha256": upload.hash.hexdigest(),
                "storage_uri": c.storage.storage_uri(dest),
                "created_by": ctx.user_id,
            }
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    body = UploadedFile(
        id=row.id,
        organization_id=row.organization_id,
        filename=row.filename,
        content_type=row.content_type,
        byte_size=row.byte_size,
        url=f"/api/v1/files/{row.id}",
        created_at=row.created_at,
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=201)


class _ImageSink:
    """One image part, capped, hashed, with the display name kept."""

    def __init__(self, tmp, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        self.max_bytes = max_bytes
        self.path = tmp / f"{secrets.token_hex(8)}.img"
        self.fh = open(self.path, "xb")  # noqa: SIM115
        self.size = 0
        self.hash = hashlib.sha256()
        self.filename = "image"

    def write(self, data: bytes) -> None:
        self.size += len(data)
        if self.size > self.max_bytes:
            self.fh.close()
            raise ThicketError(
                ErrorCode.file_too_large,
                f"The image is larger than the {self.max_bytes // (1024 * 1024)} MB limit.",
            )
        self.hash.update(data)
        self.fh.write(data)


async def _parse_image(request: Request, tmp) -> _ImageSink:  # type: ignore[no-untyped-def]
    from python_multipart.exceptions import FormParserError
    from python_multipart.multipart import MultipartParser, parse_options_header

    ctype, params = parse_options_header(request.headers.get("content-type") or "")
    if ctype != b"multipart/form-data" or b"boundary" not in params:
        raise invalid_parameter("Send the request as multipart/form-data.")
    state: dict = {"sink": None, "name": b"", "value": b"", "disp": b"", "field": ""}
    sinks: list[_ImageSink] = []

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state["name"] += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        state["value"] += data[start:end]

    def on_header_end() -> None:
        if state["name"].lower() == b"content-disposition":
            state["disp"] = state["value"]
        state["name"], state["value"] = b"", b""

    def on_headers_finished() -> None:
        _, options = parse_options_header(state["disp"])
        name = options.get(b"name", b"").decode("utf-8", "replace")
        if name != "file":
            raise invalid_parameter(f"Unknown form field '{name[:40]}'.", field=name[:40])
        if b"filename" not in options:
            raise invalid_parameter("The 'file' field must be a file upload.", field="file")
        if sinks:
            raise invalid_parameter("Upload one image per request.", field="file")
        sink = _ImageSink(tmp, MAX_IMAGE_BYTES)
        sink.filename = sanitize_filename(options[b"filename"].decode("utf-8", "replace"), "image")
        sinks.append(sink)
        state["sink"] = sink

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if state["sink"] is not None:
            state["sink"].write(data[start:end])

    def on_part_end() -> None:
        if state["sink"] is not None:
            state["sink"].fh.close()
            state["sink"] = None

    def on_part_begin() -> None:
        state["disp"] = b""

    parser = MultipartParser(
        params[b"boundary"],  # type: ignore[arg-type]
        {
            "on_part_begin": on_part_begin,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
        },
    )
    try:
        async for chunk in request.stream():
            if chunk:
                parser.write(chunk)
        parser.finalize()
    except FormParserError as exc:
        raise invalid_parameter("Malformed multipart body.") from exc
    if not sinks or sinks[0].size == 0:
        raise invalid_parameter("Attach an image in the 'file' field.", field="file")
    return sinks[0]


@router.get("/files/{file_id}", response_class=FileResponse, responses=ERRORS)
def get_file(file_id: str, request: Request, p: Principal = Depends(current_user)) -> FileResponse:
    c = container(request)
    row = c.platform.get_file(file_id) if is_valid_id(file_id, "file") else None
    if row is None:
        raise not_found("No file with that id exists.")
    authorize_resource(p, row.organization_id, Role.viewer)
    path = c.storage.resolve_uri(row.storage_uri)
    if path is None or not path.is_file():
        raise not_found("The file is missing.")
    return FileResponse(
        path, media_type=row.content_type, headers={"Cache-Control": "private, max-age=86400"}
    )
