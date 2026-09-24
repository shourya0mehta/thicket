"""PATCH /events/{event_id}: human review of a detection event."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from thicket.api.deps import container
from thicket.api.routes.openapi import ERRORS
from thicket.api.schemas import Analysis, EventReviewUpdate

router = APIRouter(tags=["review"])


@router.patch("/events/{event_id}", response_model=Analysis, responses=ERRORS)
def review_event(
    event_id: str,
    body: EventReviewUpdate,
    request: Request,
    threshold: float | None = Query(None, description="Threshold for the returned analysis."),
) -> Analysis:
    """Accept, reject or correct an event; ``unreviewed`` clears the review.

    Returns the whole analysis recomputed at ``threshold`` so metrics reflect
    the review. Rejected events are excluded from metrics; a correction to a
    known label counts for that species instead. Reviews are keyed by event
    id, which is stable across thresholds while the event's extent is
    unchanged.
    """
    return container(request).analysis.review(event_id, body, threshold)
