"""
Newsletter routes — upgraded with full Intelligence Brief structure.

GET /newsletter/latest — get the most recent newsletter
POST /newsletter/generate — generate a new newsletter via Master Strategist

Newsletter structure:
1. Track Record (rolling 30-day scorecard)
2. The One Thing That Matters Today
3. Key Developments (3 argumentative sections with "WHAT TO DO")
4. Convergence Alerts
5. New Predictions
6. Prediction Scorecard
7. Contrarian Corner
8. What We're Watching
9. Portfolio Implications
10. Travel & Safety Advisory
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import desc, and_, func
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.models import Prediction, Event, WeakSignal, Debate, Note, ConfidenceTrail
from shared.config import get_settings
from shared.llm_client import call_claude_sonnet
from services.api.auth import verify_api_key

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/newsletter", tags=["newsletter"])

# In-memory store for latest newsletter
_latest_newsletter = {"content": None, "generated_at": None, "generating": False}


class NewsletterResponse(BaseModel):
    content: Optional[str] = None
    generated_at: Optional[str] = None
    status: str = "empty"


NEWSLETTER_SYSTEM_PROMPT = """You are the Master Strategist of a multi-agent intelligence prediction system, writing a daily intelligence newsletter.

## YOUR VOICE
Think: a brilliant friend who happens to be an ex-intelligence analyst, now running a macro hedge fund. They're having a drink with you and telling you what's REALLY going on. Not academic. Not breathless. Not hedged into meaninglessness.

Specific voice guidelines:
- CONFIDENT but not cocky: "We think X will happen (65%)" not "X is definitely happening"
- DIRECT, not diplomatic: "The Fed made a mistake" not "questions remain about the efficacy"
- SPECIFIC, not vague: "$3,400 by September" not "upward price pressure"
- HONEST about uncertainty: "We genuinely don't know" is acceptable when true
- EXPLAIN THE WHY: Walk through the causal logic so readers learn to think this way
- OCCASIONAL IRREVERENCE: A well-placed blunt observation keeps readers engaged

BANNED PHRASES (never use these):
- "it remains to be seen"
- "only time will tell"
- "a complex and evolving situation"
- "stakeholders should monitor developments"
- "cautious optimism"
- "amid growing concerns"

## NEWSLETTER STRUCTURE — FOLLOW THIS EXACTLY

# THE INTELLIGENCE BRIEF — [Today's Date]

## 📊 TRACK RECORD
[Use the scorecard data provided. Show: predictions resolved, hit rate, Brier score. 
If no data yet, say "System is in calibration phase — first scores expected in 30 days."]

## 🎯 THE ONE THING THAT MATTERS TODAY
[2-3 sentences MAXIMUM. The single most important signal the system detected. 
What happened, why it matters, and what happens next. This is the hook — 
if someone reads nothing else, this must be worth their time.]

## 📝 KEY DEVELOPMENTS
[EXACTLY 3 sections. Each is a MINI OPINION PIECE — argumentative, not descriptive.
Each section follows this pattern:]

### [Argumentative Headline — a THESIS, not a summary]
[3-5 paragraphs. Not "what happened" but "what this MEANS." Trace the causal chain
through cascading consequences. Name specific numbers, dates, entities. 
End with specific implications.]

→ **WHAT TO DO:** [1-2 sentences of specific, actionable guidance]

## 🔴 CONVERGENCE ALERTS
[Only include if 3+ agents flagged the same risk from different angles.
For each alert: which agents, what signal from each, synthesized prediction with confidence,
and what to do about it. If no convergence this cycle, omit this section entirely.]

## 🔮 NEW PREDICTIONS
[List each new prediction with: claim, confidence %, deadline, category emoji.
Group by category. Maximum 6-8 predictions — quality over quantity.]

## ✅ PREDICTION SCORECARD
[Recently resolved predictions (last 7 days) with outcomes.
Active high-conviction predictions (>70%) with status updates.
Format: ✓ for correct, ✗ for incorrect, • for active.]

## 😈 CONTRARIAN CORNER
[The Devil's Advocate's best argument this week. What's one thing "everyone knows"
that might be wrong? Written as a provocative 2-3 paragraph argument.
This section should make the reader uncomfortable in a productive way.]

## 👁️ WHAT WE'RE WATCHING
[3-5 specific events or data releases in the next 7 days.
For each: date, what it is, why it matters, what outcome would be bullish vs bearish.]

## 💼 PORTFOLIO IMPLICATIONS
[Net positioning recommendation based on today's analysis.
Specific positions to add/reduce/hedge. Key price levels to watch.
If no market-moving analysis today, keep brief.]

## ✈️ TRAVEL & SAFETY ADVISORY
[Any new city/region risk changes. Flight route disruptions to watch.
Only include if relevant — don't force this section if nothing has changed.]

---

Write the FULL newsletter in markdown format. 8-12 minute read maximum.
Lead with JUDGMENT, not summary. Every section must have a "do this."
"""


def _build_newsletter_context(db: Session) -> str:
    """Build comprehensive context from current system state."""
    parts = []

    # --- Track record data ---
    parts.append("## SYSTEM SCORECARD DATA")

    # Count resolved predictions in last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    resolved = (
        db.query(Prediction)
        .filter(
            Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]),
            Prediction.resolved_date >= thirty_days_ago.date(),
        )
        .all()
    )

    correct = sum(1 for p in resolved if p.status == "RESOLVED_TRUE")
    total_resolved = len(resolved)
    hit_rate = (correct / total_resolved * 100) if total_resolved > 0 else 0
    brier_scores = [p.brier_score for p in resolved if p.brier_score is not None]
    avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

    parts.append(f"Predictions resolved (30 days): {total_resolved}")
    parts.append(f"Correct: {correct} ({hit_rate:.0f}%)")
    if avg_brier is not None:
        parts.append(f"Average Brier Score: {avg_brier:.3f}")
    else:
        parts.append("Brier Score: Not yet available (need more resolved predictions)")

    # Recently resolved (last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recently_resolved = (
        db.query(Prediction)
        .filter(
            Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]),
            Prediction.resolved_date >= seven_days_ago.date(),
        )
        .order_by(Prediction.resolved_date.desc())
        .limit(10)
        .all()
    )
    if recently_resolved:
        parts.append("\nRecently Resolved (last 7 days):")
        for p in recently_resolved:
            outcome = "✓ TRUE" if p.status == "RESOLVED_TRUE" else "✗ FALSE"
            brier = f" (Brier: {p.brier_score:.2f})" if p.brier_score else ""
            parts.append(f"  {outcome} [{p.agent}] {p.current_confidence:.0%}: {p.claim[:150]}{brier}")

    # --- Recent events (last 24h) ---
    cutoff = datetime.utcnow() - timedelta(hours=24)
    events = (
        db.query(Event)
        .filter(Event.timestamp >= cutoff)
        .order_by(Event.timestamp.desc())
        .limit(50)
        .all()
    )
    if events:
        parts.append("\n## RECENT EVENTS (last 24h)")
        for e in events[:40]:
            severity_tag = f"[{e.severity.upper()}]" if e.severity else ""
            parts.append(f"- {severity_tag} [{e.domain}] {e.source}: {(e.raw_text or '')[:250]}")

    # --- Active predictions with reasoning ---
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
            deadline = ""
            if p.time_condition_end:
                deadline = f" (deadline: {p.time_condition_end})"
            parts.append(f"- [{p.agent}] {p.current_confidence:.0%}{deadline}: {p.claim[:200]}")
            # Get initial reasoning
            trail = (
                db.query(ConfidenceTrail)
                .filter(ConfidenceTrail.prediction_id == p.id)
                .order_by(ConfidenceTrail.date.asc())
                .first()
            )
            if trail and trail.reasoning:
                parts.append(f"  Reasoning: {trail.reasoning[:300]}")

    # --- High-conviction predictions (>70%) for scorecard ---
    high_conv = [p for p in (predictions or []) if p.current_confidence >= 0.70]
    if high_conv:
        parts.append("\n## HIGH-CONVICTION PREDICTIONS (>70%)")
        for p in high_conv[:10]:
            parts.append(f"- [{p.agent}] {p.current_confidence:.0%}: {p.claim[:200]}")

    # --- Recent debates (contrarian corner material) ---
    debates = (
        db.query(Debate)
        .order_by(Debate.created_at.desc())
        .limit(5)
        .all()
    )
    if debates:
        parts.append("\n## RECENT DEVIL'S ADVOCATE DEBATES")
        for d in debates:
            parts.append(f"- [{d.agent}] Trigger: {d.trigger_reason}")
            if d.rounds and isinstance(d.rounds, list):
                for r in d.rounds[:1]:
                    if isinstance(r, dict) and r.get("devil"):
                        devil = r["devil"]
                        if isinstance(devil, dict):
                            assessment = devil.get("overall_assessment", "")
                            strongest = devil.get("strongest_weakness", "")
                            alt = devil.get("alternative_scenario", "")
                            parts.append(f"  Assessment: {assessment[:200]}")
                            parts.append(f"  Strongest weakness: {strongest[:200]}")
                            parts.append(f"  Alternative scenario: {alt[:200]}")

    # --- Weak signals ---
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

    # --- Key analyst notes ---
    notes = (
        db.query(Note)
        .filter(Note.type.in_(["key_signal", "counter_signal", "analysis", "blind_spot", "convergence"]))
        .order_by(Note.date.desc())
        .limit(15)
        .all()
    )
    if notes:
        parts.append("\n## KEY ANALYST NOTES")
        for n in notes:
            parts.append(f"- [{n.type}] {n.text[:250]}")

    return "\n".join(parts)


async def _generate_newsletter(db: Session):
    """Generate newsletter using Claude."""
    global _latest_newsletter
    _latest_newsletter["generating"] = True

    try:
        context = _build_newsletter_context(db)
        today = datetime.utcnow().strftime("%B %d, %Y")

        user_message = f"""Today is {today}. Generate the daily intelligence newsletter.

SYSTEM STATE:
{context}

INSTRUCTIONS:
1. Follow the newsletter structure EXACTLY as specified in your system prompt.
2. Lead with JUDGMENT, not summary — the reader knows what happened; they want to know what it MEANS.
3. Every Key Development section must have an argumentative headline (a thesis, not a description).
4. Every section must end with actionable guidance (the "WHAT TO DO").
5. Include the Track Record scorecard using the data provided.
6. For the Prediction Scorecard, use the recently resolved and high-conviction data provided.
7. For Contrarian Corner, use the Devil's Advocate debate material provided.
8. Be SPECIFIC — cite actual numbers, dates, prices, entities.
9. Respect the 8-12 minute read limit — be concise and cut anything that doesn't add value.
10. If data is thin in any section, acknowledge it briefly and move on — don't pad.

Write the complete newsletter in markdown."""

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

    background_tasks.add_task(_generate_newsletter, db)

    return NewsletterResponse(
        status="generating",
        generated_at=datetime.utcnow().isoformat(),
    )
