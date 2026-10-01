"""Dashboard, phenology, site comparison and alerts."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from thicket.api.deps import (
    OrgContext,
    authorize_resource,
    container,
    current_user,
    require_org_role,
)
from thicket.api.platform_schemas import (
    Alert,
    AlertPage,
    AlertStatus,
    AlertUpdate,
    Dashboard,
    Phenology,
    Role,
    SiteComparison,
)
from thicket.api.routes.openapi import ERRORS
from thicket.errors import invalid_parameter, not_found
from thicket.ids import is_valid_id
from thicket.persistence.db import utcnow
from thicket.services.auth import Principal
from thicket.services.dashboard import build_dashboard, build_phenology, build_site_comparison
from thicket.services.intake import clean_text
from thicket.services.notify import alert_model

router = APIRouter(tags=["insights"])


@router.get("/orgs/{org}/dashboard", response_model=Dashboard, responses=ERRORS)
def dashboard(
    request: Request,
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    site_id: str | None = Query(None),
    ctx: OrgContext = Depends(require_org_role(Role.viewer)),
) -> Dashboard:
    """Rollups for the period (default: the last 90 days)."""
    c = container(request)
    if site_id is not None:
        site = c.platform.get_site(site_id) if is_valid_id(site_id, "site") else None
        if site is None or site.organization_id != ctx.org_id:
            raise not_found("No site with that id exists in this organization.")
    rules = c.alerts.rules(ctx.org_id)
    return build_dashboard(
        c.platform,
        ctx.org_id,
        start=from_,
        end=to,
        site_id=site_id,
        priority_species=rules.priority_species,
    )


@router.get("/orgs/{org}/phenology", response_model=Phenology, responses=ERRORS)
def phenology(
    request: Request,
    scientific_name: str = Query(..., min_length=2, max_length=200),
    site_id: str | None = Query(None),
    years: int = Query(3, ge=1, le=10),
    ctx: OrgContext = Depends(require_org_role(Role.viewer)),
) -> Phenology:
    """Presence fraction and events per minute per ISO week and year for one species."""
    c = container(request)
    if site_id is not None:
        site = c.platform.get_site(site_id) if is_valid_id(site_id, "site") else None
        if site is None or site.organization_id != ctx.org_id:
            raise not_found("No site with that id exists in this organization.")
    name = clean_text(scientific_name, 200, "scientific_name") or ""
    return build_phenology(
        c.platform, ctx.org_id, scientific_name=name, site_id=site_id, years=years
    )


@router.get("/orgs/{org}/sites/compare", response_model=SiteComparison, responses=ERRORS)
def compare_sites(
    request: Request,
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    ctx: OrgContext = Depends(require_org_role(Role.viewer)),
) -> SiteComparison:
    c = container(request)
    sites = c.services.list_sites(ctx.org_id)
    return build_site_comparison(c.platform, ctx.org_id, sites, start=from_, end=to)


# ---------------------------------------------------------------- alerts


def _page(c, org_id: str, **filters) -> AlertPage:  # type: ignore[no-untyped-def]
    rows, total, by_status, by_category = c.platform.list_alerts(org_id, **filters)
    return AlertPage(
        items=[alert_model(a) for a in rows],
        total=total,
        counts_by_status=by_status,
        counts_by_category=by_category,
    )


@router.get("/orgs/{org}/alerts", response_model=AlertPage, responses=ERRORS)
def list_alerts(
    request: Request,
    status: str | None = Query(None),
    category: str | None = Query(None),
    kind: str | None = Query(None),
    site_id: str | None = Query(None),
    recorder_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: OrgContext = Depends(require_org_role(Role.viewer)),
) -> AlertPage:
    if status is not None and status not in {s.value for s in AlertStatus}:
        raise invalid_parameter(
            "status must be open, acknowledged, resolved or snoozed.", field="status"
        )
    if category is not None and category not in ("ecology", "quality", "recorder"):
        raise invalid_parameter("category must be ecology, quality or recorder.", field="category")
    return _page(
        container(request),
        ctx.org_id,
        status=status,
        category=category,
        kind=clean_text(kind, 40, "kind"),
        site_id=site_id,
        recorder_id=recorder_id,
        page=page,
        page_size=page_size,
    )


@router.patch("/alerts/{alert_id}", response_model=Alert, responses=ERRORS)
def update_alert(
    alert_id: str, body: AlertUpdate, request: Request, p: Principal = Depends(current_user)
) -> Alert:
    """Acknowledge, resolve, snooze or reopen an alert (reviewer and up)."""
    c = container(request)
    row = c.platform.get_alert(alert_id) if is_valid_id(alert_id, "alr") else None
    if row is None:
        raise not_found("No alert with that id exists.")
    authorize_resource(p, row.organization_id, Role.reviewer)
    values: dict = {"status": body.status.value, "note": clean_text(body.note, 2000, "note")}
    if body.status == AlertStatus.snoozed:
        if body.snoozed_until is None or body.snoozed_until <= utcnow():
            raise invalid_parameter("snoozed_until must be a future time.", field="snoozed_until")
        values["snoozed_until"] = body.snoozed_until
    else:
        values["snoozed_until"] = None
    if body.status in (AlertStatus.acknowledged, AlertStatus.resolved, AlertStatus.snoozed):
        values["acknowledged_by"] = p.user_id
    elif body.status == AlertStatus.open:
        values["acknowledged_by"] = None
    updated = c.platform.update_alert(row.id, values)
    assert updated is not None
    return alert_model(updated)


@router.post("/orgs/{org}/alerts/evaluate", response_model=AlertPage, responses=ERRORS)
def evaluate_alerts(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.manager))
) -> AlertPage:
    """Run the alert engine now and return the open alerts."""
    c = container(request)
    c.alerts.evaluate_org(ctx.org_id)
    return _page(c, ctx.org_id, open_only=True)
