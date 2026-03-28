"""
Living Questions API routes.

POST   /questions                     — Submit new Living Question
GET    /questions                     — List all active questions
GET    /questions/:id                 — Get question detail with assumptions & evidence
POST   /questions/:id/reanalyze       — Trigger manual re-analysis
PATCH  /questions/:id                 — Update status (pause/archive/resolve)
GET    /questions/:id/evidence        — Get evidence timeline
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.config import get_settings
from shared.llm_client import call_claude_sonnet, call_claude_with_web_search, parse_structured_json
from services.api.auth import verify_api_key

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/questions", tags=["living_questions"])


# =============================================================================
# SCHEMAS
# =============================================================================

class QuestionCreate(BaseModel):
    question: str = Field(..., min_length=10, description="The question or thesis to track")
    context: Optional[str] = Field(None, description="Optional context about your situation")
    category: Optional[str] = Field("INVESTMENT", description="INVESTMENT | SAFETY | BUSINESS | GEOPOLITICAL | PERSONAL")
    priority: Optional[str] = Field("normal", description="high | normal | low")
    tags: Optional[List[str]] = None


class QuestionStatusUpdate(BaseModel):
    status: str = Field(..., description="active | paused | resolved | archived")
    resolution_note: Optional[str] = None


class QuestionSummaryResponse(BaseModel):
    id: str
    question: str
    category: Optional[str]
    thesis_verdict: Optional[str]
    overall_confidence: Optional[int]
    overall_status: Optional[str]
    thesis_summary: Optional[str]
    status: str
    created_at: Optional[datetime]
    last_analyzed_at: Optional[datetime]
    next_review_date: Optional[date]
    assumption_count: int = 0
    evidence_count: int = 0
    tags: Optional[list] = None

    model_config = {"from_attributes": True}


class AssumptionResponse(BaseModel):
    id: str
    assumption_text: str
    assumption_number: int
    status: str
    confidence: Optional[int]
    green_to_yellow_trigger: Optional[str]
    yellow_to_red_trigger: Optional[str]
    supporting_evidence_count: int
    challenging_evidence_count: int
    current_assessment: Optional[str]
    keywords: Optional[list]

    model_config = {"from_attributes": True}


class EvidenceResponse(BaseModel):
    id: int
    assumption_id: Optional[str]
    evidence_type: str
    evidence_summary: str
    impact_level: Optional[str]
    source: Optional[str]
    triggered_status_change: bool
    detected_at: Optional[datetime]
    agent_that_flagged: Optional[str]

    model_config = {"from_attributes": True}


class QuestionDetailResponse(QuestionSummaryResponse):
    recommendation: Optional[str]
    agent_perspectives: Optional[dict]
    assumptions: List[AssumptionResponse] = []
    recent_evidence: List[EvidenceResponse] = []


# =============================================================================
# ANALYSIS PROMPTS
# =============================================================================

QUESTION_ANALYSIS_SYSTEM_PROMPT = """You are the Master Strategist of a multi-agent intelligence system. A user has submitted a LIVING QUESTION — a thesis they want continuously monitored and stress-tested.

Your job is to:
1. Research the question thoroughly using web search
2. Form a clear thesis with a verdict
3. Decompose the thesis into 4-7 falsifiable assumptions
4. Define tripwires for each assumption that would change the status
5. Provide specific actionable recommendation

## OUTPUT FORMAT
Respond with ONLY valid JSON:
{
    "thesis_summary": "2-3 sentence summary of your position",
    "thesis_verdict": "BULLISH|BEARISH|NEUTRAL|MIXED",
    "overall_confidence": 65,
    "recommendation": "Specific actionable recommendation — what should the reader DO?",
    "strongest_case_against": "2-3 sentences — the best argument for the opposite conclusion",
    "review_frequency": "weekly|biweekly|monthly",
    "assumptions": [
        {
            "assumption_text": "Clear, falsifiable statement",
            "assumption_number": 1,
            "status": "green|yellow|red",
            "confidence": 85,
            "supporting_evidence": "Current evidence that supports this",
            "challenging_evidence": "Current evidence that challenges this (or 'none identified')",
            "green_to_yellow_trigger": "Specific event/data that would shift to yellow",
            "yellow_to_red_trigger": "Specific event/data that would shift to red",
            "keywords": ["keyword1", "keyword2", "keyword3"],
            "relevant_agents": ["economist", "investor"],
            "assessment": "Current detailed assessment of this assumption"
        }
    ],
    "agent_perspectives": {
        "economist": "1-2 sentence perspective from economic angle",
        "geopolitical": "1-2 sentence perspective from geopolitical angle",
        "investor": "1-2 sentence perspective from market angle",
        "political": "1-2 sentence perspective from political angle",
        "sentiment": "1-2 sentence perspective from sentiment angle",
        "wildcard": "1-2 sentence perspective from technology/climate/demographics angle"
    },
    "tags": ["tag1", "tag2"]
}
"""


# =============================================================================
# ROUTES
# =============================================================================

@router.post("", response_model=dict)
async def create_question(
    body: QuestionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Submit a new Living Question for analysis."""
    # Import models here to avoid circular imports
    from shared.models import Event  # just to verify imports work
    try:
        from shared.models import LivingQuestion
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Living Questions models not yet added to shared/models.py. "
                   "Please add the models from shared/models_living_questions.py first."
        )

    # Generate ID
    count = db.query(LivingQuestion).count()
    question_id = f"LQ-{datetime.utcnow().year}-{count + 1:04d}"

    # Create the question record
    question = LivingQuestion(
        id=question_id,
        question=body.question,
        context=body.context,
        category=body.category or "INVESTMENT",
        status="analyzing",
        priority=body.priority or "normal",
        tags=body.tags,
    )
    db.add(question)
    db.commit()

    # Run analysis in background
    background_tasks.add_task(_analyze_question, question_id, body.question, body.context, body.category)

    return {
        "id": question_id,
        "status": "analyzing",
        "message": f"Question submitted. Analysis will take 30-60 seconds. Check GET /questions/{question_id} for results.",
    }


@router.get("", response_model=List[QuestionSummaryResponse])
async def list_questions(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """List all Living Questions."""
    try:
        from shared.models import LivingQuestion, QuestionAssumption, QuestionEvidence
    except ImportError:
        raise HTTPException(status_code=501, detail="Living Questions models not yet deployed.")

    query = db.query(LivingQuestion)
    if status:
        query = query.filter(LivingQuestion.status == status)
    questions = query.order_by(desc(LivingQuestion.created_at)).all()

    results = []
    for q in questions:
        assumption_count = db.query(QuestionAssumption).filter(QuestionAssumption.question_id == q.id).count()
        evidence_count = db.query(QuestionEvidence).filter(QuestionEvidence.question_id == q.id).count()

        results.append(QuestionSummaryResponse(
            id=q.id,
            question=q.question,
            category=q.category,
            thesis_verdict=q.thesis_verdict,
            overall_confidence=q.overall_confidence,
            overall_status=q.overall_status,
            thesis_summary=q.thesis_summary,
            status=q.status,
            created_at=q.created_at,
            last_analyzed_at=q.last_analyzed_at,
            next_review_date=q.next_review_date,
            assumption_count=assumption_count,
            evidence_count=evidence_count,
            tags=q.tags,
        ))

    return results


@router.get("/{question_id}", response_model=QuestionDetailResponse)
async def get_question(
    question_id: str,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Get detailed question with assumptions and evidence."""
    try:
        from shared.models import LivingQuestion, QuestionAssumption, QuestionEvidence
    except ImportError:
        raise HTTPException(status_code=501, detail="Living Questions models not yet deployed.")

    question = db.query(LivingQuestion).filter(LivingQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    assumptions = (
        db.query(QuestionAssumption)
        .filter(QuestionAssumption.question_id == question_id)
        .order_by(QuestionAssumption.assumption_number)
        .all()
    )

    evidence = (
        db.query(QuestionEvidence)
        .filter(QuestionEvidence.question_id == question_id)
        .order_by(desc(QuestionEvidence.detected_at))
        .limit(20)
        .all()
    )

    assumption_count = len(assumptions)
    evidence_count = db.query(QuestionEvidence).filter(QuestionEvidence.question_id == question_id).count()

    return QuestionDetailResponse(
        id=question.id,
        question=question.question,
        category=question.category,
        thesis_verdict=question.thesis_verdict,
        overall_confidence=question.overall_confidence,
        overall_status=question.overall_status,
        thesis_summary=question.thesis_summary,
        recommendation=question.recommendation,
        agent_perspectives=question.agent_perspectives,
        status=question.status,
        created_at=question.created_at,
        last_analyzed_at=question.last_analyzed_at,
        next_review_date=question.next_review_date,
        assumption_count=assumption_count,
        evidence_count=evidence_count,
        tags=question.tags,
        assumptions=[AssumptionResponse(
            id=a.id,
            assumption_text=a.assumption_text,
            assumption_number=a.assumption_number,
            status=a.status,
            confidence=a.confidence,
            green_to_yellow_trigger=a.green_to_yellow_trigger,
            yellow_to_red_trigger=a.yellow_to_red_trigger,
            supporting_evidence_count=a.supporting_evidence_count,
            challenging_evidence_count=a.challenging_evidence_count,
            current_assessment=a.current_assessment,
            keywords=a.keywords,
        ) for a in assumptions],
        recent_evidence=[EvidenceResponse(
            id=e.id,
            assumption_id=e.assumption_id,
            evidence_type=e.evidence_type,
            evidence_summary=e.evidence_summary,
            impact_level=e.impact_level,
            source=e.source,
            triggered_status_change=e.triggered_status_change,
            detected_at=e.detected_at,
            agent_that_flagged=e.agent_that_flagged,
        ) for e in evidence],
    )


@router.post("/{question_id}/reanalyze", response_model=dict)
async def reanalyze_question(
    question_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Trigger a manual re-analysis of a Living Question."""
    try:
        from shared.models import LivingQuestion
    except ImportError:
        raise HTTPException(status_code=501, detail="Living Questions models not yet deployed.")

    question = db.query(LivingQuestion).filter(LivingQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    background_tasks.add_task(
        _analyze_question, question_id, question.question, question.context, question.category
    )

    return {"status": "reanalyzing", "message": "Re-analysis started. Check the question detail for updated results."}


@router.patch("/{question_id}", response_model=dict)
async def update_question_status(
    question_id: str,
    body: QuestionStatusUpdate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Update a question's status (pause, resolve, archive)."""
    try:
        from shared.models import LivingQuestion
    except ImportError:
        raise HTTPException(status_code=501, detail="Living Questions models not yet deployed.")

    question = db.query(LivingQuestion).filter(LivingQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if body.status not in ("active", "paused", "resolved", "archived"):
        raise HTTPException(status_code=400, detail="Invalid status")

    question.status = body.status
    if body.resolution_note:
        question.resolution_note = body.resolution_note
    db.commit()

    return {"id": question_id, "status": body.status}


@router.get("/{question_id}/evidence", response_model=List[EvidenceResponse])
async def get_question_evidence(
    question_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Get the evidence timeline for a question."""
    try:
        from shared.models import QuestionEvidence
    except ImportError:
        raise HTTPException(status_code=501, detail="Living Questions models not yet deployed.")

    evidence = (
        db.query(QuestionEvidence)
        .filter(QuestionEvidence.question_id == question_id)
        .order_by(desc(QuestionEvidence.detected_at))
        .limit(limit)
        .all()
    )

    return [EvidenceResponse(
        id=e.id,
        assumption_id=e.assumption_id,
        evidence_type=e.evidence_type,
        evidence_summary=e.evidence_summary,
        impact_level=e.impact_level,
        source=e.source,
        triggered_status_change=e.triggered_status_change,
        detected_at=e.detected_at,
        agent_that_flagged=e.agent_that_flagged,
    ) for e in evidence]


# =============================================================================
# BACKGROUND ANALYSIS
# =============================================================================

async def _analyze_question(
    question_id: str,
    question_text: str,
    context: Optional[str],
    category: Optional[str],
):
    """Run full analysis on a Living Question using web search + LLM."""
    from shared.database import get_db_session

    logger.info(f"Starting analysis for Living Question {question_id}: {question_text[:80]}")

    try:
        user_message = f"""Analyze this Living Question thoroughly. Use web search to get current data.

QUESTION: {question_text}
{"CONTEXT: " + context if context else ""}
CATEGORY: {category or "GENERAL"}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

Instructions:
1. Search the web for current information relevant to this question
2. Form a clear thesis with a specific verdict (BULLISH/BEARISH/NEUTRAL/MIXED)
3. Decompose into 4-7 specific, falsifiable assumptions
4. For each assumption, define concrete tripwires that would change the status
5. Provide monitoring keywords for automated event matching
6. Give a specific, actionable recommendation
7. Consider ALL angles: economic, geopolitical, market, political, sentiment, technology/climate

Be SPECIFIC. Use actual numbers, dates, entities. This analysis will be continuously monitored.

Respond with ONLY valid JSON."""

        response = await call_claude_with_web_search(
            system_prompt=QUESTION_ANALYSIS_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=8192,
        )

        analysis = parse_structured_json(response)
        if not analysis:
            logger.error(f"Failed to parse analysis for {question_id}")
            with get_db_session() as db:
                from shared.models import LivingQuestion
                q = db.query(LivingQuestion).filter(LivingQuestion.id == question_id).first()
                if q:
                    q.status = "active"
                    q.thesis_summary = "Analysis produced output but JSON parsing failed. Please re-analyze."
                    q.last_analyzed_at = datetime.utcnow()
            return

        # Persist the analysis
        with get_db_session() as db:
            from shared.models import LivingQuestion, QuestionAssumption

            q = db.query(LivingQuestion).filter(LivingQuestion.id == question_id).first()
            if not q:
                logger.error(f"Question {question_id} not found after analysis")
                return

            q.thesis_summary = analysis.get("thesis_summary", "")
            q.thesis_verdict = analysis.get("thesis_verdict", "MIXED")
            q.overall_confidence = analysis.get("overall_confidence", 50)
            q.overall_status = "green"  # Start green
            q.recommendation = analysis.get("recommendation", "")
            q.initial_analysis = analysis
            q.latest_analysis = analysis
            q.agent_perspectives = analysis.get("agent_perspectives", {})
            q.last_analyzed_at = datetime.utcnow()
            q.status = "active"
            q.tags = analysis.get("tags", q.tags)

            # Set review date based on frequency
            freq = analysis.get("review_frequency", "monthly")
            if freq == "weekly":
                q.next_review_date = (date.today() + timedelta(days=7))
            elif freq == "biweekly":
                q.next_review_date = (date.today() + timedelta(days=14))
            else:
                q.next_review_date = (date.today() + timedelta(days=30))

            # Determine overall status from assumptions
            assumptions_data = analysis.get("assumptions", [])
            red_count = sum(1 for a in assumptions_data if a.get("status") == "red")
            yellow_count = sum(1 for a in assumptions_data if a.get("status") == "yellow")

            if red_count > 0:
                q.overall_status = "red"
            elif yellow_count >= 2:
                q.overall_status = "yellow"
            else:
                q.overall_status = "green"

            # Create assumption records
            for a_data in assumptions_data:
                a_num = a_data.get("assumption_number", 0)
                a_id = f"{question_id}-A{a_num}"

                assumption = QuestionAssumption(
                    id=a_id,
                    question_id=question_id,
                    assumption_text=a_data.get("assumption_text", ""),
                    assumption_number=a_num,
                    status=a_data.get("status", "green"),
                    confidence=a_data.get("confidence"),
                    green_to_yellow_trigger=a_data.get("green_to_yellow_trigger", ""),
                    yellow_to_red_trigger=a_data.get("yellow_to_red_trigger", ""),
                    current_assessment=a_data.get("assessment", ""),
                    keywords=a_data.get("keywords", []),
                    relevant_agents=a_data.get("relevant_agents", []),
                )
                db.add(assumption)

            db.flush()
            logger.info(
                f"Living Question {question_id} analyzed: "
                f"verdict={q.thesis_verdict}, confidence={q.overall_confidence}%, "
                f"status={q.overall_status}, assumptions={len(assumptions_data)}"
            )

    except Exception as e:
        logger.error(f"Analysis failed for {question_id}: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        try:
            with get_db_session() as db:
                from shared.models import LivingQuestion
                q = db.query(LivingQuestion).filter(LivingQuestion.id == question_id).first()
                if q:
                    q.status = "active"
                    q.thesis_summary = f"Analysis failed: {str(e)[:200]}. Please try re-analyzing."
                    q.last_analyzed_at = datetime.utcnow()
        except Exception:
            pass
