"""
Cross-Domain Synthesis Engine — Connects non-obvious dots across agent domains.

Runs AFTER all 6 specialists but BEFORE the Master Strategist.
This engine does the deep pattern-matching that individual agents can't:

1. MULTI-HOP CAUSAL CHAINS — traces Domain A → Domain B → Domain C cascades
2. ENTITY CONVERGENCE — flags entities appearing across 3+ domains
3. TEMPORAL DEPENDENCY GRAPHS — identifies precondition → trigger → consequence sequences
4. ABSENCE DETECTION — finds suspicious information voids
5. STRUCTURAL FORCE ALIGNMENT — identifies when multiple structural forces point the same direction

The output is injected into the Master Strategist's context, giving it
pre-digested cross-domain intelligence to synthesize.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple
from collections import defaultdict, Counter

from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

from shared.models import (
    Event, Prediction, ConfidenceTrail, WeakSignal, Claim, Actor,
)
from shared.database import get_db_session
from shared.llm_client import call_claude_sonnet
from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ============================================
# MULTI-HOP CAUSAL CHAIN DETECTION
# ============================================

CAUSAL_CHAIN_PROMPT = """You are a cross-domain causal reasoning engine. Your ONLY job is to find
multi-hop causal chains that span across different analytical domains.

You receive predictions from 6 specialist agents (economist, geopolitical, investor, political,
sentiment, wildcard). Each agent sees their domain deeply but CANNOT trace chains that cross
domain boundaries.

YOUR TASK: Find causal chains of 3+ hops that cross at least 2 domain boundaries.

EXAMPLE of what you're looking for:
- [Geopolitical] China restricts rare earth exports → [Economic] EV battery costs spike 40% →
  [Political] European industrial policy panic → [Market] Auto sector selloff →
  [Geopolitical] EU-China trade war escalation

ANTI-PATTERNS (reject these):
- Single-domain chains (geopolitical → geopolitical → geopolitical)
- Obvious/consensus chains everyone already sees
- Chains without a concrete triggering mechanism at each hop
- Chains where timing is implausible (effect before cause)

For each chain found:
1. Name each hop with its domain
2. Identify the TRANSMISSION MECHANISM between hops (how does A cause B?)
3. Estimate TIME LAG between each hop
4. Rate overall chain probability (0.0-1.0)
5. Identify the KEY ASSUMPTION that could break the chain
6. Name the EARLIEST OBSERVABLE SIGNAL that the chain is activating

Return JSON:
{
  "causal_chains": [
    {
      "chain_id": "short-descriptive-id",
      "hops": [
        {
          "domain": "geopolitical",
          "event_or_prediction": "what happens at this stage",
          "transmission_to_next": "HOW this causes the next hop",
          "time_lag_to_next": "2-4 weeks",
          "source_prediction_ids": ["pred-id-1"]
        }
      ],
      "overall_probability": 0.35,
      "key_assumption": "what must be true for this chain to play out",
      "earliest_signal": "the first observable indicator this chain is activating",
      "why_others_miss_this": "why no single agent would see this full chain",
      "so_what": "specific actionable implication"
    }
  ],
  "structural_alignments": [
    {
      "description": "Multiple structural forces pointing the same direction",
      "forces": ["force 1 description", "force 2 description"],
      "convergence_point": "what they converge on",
      "timeline": "when this becomes undeniable",
      "implication": "what to do about it"
    }
  ]
}"""


async def run_synthesis_engine(
    specialist_outputs: Dict[str, Dict[str, Any]],
    db: Session,
    hours_lookback: int = 72,
) -> Dict[str, Any]:
    """
    Run the full cross-domain synthesis engine.

    Returns a dict with:
    - causal_chains: multi-hop cross-domain chains
    - entity_convergence: entities flagged across 3+ domains
    - temporal_dependencies: precondition → trigger → consequence sequences
    - absence_signals: suspicious information voids
    - structural_alignments: multiple structural forces pointing same direction
    """
    logger.info("=== Cross-Domain Synthesis Engine starting ===")

    results = {
        "causal_chains": [],
        "entity_convergence": [],
        "temporal_dependencies": [],
        "absence_signals": [],
        "structural_alignments": [],
        "stats": {},
    }

    try:
        # Phase 1: Entity convergence (fast, no LLM needed)
        entity_conv = _detect_entity_convergence(specialist_outputs, db, hours_lookback)
        results["entity_convergence"] = entity_conv
        logger.info(f"Entity convergence: {len(entity_conv)} cross-domain entities found")

        # Phase 2: Temporal dependency detection
        temporal_deps = _detect_temporal_dependencies(db)
        results["temporal_dependencies"] = temporal_deps
        logger.info(f"Temporal dependencies: {len(temporal_deps)} sequences found")

        # Phase 3: Absence detection
        absences = _detect_absences(db, hours_lookback)
        results["absence_signals"] = absences
        logger.info(f"Absence signals: {len(absences)} information voids detected")

        # Phase 4: Multi-hop causal chains (LLM-powered)
        chains = await _find_causal_chains(specialist_outputs, entity_conv, db)
        results["causal_chains"] = chains.get("causal_chains", [])
        results["structural_alignments"] = chains.get("structural_alignments", [])
        logger.info(f"Causal chains: {len(results['causal_chains'])} cross-domain chains found")

        results["stats"] = {
            "entity_convergences": len(entity_conv),
            "temporal_dependencies": len(temporal_deps),
            "absence_signals": len(absences),
            "causal_chains": len(results["causal_chains"]),
            "structural_alignments": len(results["structural_alignments"]),
        }

    except Exception as e:
        logger.error(f"Synthesis engine failed: {e}")
        results["stats"]["error"] = str(e)[:300]

    logger.info(f"=== Synthesis Engine complete: {results['stats']} ===")
    return results


# ============================================
# ENTITY CONVERGENCE DETECTION
# ============================================

def _detect_entity_convergence(
    specialist_outputs: Dict[str, Dict[str, Any]],
    db: Session,
    hours_lookback: int = 72,
) -> List[Dict[str, Any]]:
    """
    Find entities that appear across 3+ domains simultaneously.

    "Turkey" appearing in geopolitical + economic + political predictions = high signal.
    This is something no individual agent flags because each sees it as "normal"
    within their domain.
    """
    # Track entity → set of (agent, context)
    entity_domains: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))

    # Extract entities from specialist predictions
    for agent_name, output in specialist_outputs.items():
        for pred in output.get("new_predictions", []):
            claim = pred.get("claim", "")
            # Extract entities mentioned in the claim
            entities = _extract_entities_from_text(claim)
            for entity in entities:
                entity_domains[entity][agent_name].append(claim[:150])

        for update in output.get("prediction_updates", []):
            reasoning = update.get("reasoning", "")
            entities = _extract_entities_from_text(reasoning)
            for entity in entities:
                entity_domains[entity][agent_name].append(f"Update: {reasoning[:150]}")

    # Also check recent events for entity cross-domain appearance
    cutoff = datetime.utcnow() - timedelta(hours=hours_lookback)
    try:
        events = (
            db.query(Event)
            .filter(Event.timestamp >= cutoff)
            .all()
        )

        entity_event_domains: Dict[str, Set[str]] = defaultdict(set)
        for event in events:
            if event.entities:
                for ent in event.entities:
                    name = ent.get("name", "") if isinstance(ent, dict) else str(ent)
                    if name and len(name) > 2:
                        entity_event_domains[name.lower()].add(event.domain or "unknown")
    except Exception as e:
        logger.error(f"Entity convergence event scan failed: {e}")
        entity_event_domains = {}

    # Find entities appearing in 3+ agent domains
    convergences = []
    for entity, agent_map in entity_domains.items():
        if len(agent_map) >= 3:
            # Check if events also show multi-domain presence
            event_domains = entity_event_domains.get(entity.lower(), set())

            convergences.append({
                "entity": entity,
                "agent_count": len(agent_map),
                "agents": {agent: contexts[:2] for agent, contexts in agent_map.items()},
                "event_domains": list(event_domains),
                "signal_strength": "CRITICAL" if len(agent_map) >= 4 else "HIGH",
                "interpretation": (
                    f"'{entity}' appears across {len(agent_map)} agent domains "
                    f"({', '.join(agent_map.keys())}). "
                    f"This cross-domain convergence suggests '{entity}' is a nexus point "
                    f"where multiple forces are intersecting simultaneously."
                ),
            })

    # Also check for 2-agent convergence with high event presence
    for entity, agent_map in entity_domains.items():
        if len(agent_map) == 2:
            event_domains = entity_event_domains.get(entity.lower(), set())
            if len(event_domains) >= 3:
                convergences.append({
                    "entity": entity,
                    "agent_count": len(agent_map),
                    "agents": {agent: contexts[:2] for agent, contexts in agent_map.items()},
                    "event_domains": list(event_domains),
                    "signal_strength": "HIGH",
                    "interpretation": (
                        f"'{entity}' appears in {len(agent_map)} agent predictions "
                        f"but spans {len(event_domains)} event domains. "
                        f"The event breadth suggests building pressure."
                    ),
                })

    # Sort by signal strength
    strength_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
    convergences.sort(key=lambda x: strength_order.get(x["signal_strength"], 3))

    return convergences[:15]


def _extract_entities_from_text(text: str) -> List[str]:
    """
    Extract likely entity names from text.
    Simple heuristic: capitalized multi-word phrases, known country/org names.
    """
    if not text:
        return []

    entities = []

    # Known high-value entity patterns (countries, major orgs, leaders)
    # This is a lightweight extraction — the LLM will do deeper analysis
    known_entities = [
        "China", "Russia", "Ukraine", "Iran", "Israel", "Saudi Arabia", "Turkey",
        "India", "Japan", "Taiwan", "North Korea", "South Korea", "EU", "NATO",
        "OPEC", "Fed", "Federal Reserve", "ECB", "IMF", "World Bank",
        "United States", "US", "UK", "Germany", "France", "Brazil", "Mexico",
        "Pakistan", "Indonesia", "Nigeria", "Egypt", "South Africa",
        "Xi Jinping", "Putin", "Biden", "Trump", "Modi", "Erdogan",
        "BRICS", "G7", "G20", "ASEAN", "WHO", "WTO",
        "Apple", "Google", "Microsoft", "NVIDIA", "Tesla", "OpenAI",
        "Strait of Hormuz", "South China Sea", "Black Sea", "Suez Canal",
        "Gaza", "West Bank", "Crimea", "Donbas",
    ]

    text_lower = text.lower()
    for entity in known_entities:
        if entity.lower() in text_lower:
            entities.append(entity)

    return list(set(entities))


# ============================================
# TEMPORAL DEPENDENCY DETECTION
# ============================================

def _detect_temporal_dependencies(db: Session) -> List[Dict[str, Any]]:
    """
    Find prediction chains where one prediction's outcome is a precondition
    for another prediction's trigger.

    Example: "Fed raises rates" (economic) is a precondition for
    "Housing market correction" (market) which preconditions
    "Construction sector layoffs" (economic/political).
    """
    dependencies = []

    try:
        # Get all active predictions with their resolution criteria and triggers
        active_preds = (
            db.query(Prediction)
            .filter(Prediction.status == "ACTIVE")
            .all()
        )

        if len(active_preds) < 5:
            return dependencies

        # Build a map of claims → prediction for matching
        pred_map = {}
        for pred in active_preds:
            pred_map[pred.id] = {
                "id": pred.id,
                "agent": pred.agent,
                "claim": pred.claim,
                "confidence": pred.current_confidence,
                "resolution_criteria": pred.resolution_criteria or "",
                "time_end": str(pred.time_condition_end) if pred.time_condition_end else None,
            }

        # Look for predictions whose claims contain keywords from other predictions'
        # resolution criteria (suggesting causal dependency)
        for pred_a_id, pred_a in pred_map.items():
            claim_a_words = set(pred_a["claim"].lower().split())

            for pred_b_id, pred_b in pred_map.items():
                if pred_a_id == pred_b_id:
                    continue
                if pred_a["agent"] == pred_b["agent"]:
                    continue  # Skip same-agent (they should handle this internally)

                resolution_words = set(pred_b["resolution_criteria"].lower().split())

                # Find meaningful keyword overlap (excluding common words)
                common_words = {"the", "a", "an", "in", "of", "to", "and", "or", "is",
                               "will", "by", "for", "from", "with", "that", "this",
                               "be", "on", "at", "as", "it", "not", "are", "was",
                               "has", "have", "had", "been", "would", "could", "should",
                               "may", "might", "can", "than", "more", "less", "if",
                               "within", "between", "during", "before", "after", "above",
                               "below", "through", "into", "over", "under", "about"}

                meaningful_overlap = (claim_a_words & resolution_words) - common_words

                # Filter to words of substance (length > 3)
                meaningful_overlap = {w for w in meaningful_overlap if len(w) > 3}

                if len(meaningful_overlap) >= 3:
                    dependencies.append({
                        "precondition": {
                            "prediction_id": pred_a["id"],
                            "agent": pred_a["agent"],
                            "claim": pred_a["claim"][:200],
                            "confidence": pred_a["confidence"],
                        },
                        "dependent": {
                            "prediction_id": pred_b["id"],
                            "agent": pred_b["agent"],
                            "claim": pred_b["claim"][:200],
                            "confidence": pred_b["confidence"],
                        },
                        "linking_concepts": list(meaningful_overlap)[:10],
                        "cross_domain": pred_a["agent"] != pred_b["agent"],
                        "interpretation": (
                            f"{pred_a['agent']}'s prediction may be a precondition for "
                            f"{pred_b['agent']}'s prediction. "
                            f"Shared concepts: {', '.join(list(meaningful_overlap)[:5])}"
                        ),
                    })

        # Sort by number of linking concepts (stronger link = more overlap)
        dependencies.sort(key=lambda x: len(x["linking_concepts"]), reverse=True)

    except Exception as e:
        logger.error(f"Temporal dependency detection failed: {e}")

    return dependencies[:20]


# ============================================
# ABSENCE-OF-SIGNAL DETECTION
# ============================================

def _detect_absences(db: Session, hours_lookback: int = 72) -> List[Dict[str, Any]]:
    """
    Detect suspicious information voids — when expected signals go silent.

    Types of absence:
    1. ENTITY SILENCE — entity that was generating events suddenly stops
    2. SOURCE DROPOUT — reliable source stops reporting
    3. DOMAIN VOID — entire domain has no events for unusual duration
    4. PREDICTION STALENESS — predictions that should have resolved but haven't
    5. EXPECTED EVENT MISSING — seasonal/scheduled events that didn't happen
    """
    absences = []

    try:
        now = datetime.utcnow()
        recent_cutoff = now - timedelta(hours=hours_lookback)
        historical_cutoff = now - timedelta(days=30)

        # 1. ENTITY SILENCE — entities active in the past 30d but silent in last 72h
        entity_historical = defaultdict(int)  # entity → count in 30d
        entity_recent = defaultdict(int)  # entity → count in 72h

        historical_events = (
            db.query(Event)
            .filter(Event.timestamp >= historical_cutoff)
            .all()
        )

        for event in historical_events:
            if not event.entities:
                continue
            for ent in event.entities:
                name = ent.get("name", "") if isinstance(ent, dict) else str(ent)
                if name and len(name) > 2:
                    entity_historical[name] += 1
                    if event.timestamp and event.timestamp >= recent_cutoff:
                        entity_recent[name] += 1

        for entity, hist_count in entity_historical.items():
            if hist_count >= 10 and entity_recent.get(entity, 0) == 0:
                absences.append({
                    "type": "entity_silence",
                    "entity": entity,
                    "description": (
                        f"'{entity}' appeared in {hist_count} events over 30 days "
                        f"but has ZERO events in the last {hours_lookback} hours. "
                        f"Sudden silence from a previously active entity can indicate "
                        f"information suppression, dramatic change in situation, or "
                        f"media attention shifting elsewhere."
                    ),
                    "historical_count": hist_count,
                    "recent_count": 0,
                    "strength": "HIGH" if hist_count >= 20 else "MEDIUM",
                })

        # 2. SOURCE DROPOUT — sources that were active but stopped
        source_historical = defaultdict(int)
        source_recent = defaultdict(int)

        for event in historical_events:
            source_historical[event.source] += 1
            if event.timestamp and event.timestamp >= recent_cutoff:
                source_recent[event.source] += 1

        for source, hist_count in source_historical.items():
            if hist_count >= 15 and source_recent.get(source, 0) == 0:
                absences.append({
                    "type": "source_dropout",
                    "source": source,
                    "description": (
                        f"Source '{source}' produced {hist_count} events in 30 days "
                        f"but nothing in the last {hours_lookback} hours. "
                        f"Reliable sources going silent can indicate censorship, "
                        f"access restrictions, or institutional disruption."
                    ),
                    "historical_count": hist_count,
                    "recent_count": 0,
                    "strength": "MEDIUM",
                })

        # 3. DOMAIN VOID — check each domain for unusual silence
        domain_historical = defaultdict(int)
        domain_recent = defaultdict(int)

        for event in historical_events:
            domain = event.domain or "unknown"
            domain_historical[domain] += 1
            if event.timestamp and event.timestamp >= recent_cutoff:
                domain_recent[domain] += 1

        for domain, hist_count in domain_historical.items():
            expected_72h = (hist_count / 30) * (hours_lookback / 24)
            actual = domain_recent.get(domain, 0)

            if expected_72h > 5 and actual < expected_72h * 0.2:
                absences.append({
                    "type": "domain_void",
                    "domain": domain,
                    "description": (
                        f"Domain '{domain}' has only {actual} events in the last "
                        f"{hours_lookback}h vs expected ~{expected_72h:.0f}. "
                        f"A {((1 - actual/expected_72h) * 100):.0f}% drop in domain activity "
                        f"suggests either a genuine lull or missed coverage."
                    ),
                    "expected": round(expected_72h, 1),
                    "actual": actual,
                    "strength": "HIGH" if actual == 0 else "MEDIUM",
                })

        # 4. PREDICTION STALENESS — predictions past their deadline that haven't resolved
        stale_preds = (
            db.query(Prediction)
            .filter(
                and_(
                    Prediction.status == "ACTIVE",
                    Prediction.time_condition_end < now.date(),
                )
            )
            .all()
        )

        for pred in stale_preds[:10]:
            absences.append({
                "type": "stale_prediction",
                "prediction_id": pred.id,
                "description": (
                    f"Prediction '{pred.claim[:100]}' by {pred.agent} "
                    f"passed its deadline ({pred.time_condition_end}) but remains ACTIVE. "
                    f"This could mean: the outcome is unclear, resolution data isn't being "
                    f"captured, or the situation has changed in ways we haven't tracked."
                ),
                "agent": pred.agent,
                "strength": "MEDIUM",
            })

        # Sort by strength
        strength_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        absences.sort(key=lambda x: strength_order.get(x.get("strength", "LOW"), 3))

    except Exception as e:
        logger.error(f"Absence detection failed: {e}")

    return absences[:25]


# ============================================
# MULTI-HOP CAUSAL CHAINS (LLM-powered)
# ============================================

async def _find_causal_chains(
    specialist_outputs: Dict[str, Dict[str, Any]],
    entity_convergences: List[Dict[str, Any]],
    db: Session,
) -> Dict[str, Any]:
    """
    Use Claude to find multi-hop causal chains across domains.

    This is the LLM-powered phase that does the deep dot-connecting
    that rule-based systems can't do.
    """
    # Build context for the chain detection LLM
    context_parts = []

    # All specialist predictions organized by agent
    context_parts.append("## SPECIALIST AGENT PREDICTIONS (this cycle)")
    for agent_name, output in specialist_outputs.items():
        context_parts.append(f"\n### {agent_name.upper()}")
        context_parts.append(f"Summary: {output.get('summary', 'N/A')[:300]}")

        for pred in output.get("new_predictions", [])[:5]:
            conf = pred.get("confidence", 0)
            so_what = pred.get("so_what", "")
            context_parts.append(
                f"- [{conf:.0%}] {pred.get('claim', '')[:200]}"
            )
            if so_what:
                context_parts.append(f"  SO WHAT: {so_what[:150]}")

        for update in output.get("prediction_updates", [])[:3]:
            context_parts.append(
                f"- UPDATE {update.get('prediction_id', '???')}: "
                f"→ {update.get('new_confidence', 0):.0%} ({update.get('reasoning', '')[:150]})"
            )

    # Entity convergence signals
    if entity_convergences:
        context_parts.append("\n## ENTITY CONVERGENCE SIGNALS")
        context_parts.append("These entities appear across multiple agent domains simultaneously:")
        for conv in entity_convergences[:10]:
            context_parts.append(
                f"- {conv['entity']} ({conv['signal_strength']}): "
                f"agents={', '.join(conv['agents'].keys())}, "
                f"event_domains={conv.get('event_domains', [])}"
            )

    # Active predictions from DB for broader context
    try:
        active_preds = (
            db.query(Prediction)
            .filter(
                and_(
                    Prediction.status == "ACTIVE",
                    Prediction.current_confidence >= 0.40,
                )
            )
            .order_by(desc(Prediction.current_confidence))
            .limit(30)
            .all()
        )

        context_parts.append("\n## ACTIVE HIGH-CONFIDENCE PREDICTIONS (all agents)")
        for pred in active_preds:
            context_parts.append(
                f"- [{pred.agent}] [{pred.current_confidence:.0%}] {pred.claim[:200]}"
            )
    except Exception as e:
        logger.error(f"Failed to load active predictions for chain detection: {e}")

    # Recent weak signals
    try:
        recent_signals = (
            db.query(WeakSignal)
            .filter(
                WeakSignal.detected_at >= datetime.utcnow() - timedelta(days=7)
            )
            .order_by(desc(WeakSignal.detected_at))
            .limit(10)
            .all()
        )

        if recent_signals:
            context_parts.append("\n## RECENT WEAK SIGNALS (last 7 days)")
            for sig in recent_signals:
                context_parts.append(f"- [{sig.strength}] {sig.signal[:200]}")
    except Exception as e:
        logger.error(f"Failed to load weak signals for chain detection: {e}")

    user_message = (
        "\n".join(context_parts)
        + f"\n\nToday's date: {datetime.utcnow().strftime('%Y-%m-%d')}"
        + "\n\nFind multi-hop causal chains that cross domain boundaries. "
        + "Focus on chains that are NOT obvious and that no individual specialist would see. "
        + "Also identify structural force alignments — where multiple independent structural "
        + "forces (demographic, technological, geopolitical, economic) are all pointing "
        + "in the same direction, even though they have different root causes.\n\n"
        + "Return ONLY the JSON object."
    )

    try:
        raw_response = await call_claude_sonnet(
            system_prompt=CAUSAL_CHAIN_PROMPT,
            user_message=user_message,
            max_tokens=4096,
            temperature=0.4,
        )

        # Parse the response
        text = raw_response.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        parsed = json.loads(text)
        return parsed

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse causal chain response: {e}")
        return {"causal_chains": [], "structural_alignments": []}
    except Exception as e:
        logger.error(f"Causal chain LLM call failed: {e}")
        return {"causal_chains": [], "structural_alignments": []}


# ============================================
# FORMAT SYNTHESIS OUTPUT FOR MASTER STRATEGIST
# ============================================

def format_synthesis_for_master(synthesis_results: Dict[str, Any]) -> str:
    """
    Format synthesis engine output as a context section
    for the Master Strategist prompt.
    """
    sections = []

    sections.append("## CROSS-DOMAIN SYNTHESIS ENGINE OUTPUT")
    sections.append("(Generated by automated cross-domain analysis — validate and build upon these)")

    # Causal chains
    chains = synthesis_results.get("causal_chains", [])
    if chains:
        sections.append(f"\n### MULTI-HOP CAUSAL CHAINS ({len(chains)} detected)")
        for i, chain in enumerate(chains[:5], 1):
            sections.append(f"\n**Chain {i}: {chain.get('chain_id', 'unnamed')}** "
                          f"(probability: {chain.get('overall_probability', 'N/A')})")

            for hop in chain.get("hops", []):
                sections.append(
                    f"  [{hop.get('domain', '?')}] {hop.get('event_or_prediction', '?')}"
                )
                if hop.get("transmission_to_next"):
                    sections.append(
                        f"    → via: {hop['transmission_to_next']} "
                        f"(~{hop.get('time_lag_to_next', '?')})"
                    )

            sections.append(f"  KEY ASSUMPTION: {chain.get('key_assumption', 'N/A')}")
            sections.append(f"  EARLIEST SIGNAL: {chain.get('earliest_signal', 'N/A')}")
            sections.append(f"  SO WHAT: {chain.get('so_what', 'N/A')}")

    # Entity convergence
    convergences = synthesis_results.get("entity_convergence", [])
    if convergences:
        sections.append(f"\n### ENTITY CONVERGENCE ALERTS ({len(convergences)} entities)")
        for conv in convergences[:10]:
            agents_str = ", ".join(conv.get("agents", {}).keys())
            sections.append(
                f"- **{conv['entity']}** [{conv.get('signal_strength', '?')}]: "
                f"appears in {conv.get('agent_count', '?')} agent domains ({agents_str})"
            )
            sections.append(f"  {conv.get('interpretation', '')[:200]}")

    # Absence signals
    absences = synthesis_results.get("absence_signals", [])
    if absences:
        sections.append(f"\n### ABSENCE SIGNALS — SUSPICIOUS SILENCES ({len(absences)} detected)")
        for absence in absences[:8]:
            sections.append(
                f"- [{absence.get('strength', '?')}] [{absence.get('type', '?')}] "
                f"{absence.get('description', '')[:200]}"
            )

    # Temporal dependencies
    deps = synthesis_results.get("temporal_dependencies", [])
    if deps:
        sections.append(f"\n### TEMPORAL DEPENDENCIES ({len(deps)} prediction chains)")
        for dep in deps[:5]:
            pre = dep.get("precondition", {})
            post = dep.get("dependent", {})
            sections.append(
                f"- {pre.get('agent', '?')}'s [{pre.get('confidence', 0):.0%}] "
                f"'{pre.get('claim', '?')[:80]}'"
            )
            sections.append(
                f"  → may precondition → {post.get('agent', '?')}'s [{post.get('confidence', 0):.0%}] "
                f"'{post.get('claim', '?')[:80]}'"
            )
            sections.append(f"  Linking: {', '.join(dep.get('linking_concepts', [])[:5])}")

    # Structural alignments
    alignments = synthesis_results.get("structural_alignments", [])
    if alignments:
        sections.append(f"\n### STRUCTURAL FORCE ALIGNMENTS ({len(alignments)} detected)")
        for align in alignments[:3]:
            sections.append(f"- **{align.get('description', 'N/A')[:200]}**")
            sections.append(f"  Converges on: {align.get('convergence_point', 'N/A')}")
            sections.append(f"  Timeline: {align.get('timeline', 'N/A')}")
            sections.append(f"  Implication: {align.get('implication', 'N/A')}")

    if not any([chains, convergences, absences, deps, alignments]):
        sections.append("\nNo cross-domain patterns detected this cycle.")

    return "\n".join(sections)
