"""
Debates routes.
GET /debates — list debates with optional filters
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.models import Debate
from shared.schemas import DebateResponse, PaginatedResponse
from services.api.auth import verify_api_key

router = APIRouter(prefix="/debates", tags=["debates"])


@router.get("", response_model=PaginatedResponse)
async def list_debates(
    agent: Optional[str] = None,
    prediction_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """List debates with optional filtering by agent or prediction."""
    query = db.query(Debate)

    if agent:
        query = query.filter(Debate.agent == agent)
    if prediction_id:
        query = query.filter(Debate.prediction_id == prediction_id)

    total = query.count()
    items = (
        query.order_by(Debate.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedResponse(
        items=[DebateResponse.model_validate(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )
