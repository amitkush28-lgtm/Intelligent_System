"""
Pre-mortem analysis via Claude.

Weekly: use call_claude_sonnet() with web search to run a pre-mortem.
Prompt: "Given our current prediction portfolio, if we are catastrophically
wrong in 6 months, what would we wish we'd watched?"
Load all active predictions as context.
Write results as WeakSignal rows with strength=HIGH.
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, List

from shared.database import get_db_session
from shared.models import Prediction, WeakSignal
from shared.llm_client import call_claude_with_web_search

logger = logging.getLogger(__name__)


async def run_premortem() -> Dict[str, Any]:
    """
    Run pre-mortem analysis on the active prediction portfolio.
    Uses Claude with web search to identify blind spots and
    catastrophic failure modes.
    """
    stats = {
        "active_predictions": 0,
        "signals_created": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            # Load all active predictions
            active = (
                db.query(Prediction)
                .filter(Prediction.status == "ACTIVE")
                .all()
            )
            stats["active_predictions"] = len(active)

            if not active:
                logger.info("No active predictions for pre-mortem analysis")
                return stats

            # Build the pre-mortem prompt
            predictions_summary = _format_predictions_for_premortem(active)

            system_prompt = (
                "You are a senior intelligence analyst conducting a pre-mortem exercise. "
                "A pre-mortem assumes the worst has happened and works backward to identify "
                "what was missed. You have access to web search to check current developments "
                "that the prediction system might be missing.\n\n"
                "Respond with a JSON object containing:\n"
                "{\n"
                '  "blind_spots": [\n'
                "    {\n"
                '      "signal": "Description of what we should be watching",\n'
                '      "why_missed": "Why the current framework might miss this",\n'
                '      "catastrophic_scenario": "How this could invalidate multiple predictions",\n'
                '      "suggested_action": "What to monitor or investigate"\n'
                "    }\n"
                "  ]\n"
                "}"
            )

            user_message = (
                "CURRENT PREDICTION PORTFOLIO:\n"
                f"{predictions_summary}\n\n"
                "EXERCISE: Imagine it is 6 months from now and our prediction system "
                "has been CATASTROPHICALLY WRONG on several major calls.\n\n"
                "Looking back from that future:\n"
                "1. What signals should we have been watching that we aren't?\n"
                "2. What assumptions are shared across multiple predictions that could "
                "all be wrong for the same reason?\n"
                "3. What 'black swan' developments could invalidate our entire framework?\n"
                "4. What are the current global developments (search the web) that our "
                "prediction portfolio seems blind to?\n"
                "5. Where are we most likely to be overconfident?\n\n"
                "Identify 3-7 specific blind spots. For each, be concrete about what to "
                "watch and why our current system would miss it.\n\n"
                "Return ONLY the JSON object."
            )

            try:
                response = await call_claude_with_web_search(
                    system_prompt, user_message, max_tokens=3000
                )
                blind_spots = _parse_premortem_response(response)

                for spot in blind_spots:
                    _create_premortem_signal(db, spot)
                    stats["signals_created"] += 1

            except Exception as e:
                logger.error(f"Pre-mortem LLM call failed: {e}")
                stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Pre-mortem analysis failed: {e}")
        stats["errors"] += 1

    logger.info(
        f"Pre-mortem: {stats['active_predictions']} predictions analyzed, "
        f"{stats['signals_created']} blind spots identified"
    )

    return stats


def _format_predictions_for_premortem(predictions: List[Prediction]) -> str:
    """Format active predictions into a concise summary for the pre-mortem."""
    lines = []

    # Group by agent
    by_agent: Dict[str, List[Prediction]] = {}
    for pred in predictions:
        if pred.agent not in by_agent:
            by_agent[pred.agent] = []
        by_agent[pred.agent].append(pred)

    for agent, preds in sorted(by_agent.items()):
        lines.append(f"\n### {agent.upper()} AGENT ({len(preds)} active predictions)")
        # Show top predictions by confidence
        sorted_preds = sorted(preds, key=lambda p: p.current_confidence, reverse=True)
        for pred in sorted_preds[:5]:  # Limit per agent
            deadline = ""
            if pred.time_condition_date:
                deadline = f" [deadline: {pred.time_condition_date}]"
            elif pred.time_condition_end:
                deadline = f" [deadline: {pred.time_condition_end}]"

            lines.append(
                f"- [{pred.current_confidence:.0%}] {pred.claim[:150]}{deadline}"
            )

        if len(preds) > 5:
            lines.append(f"  ... and {len(preds) - 5} more predictions")

    return "\n".join(lines)


def _parse_premortem_response(response: str) -> List[Dict[str, Any]]:
    """Parse the LLM's pre-mortem response into a list of blind spots."""
    text = response.strip()

    # Strip markdown fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "blind_spots" in parsed:
            return parsed["blind_spots"]
        elif isinstance(parsed, list):
            return parsed
        else:
            return [parsed]
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse pre-mortem JSON: {text[:200]}")
        # Return the raw text as a single blind spot
        return [{
            "signal": text[:500],
            "why_missed": "Could not parse structured response",
            "catastrophic_scenario": "Review manually",
            "suggested_action": "Manual review required",
        }]


def _create_premortem_signal(db, blind_spot: Dict[str, Any]) -> None:
    """Create a WeakSignal from a pre-mortem blind spot."""
    signal_text = (
        f"[PRE-MORTEM] {blind_spot.get('signal', 'Unknown blind spot')}. "
        f"Why missed: {blind_spot.get('why_missed', 'N/A')}. "
        f"Catastrophic scenario: {blind_spot.get('catastrophic_scenario', 'N/A')}. "
        f"Action: {blind_spot.get('suggested_action', 'N/A')}"
    )

    weak_signal = WeakSignal(
        signal=signal_text[:2000],
        strength="HIGH",  # Pre-mortem findings are always HIGH priority
        status="investigating",
        detected_at=datetime.utcnow(),
    )
    db.add(weak_signal)
