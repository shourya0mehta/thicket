"""PATCH /events/{event_id}: human review of a detection event."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from thicket.api.deps import authorize_resource, container, current_user
from thicket.api.platform_schemas import Role
from thicket.api.routes.openapi import ERRORS
from thicket.api.schemas import Analysis, EventReviewUpdate
from thicket.errors import event_not_found
from thicket.ids import is_valid_event_id
from thicket.services.auth import Principal

router = APIRouter(tags=["review"])


@router.patch("/events/{event_id}", response_model=Analysis, responses=ERRORS)
def review_event(
    event_id: str,
    body: EventReviewUpdate,
    request: Request,
    threshold: float | None = Query(None, description="Threshold for the returned analysis."),
    p: Principal = Depends(current_user),
) -> Analysis:
    """Accept, reject or correct an event; ``unreviewed`` clears the review.

    Returns the whole analysis recomputed at ``threshold`` so metrics reflect
    the review. Rejected events are excluded from metrics; a correction to a
    known label counts for that species instead. Reviews are keyed by event
    id, which is stable across thresholds while the event's extent is
    unchanged. Needs the reviewer role in the recording's organization.
    """
    c = container(request)
    if not is_valid_event_id(event_id):
        raise event_not_found()
    analysis_id = c.repo.event_analysis_id(event_id)
    if analysis_id is None:
        raise event_not_found()
    org_id = c.platform.org_of_analysis(analysis_id)
    if org_id is None or p.role_in(org_id) is None:
        raise event_not_found()
    authorize_resource(p, org_id, Role.reviewer)
    return c.analysis.review(event_id, body, threshold, reviewed_by=p.user_id)
