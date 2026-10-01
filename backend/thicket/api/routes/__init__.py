"""All ``/api/v1`` routes."""

from __future__ import annotations

from fastapi import APIRouter

from thicket.api.routes import (
    analyses,
    auth,
    events,
    insights,
    orgs,
    previews,
    reports,
    sites,
    system,
    uploads,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(previews.router)
api_router.include_router(analyses.router)
api_router.include_router(events.router)
api_router.include_router(orgs.router)
api_router.include_router(sites.router)
api_router.include_router(uploads.router)
api_router.include_router(insights.router)
api_router.include_router(reports.router)
