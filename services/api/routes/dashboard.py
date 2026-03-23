"""
Dashboard routes.
GET /dashboard/metrics — system-wide stats
GET /dashboard/calibration — calibration curve data
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.models import (
    Prediction,
    CalibrationScore,
    ConfidenceTrail,
    Note,
    Debate,
)
from shared.schemas import (
    DashboardMetrics,
    CalibrationBucket,
    CalibrationCurveResponse,
    AgentName,
)
from services.api.auth import verify_api_key
from services.api.routes.agents import _compute_agent_metrics, AGENT_NAMES

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics", response_model=DashboardMetrics)
async def get_dashboard_metrics(
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """System-wide dashboard metrics."""
    total = db.query(func.count(Prediction.id)).scalar() or 0
    active = (
        db.query(func.count(Prediction.id))
        .filter(Prediction.status == "ACTIVE")
        .scalar() or 0
    )

    # System Brier score
    system_brier = (
        db.query(func.avg(Prediction.brier_score))
        .filter(Prediction.brier_score.is_not(None))
        .scalar()
    )
    system_brier = round(system_brier, 4) if system_brier is not None else None

    # Overall accuracy
    resolved = (
        db.query(func.count(Prediction.id))
        .filter(Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]))
        .scalar() or 0
    )
    correct = (
        db.query(func.count(Prediction.id))
        .filter(
            Prediction.status == "RESOLVED_TRUE",
            Prediction.resolved_outcome == True,
        )
        .scalar() or 0
    ) + (
        db.query(func.count(Prediction.id))
        .filter(
            Prediction.status == "RESOLVED_FALSE",
            Prediction.resolved_outcome == False,
        )
        .scalar() or 0
    )
    overall_accuracy = round(correct / resolved, 4) if resolved > 0 else None

    # Calibration error
    cal_rows = (
        db.query(CalibrationScore)
        .order_by(CalibrationScore.calculated_at.desc())
        .limit(50)
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

    # Agent metrics
    agents = [_compute_agent_metrics(db, name) for name in AGENT_NAMES]

    # Recent activity: last 20 confidence trail entries, notes, debates
    recent_trail = (
        db.query(ConfidenceTrail)
        .order_by(ConfidenceTrail.created_at.desc())
        .limit(10)
        .all()
    )
    recent_notes = (
        db.query(Note)
        .order_by(Note.date.desc())
        .limit(5)
        .all()
    )
    recent_debates = (
        db.query(Debate)
        .order_by(Debate.created_at.desc())
        .limit(5)
        .all()
    )

    recent_activity = []
    for t in recent_trail:
        recent_activity.append({
            "type": "confidence_update",
            "prediction_id": t.prediction_id,
            "value": t.value,
            "trigger": t.trigger,
            "timestamp": t.created_at.isoformat() if t.created_at else None,
        })
    for n in recent_notes:
        recent_activity.append({
            "type": "note",
            "prediction_id": n.prediction_id,
            "note_type": n.type,
            "text": n.text[:100],
            "timestamp": n.date.isoformat() if n.date else None,
        })
    for d in recent_debates:
        recent_activity.append({
            "type": "debate",
            "prediction_id": d.prediction_id,
            "agent": d.agent,
            "trigger_reason": d.trigger_reason,
            "timestamp": d.created_at.isoformat() if d.created_at else None,
        })

    # Sort by timestamp descending
    recent_activity.sort(
        key=lambda x: x.get("timestamp") or "", reverse=True
    )

    return DashboardMetrics(
        system_brier_score=system_brier,
        overall_accuracy=overall_accuracy,
        active_predictions=active,
        total_predictions=total,
        calibration_error=calibration_error,
        agents=agents,
        recent_activity=recent_activity[:20],
    )


@router.get("/calibration", response_model=CalibrationCurveResponse)
async def get_calibration_curve(
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Calibration curve data: overall and per-agent."""
    # Get the most recent calibration scores
    cal_rows = (
        db.query(CalibrationScore)
        .order_by(CalibrationScore.calculated_at.desc())
        .all()
    )

    # Build overall buckets (agent-agnostic, take latest per bucket)
    seen_buckets = set()
    overall = []
    for row in cal_rows:
        if row.confidence_bucket and row.confidence_bucket not in seen_buckets:
            if row.predicted_avg is not None and row.actual_avg is not None:
                overall.append(
                    CalibrationBucket(
                        bucket=row.confidence_bucket,
                        predicted_avg=row.predicted_avg,
                        actual_avg=row.actual_avg,
                        count=row.count or 0,
                    )
                )
                seen_buckets.add(row.confidence_bucket)

    # Build per-agent calibration
    by_agent: dict[str, list[CalibrationBucket]] = {}
    seen_agent_buckets: dict[str, set] = {}
    for row in cal_rows:
        if not row.agent or not row.confidence_bucket:
            continue
        if row.agent not in seen_agent_buckets:
            seen_agent_buckets[row.agent] = set()
            by_agent[row.agent] = []
        if row.confidence_bucket not in seen_agent_buckets[row.agent]:
            if row.predicted_avg is not None and row.actual_avg is not None:
                by_agent[row.agent].append(
                    CalibrationBucket(
                        bucket=row.confidence_bucket,
                        predicted_avg=row.predicted_avg,
                        actual_avg=row.actual_avg,
                        count=row.count or 0,
                    )
                )
                seen_agent_buckets[row.agent].add(row.confidence_bucket)

    return CalibrationCurveResponse(
        overall=overall,
        by_agent={
            k: [b.model_dump() for b in v] for k, v in by_agent.items()
        },
    )
