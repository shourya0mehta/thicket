"""All ``/api/v1`` routes."""

from __future__ import annotations

from fastapi import APIRouter

from thicket.api.routes import analyses, events, previews, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(previews.router)
api_router.include_router(analyses.router)
api_router.include_router(events.router)
