"""
Trend Tracker API routes.

GET    /trends                — Get latest trend analysis results
POST   /trends/analyze        — Trigger manual trend analysis (all or specific variables)
GET    /trends/variables      — List all tracked variables
"""

import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel, Field

from services.api.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trends", tags=["trend_tracker"])


# =============================================================================
# SCHEMAS
# =============================================================================

class TrendAnalysisRequest(BaseModel):
    variables: Optional[List[str]] = Field(
        None,
        description="Specific variable keys to analyze. If null, analyzes all."
    )


class VariableInfo(BaseModel):
    key: str
    label: str
    domain: str
    description: str


class TrendResult(BaseModel):
    variable_key: str
    variable_label: str
    domain: str
    direction: str
    confidence_in_direction: Optional[int]
    current_assessment: Optional[str]
    key_data_points: List[str] = []
    implications: List[str] = []
    watch_items: List[str] = []
    severity: Optional[str]
    analyzed_at: Optional[str]


# =============================================================================
# IN-MEMORY CACHE for latest results (persists between requests within the service)
# =============================================================================

_latest_trend_results: List[dict] = []
_last_analysis_time: Optional[datetime] = None


# =============================================================================
# ROUTES
# =============================================================================

@router.get("/variables", response_model=List[VariableInfo])
async def list_tracked_variables(
    _key: str = Depends(verify_api_key),
):
    """List all structural variables tracked by the Trend Tracker."""
    from services.agents.trend_tracker import TRACKED_VARIABLES

    return [
        VariableInfo(
            key=key,
            label=config["label"],
            domain=config["domain"],
            description=config["description"],
        )
        for key, config in TRACKED_VARIABLES.items()
    ]


@router.get("", response_model=dict)
async def get_trend_results(
    _key: str = Depends(verify_api_key),
):
    """Get the latest trend analysis results."""
    global _latest_trend_results, _last_analysis_time

    if not _latest_trend_results:
        return {
            "status": "no_data",
            "message": "No trend analysis has been run yet. POST /trends/analyze to trigger one.",
            "last_analysis": None,
            "results": [],
        }

    return {
        "status": "ok",
        "last_analysis": _last_analysis_time.isoformat() if _last_analysis_time else None,
        "results_count": len(_latest_trend_results),
        "results": _latest_trend_results,
    }


@router.post("/analyze", response_model=dict)
async def trigger_trend_analysis(
    body: Optional[TrendAnalysisRequest] = None,
    background_tasks: BackgroundTasks = None,
    _key: str = Depends(verify_api_key),
):
    """Trigger a manual trend analysis. Runs in background."""
    variables = body.variables if body else None

    background_tasks.add_task(_run_analysis_background, variables)

    return {
        "status": "analyzing",
        "message": "Trend analysis started in background. Check GET /trends for results.",
        "variables": variables or "all",
    }


async def _run_analysis_background(variables: Optional[List[str]] = None):
    """Background task to run trend analysis and cache results."""
    global _latest_trend_results, _last_analysis_time

    try:
        from services.agents.trend_tracker import run_weekly_trend_analysis

        stats = await run_weekly_trend_analysis(variables=variables)
        _latest_trend_results = stats.get("full_analyses", [])
        _last_analysis_time = datetime.utcnow()

        logger.info(
            f"Trend analysis complete: {stats.get('variables_analyzed', 0)} variables, "
            f"accelerating: {stats.get('accelerating', [])}"
        )
    except Exception as e:
        logger.error(f"Background trend analysis failed: {e}")
