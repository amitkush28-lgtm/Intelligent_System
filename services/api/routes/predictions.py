"""
Prediction CRUD routes.
GET/POST /predictions — list and create
GET /predictions/{id} — full detail with trail, notes, debates, sub-predictions
GET /predictions/{id}/trail — confidence history
POST /predictions/{id}/notes — add analyst note
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from shared.database import get_db
from shared.models import Prediction, ConfidenceTrail, Note
from shared.schemas import (
    PredictionCreate,
    PredictionResponse,
    PredictionDetail,
    ConfidenceTrailCreate,
    ConfidenceTrailResponse,
    NoteCreate,
    NoteResponse,
    PaginatedResponse,
)
from shared.utils import generate_prediction_id
from services.api.auth import verify_api_key

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("", response_model=PaginatedResponse)
async def list_predictions(
    status_filter: Optional[str] = Query(None, alias="status"),
    agent: Optional[str] = None,
    domain: Optional[str] = None,
    parent_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """List predictions with optional filters and pagination."""
    query = db.query(Prediction)

    if status_filter:
        query = query.filter(Prediction.status == status_filter)
    if agent:
        query = query.filter(Prediction.agent == agent)
    if domain:
        # Domain filtering via agent name mapping or claim content
        query = query.filter(Prediction.agent == domain)
    if parent_id:
        query = query.filter(Prediction.parent_id == parent_id)

    total = query.count()
    items = (
        query.order_by(Prediction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedResponse(
        items=[PredictionResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=PredictionResponse, status_code=status.HTTP_201_CREATED)
async def create_prediction(
    body: PredictionCreate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Create a new prediction and its initial confidence trail entry."""
    pred_id = generate_prediction_id(body.agent.value, body.claim)

    prediction = Prediction(
        id=pred_id,
        agent=body.agent.value,
        claim=body.claim,
        time_condition_type=body.time_condition_type.value,
        time_condition_date=body.time_condition_date,
        time_condition_start=body.time_condition_start,
        time_condition_end=body.time_condition_end,
        resolution_criteria=body.resolution_criteria,
        current_confidence=body.current_confidence,
        parent_id=body.parent_id,
        status="ACTIVE",
    )
    db.add(prediction)

    # Create initial confidence trail entry
    trail = ConfidenceTrail(
        prediction_id=pred_id,
        value=body.current_confidence,
        trigger="initial_prediction",
        reasoning="Initial confidence at prediction creation",
    )
    db.add(trail)

    db.commit()
    db.refresh(prediction)
    return PredictionResponse.model_validate(prediction)


@router.get("/{prediction_id}", response_model=PredictionDetail)
async def get_prediction(
    prediction_id: str,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Get full prediction detail with confidence trail, notes, debates, sub-predictions."""
    prediction = (
        db.query(Prediction)
        .options(
            joinedload(Prediction.confidence_trail),
            joinedload(Prediction.notes),
            joinedload(Prediction.debates),
            joinedload(Prediction.sub_predictions),
        )
        .filter(Prediction.id == prediction_id)
        .first()
    )
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return PredictionDetail(
        **PredictionResponse.model_validate(prediction).model_dump(),
        confidence_trail=[
            ConfidenceTrailResponse.model_validate(t)
            for t in sorted(prediction.confidence_trail, key=lambda t: t.date or t.created_at)
        ],
        notes=[NoteResponse.model_validate(n) for n in prediction.notes],
        debates=[
            {
                "id": d.id,
                "prediction_id": d.prediction_id,
                "agent": d.agent,
                "trigger_reason": d.trigger_reason,
                "rounds": d.rounds,
                "devil_impact": d.devil_impact,
                "created_at": d.created_at,
            }
            for d in prediction.debates
        ],
        sub_predictions=[
            PredictionResponse.model_validate(s) for s in prediction.sub_predictions
        ],
    )


@router.get("/{prediction_id}/trail", response_model=list[ConfidenceTrailResponse])
async def get_confidence_trail(
    prediction_id: str,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Get confidence trail for a prediction, ordered chronologically."""
    prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")

    trail = (
        db.query(ConfidenceTrail)
        .filter(ConfidenceTrail.prediction_id == prediction_id)
        .order_by(ConfidenceTrail.date.asc())
        .all()
    )
    return [ConfidenceTrailResponse.model_validate(t) for t in trail]


@router.post(
    "/{prediction_id}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_note(
    prediction_id: str,
    body: NoteCreate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Add an analyst note to a prediction."""
    prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")

    note = Note(
        prediction_id=prediction_id,
        type=body.type,
        text=body.text,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return NoteResponse.model_validate(note)
