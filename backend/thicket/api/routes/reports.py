"""Report templates, report jobs and their PDF and JSON files."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from thicket.api.deps import (
    OrgContext,
    authorize_resource,
    container,
    current_user,
    require_org_role,
)
from thicket.api.platform_schemas import Report, ReportCreate, ReportList, ReportTemplates, Role
from thicket.api.routes.openapi import ERRORS
from thicket.errors import not_found
from thicket.ids import is_valid_id
from thicket.persistence.db import ReportRow
from thicket.reports.field_schema import templates
from thicket.services.auth import Principal

router = APIRouter(tags=["reports"])


@router.get("/reports/templates", response_model=ReportTemplates, responses=ERRORS)
def report_templates(p: Principal = Depends(current_user)) -> ReportTemplates:
    """The five templates with their pages and user-entered fields (docs/REPORTING.md)."""
    return templates()


@router.post("/orgs/{org}/reports", response_model=Report, status_code=202, responses=ERRORS)
def create_report(
    body: ReportCreate,
    request: Request,
    ctx: OrgContext = Depends(require_org_role(Role.reviewer)),
) -> JSONResponse:
    """Queue a report; poll ``GET /reports/{id}`` until ``status`` is ``ready``."""
    report = container(request).reports.create(ctx.org_id, body, ctx.user_id)
    return JSONResponse(
        report.model_dump(mode="json"),
        status_code=202,
        headers={"Location": f"/api/v1/reports/{report.id}"},
    )


@router.get("/orgs/{org}/reports", response_model=ReportList, responses=ERRORS)
def list_reports(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.viewer))
) -> ReportList:
    c = container(request)
    return ReportList(items=[c.reports.model(r) for r in c.platform.list_reports(ctx.org_id)])


# The file routes are declared before ``/reports/{report_id}`` so that path does not
# swallow ``<id>.pdf`` and ``<id>.json``.
def _report(request: Request, report_id: str, p: Principal, minimum: Role) -> ReportRow:
    c = container(request)
    row = c.platform.get_report(report_id) if is_valid_id(report_id, "rpt") else None
    if row is None:
        raise not_found("No report with that id exists.")
    authorize_resource(p, row.organization_id, minimum)
    return row


@router.get(
    "/reports/{report_id}.pdf",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}, **ERRORS},
)
def report_pdf(
    report_id: str, request: Request, p: Principal = Depends(current_user)
) -> FileResponse:
    row = _report(request, report_id, p, Role.viewer)
    path = container(request).reports.pdf_path(row)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="thicket_{row.template}_{row.id}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/reports/{report_id}.json",
    response_class=FileResponse,
    responses={200: {"content": {"application/json": {}}}, **ERRORS},
)
def report_bundle(
    report_id: str, request: Request, p: Principal = Depends(current_user)
) -> FileResponse:
    """The data bundle the PDF was rendered from."""
    row = _report(request, report_id, p, Role.viewer)
    path = container(request).reports.bundle_path(row)
    return FileResponse(
        path,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="thicket_{row.template}_{row.id}.json"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/reports/{report_id}", response_model=Report, responses=ERRORS)
def get_report(report_id: str, request: Request, p: Principal = Depends(current_user)) -> Report:
    return container(request).reports.model(_report(request, report_id, p, Role.viewer))


@router.delete("/reports/{report_id}", status_code=204, responses=ERRORS)
def delete_report(
    report_id: str, request: Request, p: Principal = Depends(current_user)
) -> Response:
    row = _report(request, report_id, p, Role.manager)
    container(request).reports.delete(row)
    return Response(status_code=204)
