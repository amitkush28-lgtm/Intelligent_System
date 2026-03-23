"""
Decision routes.
GET /decisions — decision-relevance recommendations
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from shared.database import get_db
from shared.models import DecisionMapping, Prediction
from shared.schemas import DecisionResponse, PredictionResponse, PaginatedResponse
from services.api.auth import verify_api_key

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("", response_model=PaginatedResponse)
async def list_decisions(
    urgency: Optional[str] = None,
    domain: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """List decision-relevance recommendations, ordered by urgency."""
    query = db.query(DecisionMapping).options(joinedload(DecisionMapping.prediction))

    if urgency:
        query = query.filter(DecisionMapping.urgency == urgency)
    if domain:
        query = query.filter(DecisionMapping.domain == domain)

    total = query.count()

    # Custom ordering: PREP_NOW > HIGH > MEDIUM > LOW
    urgency_order = {"PREP_NOW": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    items = (
        query.offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items.sort(key=lambda d: urgency_order.get(d.urgency, 4))

    results = []
    for dm in items:
        resp = DecisionResponse(
            id=dm.id,
            prediction_id=dm.prediction_id,
            action=dm.action,
            trigger_condition=dm.trigger_condition,
            urgency=dm.urgency,
            domain=dm.domain,
            inert_threshold=dm.inert_threshold,
            prediction=PredictionResponse.model_validate(dm.prediction) if dm.prediction else None,
        )
        results.append(resp)

    return PaginatedResponse(
        items=results,
        total=total,
        page=page,
        page_size=page_size,
    )
