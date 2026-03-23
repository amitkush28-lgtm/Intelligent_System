"""
Feedback Processor — Always-on worker with APScheduler.

Closes the accountability loop: predict → score → calibrate → update prompts.

Schedule:
- Every 5 min: scorer.py auto-resolution scan
- Every hour: calibration.py rebuild + bias_detector.py scan
- Every 2 hours: cross_agent_scanner.py
- Daily: sub_prediction_health.py
- Weekly: red_team.py (simplified version)
- Monthly: red_team.py (full version)

Also consumes analysis_complete from Redis to trigger immediate scoring.
"""

import asyncio
import json
import logging
import signal
import sys
import time
import traceback
from datetime import datetime
from typing import Dict, Any
from collections import defaultdict

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from shared.config import get_settings
from shared.utils import setup_logging

logger = setup_logging("feedback")
settings = get_settings()

# Queue names
ANALYSIS_COMPLETE_QUEUE = "analysis_complete"
FEEDBACK_COMPLETE_QUEUE = "feedback_complete"


def _run_scoring_cycle():
    """Scheduled task: Run scoring cycle every 5 minutes."""
    try:
        from services.feedback.scorer import run_scoring_cycle
        stats = run_scoring_cycle()
        if stats["expired"] > 0 or stats["newly_scored"] > 0:
            logger.info(f"Scoring cycle: {stats}")
    except Exception as e:
        logger.error(f"Scoring cycle failed: {e}\n{traceback.format_exc()}")


def _run_calibration_and_bias():
    """Scheduled task: Rebuild calibration curves and run bias detection every hour."""
    try:
        from services.feedback.calibration import rebuild_calibration_curves
        from services.feedback.bias_detector import run_bias_detection
        from services.feedback.prompt_updater import update_agent_prompts

        # Step 1: Rebuild calibration curves
        cal_stats = rebuild_calibration_curves()
        logger.info(f"Calibration rebuild: {cal_stats}")

        # Step 2: Run bias detection
        result = run_bias_detection()
        bias_stats = result["stats"]
        biases = result.get("biases", [])

        # Step 3: Update agent prompts if biases found
        if biases:
            # Group biases by agent
            biases_by_agent: Dict[str, list] = defaultdict(list)
            for bias in biases:
                biases_by_agent[bias.agent].append(bias)

            prompt_stats = update_agent_prompts(biases_by_agent)
            logger.info(f"Prompt updates: {prompt_stats}")
        else:
            logger.info("No biases detected — prompts unchanged")

    except Exception as e:
        logger.error(f"Calibration/bias cycle failed: {e}\n{traceback.format_exc()}")


def _run_cross_agent_scan():
    """Scheduled task: Cross-agent correlation scan every 2 hours."""
    try:
        from services.feedback.cross_agent_scanner import scan_cross_agent_correlations
        stats = scan_cross_agent_correlations()
        if any(v > 0 for k, v in stats.items() if k != "errors"):
            logger.info(f"Cross-agent scan: {stats}")
    except Exception as e:
        logger.error(f"Cross-agent scan failed: {e}\n{traceback.format_exc()}")


def _run_sub_prediction_health():
    """Scheduled task: Sub-prediction health check daily."""
    try:
        from services.feedback.sub_prediction_health import check_sub_prediction_health
        stats = check_sub_prediction_health()
        logger.info(f"Sub-prediction health: {stats}")
    except Exception as e:
        logger.error(f"Sub-prediction health check failed: {e}\n{traceback.format_exc()}")


def _run_weekly_red_team():
    """Scheduled task: Weekly simplified red team."""
    try:
        from services.feedback.red_team import run_weekly_red_team_lite
        stats = asyncio.run(run_weekly_red_team_lite())
        logger.info(f"Weekly red team: {stats}")
    except Exception as e:
        logger.error(f"Weekly red team failed: {e}\n{traceback.format_exc()}")


def _run_monthly_red_team():
    """Scheduled task: Monthly full red team."""
    try:
        from services.feedback.red_team import run_monthly_red_team
        stats = asyncio.run(run_monthly_red_team())
        logger.info(f"Monthly red team: {stats}")
    except Exception as e:
        logger.error(f"Monthly red team failed: {e}\n{traceback.format_exc()}")


def _publish_feedback_complete(stats: Dict[str, Any]) -> None:
    """Publish feedback_complete to Redis with stats."""
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        message = json.dumps({
            "type": "feedback_complete",
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat(),
        })
        r.lpush(FEEDBACK_COMPLETE_QUEUE, message)
    except redis.RedisError as e:
        logger.warning(f"Redis unavailable for feedback_complete: {e}")
    except Exception as e:
        logger.error(f"Error publishing feedback_complete: {e}")


def _listen_for_analysis_complete(shutdown_event):
    """
    Listen on Redis for analysis_complete messages.
    When received, trigger immediate scoring to catch new predictions.
    """
    logger.info("Starting Redis listener for analysis_complete")

    while not shutdown_event.is_set():
        try:
            r = redis.from_url(settings.REDIS_URL, decode_responses=True)

            while not shutdown_event.is_set():
                result = r.brpop(ANALYSIS_COMPLETE_QUEUE, timeout=10)
                if result is None:
                    continue

                _, message_str = result
                try:
                    message = json.loads(message_str)
                    logger.info(
                        f"Received analysis_complete: "
                        f"agents={message.get('agents_run', '?')}, "
                        f"predictions_created={message.get('predictions_created', '?')}"
                    )

                    # Run immediate scoring
                    _run_scoring_cycle()

                except json.JSONDecodeError:
                    logger.warning(f"Invalid analysis_complete message: {message_str[:100]}")

        except redis.RedisError as e:
            logger.warning(f"Redis connection error: {e}. Retrying in 30s...")
            shutdown_event.wait(30)
        except Exception as e:
            logger.error(f"Redis listener error: {e}")
            shutdown_event.wait(30)


def run():
    """Main entry point for the feedback processor."""
    logger.info("=" * 60)
    logger.info("Feedback Processor starting")
    logger.info("=" * 60)

    import threading
    shutdown_event = threading.Event()

    # Set up graceful shutdown
    def handle_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Create scheduler
    scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,  # If job missed while another is running, skip
            "max_instances": 1,  # Only one instance of each job at a time
            "misfire_grace_time": 300,  # Allow 5 min grace for misfires
        }
    )

    # Schedule tasks
    scheduler.add_job(
        _run_scoring_cycle,
        IntervalTrigger(minutes=5),
        id="scoring_cycle",
        name="Scoring cycle (every 5 min)",
    )

    scheduler.add_job(
        _run_calibration_and_bias,
        IntervalTrigger(hours=1),
        id="calibration_bias",
        name="Calibration + bias detection (hourly)",
    )

    scheduler.add_job(
        _run_cross_agent_scan,
        IntervalTrigger(hours=2),
        id="cross_agent_scan",
        name="Cross-agent correlation scan (every 2 hours)",
    )

    scheduler.add_job(
        _run_sub_prediction_health,
        CronTrigger(hour=9, minute=0),  # Daily at 09:00 UTC
        id="sub_prediction_health",
        name="Sub-prediction health check (daily)",
    )

    scheduler.add_job(
        _run_weekly_red_team,
        CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="weekly_red_team",
        name="Weekly red team lite (Mondays 07:00 UTC)",
    )

    scheduler.add_job(
        _run_monthly_red_team,
        CronTrigger(day=1, hour=6, minute=0),
        id="monthly_red_team",
        name="Monthly red team full (1st of month 06:00 UTC)",
    )

    # Start scheduler
    scheduler.start()
    logger.info("APScheduler started with 6 scheduled tasks")

    # Start Redis listener in a separate thread
    redis_thread = threading.Thread(
        target=_listen_for_analysis_complete,
        args=(shutdown_event,),
        daemon=True,
    )
    redis_thread.start()
    logger.info("Redis listener started for analysis_complete queue")

    # Run initial scoring cycle on startup
    logger.info("Running initial scoring cycle...")
    _run_scoring_cycle()

    # Keep the main thread alive
    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=60)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        shutdown_event.set()
        redis_thread.join(timeout=5)
        logger.info("Feedback processor stopped")


if __name__ == "__main__":
    run()
