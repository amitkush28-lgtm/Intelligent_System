"""
Weak Signal Scanner — Orchestrator.

Triggered by Railway cron daily at 06:00 UTC.
Runs orphan scanner + anomaly detector daily, pre-mortem weekly.
Publishes signals_complete to Redis.
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime
from typing import Dict, Any

import redis

from shared.config import get_settings
from shared.utils import setup_logging

logger = setup_logging("signals")
settings = get_settings()

SIGNALS_COMPLETE_QUEUE = "signals_complete"


def _run_orphan_scan() -> Dict[str, Any]:
    """Run the orphan event scanner."""
    try:
        from services.signals.orphan_scanner import scan_orphan_events
        stats = scan_orphan_events()
        logger.info(f"Orphan scan: {stats}")
        return stats
    except Exception as e:
        logger.error(f"Orphan scan failed: {e}\n{traceback.format_exc()}")
        return {"errors": 1}


def _run_anomaly_detection() -> Dict[str, Any]:
    """Run the anomaly detector."""
    try:
        from services.signals.anomaly_detector import detect_anomalies
        stats = detect_anomalies()
        logger.info(f"Anomaly detection: {stats}")
        return stats
    except Exception as e:
        logger.error(f"Anomaly detection failed: {e}\n{traceback.format_exc()}")
        return {"errors": 1}


def _run_premortem() -> Dict[str, Any]:
    """Run the pre-mortem analysis (weekly)."""
    try:
        from services.signals.premortem import run_premortem
        stats = asyncio.run(run_premortem())
        logger.info(f"Pre-mortem: {stats}")
        return stats
    except Exception as e:
        logger.error(f"Pre-mortem failed: {e}\n{traceback.format_exc()}")
        return {"errors": 1}


def _should_run_premortem() -> bool:
    """
    Pre-mortem runs weekly (on Mondays) instead of daily.
    Check if today is the right day.
    """
    return datetime.utcnow().weekday() == 0  # Monday


def _publish_signals_complete(stats: Dict[str, Any]) -> None:
    """Publish signals_complete to Redis."""
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        message = json.dumps({
            "type": "signals_complete",
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat(),
        })
        r.lpush(SIGNALS_COMPLETE_QUEUE, message)
        logger.info("Published signals_complete to Redis")
    except redis.RedisError as e:
        logger.warning(f"Redis unavailable for signals_complete: {e}")
    except Exception as e:
        logger.error(f"Error publishing signals_complete: {e}")


def run():
    """Main entry point — called by Railway cron daily at 06:00 UTC."""
    logger.info("=" * 60)
    logger.info("Weak Signal Scanner starting")
    logger.info("=" * 60)

    all_stats = {
        "orphan_scan": {},
        "anomaly_detection": {},
        "premortem": {},
        "start_time": datetime.utcnow().isoformat(),
    }

    # 1. Always run orphan scan
    logger.info("Step 1/3: Orphan event scan")
    all_stats["orphan_scan"] = _run_orphan_scan()

    # 2. Always run anomaly detection
    logger.info("Step 2/3: Anomaly detection")
    all_stats["anomaly_detection"] = _run_anomaly_detection()

    # 3. Run pre-mortem weekly (Mondays only)
    if _should_run_premortem():
        logger.info("Step 3/3: Pre-mortem analysis (weekly)")
        all_stats["premortem"] = _run_premortem()
    else:
        logger.info("Step 3/3: Pre-mortem skipped (not Monday)")
        all_stats["premortem"] = {"skipped": True}

    all_stats["end_time"] = datetime.utcnow().isoformat()

    # Publish completion
    _publish_signals_complete(all_stats)

    logger.info("=" * 60)
    logger.info("Weak Signal Scanner complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
