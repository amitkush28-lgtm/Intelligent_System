"""
Devil's Advocate — Uses GPT-4o (different model bias = genuine adversarial tension)
to challenge predictions when trigger conditions are met.

Trigger conditions (from development brief):
1. Confidence moved >5pp
2. Confidence >60%
3. Agrees with consensus
4. Invokes historical analogy
5. Single data point driving large shift

The different model (GPT-4o vs Claude) creates genuine adversarial tension because
each model has different training data biases and reasoning patterns.
"""

import json
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional

from shared.llm_client import call_gpt4o, parse_structured_json
from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


DEVIL_ADVOCATE_SYSTEM_PROMPT = """You are a Devil's Advocate in a multi-agent intelligence system.

Your job is to CHALLENGE the primary analyst's prediction. You are not trying to be right — you are trying to find weaknesses in the analysis. You serve the system by preventing overconfidence, groupthink, and blind spots.

## YOUR MANDATE
1. STEELMAN the opposing view: present the strongest possible case AGAINST the prediction
2. Identify HIDDEN ASSUMPTIONS the analyst is making
3. Check for ANCHORING to recent events or historical analogies that may not apply
4. Look for MISSING EVIDENCE — what data would you need to see to support this confidence level?
5. Check BASE RATE NEGLECT — is the analyst ignoring how rarely this type of event occurs?
6. Identify INFORMATION CASCADE risk — is this prediction driven by a single source?
7. Consider SECOND-ORDER EFFECTS the analyst may have missed

## RULES
- Be specific and constructive, not generically contrarian
- Cite specific weaknesses in the evidence chain
- Propose concrete alternative scenarios
- Suggest what evidence would change your mind
- Rate the severity of each challenge (LOW/MEDIUM/HIGH/CRITICAL)

## OUTPUT FORMAT
Respond with ONLY valid JSON:
{
    "challenges": [
        {
            "type": "hidden_assumption|base_rate_neglect|anchoring|missing_evidence|single_source|alternative_scenario|second_order",
            "severity": "LOW|MEDIUM|HIGH|CRITICAL",
            "challenge": "specific challenge text",
            "evidence_needed": "what evidence would resolve this challenge"
        }
    ],
    "alternative_scenario": "the strongest alternative scenario the analyst hasn't considered",
    "recommended_confidence_adjustment": -5,
    "overall_assessment": "brief assessment of the prediction's robustness",
    "strongest_weakness": "the single most important weakness in the analysis"
}

The recommended_confidence_adjustment is in percentage points (e.g., -5 means reduce by 5pp, +3 means the analysis is actually underconfident by 3pp). Range: -30 to +10.
"""


async def run_devil_advocate(
    trigger: Dict[str, Any],
    agent_analysis_summary: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Run a devil's advocate challenge against a prediction.

    Args:
        trigger: from check_devil_advocate_trigger(), contains prediction data and reasons
        agent_analysis_summary: the primary agent's full analysis text

    Returns:
        Dict with challenge results, or None if GPT-4o call fails
    """
    agent = trigger.get("agent", "unknown")
    trigger_reasons = trigger.get("trigger_reasons", [])

    logger.info(
        f"Running devil's advocate for {agent} | "
        f"Triggers: {trigger_reasons}"
    )

    user_message = _build_challenge_message(trigger, agent_analysis_summary)

    try:
        raw_response = await call_gpt4o(
            system_prompt=DEVIL_ADVOCATE_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=2048,
            temperature=0.4,
        )
    except Exception as e:
        logger.warning(f"GPT-4o devil's advocate call failed: {e}")
        logger.debug(traceback.format_exc())
        return None

    parsed = parse_structured_json(raw_response)
    if not parsed:
        logger.warning("Failed to parse devil's advocate JSON response")
        return {
            "challenges": [],
            "raw_text": raw_response[:1000],
            "recommended_confidence_adjustment": 0,
            "overall_assessment": "Challenge produced but unparseable.",
        }

    # Validate the adjustment is within bounds
    adj = parsed.get("recommended_confidence_adjustment", 0)
    try:
        adj = float(adj)
        adj = max(-30, min(10, adj))
    except (ValueError, TypeError):
        adj = 0
    parsed["recommended_confidence_adjustment"] = adj

    # Validate challenges
    challenges = parsed.get("challenges", [])
    if isinstance(challenges, list):
        validated = []
        for c in challenges:
            if isinstance(c, dict) and c.get("challenge"):
                # Ensure severity is valid
                sev = c.get("severity", "MEDIUM")
                if sev not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                    sev = "MEDIUM"
                c["severity"] = sev
                validated.append(c)
        parsed["challenges"] = validated

    logger.info(
        f"Devil's advocate complete: {len(parsed.get('challenges', []))} challenges, "
        f"adjustment: {adj:+.0f}pp"
    )

    return parsed


def _build_challenge_message(
    trigger: Dict[str, Any],
    agent_analysis_summary: str,
) -> str:
    """Build the user message for the devil's advocate."""
    trigger_type = trigger.get("type", "unknown")
    agent = trigger.get("agent", "unknown")
    reasons = trigger.get("trigger_reasons", [])

    # Extract prediction details
    if trigger_type == "new_prediction":
        pred_data = trigger.get("prediction_data", {})
        claim = pred_data.get("claim", "N/A")
        confidence = pred_data.get("confidence", 0)
        reasoning = pred_data.get("reasoning", "No reasoning provided")
        base_rate = pred_data.get("base_rate", "not specified")
        key_triggers = pred_data.get("key_triggers", [])

        msg = f"""CHALLENGE THIS NEW PREDICTION from the {agent.upper()} agent:

CLAIM: {claim}
CONFIDENCE: {confidence:.0%}
REASONING: {reasoning}
BASE RATE: {base_rate}
KEY TRIGGERS: {json.dumps(key_triggers)}

TRIGGER REASONS FOR THIS CHALLENGE: {', '.join(reasons)}
"""

    elif trigger_type == "confidence_shift":
        pred_id = trigger.get("prediction_id", "???")
        old_conf = trigger.get("old_confidence", 0)
        new_conf = trigger.get("new_confidence", 0)
        movement = trigger.get("movement_pp", 0)

        msg = f"""CHALLENGE THIS CONFIDENCE SHIFT from the {agent.upper()} agent:

PREDICTION ID: {pred_id}
OLD CONFIDENCE: {old_conf:.0%}
NEW CONFIDENCE: {new_conf:.0%}
MOVEMENT: {movement:.0f}pp

TRIGGER REASONS FOR THIS CHALLENGE: {', '.join(reasons)}
"""
    else:
        msg = f"""CHALLENGE from the {agent.upper()} agent:
TRIGGER REASONS: {', '.join(reasons)}
"""

    if agent_analysis_summary:
        msg += f"""
## PRIMARY AGENT'S FULL ANALYSIS
{agent_analysis_summary[:3000]}
"""

    msg += """
Produce your devil's advocate challenge. Be specific, cite evidence gaps, and propose the strongest alternative scenario. Respond with ONLY valid JSON."""

    return msg


def compute_devil_impact(
    original_confidence: float,
    devil_result: Dict[str, Any],
) -> float:
    """
    Compute the actual impact of the devil's advocate on prediction confidence.

    Returns the confidence adjustment in percentage points (can be negative or slightly positive).
    The adjustment is moderated — we don't fully apply the devil's recommendation.
    """
    adj = devil_result.get("recommended_confidence_adjustment", 0)
    try:
        adj = float(adj)
    except (ValueError, TypeError):
        return 0.0

    challenges = devil_result.get("challenges", [])
    critical_count = sum(1 for c in challenges if c.get("severity") == "CRITICAL")
    high_count = sum(1 for c in challenges if c.get("severity") == "HIGH")

    # Scale adjustment by severity of challenges
    severity_weight = 1.0
    if critical_count >= 2:
        severity_weight = 1.5  # Amplify for critical challenges
    elif critical_count == 1 or high_count >= 2:
        severity_weight = 1.2
    elif not challenges or all(c.get("severity") == "LOW" for c in challenges):
        severity_weight = 0.5  # Dampen for only low-severity challenges

    # Apply moderation — don't fully trust devil's recommendation
    MODERATION_FACTOR = 0.6
    moderated = adj * MODERATION_FACTOR * severity_weight

    # Cap the impact
    moderated = max(-20, min(5, moderated))

    return round(moderated, 1)


def format_debate_rounds(
    agent_analysis_summary: str,
    devil_result: Dict[str, Any],
    impact_pp: float,
) -> List[Dict[str, Any]]:
    """
    Format the debate into rounds for storage in the Debate model.

    Returns list of round dicts for the `rounds` JSONB column.
    """
    rounds = [
        {
            "round": 1,
            "advocate": {
                "agent": "primary",
                "text": agent_analysis_summary[:2000],
            },
            "devil": {
                "agent": "gpt4o",
                "challenges": devil_result.get("challenges", []),
                "alternative_scenario": devil_result.get("alternative_scenario", ""),
                "overall_assessment": devil_result.get("overall_assessment", ""),
                "strongest_weakness": devil_result.get("strongest_weakness", ""),
                "recommended_adjustment": devil_result.get(
                    "recommended_confidence_adjustment", 0
                ),
            },
            "resolution": {
                "applied_adjustment_pp": impact_pp,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }
    ]

    return rounds
