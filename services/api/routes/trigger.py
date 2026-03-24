"""
Trigger routes.
POST /trigger/ingestion — manually trigger data ingestion
POST /trigger/agents — manually trigger agent analysis
POST /trigger/feedback — manually trigger feedback cycle
POST /trigger/signals — manually trigger weak signal scan
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel

from shared.config import get_settings
from shared.utils import setup_logging
from services.api.auth import verify_api_key

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/trigger", tags=["trigger"])


class TriggerResponse(BaseModel):
    status: str
    service: str
    message: str
    triggered_at: str


def _run_ingestion():
    """Run ingestion in background."""
    try:
        from services.ingestion.main import run
        run()
    except Exception as e:
        logger.error(f"Ingestion trigger failed: {e}")


def _run_agents():
    """Run agents in background."""
    try:
        from services.agents.main import run
        run()
    except Exception as e:
        logger.error(f"Agents trigger failed: {e}")


def _run_feedback():
    """Run feedback scoring cycle in background."""
    try:
        from services.feedback.scorer import run_scoring_cycle
        from services.feedback.calibration import rebuild_calibration_curves
        run_scoring_cycle()
        rebuild_calibration_curves()
    except Exception as e:
        logger.error(f"Feedback trigger failed: {e}")


def _run_signals():
    """Run signal scan in background."""
    try:
        from services.signals.main import run
        run()
    except Exception as e:
        logger.error(f"Signals trigger failed: {e}")


@router.post("/ingestion", response_model=TriggerResponse)
async def trigger_ingestion(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Manually trigger data ingestion cycle."""
    background_tasks.add_task(_run_ingestion)
    return TriggerResponse(
        status="triggered",
        service="ingestion",
        message="Data ingestion started in background. Check events page for results.",
        triggered_at=datetime.utcnow().isoformat(),
    )


@router.post("/agents", response_model=TriggerResponse)
async def trigger_agents(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Manually trigger agent analysis cycle."""
    background_tasks.add_task(_run_agents)
    return TriggerResponse(
        status="triggered",
        service="agents",
        message="Agent analysis started in background. Check predictions page for results.",
        triggered_at=datetime.utcnow().isoformat(),
    )


@router.post("/feedback", response_model=TriggerResponse)
async def trigger_feedback(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Manually trigger feedback/scoring cycle."""
    background_tasks.add_task(_run_feedback)
    return TriggerResponse(
        status="triggered",
        service="feedback",
        message="Feedback cycle started in background. Check calibration for results.",
        triggered_at=datetime.utcnow().isoformat(),
    )


@router.post("/signals", response_model=TriggerResponse)
async def trigger_signals(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_api_key),
):
    """Manually trigger weak signal scan."""
    background_tasks.add_task(_run_signals)
    return TriggerResponse(
        status="triggered",
        service="signals",
        message="Signal scan started in background. Check signals page for results.",
        triggered_at=datetime.utcnow().isoformat(),
    )
