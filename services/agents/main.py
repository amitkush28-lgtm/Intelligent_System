"""
Agent Analysis Engine — Main orchestrator.

Listens on Redis ingestion_complete and verification_complete queues,
triggers analysis cycles, runs agents sequentially per domain,
manages prediction creation/updates, publishes analysis_complete to Redis.

Also runs as daily cron (08:00 UTC) for comprehensive re-analysis.

Agent execution order:
1. 6 specialist agents (can run in any order, each independent)
2. Reality Check agent (web search validation of all new predictions)
3. Devil's advocate challenges (triggered by specialist outputs)
4. Master Strategist (runs AFTER all specialists, receives their outputs)
"""

import asyncio
import json
import logging
import sys
import time
import traceback
from datetime import datetime, date
from typing import Dict, Any, List, Optional

import redis

from shared.config import get_settings
from shared.database import get_db_session
from shared.models import (
    Prediction, ConfidenceTrail, Note, Debate, Event,
)
from shared.utils import (
    setup_logging, generate_prediction_id, generate_debate_id,
    cap_confidence_change, clamp_confidence,
)

from services.agents.context_builder import build_agent_context
from services.agents.output_parser import parse_agent_output
from services.agents.prediction_validator import validate_prediction_batch
from services.agents.devils_advocate import (
    run_devil_advocate, compute_devil_impact, format_debate_rounds,
)

# Import all specialist agents
from services.agents.specialists.economist import EconomistAgent
from services.agents.specialists.geopolitical import GeopoliticalAgent
from services.agents.specialists.investor import InvestorAgent
from services.agents.specialists.political import PoliticalAgent
from services.agents.specialists.sentiment import SentimentAgent
from services.agents.specialists.wildcard import WildCardAgent
from services.agents.specialists.master import MasterAgent

logger = setup_logging("agents")
settings = get_settings()

# Configuration
INGESTION_QUEUE = "ingestion_complete"
VERIFICATION_QUEUE = "verification_complete"
ANALYSIS_COMPLETE_QUEUE = "analysis_complete"
BRPOP_TIMEOUT = 10  # seconds
MAX_CYCLES_PER_RUN = 5  # safety limit — don't run infinite cycles from queued events

# Instantiate all agents (6 specialists + master)
SPECIALIST_AGENTS = [
    EconomistAgent(),
    GeopoliticalAgent(),
    InvestorAgent(),
    PoliticalAgent(),
    SentimentAgent(),
    WildCardAgent(),
]

MASTER_AGENT = MasterAgent()


def _get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client with connection handling."""
    try:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
        )
        client.ping()
        return client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        return None


# ============================================
# PREDICTION CRUD
# ============================================

def _create_prediction(
    db,
    agent_name: str,
    pred_data: Dict[str, Any],
    parent_id: Optional[str] = None,
    event_ref: Optional[str] = None,
) -> Optional[str]:
    """
    Create a new Prediction row + initial ConfidenceTrail entry.
    Returns the prediction ID, or None on failure.
    """
    try:
        claim = pred_data.get("claim", "")
        pred_id = generate_prediction_id(agent_name, claim)

        # Check for duplicate claim (same agent, same claim text, still active)
        existing = (
            db.query(Prediction)
            .filter(
                Prediction.agent == agent_name,
                Prediction.status == "ACTIVE",
                Prediction.claim == claim,
            )
            .first()
        )
        if existing:
            logger.debug(f"Skipping duplicate prediction: {claim[:80]}")
            return existing.id

        confidence = pred_data.get("confidence", 0.5)

        pred = Prediction(
            id=pred_id,
            agent=agent_name,
            claim=claim,
            time_condition_type=pred_data.get("time_condition_type", "range"),
            time_condition_date=_parse_date_safe(pred_data.get("time_condition_date")),
            time_condition_start=_parse_date_safe(pred_data.get("time_condition_start")),
            time_condition_end=_parse_date_safe(pred_data.get("time_condition_end")),
            resolution_criteria=pred_data.get("resolution_criteria", ""),
            status="ACTIVE",
            current_confidence=confidence,
            parent_id=parent_id,
        )
        db.add(pred)

        # Initial confidence trail entry
        trail = ConfidenceTrail(
            prediction_id=pred_id,
            value=confidence,
            trigger="initial_prediction",
            reasoning=pred_data.get("reasoning", f"Initial prediction by {agent_name}"),
            event_ref=event_ref,
        )
        db.add(trail)

        db.flush()

        # Create sub-predictions
        for sub_data in pred_data.get("sub_predictions", []):
            _create_prediction(db, agent_name, sub_data, parent_id=pred_id, event_ref=event_ref)

        logger.info(f"Created prediction {pred_id}: {claim[:80]} ({confidence:.0%})")
        return pred_id

    except Exception as e:
        logger.error(f"Failed to create prediction: {e}")
        logger.debug(traceback.format_exc())
        return None


def _update_prediction_confidence(
    db,
    update_data: Dict[str, Any],
    agent_name: str,
    evidence_integrity: float = 0.70,
) -> bool:
    """
    Update an existing prediction's confidence with capping.
    Returns True on success.
    """
    try:
        pred_id = update_data.get("prediction_id", "")
        new_conf = update_data.get("new_confidence", 0)
        reasoning = update_data.get("reasoning", "")
        trigger = update_data.get("trigger", "agent analysis cycle")

        pred = db.query(Prediction).filter(Prediction.id == pred_id).first()
        if not pred:
            logger.warning(f"Prediction {pred_id} not found for update")
            return False

        if pred.status != "ACTIVE":
            logger.debug(f"Skipping update for non-active prediction {pred_id}")
            return False

        # Apply confidence capping based on evidence integrity
        old_conf = pred.current_confidence
        proposed_change_pp = (new_conf - old_conf) * 100
        capped_change_pp = cap_confidence_change(proposed_change_pp, evidence_integrity)
        final_conf = clamp_confidence(old_conf + capped_change_pp / 100)

        pred.current_confidence = final_conf

        # Create confidence trail entry
        trail = ConfidenceTrail(
            prediction_id=pred_id,
            value=final_conf,
            trigger=trigger,
            reasoning=(
                f"{reasoning}"
                + (f" [capped from {new_conf:.2f} to {final_conf:.2f} by evidence integrity {evidence_integrity:.2f}]"
                   if abs(final_conf - new_conf) > 0.005 else "")
            ),
        )
        db.add(trail)
        db.flush()

        logger.info(
            f"Updated prediction {pred_id}: {old_conf:.0%} → {final_conf:.0%} "
            f"(proposed: {new_conf:.0%}, integrity: {evidence_integrity:.2f})"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to update prediction: {e}")
        return False


def _create_note(
    db,
    note_data: Dict[str, Any],
    agent_name: str,
) -> bool:
    """Create an analytical note."""
    try:
        pred_id = note_data.get("prediction_id")
        # Verify prediction exists if linked
        if pred_id:
            pred = db.query(Prediction).filter(Prediction.id == pred_id).first()
            if not pred:
                pred_id = None  # Unlink if prediction not found

        note = Note(
            prediction_id=pred_id,
            type=note_data.get("type", "observation"),
            text=note_data.get("text", ""),
        )
        db.add(note)
        db.flush()
        return True
    except Exception as e:
        logger.error(f"Failed to create note: {e}")
        return False


def _create_debate(
    db,
    prediction_id: str,
    agent_name: str,
    trigger_reason: str,
    rounds: List[Dict[str, Any]],
    devil_impact: float,
) -> Optional[str]:
    """Create a debate record."""
    try:
        debate_id = generate_debate_id(prediction_id, agent_name)
        debate = Debate(
            id=debate_id,
            prediction_id=prediction_id,
            agent=agent_name,
            trigger_reason=trigger_reason,
            rounds=rounds,
            devil_impact=devil_impact,
        )
        db.add(debate)
        db.flush()
        logger.info(f"Created debate {debate_id} (impact: {devil_impact:+.1f}pp)")
        return debate_id
    except Exception as e:
        logger.error(f"Failed to create debate: {e}")
        return None


# ============================================
# AGENT EXECUTION
# ============================================

async def _run_specialist(
    agent,
    db,
) -> Dict[str, Any]:
    """
    Run a single specialist agent: build context → analyze → persist results.
    Returns the parsed output.
    """
    agent_name = agent.agent_name
    logger.info(f"--- Running {agent_name.upper()} agent ---")

    try:
        # Build context from Postgres
        context = build_agent_context(agent_name, db)

        # Run analysis
        output = await agent.analyze(context)

        if not output.get("raw_valid", False):
            logger.warning(f"[{agent_name}] Analysis produced no valid output")
            return output

        # Get average evidence integrity for confidence capping
        claims = context.get("verified_claims", [])
        if claims:
            avg_integrity = sum(c.get("current_integrity", 0.5) for c in claims) / len(claims)
        else:
            avg_integrity = 0.50  # Default when no claims available

        # VALIDATION GATE — filter predictions through quality checks
        raw_predictions = output.get("new_predictions", [])
        if raw_predictions:
            accepted, rejected, val_warnings = validate_prediction_batch(
                raw_predictions, agent_name, max_predictions=8
            )
            output["new_predictions"] = accepted
            output["_rejected_predictions"] = rejected
            output["_validation_warnings"] = val_warnings

            if rejected:
                logger.info(
                    f"[{agent_name}] Prediction validator rejected {len(rejected)}/{len(raw_predictions)} predictions"
                )

        # Persist validated predictions
        for pred_data in output.get("new_predictions", []):
            _create_prediction(db, agent_name, pred_data)

        # Persist prediction updates
        for update_data in output.get("prediction_updates", []):
            _update_prediction_confidence(db, update_data, agent_name, avg_integrity)

        # Persist notes
        for note_data in output.get("notes", []):
            _create_note(db, note_data, agent_name)

        db.flush()

        logger.info(
            f"[{agent_name}] Completed: "
            f"{len(output.get('new_predictions', []))} new, "
            f"{len(output.get('prediction_updates', []))} updates, "
            f"{len(output.get('notes', []))} notes"
        )

        return output

    except Exception as e:
        logger.error(f"[{agent_name}] Agent failed: {e}")
        logger.debug(traceback.format_exc())
        return {
            "new_predictions": [],
            "prediction_updates": [],
            "notes": [],
            "summary": f"Agent failed: {str(e)[:100]}",
            "raw_valid": False,
            "devil_advocate_triggers": [],
            "analysis_metadata": {"agent": agent_name, "error": str(e)[:200]},
        }


async def _run_devil_advocates(
    specialist_outputs: Dict[str, Dict[str, Any]],
    db,
) -> Dict[str, Any]:
    """
    Run devil's advocate challenges for all triggered predictions.
    Returns stats about debates created.
    """
    stats = {"triggers": 0, "debates_created": 0, "skipped": 0, "errors": 0}

    for agent_name, output in specialist_outputs.items():
        triggers = output.get("devil_advocate_triggers", [])
        if not triggers:
            continue

        for trigger in triggers:
            stats["triggers"] += 1

            try:
                summary = output.get("summary", "")
                devil_result = await run_devil_advocate(trigger, summary)

                if not devil_result:
                    stats["skipped"] += 1
                    continue

                # Compute impact
                if trigger.get("type") == "new_prediction":
                    original_conf = trigger.get("prediction_data", {}).get("confidence", 0.5)
                else:
                    original_conf = trigger.get("new_confidence", 0.5)

                impact_pp = compute_devil_impact(original_conf, devil_result)

                # Format debate rounds
                rounds = format_debate_rounds(summary, devil_result, impact_pp)

                # Determine prediction_id for the debate
                pred_id = trigger.get("prediction_id")
                if not pred_id and trigger.get("type") == "new_prediction":
                    # For new predictions, find the one we just created
                    claim = trigger.get("prediction_data", {}).get("claim", "")
                    pred = (
                        db.query(Prediction)
                        .filter(
                            Prediction.agent == agent_name,
                            Prediction.claim == claim,
                            Prediction.status == "ACTIVE",
                        )
                        .first()
                    )
                    if pred:
                        pred_id = pred.id

                if pred_id:
                    # Apply confidence adjustment from devil's advocate
                    if abs(impact_pp) > 0.5:
                        pred = db.query(Prediction).filter(Prediction.id == pred_id).first()
                        if pred and pred.status == "ACTIVE":
                            old_conf = pred.current_confidence
                            new_conf = clamp_confidence(old_conf + impact_pp / 100)
                            pred.current_confidence = new_conf

                            trail = ConfidenceTrail(
                                prediction_id=pred_id,
                                value=new_conf,
                                trigger="devil_advocate_challenge",
                                reasoning=(
                                    f"Devil's advocate adjustment: {impact_pp:+.1f}pp. "
                                    f"Strongest weakness: {devil_result.get('strongest_weakness', 'N/A')[:200]}"
                                ),
                            )
                            db.add(trail)

                    # Create debate record
                    trigger_reason = ", ".join(trigger.get("trigger_reasons", ["unspecified"]))
                    debate_id = _create_debate(
                        db, pred_id, agent_name, trigger_reason, rounds, impact_pp,
                    )
                    if debate_id:
                        stats["debates_created"] += 1
                else:
                    stats["skipped"] += 1

            except Exception as e:
                logger.error(f"Devil's advocate failed for {agent_name}: {e}")
                logger.debug(traceback.format_exc())
                stats["errors"] += 1

    db.flush()
    return stats


async def _run_master(
    specialist_outputs: Dict[str, Dict[str, Any]],
    db,
) -> Dict[str, Any]:
    """Run the Master Strategist with specialist outputs."""
    logger.info("--- Running MASTER STRATEGIST ---")

    try:
        context = build_agent_context("master", db)
        output = await MASTER_AGENT.analyze(context, specialist_outputs, db)

        if output.get("raw_valid", False):
            # Persist master's predictions
            for pred_data in output.get("new_predictions", []):
                _create_prediction(db, "master", pred_data)

            for update_data in output.get("prediction_updates", []):
                _update_prediction_confidence(db, update_data, "master", 0.70)

            for note_data in output.get("notes", []):
                _create_note(db, note_data, "master")

            db.flush()

            logger.info(
                f"[master] Completed: "
                f"{len(output.get('new_predictions', []))} new, "
                f"{len(output.get('prediction_updates', []))} updates, "
                f"{len(output.get('notes', []))} notes"
            )

        return output

    except Exception as e:
        logger.error(f"Master Strategist failed: {e}")
        logger.debug(traceback.format_exc())
        return {"summary": f"Master failed: {str(e)[:100]}", "raw_valid": False}


# ============================================
# FULL ANALYSIS CYCLE
# ============================================

async def run_analysis_cycle() -> Dict[str, Any]:
    """
    Run a complete analysis cycle:
    1. Run all 5 specialists
    2. Run devil's advocate challenges
    3. Run Master Strategist
    4. Commit to database

    Returns stats about the cycle.
    """
    cycle_start = time.time()
    stats = {
        "cycle_start": datetime.utcnow().isoformat(),
        "agents_run": [],
        "agents_failed": [],
        "predictions_created": 0,
        "predictions_updated": 0,
        "notes_created": 0,
        "debates": {},
        "master_output": {},
    }

    with get_db_session() as db:
        specialist_outputs = {}

        # Phase 1: Run all specialists
        for agent in SPECIALIST_AGENTS:
            try:
                output = await _run_specialist(agent, db)
                specialist_outputs[agent.agent_name] = output
                stats["agents_run"].append(agent.agent_name)

                stats["predictions_created"] += len(output.get("new_predictions", []))
                stats["predictions_updated"] += len(output.get("prediction_updates", []))
                stats["notes_created"] += len(output.get("notes", []))

            except Exception as e:
                logger.error(f"Specialist {agent.agent_name} failed catastrophically: {e}")
                stats["agents_failed"].append(agent.agent_name)
                # Continue with other agents — graceful degradation

        # Phase 2: Reality Check — validate new predictions against live web data
        logger.info("--- Running Reality Check (web search validation) ---")
        try:
            from services.agents.reality_check import run_reality_check

            # Collect all new predictions from this cycle with their IDs
            new_preds_for_check = []
            for agent_name, output in specialist_outputs.items():
                for pred_data in output.get("new_predictions", []):
                    claim = pred_data.get("claim", "")
                    # Find the prediction we just created
                    pred = (
                        db.query(Prediction)
                        .filter(
                            Prediction.agent == agent_name,
                            Prediction.claim == claim,
                            Prediction.status == "ACTIVE",
                        )
                        .first()
                    )
                    if pred:
                        new_preds_for_check.append({
                            "pred_id": pred.id,
                            "claim": pred.claim,
                            "confidence": pred.current_confidence,
                            "resolution_criteria": pred.resolution_criteria,
                            "agent": pred.agent,
                        })

            reality_stats = await run_reality_check(new_preds_for_check, db)
            stats["reality_check"] = reality_stats
        except Exception as e:
            logger.error(f"Reality check phase failed: {e}")
            stats["reality_check"] = {"error": str(e)[:200]}

        # Phase 3: Devil's advocate challenges
        logger.info("--- Running Devil's Advocate Challenges ---")
        try:
            debate_stats = await _run_devil_advocates(specialist_outputs, db)
            stats["debates"] = debate_stats
        except Exception as e:
            logger.error(f"Devil's advocate phase failed: {e}")
            stats["debates"] = {"error": str(e)[:200]}

        # Phase 4: Master Strategist
        try:
            master_output = await _run_master(specialist_outputs, db)
            stats["master_output"] = {
                "predictions": len(master_output.get("new_predictions", [])),
                "updates": len(master_output.get("prediction_updates", [])),
                "notes": len(master_output.get("notes", [])),
                "summary": master_output.get("summary", "")[:500],
            }
            stats["agents_run"].append("master")
        except Exception as e:
            logger.error(f"Master Strategist failed: {e}")
            stats["agents_failed"].append("master")

        # Commit happens automatically via get_db_session context manager

    elapsed = time.time() - cycle_start
    stats["cycle_duration_seconds"] = round(elapsed, 1)
    stats["cycle_end"] = datetime.utcnow().isoformat()

    return stats


# ============================================
# QUEUE PROCESSING
# ============================================

async def _process_queues(redis_client: redis.Redis) -> int:
    """
    Process ingestion_complete and verification_complete queues.
    Returns number of trigger events processed.
    """
    processed = 0

    for queue_name in [INGESTION_QUEUE, VERIFICATION_QUEUE]:
        for _ in range(MAX_CYCLES_PER_RUN):
            try:
                result = redis_client.brpop(queue_name, timeout=BRPOP_TIMEOUT)
                if not result:
                    break

                _, payload = result
                event_data = json.loads(payload)
                logger.info(
                    f"Received trigger from {queue_name}: "
                    f"{event_data.get('event', 'unknown')}"
                )
                processed += 1

            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in {queue_name}: {e}")
            except Exception as e:
                logger.error(f"Error reading from {queue_name}: {e}")
                break

    return processed


async def _publish_completion(
    redis_client: Optional[redis.Redis],
    stats: Dict[str, Any],
) -> None:
    """Publish analysis_complete to Redis."""
    if not redis_client:
        return

    try:
        payload = json.dumps({
            "event": "analysis_complete",
            "timestamp": datetime.utcnow().isoformat(),
            "stats": stats,
        }, default=str)
        redis_client.lpush(ANALYSIS_COMPLETE_QUEUE, payload)
        logger.info("Published analysis_complete to Redis")
    except Exception as e:
        logger.warning(f"Failed to publish analysis_complete: {e}")


# ============================================
# ENTRY POINTS
# ============================================

async def run_async():
    """Main async entry point — queue processing + analysis cycle."""
    run_start = time.time()
    logger.info("=" * 60)
    logger.info("Agent Analysis Engine starting")
    logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    combined_stats = {
        "run_start": datetime.utcnow().isoformat(),
        "trigger_events": 0,
        "analysis_stats": {},
        "errors": [],
    }

    redis_client = _get_redis_client()

    try:
        # Phase 1: Check queues for triggers
        if redis_client:
            logger.info("PHASE 1: Checking queues for triggers...")
            trigger_count = await _process_queues(redis_client)
            combined_stats["trigger_events"] = trigger_count
            logger.info(f"Found {trigger_count} trigger events")
        else:
            logger.warning("Redis unavailable — running analysis from cron trigger")

        # Phase 2: Run full analysis cycle
        logger.info("PHASE 2: Running analysis cycle...")
        analysis_stats = await run_analysis_cycle()
        combined_stats["analysis_stats"] = analysis_stats

        # Phase 3: Publish completion
        await _publish_completion(redis_client, combined_stats)

    except Exception as e:
        logger.error(f"Agent analysis run failed: {e}")
        logger.error(traceback.format_exc())
        combined_stats["errors"].append(str(e))
    finally:
        if redis_client:
            try:
                redis_client.close()
            except Exception:
                pass

    elapsed = time.time() - run_start
    combined_stats["run_duration_seconds"] = round(elapsed, 1)
    combined_stats["run_end"] = datetime.utcnow().isoformat()

    # Summary logging
    logger.info("=" * 60)
    logger.info(f"Agent Analysis Engine complete in {elapsed:.1f}s")
    a = combined_stats.get("analysis_stats", {})
    logger.info(f"  Agents run:         {len(a.get('agents_run', []))}")
    logger.info(f"  Agents failed:      {len(a.get('agents_failed', []))}")
    logger.info(f"  Predictions created: {a.get('predictions_created', 0)}")
    logger.info(f"  Predictions updated: {a.get('predictions_updated', 0)}")
    logger.info(f"  Notes created:      {a.get('notes_created', 0)}")
    d = a.get("debates", {})
    logger.info(f"  Debates created:    {d.get('debates_created', 0)} / {d.get('triggers', 0)} triggers")
    if combined_stats["errors"]:
        logger.warning(f"  Errors:             {len(combined_stats['errors'])}")
    logger.info("=" * 60)

    return combined_stats


def run():
    """Synchronous entry point for Railway cron."""
    asyncio.run(run_async())


if __name__ == "__main__":
    run()


# ============================================
# HELPERS
# ============================================

def _parse_date_safe(val) -> Optional[date]:
    """Safely parse a date value."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except (ValueError, IndexError):
            return None
    return None
