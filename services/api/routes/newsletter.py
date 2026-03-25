"""
Newsletter routes.
GET /newsletter/latest — get the most recent newsletter
POST /newsletter/generate — generate a new newsletter via Master Strategist
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.models import Prediction, Event, WeakSignal, Debate, Note, ConfidenceTrail
from shared.config import get_settings
from shared.llm_client import call_claude_sonnet
from services.api.auth import verify_api_key

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/newsletter", tags=["newsletter"])

# In-memory store for latest newsletter (simple for Phase 1)
_latest_newsletter = {"content": None, "generated_at": None, "generating": False}


class NewsletterResponse(BaseModel):
    content: Optional[str] = None
    generated_at: Optional[str] = None
    status: str = "empty"


NEWSLETTER_SYSTEM_PROMPT = """You are the Master Strategist of a multi-agent intelligence prediction system, writing a daily intelligence newsletter.

Write in the style of a senior intelligence analyst producing a morning briefing for policymakers and institutional investors. Your tone should be:
- Authoritative but not arrogant
- Specific and evidence-based, not vague
- Willing to make bold calls with clear reasoning
- Written like the best opinion pieces in the Financial Times or Foreign Affairs

NEWSLETTER STRUCTURE:

# Intelligence Brief — [Today's Date]

## Executive Summary
2-3 sentences capturing the single most important development and its implications.

## Key Developments
For each major theme (3-5 themes):
### [Theme Title]
Write 2-4 paragraphs as a mini opinion piece:
- What happened (specific events, data points, sources)
- Why it matters (structural analysis, not just surface description)
- Where consensus is wrong (your contrarian edge)
- What to watch next (specific triggers and timelines)

## Active Predictions
List the most important active predictions with current confidence levels and brief status updates. Group by domain.

## Convergence Alerts
Where multiple agents are flagging the same risk from different angles — these are the highest-conviction signals.

## Contrarian Corner
Your most controversial or non-consensus view, argued persuasively. This is where the system adds the most value.

## What We're Watching
3-5 specific events or data releases in the next 7 days that could shift the analysis.

Write the full newsletter in markdown format. Be specific, be bold, be useful."""


def _build_newsletter_context(db: Session) -> str:
    """Build context from current system state for newsletter generation."""
    parts = []

    # Recent events (last 24h)
    cutoff = datetime.utcnow() - timedelta(hours=24)
    events = (
        db.query(Event)
        .filter(Event.timestamp >= cutoff)
        .order_by(Event.timestamp.desc())
        .limit(50)
        .all()
    )
    if events:
        parts.append("## RECENT EVENTS (last 24h)")
        for e in events[:30]:
            severity_tag = f"[{e.severity.upper()}]" if e.severity else ""
            parts.append(f"- {severity_tag} [{e.domain}] {e.source}: {(e.raw_text or '')[:200]}")

    # Active predictions with reasoning
    predictions = (
        db.query(Prediction)
        .filter(Prediction.status == "ACTIVE")
        .order_by(Prediction.current_confidence.desc())
        .limit(30)
        .all()
    )
    if predictions:
        parts.append("\n## ACTIVE PREDICTIONS")
        for p in predictions:
            parts.append(f"- [{p.agent}] {p.current_confidence:.0%}: {p.claim}")
            # Get the initial reasoning
            trail = (
                db.query(ConfidenceTrail)
                .filter(ConfidenceTrail.prediction_id == p.id)
                .order_by(ConfidenceTrail.date.asc())
                .first()
            )
            if trail and trail.reasoning:
                parts.append(f"  Reasoning: {trail.reasoning[:300]}")

    # Recent debates
    debates = (
        db.query(Debate)
        .order_by(Debate.created_at.desc())
        .limit(5)
        .all()
    )
    if debates:
        parts.append("\n## RECENT DEBATES")
        for d in debates:
            parts.append(f"- [{d.agent}] {d.trigger_reason}")
            if d.rounds and isinstance(d.rounds, list):
                for r in d.rounds[:1]:
                    if isinstance(r, dict):
                        if r.get("devil"):
                            devil_text = r["devil"] if isinstance(r["devil"], str) else r["devil"].get("text", "")
                            parts.append(f"  Devil's advocate: {devil_text[:200]}")

    # Weak signals
    signals = (
        db.query(WeakSignal)
        .order_by(WeakSignal.detected_at.desc())
        .limit(10)
        .all()
    )
    if signals:
        parts.append("\n## WEAK SIGNALS")
        for s in signals:
            parts.append(f"- [{s.strength}] {s.signal[:200]}")

    # Key notes
    notes = (
        db.query(Note)
        .filter(Note.type.in_(["key_signal", "counter_signal", "analysis"]))
        .order_by(Note.date.desc())
        .limit(10)
        .all()
    )
    if notes:
        parts.append("\n## KEY ANALYST NOTES")
        for n in notes:
            parts.append(f"- [{n.type}] {n.text[:200]}")

    return "\n".join(parts)


async def _generate_newsletter(db: Session):
    """Generate newsletter using Claude."""
    global _latest_newsletter
    _latest_newsletter["generating"] = True

    try:
        context = _build_newsletter_context(db)
        today = datetime.utcnow().strftime("%B %d, %Y")

        user_message = f"""Today is {today}. Generate the daily intelligence newsletter based on the following system state:

{context}

Write the complete newsletter in markdown. Be specific, cite data points and events, make bold analytical calls with clear reasoning. This should read like the morning briefing a senior policymaker looks forward to reading."""

        response = await call_claude_sonnet(
            system_prompt=NEWSLETTER_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=8192,
            temperature=0.4,
        )

        _latest_newsletter["content"] = response
        _latest_newsletter["generated_at"] = datetime.utcnow().isoformat()
        _latest_newsletter["generating"] = False

        logger.info(f"Newsletter generated: {len(response)} chars")

    except Exception as e:
        logger.error(f"Newsletter generation failed: {e}")
        _latest_newsletter["generating"] = False
        _latest_newsletter["content"] = f"Newsletter generation failed: {str(e)[:200]}"
        _latest_newsletter["generated_at"] = datetime.utcnow().isoformat()


@router.get("/latest", response_model=NewsletterResponse)
async def get_latest_newsletter(
    _key: str = Depends(verify_api_key),
):
    """Get the most recently generated newsletter."""
    if _latest_newsletter["generating"]:
        return NewsletterResponse(status="generating")
    if _latest_newsletter["content"]:
        return NewsletterResponse(
            content=_latest_newsletter["content"],
            generated_at=_latest_newsletter["generated_at"],
            status="ready",
        )
    return NewsletterResponse(status="empty")


@router.post("/generate", response_model=NewsletterResponse)
async def generate_newsletter(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Generate a new daily intelligence newsletter."""
    if _latest_newsletter["generating"]:
        return NewsletterResponse(status="generating")

    # Run in background since it takes 30-60 seconds
    background_tasks.add_task(_generate_newsletter, db)

    return NewsletterResponse(
        status="generating",
        generated_at=datetime.utcnow().isoformat(),
    )
