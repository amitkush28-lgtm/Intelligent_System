"""
Context Builder — Assembles analysis context from Postgres for the 7-question chain.

Pulls: recent events (24h, domain-filtered), verified claims (current_integrity > 0.50),
active predictions for the agent's domain, relevant actors/relationships from knowledge
graph, source reliability scores, calibration notes, base rates, and cross-domain signals
from other agents.

This context is injected into each agent's system prompt before analysis.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy import and_, or_, desc
from sqlalchemy.orm import Session

from shared.models import (
    Event, Claim, Prediction, ConfidenceTrail, Actor, Relationship,
    SourceReliability, CalibrationScore, AgentPrompt, BaseRateClass,
    Note, Debate,
)
from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Maps agents to their primary domain(s)
AGENT_DOMAINS = {
    "economist": ["economic"],
    "geopolitical": ["geopolitical"],
    "investor": ["market"],
    "political": ["political"],
    "sentiment": ["sentiment"],
    "master": ["economic", "geopolitical", "market", "political", "sentiment"],
}

# Maps agents to domains they should receive cross-domain signals from
CROSS_DOMAIN_MAP = {
    "economist": ["geopolitical", "market", "political"],
    "geopolitical": ["economic", "market", "political", "sentiment"],
    "investor": ["economic", "geopolitical", "political", "sentiment"],
    "political": ["economic", "geopolitical", "sentiment"],
    "sentiment": ["geopolitical", "political", "economic"],
    "master": [],  # master gets everything directly
}


def build_agent_context(
    agent_name: str,
    db: Session,
    hours_lookback: int = 24,
    max_events: int = 50,
    max_claims: int = 30,
    max_predictions: int = 30,
    max_actors: int = 20,
) -> Dict[str, Any]:
    """
    Build the complete analysis context for an agent.

    Returns a dict with structured sections ready for prompt injection:
    - todays_events: recent events relevant to this agent's domain
    - verified_claims: claims with current_integrity > 0.50
    - active_predictions: agent's current active predictions
    - actors_and_relationships: relevant knowledge graph entries
    - source_reliability: per-source accuracy scores
    - calibration_notes: feedback-processor-generated calibration adjustments
    - reasoning_guidance: feedback-processor-generated reasoning tips
    - base_rates: relevant historical base rates
    - cross_domain_signals: predictions/notes from other agents
    """
    domains = AGENT_DOMAINS.get(agent_name, ["economic"])
    cutoff = datetime.utcnow() - timedelta(hours=hours_lookback)

    context = {}

    # 1. Recent events filtered by domain relevance
    context["todays_events"] = _get_recent_events(db, domains, cutoff, max_events)

    # 2. Verified claims with integrity > 0.50
    context["verified_claims"] = _get_verified_claims(db, domains, cutoff, max_claims)

    # 3. Active predictions for this agent
    context["active_predictions"] = _get_active_predictions(db, agent_name, max_predictions)

    # 4. Knowledge graph: relevant actors and relationships
    context["actors_and_relationships"] = _get_knowledge_graph(db, domains, max_actors)

    # 5. Source reliability scores
    context["source_reliability"] = _get_source_reliability(db, domains)

    # 6. Calibration notes from feedback processor
    context["calibration_notes"] = _get_calibration_notes(db, agent_name)

    # 7. Reasoning guidance from feedback processor
    context["reasoning_guidance"] = _get_reasoning_guidance(db, agent_name)

    # 8. Base rates for relevant domains
    context["base_rates"] = _get_base_rates(db, domains)

    # 9. Cross-domain signals from other agents
    context["cross_domain_signals"] = _get_cross_domain_signals(db, agent_name)

    return context


def format_context_for_prompt(context: Dict[str, Any]) -> Dict[str, str]:
    """
    Convert structured context dict into formatted strings for prompt injection.
    Each key maps to a section of the agent's system prompt template.
    """
    formatted = {}

    # Today's events
    events = context.get("todays_events", [])
    if events:
        lines = []
        for e in events:
            severity_tag = f"[{e['severity'].upper()}]" if e.get("severity") else ""
            integrity_tag = f"(integrity: {e['integrity_score']:.2f})" if e.get("integrity_score") else ""
            lines.append(
                f"- {severity_tag} [{e['domain']}] {e['source']}: "
                f"{e['summary'][:300]} {integrity_tag}"
            )
        formatted["TODAYS_EVENTS"] = "\n".join(lines)
    else:
        formatted["TODAYS_EVENTS"] = "No recent events in the last 24 hours."

    # Verified claims
    claims = context.get("verified_claims", [])
    if claims:
        lines = []
        for c in claims:
            status_tag = f"[{c['verification_status']}]"
            lines.append(
                f"- {status_tag} (integrity: {c['current_integrity']:.2f}) "
                f"{c['claim_text'][:200]} — Source: {c['source']}"
            )
        formatted["VERIFIED_CLAIMS"] = "\n".join(lines)
    else:
        formatted["VERIFIED_CLAIMS"] = "No verified claims above integrity threshold."

    # Active predictions
    preds = context.get("active_predictions", [])
    if preds:
        lines = []
        for p in preds:
            deadline = ""
            if p.get("time_condition_end"):
                deadline = f" (deadline: {p['time_condition_end']})"
            elif p.get("time_condition_date"):
                deadline = f" (target: {p['time_condition_date']})"
            lines.append(
                f"- [{p['id']}] Confidence: {p['current_confidence']:.0%}{deadline}\n"
                f"  Claim: {p['claim'][:200]}\n"
                f"  Resolution: {p['resolution_criteria'][:150]}"
            )
        formatted["CURRENT_PREDICTIONS"] = "\n".join(lines)
    else:
        formatted["CURRENT_PREDICTIONS"] = "No active predictions. Generate new predictions based on today's events."

    # Actors and relationships
    actors = context.get("actors_and_relationships", {})
    if actors.get("actors"):
        lines = []
        for a in actors["actors"]:
            motivations = ""
            if a.get("deep_motivations"):
                motivations = f" | Motivations: {json.dumps(a['deep_motivations'])}"
            lines.append(f"- {a['name']} ({a['type']}){motivations}")
        if actors.get("relationships"):
            lines.append("\nKey Relationships:")
            for r in actors["relationships"][:10]:
                lines.append(f"  {r['from']} --[{r['type']}]--> {r['to']} (weight: {r.get('weight', 'N/A')})")
        formatted["ACTORS_AND_RELATIONSHIPS"] = "\n".join(lines)
    else:
        formatted["ACTORS_AND_RELATIONSHIPS"] = "No knowledge graph data available yet."

    # Source reliability
    sr = context.get("source_reliability", [])
    if sr:
        lines = [f"- {s['source']} ({s['domain']}): reliability={s['score']:.2f} ({s['total']} claims)" for s in sr[:15]]
        formatted["SOURCE_RELIABILITY"] = "\n".join(lines)
    else:
        formatted["SOURCE_RELIABILITY"] = "Using default source reliability scores."

    # Calibration notes
    formatted["CALIBRATION_NOTES"] = context.get("calibration_notes", "No calibration data yet — system is in initial learning phase.")

    # Reasoning guidance
    formatted["REASONING_GUIDANCE"] = context.get("reasoning_guidance", "No specific reasoning adjustments yet.")

    # Base rates
    brs = context.get("base_rates", [])
    if brs:
        lines = [f"- {b['class_name']}: {b['base_rate']:.1%} ({b['cases']} cases) — {b.get('description', '')[:100]}" for b in brs]
        formatted["BASE_RATES"] = "\n".join(lines)
    else:
        formatted["BASE_RATES"] = "No base rate data loaded yet. Use your best judgment and state assumptions explicitly."

    # Cross-domain signals
    signals = context.get("cross_domain_signals", [])
    if signals:
        lines = []
        for s in signals:
            lines.append(
                f"- [{s['agent']}] {s['claim'][:200]} "
                f"(confidence: {s['confidence']:.0%})"
            )
        formatted["CROSS_DOMAIN_SIGNALS"] = "\n".join(lines)
    else:
        formatted["CROSS_DOMAIN_SIGNALS"] = "No cross-domain signals from other agents yet."

    return formatted


# ============================================
# PRIVATE HELPERS
# ============================================

def _get_recent_events(
    db: Session,
    domains: List[str],
    cutoff: datetime,
    limit: int,
) -> List[Dict[str, Any]]:
    """Get recent events filtered by domain, ordered by severity and recency."""
    try:
        severity_order = {"critical": 0, "significant": 1, "notable": 2, "routine": 3}

        events = (
            db.query(Event)
            .filter(
                and_(
                    Event.timestamp >= cutoff,
                    Event.domain.in_(domains),
                )
            )
            .order_by(desc(Event.timestamp))
            .limit(limit * 2)  # fetch more, then sort by severity
            .all()
        )

        result = []
        for e in events:
            summary = e.raw_text[:500] if e.raw_text else "(no text)"
            result.append({
                "id": e.id,
                "source": e.source,
                "domain": e.domain,
                "severity": e.severity or "routine",
                "timestamp": e.timestamp.isoformat() if e.timestamp else "",
                "event_type": e.event_type,
                "entities": e.entities or [],
                "summary": summary,
                "integrity_score": e.integrity_score,
            })

        # Sort: critical first, then significant, etc.
        result.sort(key=lambda x: severity_order.get(x["severity"], 4))
        return result[:limit]

    except Exception as e:
        logger.error(f"Failed to get recent events: {e}")
        return []


def _get_verified_claims(
    db: Session,
    domains: List[str],
    cutoff: datetime,
    limit: int,
) -> List[Dict[str, Any]]:
    """Get claims with current_integrity > 0.50, joined with events for domain filtering."""
    try:
        query = (
            db.query(Claim)
            .join(Event, Claim.event_id == Event.id, isouter=True)
            .filter(
                and_(
                    Claim.current_integrity > settings.MIN_EVIDENCE_INTEGRITY,
                    Claim.created_at >= cutoff,
                )
            )
        )

        # Filter by domain if events are linked
        if domains != ["economic", "geopolitical", "market", "political", "sentiment"]:
            query = query.filter(
                or_(
                    Event.domain.in_(domains),
                    Claim.event_id.is_(None),
                )
            )

        claims = query.order_by(desc(Claim.current_integrity)).limit(limit).all()

        return [
            {
                "id": c.id,
                "claim_text": c.claim_text,
                "source": c.initial_source,
                "current_integrity": c.current_integrity,
                "verification_status": c.verification_status or "UNVERIFIED",
                "corroboration_count": c.corroboration_count or 0,
                "cross_modal_sources": c.cross_modal_sources,
            }
            for c in claims
        ]

    except Exception as e:
        logger.error(f"Failed to get verified claims: {e}")
        return []


def _get_active_predictions(
    db: Session,
    agent_name: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """Get agent's current active predictions with latest confidence trail entry."""
    try:
        if agent_name == "master":
            # Master sees all agents' active predictions
            preds = (
                db.query(Prediction)
                .filter(Prediction.status == "ACTIVE")
                .order_by(desc(Prediction.created_at))
                .limit(limit)
                .all()
            )
        else:
            preds = (
                db.query(Prediction)
                .filter(
                    and_(
                        Prediction.agent == agent_name,
                        Prediction.status == "ACTIVE",
                    )
                )
                .order_by(desc(Prediction.created_at))
                .limit(limit)
                .all()
            )

        result = []
        for p in preds:
            pred_dict = {
                "id": p.id,
                "agent": p.agent,
                "claim": p.claim,
                "current_confidence": p.current_confidence,
                "time_condition_type": p.time_condition_type,
                "time_condition_date": str(p.time_condition_date) if p.time_condition_date else None,
                "time_condition_start": str(p.time_condition_start) if p.time_condition_start else None,
                "time_condition_end": str(p.time_condition_end) if p.time_condition_end else None,
                "resolution_criteria": p.resolution_criteria,
                "parent_id": p.parent_id,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }

            # Get latest confidence trail entry for reasoning context
            latest_trail = (
                db.query(ConfidenceTrail)
                .filter(ConfidenceTrail.prediction_id == p.id)
                .order_by(desc(ConfidenceTrail.date))
                .first()
            )
            if latest_trail:
                pred_dict["last_reasoning"] = latest_trail.reasoning[:300]
                pred_dict["last_trigger"] = latest_trail.trigger[:200]

            result.append(pred_dict)

        return result

    except Exception as e:
        logger.error(f"Failed to get active predictions: {e}")
        return []


def _get_knowledge_graph(
    db: Session,
    domains: List[str],
    limit: int,
) -> Dict[str, Any]:
    """Get relevant actors and relationships from knowledge graph."""
    try:
        actors = (
            db.query(Actor)
            .order_by(desc(Actor.updated_at))
            .limit(limit)
            .all()
        )

        actor_ids = [a.id for a in actors]

        relationships = []
        if actor_ids:
            rels = (
                db.query(Relationship)
                .filter(
                    or_(
                        Relationship.actor_from.in_(actor_ids),
                        Relationship.actor_to.in_(actor_ids),
                    )
                )
                .limit(50)
                .all()
            )

            # Build lookup for actor names
            actor_names = {a.id: a.name for a in actors}

            relationships = [
                {
                    "from": actor_names.get(r.actor_from, r.actor_from),
                    "to": actor_names.get(r.actor_to, r.actor_to),
                    "type": r.relationship_type,
                    "weight": r.weight,
                }
                for r in rels
            ]

        return {
            "actors": [
                {
                    "id": a.id,
                    "name": a.name,
                    "type": a.type,
                    "objective_function": a.objective_function,
                    "deep_motivations": a.deep_motivations,
                }
                for a in actors
            ],
            "relationships": relationships,
        }

    except Exception as e:
        logger.error(f"Failed to get knowledge graph: {e}")
        return {"actors": [], "relationships": []}


def _get_source_reliability(
    db: Session,
    domains: List[str],
) -> List[Dict[str, Any]]:
    """Get source reliability scores for agent's domains."""
    try:
        sources = (
            db.query(SourceReliability)
            .filter(
                or_(
                    SourceReliability.domain.in_(domains),
                    SourceReliability.domain.is_(None),
                )
            )
            .filter(SourceReliability.total_claims > 0)
            .order_by(desc(SourceReliability.total_claims))
            .limit(30)
            .all()
        )

        return [
            {
                "source": s.source_name,
                "domain": s.domain or "general",
                "score": s.reliability_score,
                "total": s.total_claims,
                "accurate": s.verified_accurate,
                "inaccurate": s.verified_inaccurate,
            }
            for s in sources
        ]

    except Exception as e:
        logger.error(f"Failed to get source reliability: {e}")
        return []


def _get_calibration_notes(db: Session, agent_name: str) -> str:
    """Get the active prompt's calibration notes for this agent."""
    try:
        prompt = (
            db.query(AgentPrompt)
            .filter(
                and_(
                    AgentPrompt.agent == agent_name,
                    AgentPrompt.active == True,
                )
            )
            .order_by(desc(AgentPrompt.version))
            .first()
        )

        if prompt and prompt.calibration_notes:
            return prompt.calibration_notes

        # Fallback: build from calibration scores
        scores = (
            db.query(CalibrationScore)
            .filter(CalibrationScore.agent == agent_name)
            .order_by(desc(CalibrationScore.calculated_at))
            .limit(10)
            .all()
        )

        if scores:
            lines = []
            for s in scores:
                if s.bias_direction and s.bias_direction != "calibrated":
                    lines.append(
                        f"In {s.confidence_bucket} range ({s.domain or 'all domains'}): "
                        f"you are {s.bias_direction}. "
                        f"Predicted avg: {s.predicted_avg:.2f}, Actual avg: {s.actual_avg:.2f} "
                        f"({s.count} predictions)."
                    )
            if lines:
                return "\n".join(lines)

        return "No calibration data yet — system is in initial learning phase."

    except Exception as e:
        logger.error(f"Failed to get calibration notes: {e}")
        return "Calibration data unavailable."


def _get_reasoning_guidance(db: Session, agent_name: str) -> str:
    """Get the active prompt's reasoning guidance for this agent."""
    try:
        prompt = (
            db.query(AgentPrompt)
            .filter(
                and_(
                    AgentPrompt.agent == agent_name,
                    AgentPrompt.active == True,
                )
            )
            .order_by(desc(AgentPrompt.version))
            .first()
        )

        if prompt and prompt.reasoning_guidance:
            return prompt.reasoning_guidance

        return "No specific reasoning adjustments yet."

    except Exception as e:
        logger.error(f"Failed to get reasoning guidance: {e}")
        return "Reasoning guidance unavailable."


def _get_base_rates(db: Session, domains: List[str]) -> List[Dict[str, Any]]:
    """Get relevant base rate classes."""
    try:
        rates = (
            db.query(BaseRateClass)
            .order_by(desc(BaseRateClass.cases))
            .limit(20)
            .all()
        )

        return [
            {
                "id": r.id,
                "class_name": r.class_name,
                "base_rate": r.base_rate,
                "cases": r.cases,
                "timespan": r.timespan,
                "description": r.description,
                "examples": r.examples,
            }
            for r in rates
        ]

    except Exception as e:
        logger.error(f"Failed to get base rates: {e}")
        return []


def _get_cross_domain_signals(
    db: Session,
    agent_name: str,
) -> List[Dict[str, Any]]:
    """
    Get recent predictions and high-confidence signals from OTHER agents
    that might be relevant to this agent's domain.
    """
    try:
        cross_agents = CROSS_DOMAIN_MAP.get(agent_name, [])
        if not cross_agents:
            return []

        # Map domains back to agent names
        domain_to_agent = {}
        for agent, doms in AGENT_DOMAINS.items():
            for d in doms:
                domain_to_agent[d] = agent

        agent_names = [domain_to_agent.get(d) for d in cross_agents if domain_to_agent.get(d)]
        agent_names = list(set(agent_names))

        if not agent_names:
            return []

        # Get recent high-confidence predictions from those agents
        preds = (
            db.query(Prediction)
            .filter(
                and_(
                    Prediction.agent.in_(agent_names),
                    Prediction.status == "ACTIVE",
                    Prediction.current_confidence >= 0.40,
                )
            )
            .order_by(desc(Prediction.current_confidence))
            .limit(15)
            .all()
        )

        return [
            {
                "agent": p.agent,
                "id": p.id,
                "claim": p.claim,
                "confidence": p.current_confidence,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in preds
        ]

    except Exception as e:
        logger.error(f"Failed to get cross-domain signals: {e}")
        return []


def get_all_agent_predictions_for_master(db: Session) -> Dict[str, List[Dict[str, Any]]]:
    """
    Special context for the Master Strategist: all active predictions grouped by agent.
    Used to detect convergence, contradiction, and blind spots.
    """
    try:
        preds = (
            db.query(Prediction)
            .filter(Prediction.status == "ACTIVE")
            .order_by(Prediction.agent, desc(Prediction.current_confidence))
            .all()
        )

        grouped = {}
        for p in preds:
            if p.agent not in grouped:
                grouped[p.agent] = []
            grouped[p.agent].append({
                "id": p.id,
                "claim": p.claim,
                "confidence": p.current_confidence,
                "time_condition_end": str(p.time_condition_end) if p.time_condition_end else None,
                "resolution_criteria": p.resolution_criteria,
            })

        return grouped

    except Exception as e:
        logger.error(f"Failed to get all predictions for master: {e}")
        return {}


def get_recent_debates(db: Session, agent_name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Get recent debates for context on challenged predictions."""
    try:
        debates = (
            db.query(Debate)
            .filter(Debate.agent == agent_name)
            .order_by(desc(Debate.created_at))
            .limit(limit)
            .all()
        )

        return [
            {
                "id": d.id,
                "prediction_id": d.prediction_id,
                "trigger_reason": d.trigger_reason,
                "rounds": d.rounds,
                "devil_impact": d.devil_impact,
            }
            for d in debates
        ]

    except Exception as e:
        logger.error(f"Failed to get recent debates: {e}")
        return []
