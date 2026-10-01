"""Sites, recorders, deployments, species accumulation and recorder health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from thicket.api.deps import (
    OrgContext,
    authorize_resource,
    container,
    current_user,
    require_org_role,
)
from thicket.api.platform_schemas import (
    Accumulation,
    Deployment,
    DeploymentCreate,
    DeploymentUpdate,
    Recorder,
    RecorderCreate,
    RecorderHealth,
    RecorderUpdate,
    Role,
    Site,
    SiteCreate,
    SiteUpdate,
)
from thicket.api.routes.openapi import ERRORS
from thicket.errors import not_found
from thicket.ids import is_valid_id
from thicket.persistence.db import DeploymentRow, RecorderRow, SiteRow
from thicket.services.auth import Principal
from thicket.services.dashboard import build_accumulation

router = APIRouter(tags=["sites"])


def _site(
    request: Request, site_id: str, p: Principal, minimum: Role
) -> tuple[SiteRow, OrgContext]:
    c = container(request)
    row = c.platform.get_site(site_id) if is_valid_id(site_id, "site") else None
    if row is None:
        raise not_found("No site with that id exists.")
    return row, authorize_resource(p, row.organization_id, minimum)


def _recorder(
    request: Request, recorder_id: str, p: Principal, minimum: Role
) -> tuple[RecorderRow, OrgContext]:
    c = container(request)
    row = c.platform.get_recorder(recorder_id) if is_valid_id(recorder_id, "rcd") else None
    if row is None:
        raise not_found("No recorder with that id exists.")
    return row, authorize_resource(p, row.organization_id, minimum)


def _deployment(
    request: Request, deployment_id: str, p: Principal, minimum: Role
) -> tuple[DeploymentRow, OrgContext]:
    c = container(request)
    row = c.platform.get_deployment(deployment_id) if is_valid_id(deployment_id, "dep") else None
    if row is None:
        raise not_found("No deployment with that id exists.")
    return row, authorize_resource(p, row.organization_id, minimum)


# ---------------------------------------------------------------- sites


@router.get("/orgs/{org}/sites", response_model=list[Site], responses=ERRORS)
def list_sites(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.viewer))
) -> list[Site]:
    return container(request).services.list_sites(ctx.org_id)


@router.post("/orgs/{org}/sites", response_model=Site, status_code=201, responses=ERRORS)
def create_site(
    body: SiteCreate, request: Request, ctx: OrgContext = Depends(require_org_role(Role.manager))
) -> Site:
    return container(request).services.create_site(ctx.org_id, body)


@router.get("/sites/{site_id}", response_model=Site, responses=ERRORS)
def get_site(site_id: str, request: Request, p: Principal = Depends(current_user)) -> Site:
    row, _ = _site(request, site_id, p, Role.viewer)
    return container(request).services.site_model(row)


@router.patch("/sites/{site_id}", response_model=Site, responses=ERRORS)
def update_site(
    site_id: str, body: SiteUpdate, request: Request, p: Principal = Depends(current_user)
) -> Site:
    row, _ = _site(request, site_id, p, Role.manager)
    c = container(request)
    site = c.services.update_site(row, body)
    # Coordinates drive sun-based hour buckets; do not keep the old ones cached.
    c.rollups.reset_cache()
    return site


@router.delete("/sites/{site_id}", status_code=204, responses=ERRORS)
def delete_site(site_id: str, request: Request, p: Principal = Depends(current_user)) -> Response:
    """Refused with 409 ``conflict`` while recordings exist for the site."""
    row, _ = _site(request, site_id, p, Role.manager)
    container(request).services.delete_site(row)
    return Response(status_code=204)


@router.get("/sites/{site_id}/accumulation", response_model=Accumulation, responses=ERRORS)
def site_accumulation(
    site_id: str, request: Request, p: Principal = Depends(current_user)
) -> Accumulation:
    """Cumulative distinct species across the site's recordings in time order."""
    row, ctx = _site(request, site_id, p, Role.viewer)
    return build_accumulation(container(request).platform, ctx.org_id, row.id)


# ------------------------------------------------------------ recorders


@router.get("/orgs/{org}/recorders", response_model=list[Recorder], responses=ERRORS)
def list_recorders(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.viewer))
) -> list[Recorder]:
    c = container(request)
    return c.services.recorder_models(ctx.org_id, c.platform.list_recorders(ctx.org_id))


@router.post("/orgs/{org}/recorders", response_model=Recorder, status_code=201, responses=ERRORS)
def create_recorder(
    body: RecorderCreate,
    request: Request,
    ctx: OrgContext = Depends(require_org_role(Role.manager)),
) -> Recorder:
    return container(request).services.create_recorder(ctx.org_id, body)


@router.get("/recorders/{recorder_id}", response_model=Recorder, responses=ERRORS)
def get_recorder(
    recorder_id: str, request: Request, p: Principal = Depends(current_user)
) -> Recorder:
    row, _ = _recorder(request, recorder_id, p, Role.viewer)
    return container(request).services.recorder_model(row)


@router.patch("/recorders/{recorder_id}", response_model=Recorder, responses=ERRORS)
def update_recorder(
    recorder_id: str, body: RecorderUpdate, request: Request, p: Principal = Depends(current_user)
) -> Recorder:
    row, _ = _recorder(request, recorder_id, p, Role.manager)
    return container(request).services.update_recorder(row, body)


@router.delete("/recorders/{recorder_id}", status_code=204, responses=ERRORS)
def delete_recorder(
    recorder_id: str, request: Request, p: Principal = Depends(current_user)
) -> Response:
    """Refused with 409 ``conflict`` while recordings exist for the recorder."""
    row, _ = _recorder(request, recorder_id, p, Role.manager)
    container(request).services.delete_recorder(row)
    return Response(status_code=204)


@router.get("/recorders/{recorder_id}/health", response_model=RecorderHealth, responses=ERRORS)
def recorder_health(
    recorder_id: str,
    request: Request,
    days: int = Query(30, ge=1, le=366),
    p: Principal = Depends(current_user),
) -> RecorderHealth:
    """Series, gaps, checks and uptime from signal profiles and telemetry."""
    row, ctx = _recorder(request, recorder_id, p, Role.viewer)
    c = container(request)
    recorder = c.services.recorder_model(row)
    dep = c.platform.deployment_for(row.id, None)
    if dep is None:
        deps = c.platform.list_deployments(ctx.org_id, recorder_id=row.id)
        dep = deps[0] if deps else None
    return c.health.build(
        row,
        recorder,
        c.services.deployment_model(dep) if dep else None,
        dep,
        days=days,
    )


# ---------------------------------------------------------- deployments


@router.get("/orgs/{org}/deployments", response_model=list[Deployment], responses=ERRORS)
def list_deployments(
    request: Request,
    active: bool | None = Query(None),
    ctx: OrgContext = Depends(require_org_role(Role.viewer)),
) -> list[Deployment]:
    c = container(request)
    return [
        c.services.deployment_model(d)
        for d in c.platform.list_deployments(ctx.org_id, active=active)
    ]


@router.post(
    "/orgs/{org}/deployments", response_model=Deployment, status_code=201, responses=ERRORS
)
def create_deployment(
    body: DeploymentCreate,
    request: Request,
    ctx: OrgContext = Depends(require_org_role(Role.manager)),
) -> Deployment:
    return container(request).services.create_deployment(ctx.org_id, body)


@router.get("/deployments/{deployment_id}", response_model=Deployment, responses=ERRORS)
def get_deployment(
    deployment_id: str, request: Request, p: Principal = Depends(current_user)
) -> Deployment:
    row, _ = _deployment(request, deployment_id, p, Role.viewer)
    return container(request).services.deployment_model(row)


@router.patch("/deployments/{deployment_id}", response_model=Deployment, responses=ERRORS)
def update_deployment(
    deployment_id: str,
    body: DeploymentUpdate,
    request: Request,
    p: Principal = Depends(current_user),
) -> Deployment:
    row, _ = _deployment(request, deployment_id, p, Role.manager)
    return container(request).services.update_deployment(row, body)


@router.delete("/deployments/{deployment_id}", status_code=204, responses=ERRORS)
def delete_deployment(
    deployment_id: str, request: Request, p: Principal = Depends(current_user)
) -> Response:
    """Recordings keep their site and recorder; only the deployment link is cleared."""
    row, _ = _deployment(request, deployment_id, p, Role.manager)
    container(request).platform.delete_deployment(row.id)
    return Response(status_code=204)
