"""
Auto-Resolution Engine — Uses LLM with web search to check if predictions have resolved.

Runs during each feedback cycle. For each active prediction approaching or past its deadline:
1. Build a prompt with the prediction claim, resolution criteria, and current date
2. Call Claude with web search to check current facts
3. Parse the response to determine: RESOLVED_TRUE, RESOLVED_FALSE, or STILL_ACTIVE
4. Update the prediction status and calculate Brier score

This replaces manual resolution and the crude "expired = FALSE" default.
"""

import logging
import traceback
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

from shared.database import get_db_session
from shared.models import Prediction, ConfidenceTrail
from shared.llm_client import call_claude_with_web_search, parse_structured_json
from shared.utils import brier_score

logger = logging.getLogger(__name__)

RESOLUTION_SYSTEM_PROMPT = """You are a fact-checking analyst. Your job is to determine whether a prediction has come true, proven false, or is still undetermined.

You will be given:
- A specific, falsifiable prediction claim
- The resolution criteria (how to determine TRUE or FALSE)
- The prediction's deadline
- Today's date

Use web search to find current, factual information relevant to the prediction. Then determine the outcome.

You MUST respond with ONLY valid JSON in this exact format:
{
    "outcome": "TRUE" | "FALSE" | "UNDETERMINED",
    "confidence_in_judgment": 0.0 to 1.0,
    "evidence": "Brief summary of the key evidence you found (2-3 sentences)",
    "sources": ["source1", "source2"]
}

Rules:
- Only return TRUE or FALSE if you have strong evidence. If uncertain, return UNDETERMINED.
- A prediction is FALSE if the deadline has passed and the predicted event did not occur.
- A prediction is TRUE if the predicted event has clearly occurred, even before the deadline.
- confidence_in_judgment reflects how sure YOU are about your verdict, not the original prediction's confidence.
- Be specific about your evidence — cite what you found via web search.
"""


def _should_check(prediction: Prediction) -> bool:
    """Determine if a prediction should be checked for resolution."""
    today = date.today()

    # Always check if past deadline
    if prediction.time_condition_type == "point" and prediction.time_condition_date:
        if today >= prediction.time_condition_date:
            return True
        # Also check within 3 days of deadline
        if (prediction.time_condition_date - today).days <= 3:
            return True

    if prediction.time_condition_type == "range" and prediction.time_condition_end:
        if today >= prediction.time_condition_end:
            return True
        if (prediction.time_condition_end - today).days <= 3:
            return True

    # For ongoing predictions, check weekly
    if prediction.time_condition_type == "ongoing":
        if prediction.created_at:
            days_active = (datetime.utcnow() - prediction.created_at).days
            # Check every 7 days
            if days_active > 0 and days_active % 7 == 0:
                return True

    # Check high-confidence predictions more often (they're more likely to resolve)
    if prediction.current_confidence > 0.85 or prediction.current_confidence < 0.15:
        return True

    return False


async def _check_prediction(prediction: Prediction) -> Optional[Dict[str, Any]]:
    """Use Claude with web search to check if a prediction has resolved."""
    today_str = date.today().isoformat()

    deadline = "Ongoing (no specific deadline)"
    if prediction.time_condition_type == "point" and prediction.time_condition_date:
        deadline = prediction.time_condition_date.isoformat()
    elif prediction.time_condition_type == "range" and prediction.time_condition_end:
        deadline = prediction.time_condition_end.isoformat()

    past_deadline = False
    if prediction.time_condition_type == "point" and prediction.time_condition_date:
        past_deadline = date.today() > prediction.time_condition_date
    elif prediction.time_condition_type == "range" and prediction.time_condition_end:
        past_deadline = date.today() > prediction.time_condition_end

    user_message = f"""Check whether this prediction has resolved:

PREDICTION: {prediction.claim}

RESOLUTION CRITERIA: {prediction.resolution_criteria}

DEADLINE: {deadline}
TODAY'S DATE: {today_str}
PAST DEADLINE: {"Yes" if past_deadline else "No"}
CURRENT CONFIDENCE: {prediction.current_confidence:.0%}
AGENT: {prediction.agent}

Search the web for current information about this topic and determine if the prediction has resolved TRUE, FALSE, or is still UNDETERMINED.

Respond with ONLY valid JSON."""

    try:
        response = await call_claude_with_web_search(
            system_prompt=RESOLUTION_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=2048,
        )

        result = parse_structured_json(response)
        if not result:
            # Try to extract from non-JSON response
            response_lower = response.lower()
            if '"outcome": "true"' in response_lower or '"outcome":"true"' in response_lower:
                result = {"outcome": "TRUE", "confidence_in_judgment": 0.7, "evidence": response[:200]}
            elif '"outcome": "false"' in response_lower or '"outcome":"false"' in response_lower:
                result = {"outcome": "FALSE", "confidence_in_judgment": 0.7, "evidence": response[:200]}
            else:
                return None

        return result

    except Exception as e:
        logger.warning(f"Resolution check failed for {prediction.id}: {e}")
        return None


def _resolve_prediction(
    db,
    prediction: Prediction,
    outcome: bool,
    evidence: str,
) -> None:
    """Resolve a prediction with the given outcome."""
    today = date.today()
    now = datetime.utcnow()

    prediction.status = "RESOLVED_TRUE" if outcome else "RESOLVED_FALSE"
    prediction.resolved_date = today
    prediction.resolved_outcome = outcome

    # Calculate Brier score
    score = brier_score(prediction.current_confidence, outcome)
    prediction.brier_score = score

    # Store post-mortem
    prediction.post_mortem = {
        "resolution_method": "auto_resolver",
        "evidence": evidence,
        "resolved_at": now.isoformat(),
        "final_confidence": prediction.current_confidence,
        "brier_score": score,
    }

    # Add confidence trail entry
    trail = ConfidenceTrail(
        prediction_id=prediction.id,
        date=now,
        value=prediction.current_confidence,
        trigger="auto_resolution",
        reasoning=(
            f"Auto-resolved as {'TRUE' if outcome else 'FALSE'}. "
            f"Evidence: {evidence[:300]}. "
            f"Brier score: {score:.4f}"
        ),
    )
    db.add(trail)

    logger.info(
        f"Resolved {prediction.id} as {'TRUE' if outcome else 'FALSE'}: "
        f"confidence={prediction.current_confidence:.2f}, brier={score:.4f}"
    )


async def run_auto_resolution() -> Dict[str, Any]:
    """
    Main entry point: check all active predictions that should be evaluated.
    Returns stats about resolutions.
    """
    stats = {
        "checked": 0,
        "resolved_true": 0,
        "resolved_false": 0,
        "undetermined": 0,
        "errors": 0,
        "skipped": 0,
    }

    try:
        with get_db_session() as db:
            active = (
                db.query(Prediction)
                .filter(Prediction.status == "ACTIVE")
                .all()
            )

            candidates = [p for p in active if _should_check(p)]
            stats["skipped"] = len(active) - len(candidates)

            logger.info(
                f"Auto-resolution: {len(candidates)} candidates "
                f"from {len(active)} active predictions"
            )

            for prediction in candidates:
                try:
                    result = await _check_prediction(prediction)
                    stats["checked"] += 1

                    if not result:
                        stats["errors"] += 1
                        continue

                    outcome = result.get("outcome", "UNDETERMINED")
                    confidence = result.get("confidence_in_judgment", 0)
                    evidence = result.get("evidence", "")

                    # Only resolve if the LLM is confident in its judgment
                    if outcome == "TRUE" and confidence >= 0.7:
                        _resolve_prediction(db, prediction, True, evidence)
                        stats["resolved_true"] += 1
                    elif outcome == "FALSE" and confidence >= 0.7:
                        _resolve_prediction(db, prediction, False, evidence)
                        stats["resolved_false"] += 1
                    else:
                        stats["undetermined"] += 1

                except Exception as e:
                    logger.error(f"Error checking {prediction.id}: {e}")
                    logger.debug(traceback.format_exc())
                    stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Auto-resolution failed: {e}")
        stats["errors"] += 1

    logger.info(
        f"Auto-resolution complete: checked={stats['checked']}, "
        f"true={stats['resolved_true']}, false={stats['resolved_false']}, "
        f"undetermined={stats['undetermined']}, errors={stats['errors']}"
    )

    return stats
