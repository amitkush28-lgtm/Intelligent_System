"""
Events routes.
GET /events — recent ingested events
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.models import Event
from shared.schemas import EventResponse, PaginatedResponse
from services.api.auth import verify_api_key

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=PaginatedResponse)
async def list_events(
    domain: Optional[str] = None,
    severity: Optional[str] = None,
    source: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """List recent ingested events with optional filtering."""
    query = db.query(Event)

    if domain:
        query = query.filter(Event.domain == domain)
    if severity:
        query = query.filter(Event.severity == severity)
    if source:
        query = query.filter(Event.source.ilike(f"%{source}%"))

    total = query.count()
    items = (
        query.order_by(Event.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedResponse(
        items=[EventResponse.model_validate(e) for e in items],
        total=total,
        page=page,
        page_size=page_size,
    )
