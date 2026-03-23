"""
Cross-agent correlation scanner.

Every 2 hours: detect convergence (multiple agents flagging same risk)
and divergence (agents disagreeing about same topic).
On confidence movement >5pp in 48hrs: publish debate_trigger to Redis.
Detect shared assumptions across agents (groupthink risk).
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

import redis

from shared.config import get_settings
from shared.database import get_db_session
from shared.models import Prediction, ConfidenceTrail, Note, WeakSignal

logger = logging.getLogger(__name__)
settings = get_settings()

# Configuration
CONVERGENCE_THRESHOLD = 3  # Min agents flagging same theme for convergence
DIVERGENCE_CONFIDENCE_GAP = 0.20  # Min confidence gap for divergence detection
RAPID_MOVEMENT_PP = 5.0  # Percentage points movement in 48h triggers debate
RAPID_MOVEMENT_HOURS = 48
DEBATE_TRIGGER_QUEUE = "debate_trigger"


def scan_cross_agent_correlations() -> Dict[str, Any]:
    """
    Run cross-agent correlation scan.
    Detects convergence, divergence, rapid movement, and groupthink.
    """
    stats = {
        "convergences_found": 0,
        "divergences_found": 0,
        "rapid_movements": 0,
        "debate_triggers_published": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            active_predictions = (
                db.query(Prediction)
                .filter(Prediction.status == "ACTIVE")
                .all()
            )

            if not active_predictions:
                return stats

            # 1. Detect convergence — multiple agents predicting similar things
            convergences = _detect_convergence(active_predictions)
            stats["convergences_found"] = len(convergences)
            for conv in convergences:
                _record_convergence(db, conv)

            # 2. Detect divergence — agents disagreeing on same topic
            divergences = _detect_divergence(active_predictions)
            stats["divergences_found"] = len(divergences)
            for div in divergences:
                _record_divergence(db, div)

            # 3. Detect rapid confidence movements
            rapid_movers = _detect_rapid_movements(db)
            stats["rapid_movements"] = len(rapid_movers)

            # 4. Publish debate triggers
            debate_count = _publish_debate_triggers(rapid_movers)
            stats["debate_triggers_published"] = debate_count

            db.flush()

    except Exception as e:
        logger.error(f"Cross-agent scan failed: {e}")
        stats["errors"] += 1

    if any(v > 0 for k, v in stats.items() if k != "errors"):
        logger.info(
            f"Cross-agent scan: convergences={stats['convergences_found']}, "
            f"divergences={stats['divergences_found']}, "
            f"rapid_movements={stats['rapid_movements']}, "
            f"debate_triggers={stats['debate_triggers_published']}"
        )

    return stats


def _detect_convergence(
    predictions: List[Prediction],
) -> List[Dict[str, Any]]:
    """
    Detect when multiple agents are making predictions about the same theme.
    Uses entity and keyword overlap to group related predictions.
    """
    convergences = []

    # Group predictions by agent
    by_agent: Dict[str, List[Prediction]] = defaultdict(list)
    for pred in predictions:
        if pred.agent != "master":  # Skip master — it's already a synthesis
            by_agent[pred.agent].append(pred)

    if len(by_agent) < 2:
        return convergences

    # Simple keyword-based theme detection across agents
    # Extract key terms from each prediction's claim
    all_claims = []
    for pred in predictions:
        if pred.agent != "master":
            keywords = _extract_keywords(pred.claim)
            all_claims.append({
                "prediction": pred,
                "keywords": keywords,
            })

    # Find keyword clusters that span multiple agents
    keyword_agents: Dict[str, set] = defaultdict(set)
    keyword_preds: Dict[str, List[Prediction]] = defaultdict(list)

    for item in all_claims:
        for kw in item["keywords"]:
            keyword_agents[kw].add(item["prediction"].agent)
            keyword_preds[kw].append(item["prediction"])

    # Keywords referenced by >= CONVERGENCE_THRESHOLD agents
    for kw, agents in keyword_agents.items():
        if len(agents) >= CONVERGENCE_THRESHOLD:
            preds = keyword_preds[kw]
            avg_confidence = sum(p.current_confidence for p in preds) / len(preds)

            convergences.append({
                "theme": kw,
                "agents": list(agents),
                "prediction_ids": [p.id for p in preds],
                "avg_confidence": avg_confidence,
                "count": len(preds),
            })

    return convergences


def _detect_divergence(
    predictions: List[Prediction],
) -> List[Dict[str, Any]]:
    """
    Detect when agents disagree about the same topic.
    Look for predictions on similar themes with confidence going in opposite directions.
    """
    divergences = []

    # Skip master agent
    specialist_preds = [p for p in predictions if p.agent != "master"]

    # Compare each pair of predictions across different agents
    for i, p1 in enumerate(specialist_preds):
        for p2 in specialist_preds[i + 1:]:
            if p1.agent == p2.agent:
                continue

            # Check if claims are related (keyword overlap)
            kw1 = _extract_keywords(p1.claim)
            kw2 = _extract_keywords(p2.claim)
            overlap = kw1 & kw2

            if len(overlap) < 2:
                continue

            # Check for significant confidence gap
            conf_gap = abs(p1.current_confidence - p2.current_confidence)
            if conf_gap >= DIVERGENCE_CONFIDENCE_GAP:
                divergences.append({
                    "theme": ", ".join(sorted(overlap)[:3]),
                    "predictions": [
                        {
                            "id": p1.id,
                            "agent": p1.agent,
                            "confidence": p1.current_confidence,
                            "claim": p1.claim[:100],
                        },
                        {
                            "id": p2.id,
                            "agent": p2.agent,
                            "confidence": p2.current_confidence,
                            "claim": p2.claim[:100],
                        },
                    ],
                    "confidence_gap": conf_gap,
                })

    return divergences


def _detect_rapid_movements(db) -> List[Dict[str, Any]]:
    """
    Find predictions where confidence moved >5pp in the last 48 hours.
    """
    movers = []
    cutoff = datetime.utcnow() - timedelta(hours=RAPID_MOVEMENT_HOURS)

    # Get recent confidence trail entries
    recent_trails = (
        db.query(ConfidenceTrail)
        .filter(ConfidenceTrail.date >= cutoff)
        .order_by(ConfidenceTrail.prediction_id, ConfidenceTrail.date)
        .all()
    )

    # Group by prediction
    by_prediction: Dict[str, List[ConfidenceTrail]] = defaultdict(list)
    for trail in recent_trails:
        by_prediction[trail.prediction_id].append(trail)

    for pred_id, trails in by_prediction.items():
        if len(trails) < 2:
            continue

        # Calculate total movement
        first_value = trails[0].value
        last_value = trails[-1].value
        movement_pp = abs(last_value - first_value) * 100

        if movement_pp >= RAPID_MOVEMENT_PP:
            # Get the prediction for context
            pred = db.query(Prediction).filter(Prediction.id == pred_id).first()
            if pred and pred.status == "ACTIVE":
                movers.append({
                    "prediction_id": pred_id,
                    "agent": pred.agent if pred else "unknown",
                    "claim": pred.claim[:100] if pred else "",
                    "movement_pp": movement_pp,
                    "direction": "up" if last_value > first_value else "down",
                    "from_confidence": first_value,
                    "to_confidence": last_value,
                })

    return movers


def _publish_debate_triggers(movers: List[Dict[str, Any]]) -> int:
    """Publish debate triggers to Redis for rapid confidence movements."""
    if not movers:
        return 0

    published = 0
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        for mover in movers:
            message = json.dumps({
                "type": "rapid_movement",
                "prediction_id": mover["prediction_id"],
                "agent": mover["agent"],
                "movement_pp": mover["movement_pp"],
                "direction": mover["direction"],
                "timestamp": datetime.utcnow().isoformat(),
            })
            r.lpush(DEBATE_TRIGGER_QUEUE, message)
            published += 1

        logger.info(f"Published {published} debate triggers to Redis")

    except redis.RedisError as e:
        logger.warning(f"Redis unavailable for debate triggers: {e}")
    except Exception as e:
        logger.error(f"Error publishing debate triggers: {e}")

    return published


def _record_convergence(db, convergence: Dict[str, Any]) -> None:
    """Record a convergence finding as a weak signal."""
    signal_text = (
        f"[CONVERGENCE] {convergence['count']} agents ({', '.join(convergence['agents'])}) "
        f"are flagging '{convergence['theme']}' with average confidence "
        f"{convergence['avg_confidence']:.0%}. "
        f"Predictions: {', '.join(convergence['prediction_ids'][:5])}"
    )

    strength = "HIGH" if convergence["count"] >= 4 else "MEDIUM"

    weak_signal = WeakSignal(
        signal=signal_text,
        strength=strength,
        status="investigating",
        detected_at=datetime.utcnow(),
    )
    db.add(weak_signal)


def _record_divergence(db, divergence: Dict[str, Any]) -> None:
    """Record a divergence finding as a weak signal."""
    preds = divergence["predictions"]
    signal_text = (
        f"[DIVERGENCE] Agents disagree on '{divergence['theme']}': "
        f"{preds[0]['agent']} at {preds[0]['confidence']:.0%} vs "
        f"{preds[1]['agent']} at {preds[1]['confidence']:.0%} "
        f"(gap: {divergence['confidence_gap']:.0%}). "
        f"Predictions: {preds[0]['id']}, {preds[1]['id']}"
    )

    strength = "HIGH" if divergence["confidence_gap"] >= 0.30 else "MEDIUM"

    weak_signal = WeakSignal(
        signal=signal_text,
        strength=strength,
        status="investigating",
        detected_at=datetime.utcnow(),
    )
    db.add(weak_signal)


def _extract_keywords(text: str) -> set:
    """
    Extract meaningful keywords from prediction claim text.
    Simple approach: lowercase, split, filter stopwords and short words.
    """
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "must", "ought",
        "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
        "into", "through", "during", "before", "after", "above", "below",
        "between", "under", "over", "up", "down", "out", "off", "than",
        "that", "this", "these", "those", "it", "its", "they", "them",
        "their", "we", "our", "you", "your", "he", "she", "his", "her",
        "and", "but", "or", "nor", "not", "no", "so", "if", "then",
        "because", "while", "although", "though", "when", "where", "which",
        "who", "whom", "what", "how", "all", "each", "every", "both",
        "few", "more", "most", "other", "some", "such", "only", "own",
        "same", "very", "just", "about", "also", "within", "likely",
        "unlikely", "possible", "probably", "will", "within", "next",
        "before", "after", "following", "increase", "decrease", "change",
        "remain", "continue", "predict", "prediction", "expect", "expected",
    }

    words = text.lower().split()
    # Clean punctuation
    cleaned = set()
    for w in words:
        w = w.strip(".,;:!?\"'()[]{}/-")
        if len(w) > 3 and w not in stopwords and w.isalpha():
            cleaned.add(w)

    return cleaned
