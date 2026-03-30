"""
Dashboard routes.
GET /dashboard/metrics — system-wide stats
GET /dashboard/calibration — calibration curve data
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from shared.database import get_db
from shared.models import (
    Prediction,
    CalibrationScore,
    ConfidenceTrail,
    Note,
    Debate,
    Event,
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


# All 23 expected data sources
EXPECTED_SOURCES = [
    "gdelt", "fred", "rss", "newsdata", "twelve_data", "congress_gov",
    "acled", "polymarket", "cftc", "sec_edgar", "bls", "world_bank",
    "ofac", "thenewsapi", "google_trends", "arxiv", "metaculus",
    "manifold", "central_banks", "crunchbase", "flightaware",
    "marine_traffic", "uspto_patents",
]


@router.get("/source-health")
async def get_source_health(
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Per-source health audit: event counts, latest event date, staleness."""
    from sqlalchemy import case, cast, Date

    # Get count and latest timestamp per source
    source_stats = (
        db.query(
            Event.source,
            func.count(Event.id).label("event_count"),
            func.max(Event.timestamp).label("latest_event"),
            func.min(Event.timestamp).label("earliest_event"),
        )
        .group_by(Event.source)
        .all()
    )

    now = datetime.utcnow()
    source_map = {}
    for row in source_stats:
        hours_since = (now - row.latest_event).total_seconds() / 3600 if row.latest_event else None
        source_map[row.source] = {
            "source": row.source,
            "event_count": row.event_count,
            "latest_event": row.latest_event.isoformat() if row.latest_event else None,
            "earliest_event": row.earliest_event.isoformat() if row.earliest_event else None,
            "hours_since_last": round(hours_since, 1) if hours_since else None,
            "status": "healthy" if hours_since and hours_since < 48 else
                      "stale" if hours_since and hours_since < 168 else
                      "dead" if hours_since else "no_data",
        }

    # Build full report including missing sources
    results = []
    for src in EXPECTED_SOURCES:
        if src in source_map:
            results.append(source_map[src])
        else:
            results.append({
                "source": src,
                "event_count": 0,
                "latest_event": None,
                "earliest_event": None,
                "hours_since_last": None,
                "status": "no_data",
            })

    # Add any unexpected sources
    for src, data in source_map.items():
        if src not in EXPECTED_SOURCES:
            data["status"] = data["status"] + " (unexpected)"
            results.append(data)

    # Sort: no_data/dead first, then by hours since last
    status_order = {"no_data": 0, "dead": 1, "stale": 2, "healthy": 3}
    results.sort(key=lambda x: (status_order.get(x["status"], 0), -(x["hours_since_last"] or 99999)))

    total = sum(r["event_count"] for r in results)
    healthy = sum(1 for r in results if r["status"] == "healthy")
    stale = sum(1 for r in results if r["status"] == "stale")
    dead = sum(1 for r in results if r["status"] == "dead")
    no_data = sum(1 for r in results if r["status"] == "no_data")

    return {
        "summary": {
            "total_events": total,
            "sources_expected": len(EXPECTED_SOURCES),
            "sources_healthy": healthy,
            "sources_stale": stale,
            "sources_dead": dead,
            "sources_no_data": no_data,
        },
        "sources": results,
    }


@router.get("/accuracy-history")
async def get_accuracy_history(
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
    days: int = 90,
):
    """Historical accuracy tracking with timeline, agent breakdown, and domain breakdown."""
    # Query all resolved predictions within the time window
    cutoff_date = datetime.utcnow().date() - timedelta(days=days)
    resolved_preds = (
        db.query(Prediction)
        .filter(
            Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]),
            Prediction.resolved_date.isnot(None),
            Prediction.resolved_date >= cutoff_date,
        )
        .order_by(Prediction.resolved_date)
        .all()
    )

    # Build timeline: group by resolved_date, calculate cumulative metrics
    timeline_dict: dict = {}
    for pred in resolved_preds:
        if pred.resolved_date not in timeline_dict:
            timeline_dict[pred.resolved_date] = {
                "date": pred.resolved_date.isoformat(),
                "resolved_count": 0,
                "correct_count": 0,
                "brier_scores": [],
            }

        timeline_dict[pred.resolved_date]["resolved_count"] += 1

        # Count as correct if status and outcome match
        if (
            (pred.status == "RESOLVED_TRUE" and pred.resolved_outcome == True)
            or (pred.status == "RESOLVED_FALSE" and pred.resolved_outcome == False)
        ):
            timeline_dict[pred.resolved_date]["correct_count"] += 1

        if pred.brier_score is not None:
            timeline_dict[pred.resolved_date]["brier_scores"].append(pred.brier_score)

    # Build cumulative timeline with rolling 7-day windows
    timeline_list = []
    cumulative_resolved = 0
    cumulative_correct = 0
    cumulative_brier_sum = 0.0
    cumulative_brier_count = 0

    for date_str in sorted(timeline_dict.keys()):
        day_data = timeline_dict[date_str]
        cumulative_resolved += day_data["resolved_count"]
        cumulative_correct += day_data["correct_count"]
        cumulative_brier_sum += sum(day_data["brier_scores"])
        cumulative_brier_count += len(day_data["brier_scores"])

        cumulative_accuracy = (
            round(cumulative_correct / cumulative_resolved, 4)
            if cumulative_resolved > 0
            else None
        )
        cumulative_brier = (
            round(cumulative_brier_sum / cumulative_brier_count, 4)
            if cumulative_brier_count > 0
            else None
        )

        # Compute 7-day rolling window
        window_start = datetime.fromisoformat(date_str).date() - timedelta(days=6)
        window_preds = [
            p
            for p in resolved_preds
            if p.resolved_date is not None and window_start <= p.resolved_date <= datetime.fromisoformat(date_str).date()
        ]
        rolling_correct = sum(
            1
            for p in window_preds
            if (p.status == "RESOLVED_TRUE" and p.resolved_outcome == True)
            or (p.status == "RESOLVED_FALSE" and p.resolved_outcome == False)
        )
        rolling_brier_scores = [p.brier_score for p in window_preds if p.brier_score is not None]
        rolling_accuracy = (
            round(rolling_correct / len(window_preds), 4) if window_preds else None
        )
        rolling_brier = (
            round(sum(rolling_brier_scores) / len(rolling_brier_scores), 4)
            if rolling_brier_scores
            else None
        )

        timeline_list.append({
            "date": date_str,
            "cumulative_accuracy": cumulative_accuracy,
            "cumulative_brier": cumulative_brier,
            "resolved_count": cumulative_resolved,
            "correct_count": cumulative_correct,
            "rolling_7d_accuracy": rolling_accuracy,
            "rolling_7d_brier": rolling_brier,
        })

    # Build by_agent breakdown
    by_agent: dict = {}
    for pred in resolved_preds:
        agent = pred.agent or "unknown"
        if agent not in by_agent:
            by_agent[agent] = []

        # Find or create the entry for this date
        date_str = pred.resolved_date.isoformat() if pred.resolved_date else None
        if not date_str:
            continue

        entry = None
        for e in by_agent[agent]:
            if e["date"] == date_str:
                entry = e
                break

        if not entry:
            entry = {
                "date": date_str,
                "resolved_count": 0,
                "correct_count": 0,
                "brier_scores": [],
            }
            by_agent[agent].append(entry)

        entry["resolved_count"] += 1
        if (
            (pred.status == "RESOLVED_TRUE" and pred.resolved_outcome == True)
            or (pred.status == "RESOLVED_FALSE" and pred.resolved_outcome == False)
        ):
            entry["correct_count"] += 1
        if pred.brier_score is not None:
            entry["brier_scores"].append(pred.brier_score)

    # Convert by_agent to cumulative format
    by_agent_final: dict = {}
    for agent, entries in by_agent.items():
        sorted_entries = sorted(entries, key=lambda e: e["date"])
        cumulative_resolved = 0
        cumulative_correct = 0
        cumulative_brier_sum = 0.0
        cumulative_brier_count = 0
        final_entries = []

        for entry in sorted_entries:
            cumulative_resolved += entry["resolved_count"]
            cumulative_correct += entry["correct_count"]
            cumulative_brier_sum += sum(entry["brier_scores"])
            cumulative_brier_count += len(entry["brier_scores"])

            final_entries.append({
                "date": entry["date"],
                "cumulative_accuracy": (
                    round(cumulative_correct / cumulative_resolved, 4)
                    if cumulative_resolved > 0
                    else None
                ),
                "cumulative_brier": (
                    round(cumulative_brier_sum / cumulative_brier_count, 4)
                    if cumulative_brier_count > 0
                    else None
                ),
                "resolved_count": cumulative_resolved,
                "correct_count": cumulative_correct,
                "rolling_7d_accuracy": None,
                "rolling_7d_brier": None,
            })

        by_agent_final[agent] = final_entries

    # Build by_domain breakdown
    by_domain: dict = {}
    for pred in resolved_preds:
        # Extract domain from prediction (simplified: use first agent part as domain indicator)
        domain = "general"
        if pred.agent:
            agent_parts = pred.agent.split("_")
            if agent_parts[0] in ["geopolitical", "economic", "market", "political", "sentiment"]:
                domain = agent_parts[0]

        if domain not in by_domain:
            by_domain[domain] = []

        date_str = pred.resolved_date.isoformat() if pred.resolved_date else None
        if not date_str:
            continue

        entry = None
        for e in by_domain[domain]:
            if e["date"] == date_str:
                entry = e
                break

        if not entry:
            entry = {
                "date": date_str,
                "resolved_count": 0,
                "correct_count": 0,
            }
            by_domain[domain].append(entry)

        entry["resolved_count"] += 1
        if (
            (pred.status == "RESOLVED_TRUE" and pred.resolved_outcome == True)
            or (pred.status == "RESOLVED_FALSE" and pred.resolved_outcome == False)
        ):
            entry["correct_count"] += 1

    # Convert by_domain to cumulative format
    by_domain_final: dict = {}
    for domain, entries in by_domain.items():
        sorted_entries = sorted(entries, key=lambda e: e["date"])
        cumulative_resolved = 0
        cumulative_correct = 0
        final_entries = []

        for entry in sorted_entries:
            cumulative_resolved += entry["resolved_count"]
            cumulative_correct += entry["correct_count"]

            final_entries.append({
                "date": entry["date"],
                "cumulative_accuracy": (
                    round(cumulative_correct / cumulative_resolved, 4)
                    if cumulative_resolved > 0
                    else None
                ),
                "cumulative_brier": None,
                "resolved_count": cumulative_resolved,
                "correct_count": cumulative_correct,
                "rolling_7d_accuracy": None,
                "rolling_7d_brier": None,
            })

        by_domain_final[domain] = final_entries

    # Compute summary stats
    total_resolved = len(resolved_preds)
    total_correct = sum(
        1
        for p in resolved_preds
        if (p.status == "RESOLVED_TRUE" and p.resolved_outcome == True)
        or (p.status == "RESOLVED_FALSE" and p.resolved_outcome == False)
    )
    overall_accuracy = (
        round(total_correct / total_resolved, 4) if total_resolved > 0 else None
    )

    brier_scores = [p.brier_score for p in resolved_preds if p.brier_score is not None]
    overall_brier = (
        round(sum(brier_scores) / len(brier_scores), 4) if brier_scores else None
    )

    # Find best and worst agents
    agent_accuracy = {}
    for agent, entries in by_agent_final.items():
        if entries:
            last_entry = entries[-1]
            if last_entry["cumulative_accuracy"] is not None:
                agent_accuracy[agent] = last_entry["cumulative_accuracy"]

    best_agent = None
    best_agent_accuracy = None
    worst_agent = None
    worst_agent_accuracy = None

    if agent_accuracy:
        best_agent = max(agent_accuracy, key=agent_accuracy.get)
        best_agent_accuracy = agent_accuracy[best_agent]
        worst_agent = min(agent_accuracy, key=agent_accuracy.get)
        worst_agent_accuracy = agent_accuracy[worst_agent]

    return {
        "timeline": timeline_list,
        "by_agent": by_agent_final,
        "by_domain": by_domain_final,
        "summary": {
            "total_resolved": total_resolved,
            "total_correct": total_correct,
            "overall_accuracy": overall_accuracy,
            "overall_brier": overall_brier,
            "best_agent": best_agent,
            "best_agent_accuracy": best_agent_accuracy,
            "worst_agent": worst_agent,
            "worst_agent_accuracy": worst_agent_accuracy,
        },
    }
