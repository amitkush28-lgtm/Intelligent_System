"""
Sub-prediction health checker.

Daily: check whether parent predictions have enough fast-resolving sub-predictions.
Flag parent predictions with no sub-predictions or only stale/expired sub-predictions.
Generate notes suggesting sub-prediction creation.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List

from shared.database import get_db_session
from shared.models import Prediction, Note

logger = logging.getLogger(__name__)

# Minimum sub-predictions for a parent prediction to be considered healthy
MIN_SUB_PREDICTIONS = 2

# A sub-prediction is "stale" if it hasn't had activity in this many days
STALE_DAYS = 14

# Only check parent predictions that are at least this old
MIN_PARENT_AGE_DAYS = 3


def check_sub_prediction_health() -> Dict[str, Any]:
    """
    Scan active parent predictions for sub-prediction health.
    Flag predictions that lack fast-resolving child predictions.
    """
    stats = {
        "parents_checked": 0,
        "healthy": 0,
        "unhealthy": 0,
        "notes_created": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            today = date.today()
            min_age_date = today - timedelta(days=MIN_PARENT_AGE_DAYS)

            # Find all active top-level predictions (no parent)
            parents = (
                db.query(Prediction)
                .filter(
                    Prediction.status == "ACTIVE",
                    Prediction.parent_id.is_(None),
                    Prediction.created_at <= datetime.combine(
                        min_age_date, datetime.min.time()
                    ),
                )
                .all()
            )
            stats["parents_checked"] = len(parents)

            for parent in parents:
                try:
                    health = _assess_parent_health(db, parent)

                    if health["is_healthy"]:
                        stats["healthy"] += 1
                    else:
                        stats["unhealthy"] += 1
                        # Create a note if we haven't already flagged this recently
                        if _should_create_note(db, parent):
                            _create_health_note(db, parent, health)
                            stats["notes_created"] += 1

                except Exception as e:
                    logger.error(
                        f"Error checking health for prediction {parent.id}: {e}"
                    )
                    stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Failed to check sub-prediction health: {e}")
        stats["errors"] += 1

    if stats["unhealthy"] > 0:
        logger.info(
            f"Sub-prediction health: {stats['parents_checked']} checked, "
            f"{stats['healthy']} healthy, {stats['unhealthy']} unhealthy, "
            f"{stats['notes_created']} notes created"
        )

    return stats


def _assess_parent_health(
    db, parent: Prediction
) -> Dict[str, Any]:
    """Assess the health of a parent prediction's sub-predictions."""
    today = date.today()

    # Get all sub-predictions
    subs = (
        db.query(Prediction)
        .filter(Prediction.parent_id == parent.id)
        .all()
    )

    total_subs = len(subs)
    active_subs = [s for s in subs if s.status == "ACTIVE"]
    resolved_subs = [
        s for s in subs
        if s.status in ("RESOLVED_TRUE", "RESOLVED_FALSE", "EXPIRED")
    ]

    # Check for stale sub-predictions (active but deadline far away or none)
    stale_subs = []
    for sub in active_subs:
        if sub.time_condition_date:
            days_until = (sub.time_condition_date - today).days
            if days_until > 90:  # Long-dated sub doesn't help
                stale_subs.append(sub)
        elif sub.time_condition_end:
            days_until = (sub.time_condition_end - today).days
            if days_until > 90:
                stale_subs.append(sub)

    # Health assessment
    is_healthy = (
        total_subs >= MIN_SUB_PREDICTIONS
        and len(active_subs) >= 1
        and len(stale_subs) < len(active_subs)  # Not all active subs are stale
    )

    # Calculate days until parent deadline
    days_to_deadline = None
    if parent.time_condition_date:
        days_to_deadline = (parent.time_condition_date - today).days
    elif parent.time_condition_end:
        days_to_deadline = (parent.time_condition_end - today).days

    return {
        "is_healthy": is_healthy,
        "total_subs": total_subs,
        "active_subs": len(active_subs),
        "resolved_subs": len(resolved_subs),
        "stale_subs": len(stale_subs),
        "days_to_deadline": days_to_deadline,
        "reasons": _get_unhealthy_reasons(
            total_subs, len(active_subs), len(stale_subs), days_to_deadline
        ),
    }


def _get_unhealthy_reasons(
    total_subs: int,
    active_subs: int,
    stale_subs: int,
    days_to_deadline: int | None,
) -> List[str]:
    """Generate human-readable reasons for unhealthy status."""
    reasons = []

    if total_subs == 0:
        reasons.append("No sub-predictions exist — cannot track leading indicators")
    elif total_subs < MIN_SUB_PREDICTIONS:
        reasons.append(
            f"Only {total_subs} sub-predictions (need >= {MIN_SUB_PREDICTIONS})"
        )

    if active_subs == 0 and total_subs > 0:
        reasons.append("All sub-predictions have resolved — no active leading indicators")

    if stale_subs > 0 and stale_subs >= active_subs:
        reasons.append(
            f"{stale_subs} of {active_subs} active sub-predictions are long-dated "
            f"(>90 days) — need faster-resolving indicators"
        )

    if days_to_deadline is not None and days_to_deadline < 30 and total_subs == 0:
        reasons.append(
            f"Deadline in {days_to_deadline} days with no sub-predictions — "
            f"limited ability to detect early signals"
        )

    return reasons


def _should_create_note(db, parent: Prediction) -> bool:
    """
    Check if we've already created a health note for this prediction recently.
    Avoid spamming the same warning.
    """
    recent_cutoff = datetime.utcnow() - timedelta(days=7)

    existing = (
        db.query(Note)
        .filter(
            Note.prediction_id == parent.id,
            Note.type == "observation",
            Note.text.contains("Sub-prediction health"),
            Note.date >= recent_cutoff,
        )
        .first()
    )

    return existing is None


def _create_health_note(
    db, parent: Prediction, health: Dict[str, Any]
) -> None:
    """Create a note flagging sub-prediction health issues."""
    reasons_text = "; ".join(health["reasons"]) if health["reasons"] else "General health check"

    suggestion = _generate_sub_prediction_suggestions(parent, health)

    note_text = (
        f"[Sub-prediction health check] "
        f"Status: UNHEALTHY. "
        f"Current sub-predictions: {health['total_subs']} total, "
        f"{health['active_subs']} active, {health['resolved_subs']} resolved. "
        f"Issues: {reasons_text}. "
        f"Suggestion: {suggestion}"
    )

    note = Note(
        prediction_id=parent.id,
        date=datetime.utcnow(),
        type="observation",
        text=note_text,
    )
    db.add(note)


def _generate_sub_prediction_suggestions(
    parent: Prediction, health: Dict[str, Any]
) -> str:
    """Generate suggestions for sub-predictions based on the parent prediction."""
    suggestions = []

    if health["total_subs"] == 0:
        suggestions.append(
            "Create 2-3 fast-resolving sub-predictions that serve as leading "
            "indicators. Focus on observable, verifiable events that would "
            "confirm or disconfirm the parent prediction."
        )
    elif health["active_subs"] == 0:
        suggestions.append(
            "All sub-predictions have resolved. Create new ones targeting "
            "the next phase of developments."
        )
    elif health["stale_subs"] > 0:
        suggestions.append(
            "Current sub-predictions are too long-dated. Add shorter-term "
            "indicators that resolve within 2-4 weeks."
        )

    if health["days_to_deadline"] is not None and health["days_to_deadline"] < 60:
        suggestions.append(
            f"Deadline approaching ({health['days_to_deadline']} days). "
            f"Create sub-predictions targeting the final decision points."
        )

    return " ".join(suggestions) if suggestions else "Review and add appropriate sub-predictions."
