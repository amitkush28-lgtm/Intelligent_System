"""
Monthly meta red team — challenges the framework itself.

- Are we asking the right questions?
- Occam's check: are predictions overly complex when simpler explanations exist?
- Methodology bias detection: does the 7-question chain itself introduce systematic bias?
- Uses call_claude_sonnet() for meta-analysis.
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from shared.database import get_db_session
from shared.models import (
    Prediction, CalibrationScore, Debate, WeakSignal, Note,
)
from shared.llm_client import call_claude_sonnet

logger = logging.getLogger(__name__)


async def run_monthly_red_team() -> Dict[str, Any]:
    """
    Full monthly meta red team analysis.
    Challenges the framework, checks for methodology bias, runs Occam's razor.
    """
    stats = {
        "analyses_run": 0,
        "findings": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            # Gather system state for the red team
            context = _gather_red_team_context(db)

            if not context["has_data"]:
                logger.info("Insufficient data for red team analysis")
                return stats

            # Run the three red team analyses
            analyses = [
                ("framework_challenge", _run_framework_challenge),
                ("occams_check", _run_occams_check),
                ("methodology_bias", _run_methodology_bias_check),
            ]

            for name, analysis_fn in analyses:
                try:
                    findings = await analysis_fn(context)
                    stats["analyses_run"] += 1

                    if findings:
                        for finding in findings:
                            _record_red_team_finding(db, name, finding)
                            stats["findings"] += 1

                except Exception as e:
                    logger.error(f"Red team analysis '{name}' failed: {e}")
                    stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Red team failed: {e}")
        stats["errors"] += 1

    logger.info(
        f"Red team complete: {stats['analyses_run']} analyses, "
        f"{stats['findings']} findings"
    )
    return stats


async def run_weekly_red_team_lite() -> Dict[str, Any]:
    """
    Simplified weekly red team — just the Occam's check on active predictions.
    Less expensive than the full monthly analysis.
    """
    stats = {"findings": 0, "errors": 0}

    try:
        with get_db_session() as db:
            context = _gather_red_team_context(db)
            if not context["has_data"]:
                return stats

            findings = await _run_occams_check(context)
            if findings:
                for finding in findings:
                    _record_red_team_finding(db, "weekly_occams", finding)
                    stats["findings"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Weekly red team failed: {e}")
        stats["errors"] += 1

    return stats


def _gather_red_team_context(db) -> Dict[str, Any]:
    """Gather comprehensive system state for red team analysis."""
    context = {"has_data": False}

    # Active predictions summary
    active = (
        db.query(Prediction)
        .filter(Prediction.status == "ACTIVE")
        .all()
    )

    resolved = (
        db.query(Prediction)
        .filter(Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE", "EXPIRED"]))
        .all()
    )

    if not active and not resolved:
        return context

    context["has_data"] = True
    context["active_count"] = len(active)
    context["resolved_count"] = len(resolved)

    # Summarize active predictions
    context["active_summary"] = []
    for pred in active[:20]:  # Limit to 20 for context window
        context["active_summary"].append({
            "id": pred.id,
            "agent": pred.agent,
            "claim": pred.claim[:200],
            "confidence": pred.current_confidence,
        })

    # Calibration state
    cal_scores = db.query(CalibrationScore).all()
    context["calibration_summary"] = []
    for cs in cal_scores:
        context["calibration_summary"].append({
            "agent": cs.agent,
            "domain": cs.domain,
            "bucket": cs.confidence_bucket,
            "predicted_avg": cs.predicted_avg,
            "actual_avg": cs.actual_avg,
            "bias": cs.bias_direction,
            "count": cs.count,
        })

    # Resolution stats
    if resolved:
        true_count = sum(1 for p in resolved if p.resolved_outcome is True)
        false_count = sum(1 for p in resolved if p.resolved_outcome is False)
        brier_scores = [p.brier_score for p in resolved if p.brier_score is not None]
        context["resolution_stats"] = {
            "total": len(resolved),
            "true": true_count,
            "false": false_count,
            "avg_brier": sum(brier_scores) / len(brier_scores) if brier_scores else None,
        }
    else:
        context["resolution_stats"] = None

    # Recent debates
    recent_debates = (
        db.query(Debate)
        .order_by(Debate.created_at.desc())
        .limit(10)
        .all()
    )
    context["recent_debates"] = [
        {
            "agent": d.agent,
            "trigger": d.trigger_reason,
            "impact": d.devil_impact,
        }
        for d in recent_debates
    ]

    return context


async def _run_framework_challenge(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Challenge whether the analytical framework is asking the right questions."""
    system_prompt = (
        "You are a meta-analyst reviewing an intelligence prediction system. "
        "Your job is to challenge the FRAMEWORK ITSELF, not individual predictions. "
        "The system uses a 7-question structural reasoning chain: "
        "(I) Actors & Structural Needs, (I-b) Deep Motivations, "
        "(II) Constraints, (III) Irreversibilities, (IV) Equilibrium, "
        "(V) Consensus Error, (VI) Second/Third-Order Effects. "
        "Respond with a JSON array of findings. Each finding has: "
        "'issue' (string), 'severity' (high/medium/low), 'recommendation' (string)."
    )

    active_text = json.dumps(context["active_summary"][:10], indent=2)
    cal_text = json.dumps(context["calibration_summary"][:10], indent=2)

    user_message = (
        f"Active predictions ({context['active_count']} total, showing sample):\n"
        f"{active_text}\n\n"
        f"Calibration state:\n{cal_text}\n\n"
        f"Resolution stats: {json.dumps(context.get('resolution_stats'))}\n\n"
        "Challenge this framework:\n"
        "1. What important analytical lenses is the 7-question chain MISSING?\n"
        "2. Does the chain create blind spots by directing attention to structural "
        "forces while missing fast-moving tactical dynamics?\n"
        "3. Are there domains where this framework is fundamentally ill-suited?\n"
        "4. What would a naive forecaster do better than this system?\n"
        "Return ONLY a JSON array of findings."
    )

    try:
        response = await call_claude_sonnet(system_prompt, user_message, max_tokens=2048)
        return _parse_findings(response)
    except Exception as e:
        logger.error(f"Framework challenge LLM call failed: {e}")
        return []


async def _run_occams_check(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check if predictions are overly complex when simpler explanations exist."""
    system_prompt = (
        "You are applying Occam's Razor to intelligence predictions. "
        "For each prediction, ask: is there a SIMPLER explanation that the "
        "analyst might be overlooking because they're attracted to complex "
        "structural narratives? "
        "Respond with a JSON array of findings. Each finding has: "
        "'prediction_id' (string), 'issue' (string), 'simpler_explanation' (string), "
        "'severity' (high/medium/low)."
    )

    active_text = json.dumps(context["active_summary"][:15], indent=2)

    user_message = (
        f"Review these active predictions for unnecessary complexity:\n"
        f"{active_text}\n\n"
        "For each prediction where a simpler explanation might suffice, "
        "flag it. Look for:\n"
        "- Overly elaborate causal chains when a simple trend continues\n"
        "- Structural arguments that ignore the most obvious explanation\n"
        "- Predictions driven by narrative appeal rather than evidence\n"
        "Return ONLY a JSON array of findings."
    )

    try:
        response = await call_claude_sonnet(system_prompt, user_message, max_tokens=2048)
        return _parse_findings(response)
    except Exception as e:
        logger.error(f"Occam's check LLM call failed: {e}")
        return []


async def _run_methodology_bias_check(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Detect if the 7-question chain itself introduces systematic bias.
    E.g., structural analysis may bias toward status-quo predictions.
    """
    system_prompt = (
        "You are a methodology auditor. The intelligence system uses a "
        "7-question structural reasoning chain that emphasizes actors, "
        "constraints, irreversibilities, equilibrium, and consensus error. "
        "Analyze the system's track record for METHODOLOGY-INDUCED BIAS. "
        "Respond with a JSON array of findings. Each finding has: "
        "'bias_type' (string), 'evidence' (string), 'severity' (high/medium/low), "
        "'recommendation' (string)."
    )

    cal_text = json.dumps(context["calibration_summary"], indent=2)
    debates_text = json.dumps(context["recent_debates"][:5], indent=2)
    resolution_text = json.dumps(context.get("resolution_stats"))

    user_message = (
        f"System calibration data:\n{cal_text}\n\n"
        f"Recent devil's advocate debates:\n{debates_text}\n\n"
        f"Resolution stats: {resolution_text}\n\n"
        "Analyze for methodology-induced biases:\n"
        "1. Does the structural focus bias toward or against change?\n"
        "2. Is the system better at certain prediction types than others?\n"
        "3. Do devil's advocate challenges actually improve outcomes?\n"
        "4. Are calibration adjustments helping or just adding noise?\n"
        "Return ONLY a JSON array of findings."
    )

    try:
        response = await call_claude_sonnet(system_prompt, user_message, max_tokens=2048)
        return _parse_findings(response)
    except Exception as e:
        logger.error(f"Methodology bias check LLM call failed: {e}")
        return []


def _parse_findings(response: str) -> List[Dict[str, Any]]:
    """Parse LLM response into a list of finding dicts."""
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
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict) and "findings" in parsed:
            return parsed["findings"]
        else:
            return [parsed]
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse red team findings: {text[:200]}")
        # Return the raw text as a single finding
        return [{"issue": text[:500], "severity": "low", "recommendation": "Review manually"}]


def _record_red_team_finding(
    db, analysis_type: str, finding: Dict[str, Any]
) -> None:
    """Record a red team finding as a weak signal."""
    severity = finding.get("severity", "medium")
    strength_map = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
    strength = strength_map.get(severity, "MEDIUM")

    issue = finding.get("issue", finding.get("bias_type", "Unknown"))
    recommendation = finding.get(
        "recommendation",
        finding.get("simpler_explanation", "Review required"),
    )

    signal_text = (
        f"[RED_TEAM:{analysis_type.upper()}] {issue}. "
        f"Recommendation: {recommendation}"
    )

    weak_signal = WeakSignal(
        signal=signal_text[:2000],  # Truncate to reasonable length
        strength=strength,
        status="investigating",
        detected_at=datetime.utcnow(),
    )
    db.add(weak_signal)
