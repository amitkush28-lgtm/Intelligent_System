"""
Shared utilities used across all services.
"""

import hashlib
import logging
from datetime import datetime, date
from typing import Optional

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def generate_prediction_id(agent: str, claim: str) -> str:
    """Generate deterministic prediction ID: PRED-YYYY-XXXX."""
    year = datetime.utcnow().year
    hash_input = f"{agent}:{claim}:{datetime.utcnow().isoformat()}"
    hash_hex = hashlib.sha256(hash_input.encode()).hexdigest()[:4].upper()
    return f"PRED-{year}-{hash_hex}"


def generate_event_id(source: str, text: str, timestamp: datetime) -> str:
    """Generate deterministic event ID for dedup."""
    hash_input = f"{source}:{text[:200]}:{timestamp.isoformat()}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def generate_claim_id(claim_text: str, source: str) -> str:
    """Generate deterministic claim ID."""
    hash_input = f"{source}:{claim_text[:200]}"
    return f"CLM-{hashlib.sha256(hash_input.encode()).hexdigest()[:8].upper()}"


def generate_debate_id(prediction_id: str, agent: str) -> str:
    """Generate debate ID."""
    ts = datetime.utcnow().strftime("%Y%m%d%H%M")
    return f"DBT-{prediction_id}-{agent}-{ts}"


def cap_confidence_change(
    proposed_change_pp: float,
    evidence_integrity: float,
) -> float:
    """
    HARD RULE: Confidence change is capped by evidence integrity.
    Agent wanting +15pp on 0.40 integrity evidence gets max +6pp.
    Formula: max_change = evidence_integrity * CONFIDENCE_CAP_MULTIPLIER * 100
    """
    max_change = evidence_integrity * settings.CONFIDENCE_CAP_MULTIPLIER * 100
    if abs(proposed_change_pp) > max_change:
        capped = max_change if proposed_change_pp > 0 else -max_change
        logger.info(
            f"Confidence change capped: {proposed_change_pp:.1f}pp -> {capped:.1f}pp "
            f"(evidence integrity: {evidence_integrity:.2f})"
        )
        return capped
    return proposed_change_pp


def clamp_confidence(value: float) -> float:
    """Clamp confidence to [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


def get_initial_source_integrity(source: str) -> float:
    """Default integrity scores from Part 4 of the brief."""
    scores = {
        "reuters": 0.75,
        "ap": 0.75,
        "established_newspaper": 0.70,
        "government_statement": 0.65,
        "think_tank": 0.60,
        "regional_outlet": 0.50,
        "verified_social_media": 0.40,
        "anonymous_source": 0.20,
        "blog": 0.15,
        "unverified_social": 0.10,
    }
    # Try exact match first, then fuzzy
    source_lower = source.lower()
    for key, score in scores.items():
        if key in source_lower:
            return score
    return 0.50  # Default for unknown sources


def confidence_bucket(confidence: float) -> str:
    """Convert confidence float to bucket string for calibration tracking."""
    pct = int(confidence * 100)
    lower = (pct // 10) * 10
    upper = lower + 10
    return f"{lower}-{upper}%"


def is_past_deadline(prediction) -> bool:
    """Check if a prediction is past its resolution deadline."""
    today = date.today()
    if prediction.time_condition_type == "point" and prediction.time_condition_date:
        return today > prediction.time_condition_date
    if prediction.time_condition_type == "range" and prediction.time_condition_end:
        return today > prediction.time_condition_end
    return False


def brier_score(predicted_probability: float, actual_outcome: bool) -> float:
    """Calculate Brier score: (predicted_probability - actual_outcome)²."""
    outcome = 1.0 if actual_outcome else 0.0
    return (predicted_probability - outcome) ** 2


def setup_logging(service_name: str) -> logging.Logger:
    """Configure structured logging for a service."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format=f"%(asctime)s [{service_name}] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(service_name)
