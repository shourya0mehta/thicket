"""Request-scoped access to the service container, the signed-in principal
and organization roles.

* :func:`principal` resolves who is calling: the session cookie, or the
  implicit local owner when ``AUTH_MODE=disabled``. Cached on
  ``request.state`` for the rest of the request.
* :func:`current_user` is the FastAPI dependency for "signed in".
* :func:`require_org_role` builds a dependency for ``/orgs/{org}/...`` routes
  that checks membership and the minimum role (owner > manager > reviewer >
  viewer). A non-member gets 403 ``forbidden``.
* :func:`authorize_resource` is for routes addressed by a resource id
  (``/sites/{site_id}``): a resource in an organization the caller does not
  belong to is reported as 404 ``not_found`` so ids do not leak existence;
  a member with too low a role gets 403.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Path, Request

from thicket.api.platform_schemas import Role
from thicket.container import Container
from thicket.errors import forbidden, invalid_parameter, not_found, unauthenticated
from thicket.ids import is_valid_id
from thicket.services.auth import SESSION_COOKIE, Principal
from thicket.services.intake import file_too_large

MULTIPART_OVERHEAD_BYTES = 1024 * 1024

ROLE_LABEL = {
    "owner": "an owner",
    "manager": "a manager or owner",
    "reviewer": "a reviewer, manager or owner",
    "viewer": "a member",
}


def container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def check_content_length(request: Request, max_bytes: int) -> None:
    """Reject obviously oversized uploads before reading the body."""
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        size = int(raw)
    except ValueError as exc:
        raise invalid_parameter("Invalid Content-Length header.") from exc
    if size > max_bytes + MULTIPART_OVERHEAD_BYTES:
        raise file_too_large(max_bytes)


# ------------------------------------------------------------- principals


def principal(request: Request) -> Principal | None:
    cached = getattr(request.state, "principal", None)
    if cached is not None or getattr(request.state, "principal_resolved", False):
        return cached
    c = container(request)
    p = c.auth.principal_from_cookie(request.cookies.get(SESSION_COOKIE))
    request.state.principal = p
    request.state.principal_resolved = True
    if p is not None and p.session is not None and p.session.refresh:
        request.state.refresh_session = True
    return p


def current_user(request: Request) -> Principal:
    p = principal(request)
    if p is None:
        raise unauthenticated()
    return p


@dataclass
class OrgContext:
    org_id: str
    role: str
    principal: Principal

    @property
    def user_id(self) -> str:
        return self.principal.user_id


def _check_role(p: Principal, org_id: str, minimum: str) -> str:
    role = p.role_in(org_id)
    if role is None:
        raise forbidden("You are not a member of this organization.")
    if not p.has_role(org_id, minimum):
        raise forbidden(
            f"This action needs {ROLE_LABEL.get(minimum, minimum)} of the organization."
        )
    return role


def require_org_role(minimum: Role | str) -> Callable[..., OrgContext]:
    minimum_str = str(minimum.value if isinstance(minimum, Role) else minimum)

    def _dep(
        request: Request,
        org: str = Path(..., description="Organization id"),
        p: Principal = Depends(current_user),
    ) -> OrgContext:
        if not is_valid_id(org, "org"):
            raise not_found("No organization with that id exists.")
        role = _check_role(p, org, minimum_str)
        c = container(request)
        if c.platform.get_org(org) is None:
            raise not_found("No organization with that id exists.")
        return OrgContext(org_id=org, role=role, principal=p)

    return _dep


def authorize_resource(p: Principal, org_id: str | None, minimum: Role | str) -> OrgContext:
    """Role check for a resource that belongs to ``org_id`` (None: not found)."""
    minimum_str = str(minimum.value if isinstance(minimum, Role) else minimum)
    if org_id is None or p.role_in(org_id) is None:
        raise not_found()
    if not p.has_role(org_id, minimum_str):
        raise forbidden(f"This action needs {ROLE_LABEL.get(minimum_str, minimum_str)}.")
    return OrgContext(org_id=org_id, role=p.role_in(org_id) or "", principal=p)


def visible_org_ids(p: Principal) -> list[str]:
    return list(p.roles)
