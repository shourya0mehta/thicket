"""Sign-in, sessions and the signed-in user's own resources.

``/auth/*`` per docs/PLATFORM_API.md plus ``/me/notifications`` and
``/me/notification-prefs``. The session cookie is HttpOnly, SameSite=Lax,
Secure when ``PUBLIC_BASE_URL`` is https, 30 days and renewed on use.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict

from thicket.api.deps import container, current_user
from thicket.api.platform_schemas import (
    AuthConfig,
    DevLogin,
    Me,
    NotificationPage,
    NotificationPrefs,
)
from thicket.api.routes.openapi import ERRORS
from thicket.errors import invalid_parameter
from thicket.services.auth import (
    OAUTH_COOKIE,
    OAUTH_MAX_AGE,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    Principal,
)

router = APIRouter(tags=["auth"])


class MarkRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] | None = None
    all: bool = False


def _set_session(response: Response, request: Request, user_id: str) -> None:
    c = container(request)
    token, _ = c.auth.issue_session(user_id)
    response.set_cookie(SESSION_COOKIE, token, **c.auth.cookie_params(SESSION_MAX_AGE))


def _me(request: Request, p: Principal) -> Me:
    c = container(request)
    return c.services.me(p, c.settings.auth_mode, c.platform.unread_count(p.user_id))


@router.get("/auth/config", response_model=AuthConfig)
def auth_config(request: Request) -> AuthConfig:
    """Which sign-in mode this server runs and where the sign-in button goes."""
    return container(request).auth.config()


@router.get("/auth/google/start", responses=ERRORS)
def google_start(request: Request, next: str | None = Query(None)) -> RedirectResponse:  # noqa: A002
    """Redirect to Google (authorization code flow with PKCE); state in a short-lived cookie."""
    c = container(request)
    url, cookie = c.auth.start_google(next)
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(OAUTH_COOKIE, cookie, **c.auth.cookie_params(OAUTH_MAX_AGE))
    return resp


@router.get("/auth/google/callback", responses=ERRORS)
def google_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
) -> RedirectResponse:
    """Finish the Google sign-in: verify state and the ID token, set the session, go to the app."""
    c = container(request)
    user, next_path = c.auth.finish_google(
        code=code, state=state, error=error, oauth_cookie=request.cookies.get(OAUTH_COOKIE)
    )
    resp = RedirectResponse(c.auth.post_login_redirect(next_path), status_code=302)
    resp.delete_cookie(OAUTH_COOKIE, path="/")
    _set_session(resp, request, user.id)
    return resp


@router.post("/auth/dev", response_model=Me, responses=ERRORS)
def dev_login(body: DevLogin, request: Request) -> JSONResponse:
    """Email-only sign-in for development (``AUTH_MODE=dev``)."""
    c = container(request)
    user = c.auth.dev_login(body.email, body.name)
    roles = c.platform.roles_for_user(user.id)
    p = Principal(user=user, roles=roles)
    me = _me(request, p)
    resp = JSONResponse(me.model_dump(mode="json"))
    _set_session(resp, request, user.id)
    return resp


@router.post("/auth/logout", status_code=204, responses=ERRORS)
def logout(request: Request, p: Principal = Depends(current_user)) -> Response:
    c = container(request)
    if p.session is not None:
        c.auth.revoke(p.session)
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/auth/me", response_model=Me, responses=ERRORS)
def me(request: Request, p: Principal = Depends(current_user)) -> Me:
    return _me(request, p)


@router.get("/me/notifications", response_model=NotificationPage, responses=ERRORS)
def my_notifications(
    request: Request,
    unread_only: bool = Query(False),
    p: Principal = Depends(current_user),
) -> NotificationPage:
    return container(request).notify.page(p.user_id, unread_only)


@router.post("/me/notifications/read", status_code=204, responses=ERRORS)
def mark_notifications_read(
    body: MarkRead, request: Request, p: Principal = Depends(current_user)
) -> Response:
    if not body.all and not body.ids:
        raise invalid_parameter("Send ids or all=true.", field="ids")
    container(request).platform.mark_read(p.user_id, body.ids, body.all)
    return Response(status_code=204)


@router.get("/me/notification-prefs", response_model=NotificationPrefs, responses=ERRORS)
def get_prefs(request: Request, p: Principal = Depends(current_user)) -> NotificationPrefs:
    return container(request).notify.prefs(p.user_id)


@router.put("/me/notification-prefs", response_model=NotificationPrefs, responses=ERRORS)
def put_prefs(
    body: NotificationPrefs, request: Request, p: Principal = Depends(current_user)
) -> NotificationPrefs:
    return container(request).notify.put_prefs(p.user_id, body)
