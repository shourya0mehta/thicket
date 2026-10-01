"""Organizations, members, invites and alert rules."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from thicket.api.deps import OrgContext, container, current_user, require_org_role
from thicket.api.platform_schemas import (
    AlertRules,
    Invite,
    InviteCreate,
    Membership,
    MembershipUpdate,
    Organization,
    OrganizationCreate,
    OrganizationUpdate,
    Role,
)
from thicket.api.routes.openapi import ERRORS
from thicket.errors import forbidden, not_found
from thicket.ids import LOCAL_ORG_ID, is_valid_id
from thicket.services.auth import Principal

router = APIRouter(tags=["organizations"])


@router.get("/orgs", response_model=list[Organization], responses=ERRORS)
def list_orgs(request: Request, p: Principal = Depends(current_user)) -> list[Organization]:
    """Organizations the signed-in user belongs to."""
    return container(request).services.orgs_for(p)


@router.post("/orgs", response_model=Organization, status_code=201, responses=ERRORS)
def create_org(
    body: OrganizationCreate, request: Request, p: Principal = Depends(current_user)
) -> Organization:
    """Create an organization; the creator becomes its owner."""
    return container(request).services.create_org(p, body)


@router.get("/orgs/{org}", response_model=Organization, responses=ERRORS)
def get_org(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.viewer))
) -> Organization:
    c = container(request)
    org = c.platform.get_org(ctx.org_id)
    if org is None:
        raise not_found("No organization with that id exists.")
    return c.services.org_model(org)


@router.patch("/orgs/{org}", response_model=Organization, responses=ERRORS)
def update_org(
    body: OrganizationUpdate,
    request: Request,
    ctx: OrgContext = Depends(require_org_role(Role.manager)),
) -> Organization:
    """Rename or change settings. A new time zone moves every day boundary, so the
    organization's rollups are rebuilt right away rather than at the nightly run."""
    c = container(request)
    before = c.platform.get_org(ctx.org_id)
    org = c.services.update_org(ctx.org_id, body)
    c.rollups.reset_cache()
    if before is not None and before.timezone != org.timezone:
        c.rollups.rebuild(ctx.org_id)
    return org


@router.delete("/orgs/{org}", status_code=204, responses=ERRORS)
def delete_org(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.owner))
) -> Response:
    """Delete the organization and everything in it (sites, recordings, alerts, reports)."""
    if ctx.org_id == LOCAL_ORG_ID:
        raise forbidden("The local workspace cannot be deleted.")
    c = container(request)
    c.services.delete_org(ctx.org_id, c.storage)
    ctx.principal.roles.pop(ctx.org_id, None)
    return Response(status_code=204)


# ------------------------------------------------------------- members


@router.get("/orgs/{org}/members", response_model=list[Membership], responses=ERRORS)
def list_members(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.viewer))
) -> list[Membership]:
    return container(request).services.members(ctx.org_id)


@router.patch("/orgs/{org}/members/{user_id}", response_model=Membership, responses=ERRORS)
def update_member(
    user_id: str,
    body: MembershipUpdate,
    request: Request,
    ctx: OrgContext = Depends(require_org_role(Role.owner)),
) -> Membership:
    if not is_valid_id(user_id, "user"):
        raise not_found("That user is not a member of this organization.")
    return container(request).services.set_role(ctx.org_id, user_id, body.role)


@router.delete("/orgs/{org}/members/{user_id}", status_code=204, responses=ERRORS)
def remove_member(
    user_id: str, request: Request, ctx: OrgContext = Depends(require_org_role(Role.viewer))
) -> Response:
    """Owners remove anyone; any member may remove themselves (leave)."""
    if not is_valid_id(user_id, "user"):
        raise not_found("That user is not a member of this organization.")
    if user_id != ctx.user_id and not ctx.principal.has_role(ctx.org_id, "owner"):
        raise forbidden("Only an owner can remove other members.")
    container(request).services.remove_member(ctx.org_id, user_id)
    if user_id == ctx.user_id:
        ctx.principal.roles.pop(ctx.org_id, None)
    return Response(status_code=204)


# ------------------------------------------------------------- invites


@router.post("/orgs/{org}/invites", response_model=Invite, status_code=201, responses=ERRORS)
def create_invite(
    body: InviteCreate,
    request: Request,
    ctx: OrgContext = Depends(require_org_role(Role.manager)),
) -> Invite:
    """Invite by email. The ``accept_url`` is returned once, to the inviter only."""
    return container(request).services.create_invite(
        ctx.org_id, ctx.principal, body.email, body.role
    )


@router.get("/orgs/{org}/invites", response_model=list[Invite], responses=ERRORS)
def list_invites(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.manager))
) -> list[Invite]:
    c = container(request)
    return [c.services.invite_model(i) for i in c.platform.list_invites(ctx.org_id)]


@router.post("/invites/{token}/accept", response_model=Organization, responses=ERRORS)
def accept_invite(
    token: str, request: Request, p: Principal = Depends(current_user)
) -> Organization:
    """Join the organization an invite link points to (the signed-in email must match)."""
    return container(request).services.accept_invite(token, p)


# --------------------------------------------------------- alert rules


@router.get("/orgs/{org}/alert-rules", response_model=AlertRules, responses=ERRORS)
def get_alert_rules(
    request: Request, ctx: OrgContext = Depends(require_org_role(Role.viewer))
) -> AlertRules:
    return container(request).alerts.rules(ctx.org_id)


@router.put("/orgs/{org}/alert-rules", response_model=AlertRules, responses=ERRORS)
def put_alert_rules(
    body: AlertRules,
    request: Request,
    ctx: OrgContext = Depends(require_org_role(Role.manager)),
) -> AlertRules:
    return container(request).alerts.put_rules(ctx.org_id, body)
