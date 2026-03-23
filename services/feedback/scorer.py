"""
Brier score calculator and auto-resolution engine.

Responsibilities:
- Every 5 min: scan for predictions past deadline → auto-resolve as EXPIRED
- On resolution: calculate Brier score = (predicted_probability - actual_outcome)²
- Handle both point and range time conditions
"""

import logging
from datetime import datetime, date
from typing import Dict, Any

from sqlalchemy.orm import Session

from shared.database import get_db_session
from shared.models import Prediction, ConfidenceTrail
from shared.utils import is_past_deadline, brier_score

logger = logging.getLogger(__name__)


def scan_and_resolve_expired() -> Dict[str, Any]:
    """
    Scan all ACTIVE predictions for those past their deadline.
    Auto-resolve as EXPIRED (status=RESOLVED_FALSE, resolved_outcome=False).
    Returns stats about what was resolved.
    """
    stats = {
        "scanned": 0,
        "expired": 0,
        "scored": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            # Fetch all active predictions
            active_predictions = (
                db.query(Prediction)
                .filter(Prediction.status == "ACTIVE")
                .all()
            )
            stats["scanned"] = len(active_predictions)

            for pred in active_predictions:
                try:
                    if is_past_deadline(pred):
                        _expire_prediction(db, pred)
                        stats["expired"] += 1
                        stats["scored"] += 1
                except Exception as e:
                    logger.error(
                        f"Error processing prediction {pred.id}: {e}"
                    )
                    stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Failed to scan predictions: {e}")
        stats["errors"] += 1

    if stats["expired"] > 0:
        logger.info(
            f"Auto-resolution: scanned={stats['scanned']}, "
            f"expired={stats['expired']}, scored={stats['scored']}"
        )

    return stats


def _expire_prediction(db: Session, prediction: Prediction) -> None:
    """Expire a single prediction and compute its Brier score."""
    now = datetime.utcnow()
    today = date.today()

    # Set resolution fields
    prediction.status = "EXPIRED"
    prediction.resolved_date = today
    prediction.resolved_outcome = False  # Expired = FALSE per spec

    # Calculate Brier score: (predicted_probability - 0)² since outcome is FALSE
    score = brier_score(prediction.current_confidence, False)
    prediction.brier_score = score

    # Add confidence trail entry for the expiration
    trail_entry = ConfidenceTrail(
        prediction_id=prediction.id,
        date=now,
        value=prediction.current_confidence,
        trigger="auto_expiration",
        reasoning=(
            f"Prediction expired past deadline. "
            f"Final confidence: {prediction.current_confidence:.2f}. "
            f"Brier score: {score:.4f}. "
            f"Auto-resolved as FALSE (expired without resolution)."
        ),
    )
    db.add(trail_entry)

    logger.info(
        f"Expired prediction {prediction.id}: "
        f"confidence={prediction.current_confidence:.2f}, "
        f"brier={score:.4f}"
    )


def score_resolved_prediction(db: Session, prediction: Prediction) -> float:
    """
    Calculate and store Brier score for a manually resolved prediction.
    Called when a prediction is resolved TRUE or FALSE by an agent or user.
    Returns the Brier score.
    """
    if prediction.resolved_outcome is None:
        logger.warning(
            f"Cannot score prediction {prediction.id}: no resolved_outcome"
        )
        return -1.0

    score = brier_score(prediction.current_confidence, prediction.resolved_outcome)
    prediction.brier_score = score

    logger.info(
        f"Scored prediction {prediction.id}: "
        f"confidence={prediction.current_confidence:.2f}, "
        f"outcome={prediction.resolved_outcome}, "
        f"brier={score:.4f}"
    )

    return score


def score_all_unscored() -> Dict[str, Any]:
    """
    Find resolved predictions without Brier scores and compute them.
    Catches any that were resolved externally without scoring.
    """
    stats = {"scored": 0, "errors": 0}

    try:
        with get_db_session() as db:
            unscored = (
                db.query(Prediction)
                .filter(
                    Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE", "EXPIRED"]),
                    Prediction.brier_score.is_(None),
                    Prediction.resolved_outcome.isnot(None),
                )
                .all()
            )

            for pred in unscored:
                try:
                    score_resolved_prediction(db, pred)
                    stats["scored"] += 1
                except Exception as e:
                    logger.error(f"Error scoring prediction {pred.id}: {e}")
                    stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Failed to score unscored predictions: {e}")
        stats["errors"] += 1

    if stats["scored"] > 0:
        logger.info(f"Scored {stats['scored']} previously unscored predictions")

    return stats


def run_scoring_cycle() -> Dict[str, Any]:
    """Run a complete scoring cycle: expire + score unscored."""
    expire_stats = scan_and_resolve_expired()
    score_stats = score_all_unscored()

    return {
        "expired": expire_stats["expired"],
        "newly_scored": score_stats["scored"],
        "scanned": expire_stats["scanned"],
        "errors": expire_stats["errors"] + score_stats["errors"],
    }
