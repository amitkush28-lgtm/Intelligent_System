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
    parent_id: Optional[str] = None
    sub_label: Optional[str] = None
    monitoring_data_points: Optional[list] = None
    baseline_data: Optional[dict] = None

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
            parent_id=a.parent_id,
            sub_label=a.sub_label,
            monitoring_data_points=a.monitoring_data_points,
            baseline_data=a.baseline_data,
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
# FOLLOW-UP CONVERSATION
# =============================================================================

class FollowupRequest(BaseModel):
    message: str = Field(..., min_length=2, description="Follow-up question or comment")


class FollowupMessageResponse(BaseModel):
    id: int
    role: str
    message: str
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


FOLLOWUP_SYSTEM_PROMPT = """You are the Master Strategist of a multi-agent intelligence system. The user is asking a follow-up question about a Living Question they've been tracking.

You have full context on:
- The original question and thesis
- The current verdict, confidence level, and traffic-light status
- All assumptions and their current states (including any sub-assumptions)
- Recent evidence that has been logged
- Agent perspectives from 6 specialist agents

Answer the user's follow-up question with the same voice as the intelligence newsletter: confident, direct, specific, honest about uncertainty. Reference specific assumptions by number when relevant. Cite specific data points from the evidence when available.

## TOOL CAPABILITY — MODIFYING THE TRACKING SYSTEM

You can take REAL ACTIONS on the tracking system by including a `tool_actions` array in your JSON response. Available actions:

### create_sub_assumption
Add a sub-assumption under an existing parent assumption:
{
  "action": "create_sub_assumption",
  "parent_assumption_number": 6,
  "sub_label": "A",
  "assumption_text": "IT services sector will maintain 6-8% annual growth...",
  "status": "yellow",
  "confidence": 60,
  "green_to_yellow_trigger": "If TCS/Infosys report headcount declines >8% YoY...",
  "yellow_to_red_trigger": "If headcount declines >15% YoY sustained...",
  "keywords": ["IT services", "TCS", "Infosys", "headcount"],
  "relevant_agents": ["economist", "investor"],
  "monitoring_data_points": ["TCS headcount", "Infosys margins", "Bangalore unemployment"],
  "baseline_data": {"IT_headcount": "5.1M", "operating_margins": "19-21%"}
}

### update_assumption
Modify an existing assumption's status, confidence, or assessment:
{
  "action": "update_assumption",
  "assumption_number": 3,
  "sub_label": null,
  "updates": {
    "status": "yellow",
    "confidence": 45,
    "current_assessment": "New evidence suggests this assumption is under pressure..."
  }
}

### add_monitoring_data
Add data points to track for an assumption:
{
  "action": "add_monitoring_data",
  "assumption_number": 6,
  "sub_label": "A",
  "monitoring_data_points": ["Q4 earnings", "AI services revenue %"],
  "baseline_data": {"metric_name": "value"}
}

## RESPONSE FORMAT

Respond with ONLY valid JSON:
{
  "message": "Your natural language response to the user (2-4 paragraphs, same voice as before)",
  "tool_actions": [
    // Array of action objects, or empty array if no actions needed
  ]
}

IMPORTANT:
- Only include tool_actions when the conversation clearly warrants a change to the tracking system
- When the user asks you to add/create/track something, DO include the appropriate action
- When the user is just asking a question, return an empty tool_actions array
- The message field should describe what you did AND provide analytical insight
- Always include the message field — it's what the user sees"""


@router.get("/{question_id}/followups", response_model=List[FollowupMessageResponse])
async def get_followups(
    question_id: str,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Get the follow-up conversation history for a question."""
    from shared.models import LivingQuestion, QuestionFollowup

    question = db.query(LivingQuestion).filter(LivingQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    followups = (
        db.query(QuestionFollowup)
        .filter(QuestionFollowup.question_id == question_id)
        .order_by(QuestionFollowup.created_at.asc())
        .all()
    )

    return [FollowupMessageResponse(
        id=f.id,
        role=f.role,
        message=f.message,
        created_at=f.created_at,
    ) for f in followups]


@router.post("/{question_id}/followups", response_model=FollowupMessageResponse)
async def ask_followup(
    question_id: str,
    body: FollowupRequest,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Ask a follow-up question about a Living Question. Returns the AI response."""
    from shared.models import LivingQuestion, QuestionAssumption, QuestionEvidence, QuestionFollowup

    question = db.query(LivingQuestion).filter(LivingQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Save the user message
    user_msg = QuestionFollowup(
        question_id=question_id,
        role="user",
        message=body.message,
    )
    db.add(user_msg)
    db.flush()

    # Build context from the question's current state
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
        .limit(15)
        .all()
    )

    # Build conversation history (last 10 messages for context)
    history = (
        db.query(QuestionFollowup)
        .filter(QuestionFollowup.question_id == question_id)
        .order_by(QuestionFollowup.created_at.desc())
        .limit(10)
        .all()
    )
    history.reverse()  # chronological order

    context_parts = []
    context_parts.append(f"QUESTION: {question.question}")
    if question.context:
        context_parts.append(f"CONTEXT: {question.context}")
    context_parts.append(f"CATEGORY: {question.category or 'GENERAL'}")
    context_parts.append(f"VERDICT: {question.thesis_verdict or 'PENDING'}")
    context_parts.append(f"CONFIDENCE: {question.overall_confidence or '?'}%")
    context_parts.append(f"STATUS: {question.overall_status or 'green'} (traffic light)")
    if question.thesis_summary:
        context_parts.append(f"THESIS: {question.thesis_summary}")
    if question.recommendation:
        context_parts.append(f"RECOMMENDATION: {question.recommendation}")

    if assumptions:
        context_parts.append("\nASSUMPTIONS:")
        # Show parent assumptions first, then their sub-assumptions
        parents = [a for a in assumptions if a.parent_id is None]
        subs = [a for a in assumptions if a.parent_id is not None]
        sub_map = {}
        for s in subs:
            if s.parent_id not in sub_map:
                sub_map[s.parent_id] = []
            sub_map[s.parent_id].append(s)

        for a in parents:
            context_parts.append(
                f"  #{a.assumption_number} [{a.status.upper()}] ({a.confidence or '?'}%): {a.assumption_text}"
            )
            if a.current_assessment:
                context_parts.append(f"    Assessment: {a.current_assessment[:200]}")
            if a.green_to_yellow_trigger:
                context_parts.append(f"    Yellow trigger: {a.green_to_yellow_trigger}")
            if a.yellow_to_red_trigger:
                context_parts.append(f"    Red trigger: {a.yellow_to_red_trigger}")
            if a.monitoring_data_points:
                context_parts.append(f"    Monitoring: {', '.join(a.monitoring_data_points[:5])}")

            # Show sub-assumptions indented
            for sub in sub_map.get(a.id, []):
                context_parts.append(
                    f"    #{a.assumption_number}{sub.sub_label} [{sub.status.upper()}] ({sub.confidence or '?'}%): {sub.assumption_text}"
                )
                if sub.current_assessment:
                    context_parts.append(f"      Assessment: {sub.current_assessment[:200]}")
                if sub.green_to_yellow_trigger:
                    context_parts.append(f"      Yellow trigger: {sub.green_to_yellow_trigger}")
                if sub.yellow_to_red_trigger:
                    context_parts.append(f"      Red trigger: {sub.yellow_to_red_trigger}")
                if sub.monitoring_data_points:
                    context_parts.append(f"      Monitoring: {', '.join(sub.monitoring_data_points[:5])}")
                if sub.baseline_data:
                    baseline_str = ", ".join(f"{k}: {v}" for k, v in sub.baseline_data.items())
                    context_parts.append(f"      Baseline: {baseline_str[:200]}")

    if evidence:
        context_parts.append("\nRECENT EVIDENCE:")
        for e in evidence[:10]:
            impact = f"[{e.impact_level.upper()}]" if e.impact_level else ""
            context_parts.append(f"  {impact} {e.evidence_summary[:200]}")
            if e.source:
                context_parts.append(f"    Source: {e.source}")

    if question.agent_perspectives:
        context_parts.append("\nAGENT PERSPECTIVES:")
        for agent, text in question.agent_perspectives.items():
            context_parts.append(f"  {agent}: {text[:200]}")

    full_context = "\n".join(context_parts)

    # Build messages for the LLM call (include conversation history)
    conversation = f"""LIVING QUESTION CONTEXT:
{full_context}

CONVERSATION HISTORY:
"""
    for msg in history:
        role_label = "USER" if msg.role == "user" else "ASSISTANT"
        conversation += f"{role_label}: {msg.message}\n\n"

    # Call Claude for the response
    tool_actions = []
    try:
        raw_response = await call_claude_sonnet(
            system_prompt=FOLLOWUP_SYSTEM_PROMPT,
            user_message=conversation,
            max_tokens=3072,
            temperature=0.3,
        )

        # Try to parse structured response with tool_actions
        parsed = parse_structured_json(raw_response)
        if parsed and isinstance(parsed, dict) and "message" in parsed:
            response = parsed["message"]
            tool_actions = parsed.get("tool_actions", [])
        else:
            # Fallback: treat entire response as the message
            response = raw_response

    except Exception as e:
        logger.error(f"Follow-up LLM call failed for {question_id}: {e}")
        response = f"I wasn't able to process this follow-up right now. Please try again shortly. (Error: {str(e)[:100]})"

    # Execute tool actions if any
    actions_taken = []
    if tool_actions:
        for action_data in tool_actions:
            try:
                result = _execute_followup_action(db, question_id, action_data, assumptions)
                actions_taken.append(result)
            except Exception as e:
                logger.error(f"Follow-up action failed: {e}")
                actions_taken.append({"action": action_data.get("action", "unknown"), "error": str(e)[:200]})

    # Save the assistant response with tool actions
    assistant_msg = QuestionFollowup(
        question_id=question_id,
        role="assistant",
        message=response,
        tool_actions=actions_taken if actions_taken else None,
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    return FollowupMessageResponse(
        id=assistant_msg.id,
        role="assistant",
        message=assistant_msg.message,
        created_at=assistant_msg.created_at,
    )


# =============================================================================
# FOLLOW-UP ACTION EXECUTION
# =============================================================================

def _execute_followup_action(
    db: Session,
    question_id: str,
    action_data: dict,
    existing_assumptions: list,
) -> dict:
    """
    Execute a structured action from the follow-up LLM response.
    Returns a dict describing what was done.
    """
    from shared.models import QuestionAssumption

    action_type = action_data.get("action", "")

    if action_type == "create_sub_assumption":
        parent_num = action_data.get("parent_assumption_number")
        sub_label = action_data.get("sub_label", "A")

        # Find the parent assumption
        parent = None
        for a in existing_assumptions:
            if a.assumption_number == parent_num and a.parent_id is None:
                parent = a
                break

        if not parent:
            return {"action": "create_sub_assumption", "error": f"Parent assumption #{parent_num} not found"}

        # Generate sub-assumption ID: LQ-2026-0001-A6A
        sub_id = f"{question_id}-A{parent_num}{sub_label}"

        # Check if it already exists
        existing = db.query(QuestionAssumption).filter(QuestionAssumption.id == sub_id).first()
        if existing:
            return {"action": "create_sub_assumption", "status": "already_exists", "id": sub_id}

        sub_assumption = QuestionAssumption(
            id=sub_id,
            question_id=question_id,
            parent_id=parent.id,
            assumption_text=action_data.get("assumption_text", ""),
            assumption_number=parent_num,
            sub_label=sub_label,
            status=action_data.get("status", "green"),
            confidence=action_data.get("confidence"),
            green_to_yellow_trigger=action_data.get("green_to_yellow_trigger", ""),
            yellow_to_red_trigger=action_data.get("yellow_to_red_trigger", ""),
            keywords=action_data.get("keywords", []),
            relevant_agents=action_data.get("relevant_agents", []),
            monitoring_data_points=action_data.get("monitoring_data_points", []),
            baseline_data=action_data.get("baseline_data", {}),
            current_assessment=action_data.get("assumption_text", ""),
        )
        db.add(sub_assumption)
        db.flush()

        logger.info(f"Created sub-assumption {sub_id} under #{parent_num}")
        return {
            "action": "create_sub_assumption",
            "status": "created",
            "id": sub_id,
            "parent_id": parent.id,
            "sub_label": sub_label,
        }

    elif action_type == "update_assumption":
        target_num = action_data.get("assumption_number")
        target_sub_label = action_data.get("sub_label")
        updates = action_data.get("updates", {})

        # Find the assumption
        target = None
        for a in existing_assumptions:
            if a.assumption_number == target_num:
                if target_sub_label:
                    if a.sub_label == target_sub_label:
                        target = a
                        break
                elif a.parent_id is None:
                    target = a
                    break

        if not target:
            # Also check for newly created sub-assumptions
            label_suffix = f"{target_num}{target_sub_label}" if target_sub_label else str(target_num)
            target_id = f"{question_id}-A{label_suffix}"
            target = db.query(QuestionAssumption).filter(QuestionAssumption.id == target_id).first()

        if not target:
            return {"action": "update_assumption", "error": f"Assumption #{target_num}{target_sub_label or ''} not found"}

        # Apply updates
        old_status = target.status
        for field, value in updates.items():
            if field in ("status", "confidence", "current_assessment",
                        "green_to_yellow_trigger", "yellow_to_red_trigger",
                        "keywords", "relevant_agents"):
                setattr(target, field, value)

        if "status" in updates and updates["status"] != old_status:
            from datetime import datetime
            target.last_status_change_at = datetime.utcnow()
            target.last_status_change_reason = f"Updated via follow-up conversation"

        db.flush()

        logger.info(f"Updated assumption #{target_num}{target_sub_label or ''}: {list(updates.keys())}")
        return {
            "action": "update_assumption",
            "status": "updated",
            "id": target.id,
            "fields_updated": list(updates.keys()),
        }

    elif action_type == "add_monitoring_data":
        target_num = action_data.get("assumption_number")
        target_sub_label = action_data.get("sub_label")

        # Find the assumption
        target = None
        for a in existing_assumptions:
            if a.assumption_number == target_num:
                if target_sub_label and a.sub_label == target_sub_label:
                    target = a
                    break
                elif not target_sub_label and a.parent_id is None:
                    target = a
                    break

        if not target:
            return {"action": "add_monitoring_data", "error": f"Assumption #{target_num}{target_sub_label or ''} not found"}

        # Merge monitoring data points
        existing_points = target.monitoring_data_points or []
        new_points = action_data.get("monitoring_data_points", [])
        merged_points = list(set(existing_points + new_points))
        target.monitoring_data_points = merged_points

        # Merge baseline data
        existing_baseline = target.baseline_data or {}
        new_baseline = action_data.get("baseline_data", {})
        existing_baseline.update(new_baseline)
        target.baseline_data = existing_baseline

        db.flush()

        logger.info(f"Added monitoring data to assumption #{target_num}{target_sub_label or ''}")
        return {
            "action": "add_monitoring_data",
            "status": "updated",
            "id": target.id,
            "data_points_count": len(merged_points),
        }

    else:
        return {"action": action_type, "error": f"Unknown action type: {action_type}"}


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
        # STEP 1: Research phase — web search for current data (free-form text output)
        research_prompt = f"""Research this question thoroughly using web search. Gather current data, statistics, and recent developments.

QUESTION: {question_text}
{"CONTEXT: " + context if context else ""}
CATEGORY: {category or "GENERAL"}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

Search for:
- Current market data, prices, and trends relevant to this question
- Recent news and developments (last 30 days)
- Expert opinions and analyst forecasts
- Key risks and opportunities
- Data from multiple perspectives: economic, geopolitical, market, political, sentiment, technology

Provide a comprehensive research brief with specific numbers, dates, and sources."""

        research_response = await call_claude_with_web_search(
            system_prompt="You are a research analyst gathering current data for an intelligence system. Be thorough and specific. Include actual numbers, dates, and data points.",
            user_message=research_prompt,
            max_tokens=8192,
        )

        logger.info(f"Research phase complete for {question_id}: {len(research_response)} chars")

        # STEP 2: Analysis phase — clean JSON generation from research (no web search)
        analysis_message = f"""Based on the following research, produce a structured analysis of this Living Question.

QUESTION: {question_text}
{"CONTEXT: " + context if context else ""}
CATEGORY: {category or "GENERAL"}

RESEARCH DATA:
{research_response[:6000]}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

Using the research above, produce your analysis. You MUST respond with ONLY valid JSON — no markdown, no explanation, no text before or after the JSON object."""

        # Attempt analysis with retry — increase tokens on retry if truncation suspected
        analysis = None
        for attempt, tokens in enumerate([8192, 12000], 1):
            try:
                json_response = await call_claude_sonnet(
                    system_prompt=QUESTION_ANALYSIS_SYSTEM_PROMPT,
                    user_message=analysis_message,
                    max_tokens=tokens,
                    temperature=0.2,
                )

                analysis = parse_structured_json(json_response)
                if analysis and analysis.get("thesis_summary"):
                    logger.info(f"Analysis parsed on attempt {attempt} ({tokens} max_tokens, response={len(json_response)} chars)")
                    break
                else:
                    logger.warning(
                        f"Parse attempt {attempt} for {question_id}: empty or missing thesis_summary "
                        f"(response={len(json_response)} chars, max_tokens={tokens})"
                    )
                    logger.debug(f"Response tail: ...{json_response[-300:]}")
                    analysis = None
            except Exception as e:
                logger.error(f"LLM call attempt {attempt} failed for {question_id}: {e}")
                analysis = None

        if not analysis:
            logger.error(f"Failed to parse analysis for {question_id} after all attempts")
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

            # Delete old assumptions before creating new ones (safe for re-analysis)
            db.query(QuestionAssumption).filter(
                QuestionAssumption.question_id == question_id
            ).delete()
            db.flush()

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
