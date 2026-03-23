"""
Agent routes.
GET /agents — list agents with current metrics
GET /agents/{id}/metrics — Brier score, calibration, accuracy for a specific agent
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.models import Prediction, CalibrationScore, Debate
from shared.schemas import AgentMetrics, AgentListResponse, AgentName
from services.api.auth import verify_api_key

router = APIRouter(prefix="/agents", tags=["agents"])

AGENT_NAMES = [a.value for a in AgentName]


def _compute_agent_metrics(db: Session, agent_name: str) -> AgentMetrics:
    """Compute metrics for a single agent from the database."""
    total = db.query(func.count(Prediction.id)).filter(Prediction.agent == agent_name).scalar() or 0
    active = (
        db.query(func.count(Prediction.id))
        .filter(Prediction.agent == agent_name, Prediction.status == "ACTIVE")
        .scalar() or 0
    )
    resolved = (
        db.query(func.count(Prediction.id))
        .filter(
            Prediction.agent == agent_name,
            Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]),
        )
        .scalar() or 0
    )

    # Accuracy: % of resolved predictions where outcome matched high confidence
    accuracy = None
    if resolved > 0:
        correct = (
            db.query(func.count(Prediction.id))
            .filter(
                Prediction.agent == agent_name,
                Prediction.resolved_outcome.is_not(None),
                case(
                    (Prediction.current_confidence >= 0.5, Prediction.resolved_outcome == True),
                    (Prediction.current_confidence < 0.5, Prediction.resolved_outcome == False),
                    else_=False,
                ),
            )
            .scalar() or 0
        )
        accuracy = round(correct / resolved, 4) if resolved > 0 else None

    # Average Brier score
    brier_avg = (
        db.query(func.avg(Prediction.brier_score))
        .filter(
            Prediction.agent == agent_name,
            Prediction.brier_score.is_not(None),
        )
        .scalar()
    )
    brier_avg = round(brier_avg, 4) if brier_avg is not None else None

    # Calibration error from calibration_scores table
    cal_rows = (
        db.query(CalibrationScore)
        .filter(CalibrationScore.agent == agent_name)
        .order_by(CalibrationScore.calculated_at.desc())
        .limit(10)
        .all()
    )
    calibration_error = None
    if cal_rows:
        errors = [
            abs(r.predicted_avg - r.actual_avg)
            for r in cal_rows
            if r.predicted_avg is not None and r.actual_avg is not None
        ]
        if errors:
            calibration_error = round(sum(errors) / len(errors), 4)

    # Known biases
    known_biases = []
    for row in cal_rows:
        if row.bias_direction and row.bias_direction != "calibrated":
            bias_desc = f"{row.bias_direction} in {row.confidence_bucket or 'overall'}"
            if row.domain:
                bias_desc += f" ({row.domain})"
            if bias_desc not in known_biases:
                known_biases.append(bias_desc)

    # Devil's advocate average impact
    devil_impact_avg = (
        db.query(func.avg(Debate.devil_impact))
        .filter(Debate.agent == agent_name, Debate.devil_impact.is_not(None))
        .scalar()
    )
    devil_impact_avg = round(devil_impact_avg, 4) if devil_impact_avg is not None else None

    return AgentMetrics(
        agent=agent_name,
        total_predictions=total,
        active_predictions=active,
        resolved_predictions=resolved,
        accuracy=accuracy,
        brier_avg=brier_avg,
        calibration_error=calibration_error,
        known_biases=known_biases,
        devil_impact_avg=devil_impact_avg,
    )


@router.get("", response_model=AgentListResponse)
async def list_agents(
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """List all agents with their current performance metrics."""
    agents = [_compute_agent_metrics(db, name) for name in AGENT_NAMES]
    return AgentListResponse(agents=agents)


@router.get("/{agent_id}/metrics", response_model=AgentMetrics)
async def get_agent_metrics(
    agent_id: str,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Get detailed metrics for a specific agent."""
    if agent_id not in AGENT_NAMES:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return _compute_agent_metrics(db, agent_id)
