"""
Devil's Advocate — Uses Gemini (different model bias = genuine adversarial tension)
to challenge predictions when trigger conditions are met.

Upgraded to specifically target cognitive biases:
- Confirmation bias
- Recency bias
- Anchoring
- Base rate neglect
- Historical analogy abuse
- Consensus herding
- Geographic bias
- Narrative bias

The different model (Gemini vs Claude) creates genuine adversarial tension because
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


DEVIL_ADVOCATE_SYSTEM_PROMPT = """You are a Devil's Advocate in a multi-agent intelligence prediction system.

Your job is to CHALLENGE the primary analyst's prediction by specifically hunting for cognitive biases and analytical weaknesses. You are not trying to be right — you are trying to PREVENT OVERCONFIDENCE, GROUPTHINK, and BLIND SPOTS.

## YOUR MANDATE — HUNT FOR THESE SPECIFIC BIASES

1. CONFIRMATION BIAS: Is the analyst only citing evidence that supports their conclusion? What contradicting evidence are they ignoring or dismissing?

2. RECENCY BIAS: Is this prediction over-weighted by the most recent events? Would the analyst have made the same prediction 3 months ago with different recent data?

3. ANCHORING: Is the analyst anchored to a specific number, scenario, or historical reference point? What if that anchor is wrong?

4. BASE RATE NEGLECT: How often does this type of event ACTUALLY occur historically? Is the analyst predicting something far more common or rare than base rates suggest?

5. HISTORICAL ANALOGY ABUSE: Is the analyst drawing a parallel to a historical event? How is the current situation DIFFERENT from that analogy? (Every historical analogy breaks down on specifics.)

6. CONSENSUS HERDING: Does this prediction agree with what most analysts/markets already believe? If so, where's the edge? The market has already priced consensus views.

7. GEOGRAPHIC/CULTURAL BIAS: Is the analyst applying Western/American analytical frameworks to non-Western actors? Are deep motivational forces being ignored?

8. NARRATIVE BIAS: Is the analyst fitting events into a pre-existing narrative rather than letting the data speak? Would the evidence support a different narrative equally well?

9. SINGLE-SOURCE DEPENDENCY: Is this prediction resting heavily on one data point, one source, or one event? How robust is it to that source being wrong?

10. TIMING OVERCONFIDENCE: Even if the direction is right, is the timeline realistic? Most geopolitical and technology predictions are directionally correct but far too early or late.

## RULES
- Be SPECIFIC and CONSTRUCTIVE, not generically contrarian
- For each bias identified, cite the SPECIFIC weakness in the evidence chain
- Propose at least one CONCRETE alternative scenario the analyst hasn't considered
- Suggest what EVIDENCE would resolve each challenge
- Rate each challenge severity: LOW | MEDIUM | HIGH | CRITICAL
- Be willing to say the analysis is SOLID when it genuinely is (adjust confidence UP if warranted)

## OUTPUT FORMAT
Respond with ONLY valid JSON:
{
    "challenges": [
        {
            "type": "confirmation_bias|recency_bias|anchoring|base_rate_neglect|historical_analogy|consensus_herding|geographic_bias|narrative_bias|single_source|timing_overconfidence|missing_evidence|alternative_scenario|second_order",
            "severity": "LOW|MEDIUM|HIGH|CRITICAL",
            "challenge": "specific challenge text explaining the weakness",
            "evidence_needed": "what evidence would resolve this challenge"
        }
    ],
    "alternative_scenario": "the strongest alternative scenario the analyst hasn't considered — make it specific and plausible, not just generically 'the opposite might happen'",
    "recommended_confidence_adjustment": -5,
    "overall_assessment": "brief assessment of the prediction's robustness — is this a solid prediction with minor issues, or fundamentally flawed?",
    "strongest_weakness": "the single most important weakness — if the analyst could only address ONE thing, what should it be?"
}

The recommended_confidence_adjustment is in percentage points (e.g., -5 means reduce by 5pp, +3 means the analysis is actually stronger than stated). Range: -30 to +10.
"""


async def run_devil_advocate(
    trigger: Dict[str, Any],
    agent_analysis_summary: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Run a devil's advocate challenge against a prediction.
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
            max_tokens=3072,
            temperature=0.4,
        )
    except Exception as e:
        logger.warning(f"Gemini devil's advocate call failed: {e}")
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

    # Validate the adjustment
    adj = parsed.get("recommended_confidence_adjustment", 0)
    try:
        adj = float(adj)
        adj = max(-30, min(10, adj))
    except (ValueError, TypeError):
        adj = 0
    parsed["recommended_confidence_adjustment"] = adj

    # Validate challenges
    valid_types = {
        "confirmation_bias", "recency_bias", "anchoring", "base_rate_neglect",
        "historical_analogy", "consensus_herding", "geographic_bias", "narrative_bias",
        "single_source", "timing_overconfidence", "missing_evidence",
        "alternative_scenario", "second_order", "hidden_assumption",
    }
    challenges = parsed.get("challenges", [])
    if isinstance(challenges, list):
        validated = []
        for c in challenges:
            if isinstance(c, dict) and c.get("challenge"):
                sev = c.get("severity", "MEDIUM")
                if sev not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                    sev = "MEDIUM"
                c["severity"] = sev
                # Normalize type
                c_type = c.get("type", "missing_evidence")
                if c_type not in valid_types:
                    c_type = "missing_evidence"
                c["type"] = c_type
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

    if trigger_type == "new_prediction":
        pred_data = trigger.get("prediction_data", {})
        claim = pred_data.get("claim", "N/A")
        confidence = pred_data.get("confidence", 0)
        reasoning = pred_data.get("reasoning", "No reasoning provided")
        base_rate = pred_data.get("base_rate", "not specified")
        key_triggers = pred_data.get("key_triggers", [])
        so_what = pred_data.get("so_what", "Not specified")
        category = pred_data.get("category", "N/A")

        msg = f"""CHALLENGE THIS NEW PREDICTION from the {agent.upper()} agent:

CLAIM: {claim}
CONFIDENCE: {confidence:.0%}
CATEGORY: {category}
REASONING: {reasoning}
BASE RATE: {base_rate}
KEY TRIGGERS: {json.dumps(key_triggers)}
SO WHAT (actionable guidance): {so_what}

TRIGGER REASONS FOR THIS CHALLENGE: {', '.join(reasons)}

SPECIFIC BIAS CHECKS TO PERFORM:
1. Does the confidence level match the base rate? (base_rate_neglect check)
2. Is the reasoning over-reliant on recent events? (recency_bias check)
3. Is there a historical analogy being used? If so, how does today differ? (historical_analogy check)
4. Is this what "everyone" already thinks? (consensus_herding check)
5. What's the strongest evidence AGAINST this prediction? (confirmation_bias check)
6. Is the timeline realistic? (timing_overconfidence check)
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

TRIGGER REASONS: {', '.join(reasons)}

SPECIFIC CHECKS:
1. Is this shift driven by a SINGLE new data point? (single_source check)
2. Is the analyst ANCHORED to the previous confidence? (anchoring check)
3. Is the shift justified by the evidence weight, or is it recency bias?
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
Produce your devil's advocate challenge. Hunt specifically for the cognitive biases listed above. Be constructive — identify the specific weakness and suggest how to resolve it. Respond with ONLY valid JSON."""

    return msg


def compute_devil_impact(
    original_confidence: float,
    devil_result: Dict[str, Any],
) -> float:
    """
    Compute the actual impact of the devil's advocate on prediction confidence.
    Returns confidence adjustment in percentage points.
    """
    adj = devil_result.get("recommended_confidence_adjustment", 0)
    try:
        adj = float(adj)
    except (ValueError, TypeError):
        return 0.0

    challenges = devil_result.get("challenges", [])
    critical_count = sum(1 for c in challenges if c.get("severity") == "CRITICAL")
    high_count = sum(1 for c in challenges if c.get("severity") == "HIGH")

    # Scale by severity
    severity_weight = 1.0
    if critical_count >= 2:
        severity_weight = 1.5
    elif critical_count == 1 or high_count >= 2:
        severity_weight = 1.2
    elif not challenges or all(c.get("severity") == "LOW" for c in challenges):
        severity_weight = 0.5

    # Moderation factor — don't fully trust devil's recommendation
    MODERATION_FACTOR = 0.6
    moderated = adj * MODERATION_FACTOR * severity_weight

    moderated = max(-20, min(5, moderated))

    return round(moderated, 1)


def format_debate_rounds(
    agent_analysis_summary: str,
    devil_result: Dict[str, Any],
    impact_pp: float,
) -> List[Dict[str, Any]]:
    """Format the debate into rounds for storage."""
    rounds = [
        {
            "round": 1,
            "advocate": {
                "agent": "primary",
                "text": agent_analysis_summary[:2000],
            },
            "devil": {
                "agent": "gemini",
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
