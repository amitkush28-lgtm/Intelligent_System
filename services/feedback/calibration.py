"""
Calibration curve builder.

Every hour: rebuild calibration curves by agent, domain, confidence bucket.
For each bucket: calculate predicted_avg and actual_avg.
Write results to CalibrationScore model.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import func

from shared.database import get_db_session
from shared.models import Prediction, CalibrationScore
from shared.utils import confidence_bucket, brier_score

logger = logging.getLogger(__name__)

# All agents to track
AGENTS = ["geopolitical", "economist", "investor", "political", "sentiment", "master"]

# Domains
DOMAINS = ["geopolitical", "economic", "market", "political", "sentiment"]

# Minimum predictions per bucket to compute meaningful calibration
MIN_BUCKET_COUNT = 3


def rebuild_calibration_curves() -> Dict[str, Any]:
    """
    Rebuild all calibration curves from resolved predictions.
    Computes per-agent, per-domain, and per-bucket statistics.
    Returns stats about what was computed.
    """
    stats = {
        "total_resolved": 0,
        "buckets_computed": 0,
        "agents_processed": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            # Fetch all resolved predictions with outcomes
            resolved = (
                db.query(Prediction)
                .filter(
                    Prediction.status.in_(
                        ["RESOLVED_TRUE", "RESOLVED_FALSE", "EXPIRED"]
                    ),
                    Prediction.resolved_outcome.isnot(None),
                )
                .all()
            )
            stats["total_resolved"] = len(resolved)

            if len(resolved) == 0:
                logger.info("No resolved predictions to calibrate")
                return stats

            # Delete old calibration scores before rebuilding
            db.query(CalibrationScore).delete()
            db.flush()

            # Build calibration by agent (all domains combined)
            for agent in AGENTS:
                agent_preds = [p for p in resolved if p.agent == agent]
                if not agent_preds:
                    continue

                stats["agents_processed"] += 1
                buckets_written = _compute_and_write_buckets(
                    db, agent_preds, agent, domain=None
                )
                stats["buckets_computed"] += buckets_written

            # Build calibration by agent × domain
            for agent in AGENTS:
                for domain in DOMAINS:
                    domain_preds = [
                        p for p in resolved
                        if p.agent == agent and _prediction_domain(p) == domain
                    ]
                    if len(domain_preds) < MIN_BUCKET_COUNT:
                        continue

                    buckets_written = _compute_and_write_buckets(
                        db, domain_preds, agent, domain=domain
                    )
                    stats["buckets_computed"] += buckets_written

            # Build overall calibration (all agents)
            overall_written = _compute_and_write_buckets(
                db, resolved, agent="system", domain=None
            )
            stats["buckets_computed"] += overall_written

            db.flush()

    except Exception as e:
        logger.error(f"Failed to rebuild calibration curves: {e}")
        stats["errors"] += 1

    logger.info(
        f"Calibration rebuild: resolved={stats['total_resolved']}, "
        f"buckets={stats['buckets_computed']}, agents={stats['agents_processed']}"
    )

    return stats


def _compute_and_write_buckets(
    db: Session,
    predictions: List[Prediction],
    agent: str,
    domain: Optional[str],
) -> int:
    """
    Compute calibration buckets from a list of resolved predictions and
    write CalibrationScore rows. Returns count of buckets written.
    """
    # Group predictions by confidence bucket
    buckets: Dict[str, List[Prediction]] = defaultdict(list)
    for pred in predictions:
        bucket = confidence_bucket(pred.current_confidence)
        buckets[bucket].append(pred)

    written = 0
    for bucket_name, bucket_preds in sorted(buckets.items()):
        if len(bucket_preds) < MIN_BUCKET_COUNT:
            continue

        # Calculate statistics
        predicted_avg = sum(p.current_confidence for p in bucket_preds) / len(bucket_preds)
        actual_avg = sum(
            1.0 if p.resolved_outcome else 0.0 for p in bucket_preds
        ) / len(bucket_preds)

        # Calculate average Brier score for this bucket
        brier_scores = []
        for p in bucket_preds:
            if p.brier_score is not None:
                brier_scores.append(p.brier_score)
            elif p.resolved_outcome is not None:
                brier_scores.append(
                    brier_score(p.current_confidence, p.resolved_outcome)
                )
        brier_avg = sum(brier_scores) / len(brier_scores) if brier_scores else None

        # Determine bias direction
        bias_direction = _compute_bias_direction(predicted_avg, actual_avg)

        # Write calibration score
        cal_score = CalibrationScore(
            agent=agent,
            domain=domain,
            confidence_bucket=bucket_name,
            predicted_avg=predicted_avg,
            actual_avg=actual_avg,
            count=len(bucket_preds),
            brier_avg=brier_avg,
            bias_direction=bias_direction,
            calculated_at=datetime.utcnow(),
        )
        db.add(cal_score)
        written += 1

    return written


def _compute_bias_direction(predicted_avg: float, actual_avg: float) -> str:
    """
    Determine bias direction.
    overconfident: predicted_avg > actual_avg + 0.05
    underconfident: predicted_avg < actual_avg - 0.05
    calibrated: within 0.05 tolerance
    """
    diff = predicted_avg - actual_avg
    if diff > 0.05:
        return "overconfident"
    elif diff < -0.05:
        return "underconfident"
    else:
        return "calibrated"


def _prediction_domain(prediction: Prediction) -> Optional[str]:
    """
    Infer the domain of a prediction from the agent name.
    Since predictions don't have a domain column directly,
    we map from the agent that created them.
    """
    agent_domain_map = {
        "geopolitical": "geopolitical",
        "economist": "economic",
        "investor": "market",
        "political": "political",
        "sentiment": "sentiment",
        "master": None,  # Master spans all domains
    }
    return agent_domain_map.get(prediction.agent)


def get_calibration_summary() -> Dict[str, Any]:
    """
    Get a summary of current calibration state for all agents.
    Used by other services to understand system calibration.
    """
    summary = {}

    try:
        with get_db_session() as db:
            scores = db.query(CalibrationScore).all()

            for score in scores:
                key = f"{score.agent}:{score.domain or 'all'}"
                if key not in summary:
                    summary[key] = {
                        "agent": score.agent,
                        "domain": score.domain,
                        "buckets": [],
                        "overall_bias": None,
                    }
                summary[key]["buckets"].append({
                    "bucket": score.confidence_bucket,
                    "predicted_avg": score.predicted_avg,
                    "actual_avg": score.actual_avg,
                    "count": score.count,
                    "bias": score.bias_direction,
                })

            # Compute overall bias per agent
            for key, data in summary.items():
                biases = [b["bias"] for b in data["buckets"] if b["bias"]]
                if biases:
                    overconf = biases.count("overconfident")
                    underconf = biases.count("underconfident")
                    if overconf > underconf:
                        data["overall_bias"] = "overconfident"
                    elif underconf > overconf:
                        data["overall_bias"] = "underconfident"
                    else:
                        data["overall_bias"] = "calibrated"

    except Exception as e:
        logger.error(f"Failed to get calibration summary: {e}")

    return summary
