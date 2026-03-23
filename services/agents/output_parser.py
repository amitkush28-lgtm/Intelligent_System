"""
Output Parser — Parses structured JSON from LLM agent responses.

Extracts predictions, confidence updates, analytical notes, and debate triggers
from the structured JSON output of each agent's analysis.

Expected LLM output format:
{
    "predictions": [
        {
            "claim": "...",
            "time_condition_type": "range",
            "time_condition_start": "2026-04-01",
            "time_condition_end": "2026-06-30",
            "confidence": 0.65,
            "resolution_criteria": "...",
            "reasoning": "...",
            "base_rate": "...",
            "key_triggers": ["...", "..."],
            "sub_predictions": [
                {
                    "claim": "...",
                    "time_condition_type": "point",
                    "time_condition_date": "2026-04-15",
                    "confidence": 0.70,
                    "resolution_criteria": "..."
                }
            ]
        }
    ],
    "prediction_updates": [
        {
            "prediction_id": "PRED-2026-XXXX",
            "new_confidence": 0.72,
            "reasoning": "...",
            "trigger": "..."
        }
    ],
    "notes": [
        {
            "prediction_id": "PRED-2026-XXXX" | null,
            "type": "observation|key_signal|counter_signal|analysis",
            "text": "..."
        }
    ],
    "summary": "Brief analysis summary"
}
"""

import logging
from datetime import date, datetime
from typing import Dict, Any, List, Optional, Tuple

from shared.llm_client import parse_structured_json

logger = logging.getLogger(__name__)


def parse_agent_output(
    raw_response: str,
    agent_name: str,
) -> Dict[str, Any]:
    """
    Parse structured JSON from an agent's LLM response.

    Returns dict with:
    - new_predictions: list of new prediction dicts
    - prediction_updates: list of confidence update dicts
    - notes: list of analytical note dicts
    - summary: brief text summary
    - raw_valid: whether JSON parsing succeeded
    """
    result = {
        "new_predictions": [],
        "prediction_updates": [],
        "notes": [],
        "summary": "",
        "raw_valid": False,
    }

    parsed = parse_structured_json(raw_response)
    if not parsed:
        logger.warning(f"[{agent_name}] Failed to parse structured JSON from response")
        # Try to salvage what we can from plain text
        result["summary"] = raw_response[:500]
        return result

    result["raw_valid"] = True

    # Extract new predictions
    raw_preds = parsed.get("predictions", [])
    if isinstance(raw_preds, list):
        for p in raw_preds:
            pred = _validate_prediction(p, agent_name)
            if pred:
                result["new_predictions"].append(pred)

    # Extract prediction updates (confidence changes)
    raw_updates = parsed.get("prediction_updates", [])
    if isinstance(raw_updates, list):
        for u in raw_updates:
            update = _validate_update(u, agent_name)
            if update:
                result["prediction_updates"].append(update)

    # Extract analytical notes
    raw_notes = parsed.get("notes", [])
    if isinstance(raw_notes, list):
        for n in raw_notes:
            note = _validate_note(n)
            if note:
                result["notes"].append(note)

    # Extract summary
    result["summary"] = parsed.get("summary", "")

    logger.info(
        f"[{agent_name}] Parsed: {len(result['new_predictions'])} new predictions, "
        f"{len(result['prediction_updates'])} updates, {len(result['notes'])} notes"
    )

    return result


def _validate_prediction(raw: Any, agent_name: str) -> Optional[Dict[str, Any]]:
    """Validate and normalize a single prediction from LLM output."""
    if not isinstance(raw, dict):
        return None

    claim = raw.get("claim", "").strip()
    if not claim or len(claim) < 10:
        logger.debug(f"[{agent_name}] Skipping prediction with short/empty claim")
        return None

    confidence = raw.get("confidence", 0.5)
    try:
        confidence = float(confidence)
        # Handle 0-100 scale
        if confidence > 1.0:
            confidence = confidence / 100.0
        confidence = max(0.01, min(0.99, confidence))
    except (ValueError, TypeError):
        confidence = 0.5

    resolution_criteria = raw.get("resolution_criteria", "").strip()
    if not resolution_criteria:
        resolution_criteria = f"Verify whether: {claim}"

    # Parse time conditions
    tc_type = raw.get("time_condition_type", "range")
    if tc_type not in ("point", "range", "ongoing"):
        tc_type = "range"

    tc_date = _parse_date(raw.get("time_condition_date"))
    tc_start = _parse_date(raw.get("time_condition_start"))
    tc_end = _parse_date(raw.get("time_condition_end"))

    # If no dates provided, set reasonable defaults
    if tc_type == "range" and not tc_end:
        # Default: 90 days from now
        from datetime import timedelta
        tc_end = (date.today() + timedelta(days=90)).isoformat()
        if not tc_start:
            tc_start = date.today().isoformat()

    if tc_type == "point" and not tc_date:
        from datetime import timedelta
        tc_date = (date.today() + timedelta(days=30)).isoformat()

    pred = {
        "claim": claim,
        "confidence": confidence,
        "time_condition_type": tc_type,
        "time_condition_date": tc_date,
        "time_condition_start": tc_start,
        "time_condition_end": tc_end,
        "resolution_criteria": resolution_criteria,
        "reasoning": raw.get("reasoning", ""),
        "base_rate": raw.get("base_rate", "no reference class"),
        "key_triggers": raw.get("key_triggers", []),
        "sub_predictions": [],
    }

    # Parse sub-predictions
    raw_subs = raw.get("sub_predictions", [])
    if isinstance(raw_subs, list):
        for s in raw_subs:
            sub = _validate_prediction(s, agent_name)
            if sub:
                pred["sub_predictions"].append(sub)

    return pred


def _validate_update(raw: Any, agent_name: str) -> Optional[Dict[str, Any]]:
    """Validate a prediction confidence update."""
    if not isinstance(raw, dict):
        return None

    pred_id = raw.get("prediction_id", "").strip()
    if not pred_id:
        return None

    new_conf = raw.get("new_confidence")
    try:
        new_conf = float(new_conf)
        if new_conf > 1.0:
            new_conf = new_conf / 100.0
        new_conf = max(0.01, min(0.99, new_conf))
    except (ValueError, TypeError):
        return None

    reasoning = raw.get("reasoning", "").strip()
    trigger = raw.get("trigger", "agent analysis cycle").strip()

    return {
        "prediction_id": pred_id,
        "new_confidence": new_conf,
        "reasoning": reasoning or f"Updated by {agent_name} analysis",
        "trigger": trigger,
    }


def _validate_note(raw: Any) -> Optional[Dict[str, Any]]:
    """Validate an analytical note."""
    if not isinstance(raw, dict):
        return None

    text = raw.get("text", "").strip()
    if not text:
        return None

    note_type = raw.get("type", "observation")
    if note_type not in ("observation", "key_signal", "counter_signal", "analysis"):
        note_type = "observation"

    return {
        "prediction_id": raw.get("prediction_id"),
        "type": note_type,
        "text": text,
    }


def _parse_date(val: Any) -> Optional[str]:
    """Parse a date value from LLM output into ISO format string."""
    if not val:
        return None

    if isinstance(val, date):
        return val.isoformat()

    if isinstance(val, str):
        val = val.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(val, fmt).date().isoformat()
            except ValueError:
                continue
        # Try just the year-month-day portion
        try:
            return val[:10]
        except Exception:
            pass

    return None


def check_devil_advocate_trigger(
    agent_name: str,
    parsed_output: Dict[str, Any],
    existing_predictions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Check if any predictions should trigger devil's advocate challenge.

    Trigger conditions (from development brief):
    1. Confidence moved >5pp
    2. Confidence >60%
    3. Agrees with consensus (multiple agents same direction)
    4. Invokes historical analogy
    5. Single data point driving large shift
    """
    triggers = []

    # Check new predictions with high confidence
    for pred in parsed_output.get("new_predictions", []):
        reasons = []
        conf = pred.get("confidence", 0)

        if conf > 0.80:
            reasons.append(f"very_high_confidence ({conf:.0%})")
        elif conf > 0.60:
            reasons.append(f"high_confidence ({conf:.0%})")

        reasoning = pred.get("reasoning", "").lower()
        analogy_keywords = ["historically", "precedent", "similar to", "just like", "analogous", "reminiscent"]
        if any(kw in reasoning for kw in analogy_keywords):
            reasons.append("invokes_historical_analogy")

        if reasons:
            triggers.append({
                "type": "new_prediction",
                "prediction_data": pred,
                "trigger_reasons": reasons,
                "agent": agent_name,
            })

    # Check prediction updates with large confidence movements
    for update in parsed_output.get("prediction_updates", []):
        pred_id = update.get("prediction_id", "")
        new_conf = update.get("new_confidence", 0)

        # Find old confidence
        old_conf = None
        for ep in existing_predictions:
            if ep.get("id") == pred_id:
                old_conf = ep.get("current_confidence")
                break

        if old_conf is not None:
            movement = abs(new_conf - old_conf)
            if movement > 0.05:
                triggers.append({
                    "type": "confidence_shift",
                    "prediction_id": pred_id,
                    "old_confidence": old_conf,
                    "new_confidence": new_conf,
                    "movement_pp": movement * 100,
                    "trigger_reasons": [f"confidence_moved_{movement*100:.0f}pp"],
                    "agent": agent_name,
                })

    return triggers
