"""
Weak signal routes.
GET /signals/weak — weak signal feed
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.models import WeakSignal
from shared.schemas import WeakSignalResponse, PaginatedResponse
from services.api.auth import verify_api_key

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/weak", response_model=PaginatedResponse)
async def list_weak_signals(
    strength: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """List weak signals with optional filtering."""
    query = db.query(WeakSignal)

    if strength:
        query = query.filter(WeakSignal.strength == strength)
    if status_filter:
        query = query.filter(WeakSignal.status == status_filter)

    total = query.count()
    items = (
        query.order_by(WeakSignal.detected_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedResponse(
        items=[WeakSignalResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )
