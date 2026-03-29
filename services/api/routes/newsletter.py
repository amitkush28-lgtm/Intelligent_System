"""
Newsletter routes — multi-cadence support (daily, weekly, monthly, yearly).

GET /newsletter/latest?cadence=daily — get the most recent newsletter of a specific cadence
POST /newsletter/generate?cadence=daily — generate a new newsletter (default: daily)

Cadences supported:
- daily: 8-12 min read, 24h context, all 10 sections
- weekly: 15-20 min read, 7d context, 6 sections (Week in Review, Key Themes, Prediction Performance, etc.)
- monthly: 25-30 min read, 30d context, 9 sections (Executive Summary, Month in Numbers, Macro Regime, etc.)
- yearly: 45-60 min read, 365d context, 7 sections (Year in Review, Big Calls, System Performance, etc.)
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Query
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

# In-memory store for latest newsletters by cadence
_latest_newsletters = {
    "daily": {"content": None, "generated_at": None, "generating": False},
    "weekly": {"content": None, "generated_at": None, "generating": False},
    "monthly": {"content": None, "generated_at": None, "generating": False},
    "yearly": {"content": None, "generated_at": None, "generating": False},
}


class NewsletterResponse(BaseModel):
    content: Optional[str] = None
    generated_at: Optional[str] = None
    status: str = "empty"


# BANNED PHRASES (never use these, across all cadences)
BANNED_PHRASES = [
    "it remains to be seen",
    "only time will tell",
    "a complex and evolving situation",
    "stakeholders should monitor developments",
    "cautious optimism",
    "amid growing concerns",
]

# VOICE GUIDELINES (consistent across all cadences)
SHARED_VOICE_GUIDELINES = """## YOUR VOICE
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
"""

DAILY_SYSTEM_PROMPT = """You are the Master Strategist of a multi-agent intelligence prediction system, writing a daily intelligence newsletter.

""" + SHARED_VOICE_GUIDELINES + """

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

WEEKLY_SYSTEM_PROMPT = """You are the Master Strategist of a multi-agent intelligence prediction system, writing a weekly intelligence newsletter.

""" + SHARED_VOICE_GUIDELINES + """

## NEWSLETTER STRUCTURE — FOLLOW THIS EXACTLY

# WEEKLY INTELLIGENCE BRIEF — [Week of Date]

## 📊 WEEK IN REVIEW
[Biggest moves and signals this week. Lead with the 3-4 most significant developments.
This is your hook — what made this week matter? More reflective than daily, stepping back from noise.]

## 🎯 KEY THEMES
[EXACTLY 3 thematic deep-dives across the week's events. Not chronological, but thematic —
what patterns connect seemingly different events? Trace second and third-order consequences.
Each theme: 3-4 paragraphs, ending with "→ **WHAT TO DO:**" guidance.]

### [Theme 1: Overarching Pattern or Risk]
[Analysis]

→ **WHAT TO DO:** [Guidance]

### [Theme 2: Overarching Pattern or Risk]
[Analysis]

→ **WHAT TO DO:** [Guidance]

### [Theme 3: Overarching Pattern or Risk]
[Analysis]

→ **WHAT TO DO:** [Guidance]

## 📈 PREDICTION PERFORMANCE
[Weekly scorecard: resolved predictions, hit rate, trending accuracy.
Active high-conviction predictions (>70%) and their week-over-week confidence changes.
More strategic than daily — show patterns and learning.]

## ❓ LIVING QUESTIONS UPDATE
[How this week's evidence updated our active living questions. Which are tracking true?
Which are becoming falsified? New evidence, new probabilities.]

## 📅 WEEK AHEAD CALENDAR
[Key events/data releases next week. For each: date, what, why it matters, bull/bear outcomes.
3-5 items maximum — focus on market-moving events.]

## 💼 PORTFOLIO POSITIONING
[Week's net positioning recommendation. Specific positions, hedges, rotations.
How has the week changed our macro thesis?]

---

Write the FULL newsletter in markdown format. 15-20 minute read maximum.
Voice: more reflective, pattern-spotting, "stepping back from the noise."
Every section must have a "do this." Lead with judgment and synthesis, not summary.
"""

MONTHLY_SYSTEM_PROMPT = """You are the Master Strategist of a multi-agent intelligence prediction system, writing a monthly strategic intelligence newsletter.

""" + SHARED_VOICE_GUIDELINES + """

## NEWSLETTER STRUCTURE — FOLLOW THIS EXACTLY

# MONTHLY STRATEGIC REVIEW — [Month/Year]

## 📋 EXECUTIVE SUMMARY
[The single most important insight from the month. What regime are we in?
What's the one call that matters most? 2-3 paragraphs maximum.]

## 📊 MONTH IN NUMBERS
[Full scorecard: predictions resolved this month, hit rate trend, Brier score.
Portfolio performance attribution. Key market moves (% changes, absolute levels).
This is the dashboard view of the month.]

## 🌍 MACRO REGIME ASSESSMENT
[Are we in risk-on or risk-off? Are rates rising or falling? Is the macro backdrop
supportive for growth, stagflation, deflation? How has this month's data updated our regime assessment?
2-3 paragraphs, ending with "→ **IMPLICATIONS:**"]

## 🔄 SECTOR ROTATION THESIS
[How should positioning rotate based on this month's macro thesis?
Which sectors benefit, which suffer? Relative value calls.
Specific recommended rotations.]

## ⚠️ GEOPOLITICAL RISK MAP
[Major geopolitical risks and how they've evolved this month.
New hot spots, de-escalations, cascading effects.
Risk/reward assessment for next month.]

## 🎯 PREDICTION ACCURACY DEEP-DIVE
[What did we get right this month and why? What did we get wrong and what's the lesson?
How are our core frameworks holding up under this month's evidence?
Are we overconfident or underconfident in specific domains?]

## ❓ LIVING QUESTIONS DASHBOARD
[Full status of all active living questions. Which are tracking true?
Which are on the edge of falsification? Where's the evidence pointing?
New questions that emerged this month.]

## 📈 STRATEGIC POSITIONING
[Month-end net positioning. Major bets, hedges, convictions.
How has positioning shifted from month start? Why?]

## 😈 CONTRARIAN THESIS OF THE MONTH
[The one contrarian bet we're making. What's "everyone knows" that might be wrong?
Why are we positioned against the consensus? What would prove us wrong?]

---

Write the FULL newsletter in markdown format. 25-30 minute read maximum.
Voice: more authoritative, strategic, connecting dots across weeks.
This is your "state of the system" address. Lead with judgment.
"""

YEARLY_SYSTEM_PROMPT = """You are the Master Strategist of a multi-agent intelligence prediction system, writing an annual intelligence review and outlook.

""" + SHARED_VOICE_GUIDELINES + """

## NEWSLETTER STRUCTURE — FOLLOW THIS EXACTLY

# ANNUAL INTELLIGENCE REVIEW & OUTLOOK — [Year]

## 📖 YEAR IN REVIEW
[The big picture: what was the defining macro narrative of the year?
What was the biggest surprise? How did the year unfold differently than we expected at year-start?
3-4 paragraphs setting the tone for the review.]

## ✅ THE BIG CALLS: WHAT WE GOT RIGHT
[The predictions we nailed this year. Why did we get these right?
What did the system do well? Pattern recognition? Forecasting? Probabilistic thinking?
2-3 major calls with explanation.]

## ❌ THE BIG CALLS: WHAT WE GOT WRONG
[The predictions we missed badly. Why? Did our models fail? Was it bad luck?
What's the honest post-mortem? 2-3 major misses with brutal honesty.]

## 📊 SYSTEM PERFORMANCE AUDIT
[Full year scorecard: total predictions, resolution rate, hit rate trend across quarters,
Brier score evolution, calibration analysis.
Portfolio performance vs. major indices.
This is your annual report card.]

## 🌍 MACRO REGIME SHIFTS
[What were the year's defining macro regime changes?
From [regime A] to [regime B]. Evidence. Timing. Consequences.
How did year-end regimes differ from year-start?]

## 🔮 TOP 10 PREDICTIONS: WHAT CAME TRUE
[The 10 biggest predictions we got right or are tracking well toward resolution.
These are your trophy calls. Headlines and confidence levels.]

## 🎓 LESSONS LEARNED
[The system's biggest lessons from this year.
Where did our frameworks break? Where did they shine?
What do we believe differently now than year-start?
3-5 key lessons, candidly stated.]

## 🔮 YEAR AHEAD FRAMEWORK
[Big calls for next year. Macro thesis. Top 10 predictions for year ahead.
Where we're most confident. Where we're most uncertain.
The fundamental thesis that drives all year-ahead positioning.]

---

Write the FULL newsletter in markdown format. 45-60 minute read maximum.
Voice: reflective, honest self-assessment, forward-looking. This is your annual address.
Be brutally honest about failures. Celebrate wins. Chart the course for next year.
Lead with judgment and learning.
"""


def _build_newsletter_context(db: Session, cadence: str = "daily") -> str:
    """Build comprehensive context from current system state, adjusted for cadence.

    Cadence determines:
    - daily: 24h events, 7d resolved predictions
    - weekly: 7d events, 14d resolved predictions
    - monthly: 30d events, 30d resolved predictions
    - yearly: 365d events, all resolved predictions
    """
    parts = []

    # Determine lookback windows based on cadence
    if cadence == "daily":
        event_lookback = timedelta(hours=24)
        recent_lookback = timedelta(days=7)
        resolved_lookback = timedelta(days=7)
    elif cadence == "weekly":
        event_lookback = timedelta(days=7)
        recent_lookback = timedelta(days=14)
        resolved_lookback = timedelta(days=14)
    elif cadence == "monthly":
        event_lookback = timedelta(days=30)
        recent_lookback = timedelta(days=30)
        resolved_lookback = timedelta(days=30)
    elif cadence == "yearly":
        event_lookback = timedelta(days=365)
        recent_lookback = timedelta(days=365)
        resolved_lookback = timedelta(days=10000)  # All
    else:
        # Default to daily
        event_lookback = timedelta(hours=24)
        recent_lookback = timedelta(days=7)
        resolved_lookback = timedelta(days=7)

    parts.append("## SYSTEM SCORECARD DATA")

    # --- Track record data ---
    # For monthly/yearly, look at longer windows
    if cadence == "yearly":
        scorecard_window = timedelta(days=365)
    elif cadence == "monthly":
        scorecard_window = timedelta(days=30)
    else:
        scorecard_window = timedelta(days=30)

    scorecard_cutoff = datetime.utcnow() - scorecard_window
    resolved = (
        db.query(Prediction)
        .filter(
            Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]),
            Prediction.resolved_date >= scorecard_cutoff.date(),
        )
        .all()
    )

    correct = sum(1 for p in resolved if p.status == "RESOLVED_TRUE")
    total_resolved = len(resolved)
    hit_rate = (correct / total_resolved * 100) if total_resolved > 0 else 0
    brier_scores = [p.brier_score for p in resolved if p.brier_score is not None]
    avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

    period_label = f"{scorecard_window.days} days"
    parts.append(f"Predictions resolved ({period_label}): {total_resolved}")
    parts.append(f"Correct: {correct} ({hit_rate:.0f}%)")
    if avg_brier is not None:
        parts.append(f"Average Brier Score: {avg_brier:.3f}")
    else:
        parts.append("Brier Score: Not yet available (need more resolved predictions)")

    # Recently resolved (within recent lookback)
    recent_cutoff = datetime.utcnow() - recent_lookback
    recently_resolved = (
        db.query(Prediction)
        .filter(
            Prediction.status.in_(["RESOLVED_TRUE", "RESOLVED_FALSE"]),
            Prediction.resolved_date >= recent_cutoff.date(),
        )
        .order_by(Prediction.resolved_date.desc())
        .limit(20)
        .all()
    )
    if recently_resolved:
        parts.append(f"\nRecently Resolved ({recent_lookback.days}d window):")
        for p in recently_resolved:
            outcome = "✓ TRUE" if p.status == "RESOLVED_TRUE" else "✗ FALSE"
            brier = f" (Brier: {p.brier_score:.2f})" if p.brier_score else ""
            parts.append(f"  {outcome} [{p.agent}] {p.current_confidence:.0%}: {p.claim[:150]}{brier}")

    # --- Recent events (within lookback window) ---
    cutoff = datetime.utcnow() - event_lookback
    events = (
        db.query(Event)
        .filter(Event.timestamp >= cutoff)
        .order_by(Event.timestamp.desc())
        .limit(50)
        .all()
    )
    event_label = f"{event_lookback.days if event_lookback.days > 0 else '24h'}"
    if events:
        parts.append(f"\n## RECENT EVENTS (last {event_label})")
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


def _get_system_prompt_for_cadence(cadence: str) -> str:
    """Get the appropriate system prompt for the cadence."""
    if cadence == "weekly":
        return WEEKLY_SYSTEM_PROMPT
    elif cadence == "monthly":
        return MONTHLY_SYSTEM_PROMPT
    elif cadence == "yearly":
        return YEARLY_SYSTEM_PROMPT
    else:
        return DAILY_SYSTEM_PROMPT


async def _generate_newsletter(db: Session, cadence: str = "daily"):
    """Generate newsletter using Claude, with cadence support.

    Args:
        db: Database session
        cadence: One of 'daily', 'weekly', 'monthly', 'yearly'
    """
    global _latest_newsletters

    if cadence not in _latest_newsletters:
        cadence = "daily"

    _latest_newsletters[cadence]["generating"] = True

    try:
        context = _build_newsletter_context(db, cadence=cadence)
        today = datetime.utcnow().strftime("%B %d, %Y")

        system_prompt = _get_system_prompt_for_cadence(cadence)

        # Customize the instruction message based on cadence
        if cadence == "weekly":
            cadence_instruction = "Generate the weekly intelligence newsletter."
            read_time = "15-20 minute read limit"
        elif cadence == "monthly":
            cadence_instruction = "Generate the monthly strategic intelligence newsletter."
            read_time = "25-30 minute read limit"
        elif cadence == "yearly":
            cadence_instruction = "Generate the annual intelligence review and outlook."
            read_time = "45-60 minute read limit"
        else:
            cadence_instruction = "Generate the daily intelligence newsletter."
            read_time = "8-12 minute read limit"

        user_message = f"""Today is {today}. {cadence_instruction}

SYSTEM STATE:
{context}

INSTRUCTIONS:
1. Follow the newsletter structure EXACTLY as specified in your system prompt.
2. Lead with JUDGMENT, not summary — the reader knows what happened; they want to know what it MEANS.
3. Every argumentative section must have a thesis (not a description) and end with actionable guidance.
4. Include the Track Record scorecard using the data provided.
5. Use the Devil's Advocate debate material for contrarian sections.
6. Be SPECIFIC — cite actual numbers, dates, prices, entities.
7. Respect the {read_time} — be concise and cut anything that doesn't add value.
8. If data is thin in any section, acknowledge it briefly and move on — don't pad.

Write the complete newsletter in markdown."""

        response = await call_claude_sonnet(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=12000,
            temperature=0.4,
        )

        _latest_newsletters[cadence]["content"] = response
        _latest_newsletters[cadence]["generated_at"] = datetime.utcnow().isoformat()
        _latest_newsletters[cadence]["generating"] = False

        logger.info(f"{cadence.upper()} newsletter generated: {len(response)} chars")

    except Exception as e:
        logger.error(f"{cadence.upper()} newsletter generation failed: {e}")
        _latest_newsletters[cadence]["generating"] = False
        _latest_newsletters[cadence]["content"] = f"Newsletter generation failed: {str(e)[:200]}"
        _latest_newsletters[cadence]["generated_at"] = datetime.utcnow().isoformat()


@router.get("/latest", response_model=NewsletterResponse)
async def get_latest_newsletter(
    cadence: str = Query("daily", regex="^(daily|weekly|monthly|yearly)$"),
    _key: str = Depends(verify_api_key),
):
    """Get the most recently generated newsletter of a specific cadence.

    Args:
        cadence: Newsletter cadence (daily, weekly, monthly, yearly). Default: daily
    """
    if cadence not in _latest_newsletters:
        cadence = "daily"

    nl = _latest_newsletters[cadence]

    if nl["generating"]:
        return NewsletterResponse(status="generating")
    if nl["content"]:
        return NewsletterResponse(
            content=nl["content"],
            generated_at=nl["generated_at"],
            status="ready",
        )
    return NewsletterResponse(status="empty")


@router.post("/generate", response_model=NewsletterResponse)
async def generate_newsletter(
    cadence: str = Query("daily", regex="^(daily|weekly|monthly|yearly)$"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Generate a new intelligence newsletter of a specific cadence.

    Args:
        cadence: Newsletter cadence (daily, weekly, monthly, yearly). Default: daily
    """
    if cadence not in _latest_newsletters:
        cadence = "daily"

    if _latest_newsletters[cadence]["generating"]:
        return NewsletterResponse(status="generating")

    background_tasks.add_task(_generate_newsletter, db, cadence)

    return NewsletterResponse(
        status="generating",
        generated_at=datetime.utcnow().isoformat(),
    )
