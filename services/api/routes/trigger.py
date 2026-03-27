"""
Pipeline trigger routes.
POST /trigger/ingestion — run data ingestion
POST /trigger/agents — run agent analysis
POST /trigger/feedback — run feedback + auto-resolution
POST /trigger/signals — run weak signal scanner
POST /trigger/resolve — run auto-resolution only
"""

import asyncio
import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from shared.config import get_settings
from services.api.auth import verify_api_key

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/trigger", tags=["trigger"])


@router.post("/ingestion")
async def trigger_ingestion(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Trigger data ingestion pipeline."""
    async def _run():
        try:
            from services.ingestion.main import run_async
            await run_async()
        except Exception as e:
            logger.error(f"Ingestion trigger failed: {e}")

    background_tasks.add_task(asyncio.run, _run())
    return {"status": "triggered", "service": "ingestion"}


@router.post("/agents")
async def trigger_agents(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Trigger agent analysis cycle."""
    async def _run():
        try:
            from services.agents.main import run_async
            await run_async()
        except Exception as e:
            logger.error(f"Agents trigger failed: {e}")

    background_tasks.add_task(asyncio.run, _run())
    return {"status": "triggered", "service": "agents"}


@router.post("/feedback")
async def trigger_feedback(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Trigger feedback cycle: scoring + calibration + auto-resolution."""
    async def _run():
        try:
            # Step 1: Standard scoring (expire past-deadline predictions)
            from services.feedback.scorer import run_scoring_cycle
            score_stats = run_scoring_cycle()
            logger.info(f"Scoring cycle: {score_stats}")

            # Step 2: Calibration
            from services.feedback.calibration import rebuild_calibration_curves
            cal_stats = rebuild_calibration_curves()
            logger.info(f"Calibration: {cal_stats}")

            # Step 3: Auto-resolution (LLM checks predictions against reality)
            from services.feedback.auto_resolver import run_auto_resolution
            resolve_stats = await run_auto_resolution()
            logger.info(f"Auto-resolution: {resolve_stats}")

        except Exception as e:
            logger.error(f"Feedback trigger failed: {e}")

    background_tasks.add_task(asyncio.run, _run())
    return {"status": "triggered", "service": "feedback"}


@router.post("/signals")
async def trigger_signals(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Trigger weak signal scanner."""
    async def _run():
        try:
            from services.signals.main import run_async
            await run_async()
        except Exception as e:
            logger.error(f"Signals trigger failed: {e}")

    background_tasks.add_task(asyncio.run, _run())
    return {"status": "triggered", "service": "signals"}


@router.post("/resolve")
async def trigger_resolve(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Trigger auto-resolution only (check predictions against reality via web search)."""
    async def _run():
        try:
            from services.feedback.auto_resolver import run_auto_resolution
            stats = await run_auto_resolution()
            logger.info(f"Auto-resolution: {stats}")
        except Exception as e:
            logger.error(f"Resolution trigger failed: {e}")

    background_tasks.add_task(asyncio.run, _run())
    return {"status": "triggered", "service": "auto_resolver"}
