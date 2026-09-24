"""GET /health and GET /models."""

from __future__ import annotations

from fastapi import APIRouter, Request

from thicket.api.deps import container
from thicket.api.schemas import HealthResponse, ModelsResponse

router = APIRouter(tags=["system"])


@router.head("/health", include_in_schema=False)
@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Liveness plus model status. Always HTTP 200; ``degraded`` when BirdNET is not ready."""
    c = container(request)
    statuses = c.registry.statuses()
    return HealthResponse(
        status="ok" if statuses.get("birdnet") == "ready" else "degraded",
        version=c.settings.app_version,
        environment=c.settings.environment,
        models=statuses,
        ffmpeg=c.ffmpeg,
    )


@router.get("/models", response_model=ModelsResponse)
def models(request: Request) -> ModelsResponse:
    return ModelsResponse(models=container(request).registry.infos())
