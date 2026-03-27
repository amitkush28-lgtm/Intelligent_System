"""
Reality Check Agent — Web search validation with agent feedback loop.

Runs AFTER all specialist agents but BEFORE the Master Strategist.
For each new prediction:
1. Searches the web for current facts relevant to the prediction
2. If the prediction uses stale/wrong data, sends a correction back
   to the ORIGINAL agent with the real data
3. The original agent then reassesses and produces a corrected prediction

This is the system's "grounding" mechanism — ensures all predictions
reference current reality, not stale training data.
"""

import logging
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional

from shared.llm_client import call_claude_with_web_search, call_claude_sonnet, parse_structured_json
from shared.models import Prediction, ConfidenceTrail, Note

logger = logging.getLogger(__name__)

REALITY_CHECK_SYSTEM_PROMPT = """You are the REALITY CHECK agent in a multi-agent intelligence prediction system. Your job is to validate predictions against CURRENT real-world data using web search.

For each prediction, you must:
1. Search the web for the CURRENT state of whatever the prediction references (prices, rates, political situations, military deployments, etc.)
2. Check if the prediction's numbers match reality
3. Check if the prediction's assumptions are still valid
4. Determine if the prediction needs correction

You MUST respond with ONLY valid JSON:
{
    "checks": [
        {
            "prediction_id": "PRED-2026-XXXX",
            "status": "VALID" | "NEEDS_CORRECTION",
            "current_facts": "What the web search revealed — be SPECIFIC with numbers, dates, names (3-5 sentences)",
            "issue": "Description of the problem (null if VALID)",
            "correction_brief": "Specific data the original agent needs to know to fix their prediction (null if VALID)"
        }
    ]
}

Rules:
- VALID: The prediction is grounded in current reality. No changes needed.
- NEEDS_CORRECTION: The prediction uses wrong prices, outdated facts, or stale assumptions. Provide specific current data.
- Be VERY specific in current_facts — include actual numbers, dates, names from your web search.
- correction_brief should be a concise factual statement like "Gold is currently trading at $4,487/oz, not ~$2,400. USD/JPY is at 159.67, not ~145."
"""

REASSESS_SYSTEM_PROMPT = """You are the {agent_name} specialist in a multi-agent intelligence system. 

The Reality Check agent found that one of your predictions is based on INCORRECT or OUTDATED data. You must now reassess this prediction using the CORRECT current data provided below.

You have two options:
1. REVISE the prediction with corrected numbers/assumptions and a new confidence level
2. WITHDRAW the prediction if the corrected data makes it no longer meaningful

Respond with ONLY valid JSON:
{{
    "action": "REVISE" | "WITHDRAW",
    "revised_claim": "The corrected prediction claim (null if WITHDRAW)",
    "revised_confidence": 0.0 to 1.0 (null if WITHDRAW),
    "revised_resolution_criteria": "Updated resolution criteria (null if WITHDRAW)",
    "reasoning": "DETAILED explanation of how the corrected data changes your analysis. If revising, explain your new prediction. If withdrawing, explain why the prediction is no longer meaningful.",
    "key_triggers": ["event that would change this prediction"]
}}
"""


async def run_reality_check(
    new_predictions: List[Dict[str, Any]],
    db,
) -> Dict[str, Any]:
    """
    Run reality checks on all new predictions, then feed corrections
    back to original agents for reassessment.
    """
    stats = {
        "checked": 0,
        "valid": 0,
        "needs_correction": 0,
        "reassessed": 0,
        "revised": 0,
        "withdrawn": 0,
        "errors": 0,
    }

    if not new_predictions:
        logger.info("Reality check: no new predictions to validate")
        return stats

    # Step 1: Check all predictions against reality
    logger.info(f"Reality check: validating {len(new_predictions)} new predictions")
    
    batches = [new_predictions[i:i+5] for i in range(0, len(new_predictions), 5)]
    corrections_needed = []

    for batch in batches:
        try:
            results = await _check_batch(batch)
            for check in results:
                stats["checked"] += 1
                if check.get("status") == "VALID":
                    stats["valid"] += 1
                else:
                    stats["needs_correction"] += 1
                    # Find the original prediction data
                    pred_id = check.get("prediction_id", "")
                    original = next((p for p in new_predictions if p.get("pred_id") == pred_id), None)
                    if original:
                        corrections_needed.append({
                            "check": check,
                            "original": original,
                        })
        except Exception as e:
            logger.error(f"Reality check batch failed: {e}")
            stats["errors"] += len(batch)

    # Step 2: Feed corrections back to original agents for reassessment
    for item in corrections_needed:
        try:
            check = item["check"]
            original = item["original"]
            pred_id = check["prediction_id"]
            agent_name = original.get("agent", "unknown")

            logger.info(
                f"Reality check correction for {pred_id} ({agent_name}): "
                f"{check.get('issue', '')[:100]}"
            )

            # Call the original agent with the correction
            reassessment = await _reassess_prediction(
                agent_name=agent_name,
                original_claim=original.get("claim", ""),
                original_confidence=original.get("confidence", 0.5),
                original_resolution=original.get("resolution_criteria", ""),
                correction_brief=check.get("correction_brief", ""),
                current_facts=check.get("current_facts", ""),
            )

            stats["reassessed"] += 1

            if not reassessment:
                stats["errors"] += 1
                continue

            action = reassessment.get("action", "REVISE")

            if action == "WITHDRAW":
                # Mark prediction as superseded
                pred = db.query(Prediction).filter(Prediction.id == pred_id).first()
                if pred:
                    pred.status = "SUPERSEDED"
                    trail = ConfidenceTrail(
                        prediction_id=pred_id,
                        date=datetime.utcnow(),
                        value=pred.current_confidence,
                        trigger="reality_check_withdrawal",
                        reasoning=(
                            f"Prediction withdrawn after reality check. "
                            f"Issue: {check.get('issue', '')} "
                            f"Current facts: {check.get('current_facts', '')}"
                        ),
                    )
                    db.add(trail)
                    stats["withdrawn"] += 1
                    logger.info(f"Withdrawn {pred_id} after reality check")

            elif action == "REVISE":
                # Update the prediction with corrected data
                pred = db.query(Prediction).filter(Prediction.id == pred_id).first()
                if pred:
                    old_claim = pred.claim
                    old_conf = pred.current_confidence

                    revised_claim = reassessment.get("revised_claim", pred.claim)
                    revised_conf = reassessment.get("revised_confidence", pred.current_confidence)
                    revised_resolution = reassessment.get("revised_resolution_criteria", pred.resolution_criteria)
                    reasoning = reassessment.get("reasoning", "")

                    # Update prediction fields
                    pred.claim = revised_claim
                    pred.current_confidence = max(0.01, min(0.99, revised_conf))
                    pred.resolution_criteria = revised_resolution

                    # Add confidence trail showing the correction
                    trail = ConfidenceTrail(
                        prediction_id=pred_id,
                        date=datetime.utcnow(),
                        value=pred.current_confidence,
                        trigger="reality_check_revision",
                        reasoning=(
                            f"Prediction revised after reality check. "
                            f"Original claim: {old_claim[:200]}. "
                            f"Correction: {check.get('correction_brief', '')}. "
                            f"Agent's reassessment: {reasoning[:300]}"
                        ),
                    )
                    db.add(trail)

                    # Add note documenting the correction
                    note = Note(
                        prediction_id=pred_id,
                        type="counter_signal",
                        text=(
                            f"[Reality Check Correction] Original claim used stale data. "
                            f"{check.get('correction_brief', '')} "
                            f"Prediction revised from \"{old_claim[:150]}\" (at {old_conf:.0%}) "
                            f"to \"{revised_claim[:150]}\" (at {pred.current_confidence:.0%})."
                        ),
                    )
                    db.add(note)

                    stats["revised"] += 1
                    logger.info(
                        f"Revised {pred_id}: \"{old_claim[:60]}\" → \"{revised_claim[:60]}\" "
                        f"({old_conf:.0%} → {pred.current_confidence:.0%})"
                    )

        except Exception as e:
            logger.error(f"Reassessment failed for {item.get('check', {}).get('prediction_id', '?')}: {e}")
            logger.debug(traceback.format_exc())
            stats["errors"] += 1

    db.flush()

    logger.info(
        f"Reality check complete: checked={stats['checked']}, valid={stats['valid']}, "
        f"corrections={stats['needs_correction']}, revised={stats['revised']}, "
        f"withdrawn={stats['withdrawn']}, errors={stats['errors']}"
    )

    return stats


async def _check_batch(predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Check a batch of predictions against reality via web search."""
    pred_descriptions = []
    for p in predictions:
        pred_id = p.get("pred_id", "unknown")
        claim = p.get("claim", "")
        confidence = p.get("confidence", 0.5)
        resolution = p.get("resolution_criteria", "")
        agent = p.get("agent", "")

        pred_descriptions.append(
            f"[{pred_id}] ({agent}, {confidence:.0%} confidence)\n"
            f"  Claim: {claim}\n"
            f"  Resolution: {resolution}"
        )

    user_message = f"""Check these {len(predictions)} predictions against current reality. Search the web for each one.

{chr(10).join(pred_descriptions)}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

For EACH prediction, search the web to verify. Pay special attention to:
- Are price levels correct? (gold, oil, forex, indices — search for current prices)
- Has the predicted event already happened?
- Are political/geopolitical assumptions still valid?
- Do the timeframes make sense?

Be SPECIFIC with numbers in your current_facts field.

Respond with ONLY valid JSON."""

    try:
        response = await call_claude_with_web_search(
            system_prompt=REALITY_CHECK_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=4096,
        )

        result = parse_structured_json(response)
        if result and "checks" in result:
            return result["checks"]

        logger.warning("Reality check response was not clean JSON")
        return []

    except Exception as e:
        logger.error(f"Reality check LLM call failed: {e}")
        return []


async def _reassess_prediction(
    agent_name: str,
    original_claim: str,
    original_confidence: float,
    original_resolution: str,
    correction_brief: str,
    current_facts: str,
) -> Optional[Dict[str, Any]]:
    """
    Send a correction back to the original agent and get a reassessment.
    This is the key feedback loop — the agent sees real data and revises.
    """
    system_prompt = REASSESS_SYSTEM_PROMPT.format(agent_name=agent_name.upper())

    user_message = f"""Your prediction has been flagged by the Reality Check agent.

YOUR ORIGINAL PREDICTION:
  Claim: {original_claim}
  Confidence: {original_confidence:.0%}
  Resolution: {original_resolution}

REALITY CHECK CORRECTION:
  {correction_brief}

CURRENT FACTS (from web search):
  {current_facts}

Based on these CORRECTED facts, reassess your prediction. Either:
1. REVISE it with accurate numbers and updated reasoning
2. WITHDRAW it if the corrected data makes it no longer meaningful

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

Respond with ONLY valid JSON."""

    try:
        response = await call_claude_sonnet(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=4096,
            temperature=0.3,
        )

        result = parse_structured_json(response)
        return result if result else None

    except Exception as e:
        logger.error(f"Reassessment call failed for {agent_name}: {e}")
        return None
