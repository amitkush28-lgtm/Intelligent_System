"""
Living Questions Daily Monitor — matches new events against active question assumptions.

Called after daily ingestion in the pipeline. For each active Living Question:
1. Fetch new events from the last 24 hours
2. Keyword-match events against each assumption's monitoring keywords
3. For matched events, use LLM to evaluate relevance and impact
4. Log evidence and check tripwire thresholds
5. Trigger re-analysis if warranted

Integrates into the scheduler pipeline as a new step between ingestion and agent analysis.
"""

import asyncio
import logging
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from shared.config import get_settings
from shared.database import get_db_session
from shared.llm_client import call_claude_haiku, parse_structured_json
from shared.models import (
    LivingQuestion,
    QuestionAssumption,
    QuestionEvidence,
    Event,
)
from shared.utils import setup_logging

logger = setup_logging("question_monitor")
settings = get_settings()

# Minimum keyword overlap to flag an event for LLM evaluation
MIN_KEYWORD_OVERLAP = 1

# Maximum events to evaluate per assumption per run (cost control)
MAX_EVALUATIONS_PER_ASSUMPTION = 10

# Maximum total LLM evaluations per run
MAX_TOTAL_EVALUATIONS = 100


EVIDENCE_EVALUATION_PROMPT = """You are evaluating whether a new event is relevant to a Living Question assumption.

LIVING QUESTION: "{question}"
ASSUMPTION #{assumption_number}: "{assumption_text}"
CURRENT STATUS: {status}
GREEN→YELLOW TRIPWIRE: "{green_to_yellow}"
YELLOW→RED TRIPWIRE: "{yellow_to_red}"

NEW EVENT:
Source: {source}
Date: {event_date}
Content: {event_text}

EVALUATE:
1. Is this event relevant to this assumption? Consider both direct and indirect relevance.
2. If relevant: Does it SUPPORT or CHALLENGE the assumption?
3. How significant is the impact? (HIGH/MEDIUM/LOW)
4. Does it move the assumption closer to crossing a tripwire?

Respond with ONLY valid JSON:
{{
    "relevant": true or false,
    "evidence_type": "SUPPORTS" or "CHALLENGES" or "NEUTRAL",
    "impact_level": "HIGH" or "MEDIUM" or "LOW",
    "summary": "One sentence describing what this evidence means for the assumption",
    "tripwire_approached": true or false,
    "recommended_status_change": null or "yellow" or "red",
    "reasoning": "Brief explanation of your evaluation"
}}

If not relevant, return: {{"relevant": false}}"""


def _keyword_match_score(event_text: str, keywords: List[str]) -> int:
    """Count how many assumption keywords appear in the event text."""
    if not event_text or not keywords:
        return 0
    text_lower = event_text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def _get_active_questions_with_assumptions(db) -> List[Dict[str, Any]]:
    """Load all active Living Questions with their assumptions."""
    questions = (
        db.query(LivingQuestion)
        .filter(LivingQuestion.status == "active")
        .all()
    )

    result = []
    for q in questions:
        assumptions = (
            db.query(QuestionAssumption)
            .filter(QuestionAssumption.question_id == q.id)
            .order_by(QuestionAssumption.assumption_number)
            .all()
        )
        result.append({
            "question": q,
            "assumptions": assumptions,
        })

    return result


def _get_recent_events(db, hours: int = 24) -> List[Event]:
    """Fetch events ingested in the last N hours."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    return (
        db.query(Event)
        .filter(Event.timestamp >= cutoff)
        .order_by(Event.timestamp.desc())
        .limit(2000)
        .all()
    )


def _match_events_to_assumption(
    events: List[Event],
    assumption: QuestionAssumption,
) -> List[Tuple[Event, int]]:
    """Match events against an assumption's keywords. Returns (event, match_score) tuples."""
    keywords = assumption.keywords or []
    if not keywords:
        return []

    matches = []
    for event in events:
        text = event.raw_text or ""
        score = _keyword_match_score(text, keywords)
        if score >= MIN_KEYWORD_OVERLAP:
            matches.append((event, score))

    # Sort by match score descending, limit to prevent cost explosion
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[:MAX_EVALUATIONS_PER_ASSUMPTION]


async def _evaluate_evidence(
    event: Event,
    question: LivingQuestion,
    assumption: QuestionAssumption,
) -> Optional[Dict[str, Any]]:
    """Use LLM to evaluate if an event is relevant evidence for an assumption."""
    try:
        prompt = EVIDENCE_EVALUATION_PROMPT.format(
            question=question.question,
            assumption_number=assumption.assumption_number,
            assumption_text=assumption.assumption_text,
            status=assumption.status,
            green_to_yellow=assumption.green_to_yellow_trigger or "Not defined",
            yellow_to_red=assumption.yellow_to_red_trigger or "Not defined",
            source=event.source,
            event_date=event.timestamp.strftime("%Y-%m-%d") if event.timestamp else "Unknown",
            event_text=(event.raw_text or "")[:500],
        )

        response = await call_claude_haiku(
            system_prompt="You are an intelligence analyst evaluating evidence relevance. Be precise and conservative. Only mark events as relevant if they genuinely inform the assumption. Respond with ONLY valid JSON.",
            user_message=prompt,
            max_tokens=512,
            temperature=0.1,
        )

        result = parse_structured_json(response)
        return result if result else None

    except Exception as e:
        logger.warning(f"Evidence evaluation failed for event {event.id}: {e}")
        return None


def _log_evidence(
    db,
    question_id: str,
    assumption_id: str,
    event_id: str,
    evaluation: Dict[str, Any],
) -> QuestionEvidence:
    """Create a QuestionEvidence record from an LLM evaluation."""
    evidence = QuestionEvidence(
        question_id=question_id,
        assumption_id=assumption_id,
        event_id=event_id,
        evidence_type=evaluation.get("evidence_type", "NEUTRAL"),
        evidence_summary=evaluation.get("summary", ""),
        evidence_detail=evaluation.get("reasoning", ""),
        source="pipeline",
        impact_level=evaluation.get("impact_level", "LOW"),
        triggered_status_change=False,
        detected_by="pipeline",
        agent_that_flagged="question_monitor",
    )
    db.add(evidence)
    return evidence


def _check_and_update_assumption_status(
    db,
    assumption: QuestionAssumption,
    evaluation: Dict[str, Any],
    evidence: QuestionEvidence,
) -> bool:
    """Check if evidence warrants an assumption status change. Returns True if changed."""
    recommended = evaluation.get("recommended_status_change")
    if not recommended:
        return False

    current = assumption.status or "green"

    # Only allow forward progression: green -> yellow -> red
    valid_transitions = {
        "green": ["yellow", "red"],
        "yellow": ["red"],
        "red": [],
    }

    if recommended not in valid_transitions.get(current, []):
        return False

    # Apply the status change
    old_status = assumption.status
    assumption.status = recommended
    assumption.last_status_change_at = datetime.utcnow()
    assumption.last_status_change_reason = evaluation.get("summary", "Evidence triggered status change")

    # Update evidence record
    evidence.triggered_status_change = True
    evidence.previous_status = old_status
    evidence.new_status = recommended

    # Update evidence counts
    if evaluation.get("evidence_type") == "CHALLENGES":
        assumption.challenging_evidence_count = (assumption.challenging_evidence_count or 0) + 1
    elif evaluation.get("evidence_type") == "SUPPORTS":
        assumption.supporting_evidence_count = (assumption.supporting_evidence_count or 0) + 1

    logger.info(
        f"Assumption {assumption.id} status changed: {old_status} -> {recommended}. "
        f"Reason: {evaluation.get('summary', 'N/A')[:100]}"
    )
    return True


def _update_question_overall_status(db, question: LivingQuestion) -> bool:
    """Recompute the question's overall status based on current assumption statuses. Returns True if re-analysis needed."""
    assumptions = (
        db.query(QuestionAssumption)
        .filter(QuestionAssumption.question_id == question.id)
        .all()
    )

    red_count = sum(1 for a in assumptions if a.status == "red")
    yellow_count = sum(1 for a in assumptions if a.status == "yellow")

    old_status = question.overall_status

    if red_count > 0:
        question.overall_status = "red"
    elif yellow_count >= 2:
        question.overall_status = "yellow"
    else:
        question.overall_status = "green"

    question.last_evidence_at = datetime.utcnow()

    # Determine if re-analysis is warranted
    needs_reanalysis = False
    if red_count > 0:
        needs_reanalysis = True
        logger.info(f"Question {question.id}: {red_count} RED assumption(s) — re-analysis triggered")
    elif yellow_count >= 2 and old_status == "green":
        needs_reanalysis = True
        logger.info(f"Question {question.id}: {yellow_count} YELLOW assumptions (was GREEN) — re-analysis triggered")

    return needs_reanalysis


async def _trigger_reanalysis(question_id: str, question_text: str, context: str, category: str, trigger: str):
    """Trigger a full re-analysis of a Living Question."""
    try:
        from services.api.routes.questions import _analyze_question
        logger.info(f"Triggering re-analysis for {question_id}: {trigger}")
        await _analyze_question(question_id, question_text, context, category)

        # Log the re-analysis
        from shared.models import QuestionReanalysis
        with get_db_session() as db:
            reanalysis = QuestionReanalysis(
                question_id=question_id,
                trigger_type="EVENT_DRIVEN",
                trigger_description=trigger,
            )
            db.add(reanalysis)
            db.commit()

    except Exception as e:
        logger.error(f"Re-analysis trigger failed for {question_id}: {e}")


async def run_daily_monitoring() -> Dict[str, Any]:
    """
    Main entry point: run the daily Living Questions monitoring cycle.

    Returns stats dict with monitoring results.
    """
    stats = {
        "questions_monitored": 0,
        "events_scanned": 0,
        "events_matched": 0,
        "evidence_logged": 0,
        "status_changes": 0,
        "reanalyses_triggered": 0,
        "errors": [],
    }

    total_evaluations = 0

    try:
        with get_db_session() as db:
            # Load active questions
            question_data = _get_active_questions_with_assumptions(db)
            if not question_data:
                logger.info("No active Living Questions to monitor")
                return stats

            stats["questions_monitored"] = len(question_data)

            # Fetch recent events
            recent_events = _get_recent_events(db, hours=26)  # 26h for overlap safety
            stats["events_scanned"] = len(recent_events)

            if not recent_events:
                logger.info("No recent events to match against")
                return stats

            logger.info(
                f"Monitoring {len(question_data)} questions against {len(recent_events)} recent events"
            )

            reanalysis_queue = []

            for qd in question_data:
                question = qd["question"]
                assumptions = qd["assumptions"]

                for assumption in assumptions:
                    if total_evaluations >= MAX_TOTAL_EVALUATIONS:
                        logger.warning("Hit max evaluation limit, stopping")
                        break

                    # Match events against assumption keywords
                    matched = _match_events_to_assumption(recent_events, assumption)
                    stats["events_matched"] += len(matched)

                    for event, match_score in matched:
                        if total_evaluations >= MAX_TOTAL_EVALUATIONS:
                            break

                        # LLM evaluation
                        evaluation = await _evaluate_evidence(event, question, assumption)
                        total_evaluations += 1

                        if not evaluation or not evaluation.get("relevant"):
                            continue

                        # Log the evidence
                        evidence = _log_evidence(
                            db, question.id, assumption.id, event.id, evaluation
                        )
                        stats["evidence_logged"] += 1

                        # Update counts even without status change
                        if evaluation.get("evidence_type") == "CHALLENGES":
                            assumption.challenging_evidence_count = (assumption.challenging_evidence_count or 0) + 1
                        elif evaluation.get("evidence_type") == "SUPPORTS":
                            assumption.supporting_evidence_count = (assumption.supporting_evidence_count or 0) + 1

                        # Check for status change
                        if evaluation.get("tripwire_approached") and evaluation.get("recommended_status_change"):
                            changed = _check_and_update_assumption_status(
                                db, assumption, evaluation, evidence
                            )
                            if changed:
                                stats["status_changes"] += 1

                # After processing all assumptions, update overall question status
                needs_reanalysis = _update_question_overall_status(db, question)
                if needs_reanalysis:
                    reanalysis_queue.append({
                        "id": question.id,
                        "question": question.question,
                        "context": question.context,
                        "category": question.category,
                        "trigger": f"Status changed to {question.overall_status} during daily monitoring",
                    })

            db.commit()
            logger.info(f"Evidence logging committed: {stats['evidence_logged']} new evidence entries")

        # Trigger re-analyses outside the main DB session
        for rq in reanalysis_queue:
            try:
                await _trigger_reanalysis(
                    rq["id"], rq["question"], rq["context"], rq["category"], rq["trigger"]
                )
                stats["reanalyses_triggered"] += 1
            except Exception as e:
                logger.error(f"Re-analysis failed for {rq['id']}: {e}")
                stats["errors"].append(f"Reanalysis {rq['id']}: {str(e)[:100]}")

    except Exception as e:
        logger.error(f"Daily monitoring failed: {e}")
        logger.debug(traceback.format_exc())
        stats["errors"].append(str(e)[:200])

    logger.info(
        f"Daily monitoring complete: "
        f"{stats['questions_monitored']} questions, "
        f"{stats['events_scanned']} events scanned, "
        f"{stats['events_matched']} matched, "
        f"{stats['evidence_logged']} evidence logged, "
        f"{stats['status_changes']} status changes, "
        f"{stats['reanalyses_triggered']} re-analyses triggered"
    )

    return stats
