"""
Trend Intelligence Agent — "What Is Changing and How Fast?"

Runs BEFORE specialist agents each cycle. Analyzes the database for:
1. Event frequency trends — are events in a domain accelerating or decelerating?
2. Confidence velocity — which predictions are moving fast, and in what direction?
3. Source pattern shifts — are new sources lighting up or going quiet?
4. Entity momentum — which entities are appearing more/less frequently?
5. Cross-domain convergence — are multiple domains trending toward the same conclusion?
6. Pattern breaks — statistical outliers vs recent baselines

Produces a TREND INTELLIGENCE BRIEF that gets injected into every specialist's context,
so they know not just "what happened today" but "what direction things are moving."
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import func, and_, desc, case
from sqlalchemy.orm import Session

from shared.models import (
    Event, Prediction, ConfidenceTrail, Claim, WeakSignal,
)
from shared.llm_client import call_claude_sonnet

logger = logging.getLogger(__name__)


# ============================================
# CONFIGURATION
# ============================================

# Lookback windows for trend computation
WINDOWS = {
    "recent": 24,       # hours — today
    "baseline": 168,    # hours — past 7 days
    "extended": 720,    # hours — past 30 days
}

# Minimum event count to compute meaningful trends
MIN_EVENTS_FOR_TREND = 5

# Z-score threshold for flagging anomalies
Z_THRESHOLD = 2.0

# Domains to track
ALL_DOMAINS = ["economic", "geopolitical", "market", "political", "sentiment", "technology", "health"]

TREND_SYNTHESIS_PROMPT = """You are the TREND INTELLIGENCE ANALYST for a multi-agent prediction system.

You receive statistical trend data computed from the system's database. Your job is to:

1. INTERPRET the numbers — what do the trends MEAN for the world?
2. FLAG what matters — which trends should specialists pay attention to?
3. CONNECT trends across domains — if geopolitical events are accelerating AND market volatility is rising, say so
4. IDENTIFY pattern breaks — where is something happening that HASN'T happened recently?
5. WARN about velocity — if a prediction's confidence is moving fast, other agents need to know

Be concise and actionable. Each insight should tell an agent: "Pay attention to X because Y is changing at rate Z."

DO NOT just restate the numbers. INTERPRET them.

Respond in this exact JSON format:
{
  "headline": "One-sentence summary of the most important trend right now",
  "critical_alerts": [
    {
      "domain": "which domain(s) this affects",
      "alert": "What is happening",
      "velocity": "How fast (accelerating/decelerating/steady)",
      "implication": "What this means for predictions",
      "urgency": "high|medium|low"
    }
  ],
  "domain_trends": {
    "economic": "2-3 sentence trend summary for economist agent",
    "geopolitical": "2-3 sentence trend summary for geopolitical agent",
    "market": "2-3 sentence trend summary for investor agent",
    "political": "2-3 sentence trend summary for political agent",
    "sentiment": "2-3 sentence trend summary for sentiment agent"
  },
  "confidence_movers": [
    {
      "prediction_id": "PRED-...",
      "claim": "short claim text",
      "direction": "rising|falling",
      "velocity": "fast|moderate|slow",
      "change_7d": "+0.15 or -0.08",
      "significance": "Why this movement matters"
    }
  ],
  "entity_spotlight": [
    {
      "entity": "Name",
      "trend": "appearing more/less, in what context",
      "cross_domain": true/false,
      "note": "Why this entity deserves attention"
    }
  ],
  "pattern_breaks": [
    {
      "what": "Description of the break",
      "baseline": "What was normal",
      "current": "What is happening now",
      "possible_meaning": "Interpretation"
    }
  ],
  "convergence_signals": [
    {
      "domains": ["domain1", "domain2"],
      "signal": "What multiple domains are pointing toward",
      "confidence": "high|medium|low"
    }
  ]
}"""


# ============================================
# CORE TREND COMPUTATION (No LLM — pure stats)
# ============================================

def compute_event_frequency_trends(db: Session) -> Dict[str, Any]:
    """
    Compare event frequency: today vs 7-day baseline vs 30-day baseline.
    Returns per-domain and per-source frequency ratios.
    """
    now = datetime.utcnow()

    windows = {
        "recent": now - timedelta(hours=WINDOWS["recent"]),
        "baseline": now - timedelta(hours=WINDOWS["baseline"]),
        "extended": now - timedelta(hours=WINDOWS["extended"]),
    }

    domain_trends = {}
    source_trends = {}

    for domain in ALL_DOMAINS:
        counts = {}
        for window_name, cutoff in windows.items():
            count = (
                db.query(func.count(Event.id))
                .filter(and_(Event.timestamp >= cutoff, Event.domain == domain))
                .scalar()
            ) or 0
            counts[window_name] = count

        # Normalize to daily rates
        recent_daily = counts["recent"]  # 24h = 1 day
        baseline_daily = counts["baseline"] / 7 if counts["baseline"] > 0 else 0
        extended_daily = counts["extended"] / 30 if counts["extended"] > 0 else 0

        # Compute trend direction
        if baseline_daily > 0 and counts["recent"] >= MIN_EVENTS_FOR_TREND:
            ratio_vs_baseline = recent_daily / baseline_daily
            ratio_vs_extended = recent_daily / extended_daily if extended_daily > 0 else 1.0
        else:
            ratio_vs_baseline = 1.0
            ratio_vs_extended = 1.0

        direction = "steady"
        if ratio_vs_baseline > 1.5:
            direction = "surging" if ratio_vs_baseline > 2.5 else "accelerating"
        elif ratio_vs_baseline < 0.5:
            direction = "collapsing" if ratio_vs_baseline < 0.25 else "decelerating"
        elif ratio_vs_baseline > 1.2:
            direction = "increasing"
        elif ratio_vs_baseline < 0.8:
            direction = "decreasing"

        domain_trends[domain] = {
            "recent_24h": counts["recent"],
            "avg_daily_7d": round(baseline_daily, 1),
            "avg_daily_30d": round(extended_daily, 1),
            "ratio_vs_7d": round(ratio_vs_baseline, 2),
            "ratio_vs_30d": round(ratio_vs_extended, 2),
            "direction": direction,
        }

    # Per-source trends (top sources only)
    for window_name, cutoff in windows.items():
        rows = (
            db.query(Event.source, func.count(Event.id).label("cnt"))
            .filter(Event.timestamp >= cutoff)
            .group_by(Event.source)
            .all()
        )
        for row in rows:
            if row.source not in source_trends:
                source_trends[row.source] = {}
            source_trends[row.source][window_name] = row.cnt

    # Compute source acceleration
    source_analysis = {}
    for src, counts in source_trends.items():
        recent = counts.get("recent", 0)
        baseline_daily = counts.get("baseline", 0) / 7
        if baseline_daily > 0 and recent >= 3:
            ratio = recent / baseline_daily
            if ratio > 2.0:
                source_analysis[src] = {"ratio": round(ratio, 2), "direction": "spike"}
            elif ratio < 0.3:
                source_analysis[src] = {"ratio": round(ratio, 2), "direction": "dropout"}

    return {
        "domain_trends": domain_trends,
        "source_anomalies": source_analysis,
    }


def compute_confidence_velocity(db: Session) -> List[Dict[str, Any]]:
    """
    Find predictions whose confidence is moving fastest.
    Computes velocity (change/time) and acceleration (change in velocity).
    """
    now = datetime.utcnow()
    cutoff_7d = now - timedelta(days=7)
    cutoff_3d = now - timedelta(days=3)

    # Get active predictions with recent trail entries
    predictions = (
        db.query(Prediction)
        .filter(Prediction.status == "ACTIVE")
        .all()
    )

    movers = []

    for pred in predictions:
        trails = (
            db.query(ConfidenceTrail)
            .filter(ConfidenceTrail.prediction_id == pred.id)
            .order_by(ConfidenceTrail.created_at.asc())
            .all()
        )

        if len(trails) < 2:
            continue

        # Current confidence
        current = trails[-1].value
        current_time = trails[-1].created_at

        # Find confidence 7 days ago (closest trail entry)
        conf_7d = None
        for t in trails:
            if t.created_at >= cutoff_7d:
                conf_7d = t.value
                break
        if conf_7d is None:
            conf_7d = trails[0].value  # earliest available

        # Find confidence 3 days ago
        conf_3d = None
        for t in trails:
            if t.created_at >= cutoff_3d:
                conf_3d = t.value
                break
        if conf_3d is None:
            conf_3d = conf_7d

        change_7d = current - conf_7d
        change_3d = current - conf_3d

        # Velocity = change per day
        days_span = max((current_time - trails[0].created_at).total_seconds() / 86400, 0.1)
        velocity = change_7d / min(days_span, 7)

        # Acceleration = is the change speeding up?
        # Compare velocity in last 3 days vs previous 4 days
        if abs(change_7d) > 0.05 or abs(change_3d) > 0.03:
            velocity_recent = change_3d / 3 if abs(change_3d) > 0.01 else 0
            velocity_prior = (change_7d - change_3d) / 4 if abs(change_7d - change_3d) > 0.01 else 0

            if abs(velocity_recent) > abs(velocity_prior) * 1.5:
                acceleration = "accelerating"
            elif abs(velocity_recent) < abs(velocity_prior) * 0.5:
                acceleration = "decelerating"
            else:
                acceleration = "steady"

            # Classify speed
            abs_velocity = abs(velocity)
            if abs_velocity > 0.05:
                speed = "fast"
            elif abs_velocity > 0.02:
                speed = "moderate"
            else:
                speed = "slow"

            movers.append({
                "prediction_id": pred.id,
                "agent": pred.agent,
                "claim": pred.claim[:120],
                "current_confidence": round(current, 3),
                "change_7d": round(change_7d, 3),
                "change_3d": round(change_3d, 3),
                "velocity_per_day": round(velocity, 4),
                "acceleration": acceleration,
                "speed": speed,
                "direction": "rising" if change_7d > 0 else "falling",
                "trail_count": len(trails),
                "latest_trigger": trails[-1].trigger[:100] if trails[-1].trigger else "",
                "latest_reasoning": trails[-1].reasoning[:200] if trails[-1].reasoning else "",
            })

    # Sort by absolute velocity (fastest movers first)
    movers.sort(key=lambda x: abs(x["velocity_per_day"]), reverse=True)
    return movers[:20]


def compute_entity_momentum(db: Session) -> List[Dict[str, Any]]:
    """
    Track which entities are appearing more/less frequently across events.
    Detects entities gaining momentum across multiple domains.
    """
    now = datetime.utcnow()
    recent_cutoff = now - timedelta(hours=48)
    baseline_cutoff = now - timedelta(days=14)

    # Get entities from recent events
    recent_events = (
        db.query(Event.entities, Event.domain)
        .filter(Event.timestamp >= recent_cutoff)
        .all()
    )

    baseline_events = (
        db.query(Event.entities, Event.domain)
        .filter(and_(
            Event.timestamp >= baseline_cutoff,
            Event.timestamp < recent_cutoff,
        ))
        .all()
    )

    def extract_entities(event_rows) -> Tuple[Counter, Dict[str, set]]:
        counts = Counter()
        domains = defaultdict(set)
        for entities_json, domain in event_rows:
            if not entities_json:
                continue
            entities = entities_json if isinstance(entities_json, list) else []
            for ent in entities:
                name = ent.get("name", "") if isinstance(ent, dict) else str(ent)
                if name and len(name) > 2:
                    counts[name] += 1
                    domains[name].add(domain)
        return counts, domains

    recent_counts, recent_domains = extract_entities(recent_events)
    baseline_counts, baseline_domains = extract_entities(baseline_events)

    # Normalize baseline to 2-day equivalent
    baseline_days = 12  # 14 - 2 days already excluded
    baseline_normalized = {k: v / (baseline_days / 2) for k, v in baseline_counts.items()}

    momentum_entities = []

    for entity, recent_count in recent_counts.most_common(50):
        baseline_rate = baseline_normalized.get(entity, 0)

        if recent_count >= 3:  # Minimum threshold
            if baseline_rate > 0:
                ratio = recent_count / baseline_rate
            else:
                ratio = float(recent_count)  # New entity

            cross_domain = len(recent_domains[entity]) >= 2

            if ratio > 2.0 or (ratio > 1.5 and cross_domain):
                momentum_entities.append({
                    "entity": entity,
                    "recent_mentions": recent_count,
                    "baseline_rate_2d": round(baseline_rate, 1),
                    "momentum_ratio": round(ratio, 2),
                    "domains": sorted(recent_domains[entity]),
                    "cross_domain": cross_domain,
                    "trend": "surging" if ratio > 3.0 else "rising",
                })

        # Also detect entities going quiet
        for entity, baseline_count in baseline_counts.most_common(30):
            if entity not in recent_counts and baseline_normalized.get(entity, 0) > 2:
                momentum_entities.append({
                    "entity": entity,
                    "recent_mentions": 0,
                    "baseline_rate_2d": round(baseline_normalized[entity], 1),
                    "momentum_ratio": 0,
                    "domains": sorted(baseline_domains[entity]),
                    "cross_domain": len(baseline_domains[entity]) >= 2,
                    "trend": "gone_silent",
                })

    # Sort: surging and gone_silent first, then by momentum
    trend_order = {"surging": 0, "gone_silent": 1, "rising": 2}
    momentum_entities.sort(key=lambda x: (trend_order.get(x["trend"], 3), -x.get("momentum_ratio", 0)))

    return momentum_entities[:15]


def compute_severity_escalation(db: Session) -> Dict[str, Any]:
    """
    Track whether event severity is escalating or de-escalating per domain.
    Are we seeing more 'critical' events relative to 'routine' ones?
    """
    now = datetime.utcnow()
    severity_weights = {"critical": 4, "significant": 3, "notable": 2, "routine": 1}

    results = {}

    for window_name, hours in [("recent_24h", 24), ("baseline_7d", 168)]:
        cutoff = now - timedelta(hours=hours)

        rows = (
            db.query(Event.domain, Event.severity, func.count(Event.id))
            .filter(Event.timestamp >= cutoff)
            .group_by(Event.domain, Event.severity)
            .all()
        )

        for domain, severity, count in rows:
            if domain not in results:
                results[domain] = {"recent": {}, "baseline": {}}
            key = "recent" if window_name == "recent_24h" else "baseline"
            results[domain][key][severity or "routine"] = count

    # Compute weighted severity scores
    domain_escalation = {}
    for domain, data in results.items():
        recent_total = sum(data["recent"].values()) or 1
        baseline_total = sum(data["baseline"].values()) or 1

        recent_weighted = sum(
            severity_weights.get(sev, 1) * cnt / recent_total
            for sev, cnt in data["recent"].items()
        )
        baseline_weighted = sum(
            severity_weights.get(sev, 1) * cnt / baseline_total
            for sev, cnt in data["baseline"].items()
        )

        if baseline_weighted > 0:
            escalation = recent_weighted / baseline_weighted
        else:
            escalation = 1.0

        domain_escalation[domain] = {
            "recent_severity_score": round(recent_weighted, 2),
            "baseline_severity_score": round(baseline_weighted, 2),
            "escalation_ratio": round(escalation, 2),
            "direction": "escalating" if escalation > 1.3 else "de-escalating" if escalation < 0.7 else "stable",
        }

    return domain_escalation


def compute_cross_domain_convergence(db: Session) -> List[Dict[str, Any]]:
    """
    Detect when multiple domains are trending in the same direction simultaneously.
    This often signals a systemic shift.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=72)

    # Get recent predictions by domain with their confidence direction
    predictions = (
        db.query(Prediction)
        .filter(and_(Prediction.status == "ACTIVE"))
        .all()
    )

    # Group predictions by rough topic (extract key phrases)
    domain_directions = defaultdict(list)

    for pred in predictions:
        trails = (
            db.query(ConfidenceTrail)
            .filter(ConfidenceTrail.prediction_id == pred.id)
            .order_by(ConfidenceTrail.created_at.desc())
            .limit(3)
            .all()
        )

        if len(trails) >= 2:
            change = trails[0].value - trails[-1].value
            if abs(change) > 0.03:
                domain_directions[pred.agent].append({
                    "claim": pred.claim[:100],
                    "direction": "up" if change > 0 else "down",
                    "magnitude": round(abs(change), 3),
                })

    # Find convergence: multiple agents moving in same direction
    convergence_signals = []

    agents = list(domain_directions.keys())
    for i, agent1 in enumerate(agents):
        for agent2 in agents[i + 1:]:
            up1 = sum(1 for d in domain_directions[agent1] if d["direction"] == "up")
            down1 = sum(1 for d in domain_directions[agent1] if d["direction"] == "down")
            up2 = sum(1 for d in domain_directions[agent2] if d["direction"] == "up")
            down2 = sum(1 for d in domain_directions[agent2] if d["direction"] == "down")

            # Both agents predominantly moving same direction
            if up1 > down1 and up2 > down2 and up1 >= 2 and up2 >= 2:
                convergence_signals.append({
                    "agents": [agent1, agent2],
                    "direction": "both_rising",
                    "strength": min(up1, up2),
                })
            elif down1 > up1 and down2 > up2 and down1 >= 2 and down2 >= 2:
                convergence_signals.append({
                    "agents": [agent1, agent2],
                    "direction": "both_falling",
                    "strength": min(down1, down2),
                })
            elif (up1 > down1 and down2 > up2) or (down1 > up1 and up2 > down2):
                if min(max(up1, down1), max(up2, down2)) >= 2:
                    convergence_signals.append({
                        "agents": [agent1, agent2],
                        "direction": "diverging",
                        "strength": min(max(up1, down1), max(up2, down2)),
                    })

    convergence_signals.sort(key=lambda x: x["strength"], reverse=True)
    return convergence_signals[:10]


# ============================================
# MAIN ENTRY POINT
# ============================================

async def run_trend_intelligence(db: Session) -> Dict[str, Any]:
    """
    Run the full trend intelligence analysis.
    Returns both raw stats and LLM-synthesized brief.
    """
    logger.info("--- Running Trend Intelligence Agent ---")
    start = datetime.utcnow()

    # Phase 1: Compute all statistical trends (no LLM needed)
    stats = {}

    try:
        stats["event_frequency"] = compute_event_frequency_trends(db)
    except Exception as e:
        logger.error(f"Event frequency computation failed: {e}")
        stats["event_frequency"] = {}

    try:
        stats["confidence_velocity"] = compute_confidence_velocity(db)
    except Exception as e:
        logger.error(f"Confidence velocity computation failed: {e}")
        stats["confidence_velocity"] = []

    try:
        stats["entity_momentum"] = compute_entity_momentum(db)
    except Exception as e:
        logger.error(f"Entity momentum computation failed: {e}")
        stats["entity_momentum"] = []

    try:
        stats["severity_escalation"] = compute_severity_escalation(db)
    except Exception as e:
        logger.error(f"Severity escalation computation failed: {e}")
        stats["severity_escalation"] = {}

    try:
        stats["cross_domain_convergence"] = compute_cross_domain_convergence(db)
    except Exception as e:
        logger.error(f"Cross-domain convergence computation failed: {e}")
        stats["cross_domain_convergence"] = []

    # Phase 2: LLM synthesis — interpret the numbers
    import json
    trend_data_str = json.dumps(stats, indent=2, default=str)

    try:
        from shared.llm_client import parse_structured_json

        raw_response = await call_claude_sonnet(
            system_prompt=TREND_SYNTHESIS_PROMPT,
            user_message=f"Here is the trend data from the database. Analyze and interpret:\n\n{trend_data_str}",
            max_tokens=4096,
            temperature=0.3,
        )

        brief = parse_structured_json(raw_response)
        if not brief or not brief.get("headline"):
            logger.warning("Trend synthesis LLM response didn't parse, using raw stats")
            brief = _build_fallback_brief(stats)
    except Exception as e:
        logger.error(f"Trend synthesis LLM failed: {e}")
        brief = _build_fallback_brief(stats)

    elapsed = (datetime.utcnow() - start).total_seconds()
    logger.info(f"Trend Intelligence complete in {elapsed:.1f}s")

    return {
        "raw_stats": stats,
        "brief": brief,
        "computed_at": datetime.utcnow().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
    }


def _build_fallback_brief(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Build a minimal brief from raw stats when LLM fails."""
    # Find domains with biggest changes
    alerts = []
    freq = stats.get("event_frequency", {}).get("domain_trends", {})
    for domain, data in freq.items():
        if data.get("direction") in ("surging", "accelerating", "collapsing", "decelerating"):
            alerts.append({
                "domain": domain,
                "alert": f"Event frequency {data['direction']}: {data['ratio_vs_7d']}x vs 7-day baseline",
                "velocity": data["direction"],
                "implication": f"{data['recent_24h']} events in 24h vs {data['avg_daily_7d']}/day average",
                "urgency": "high" if data["direction"] in ("surging", "collapsing") else "medium",
            })

    movers = stats.get("confidence_velocity", [])[:5]

    return {
        "headline": f"{len(alerts)} domain(s) showing unusual activity; {len(movers)} predictions moving fast",
        "critical_alerts": alerts,
        "domain_trends": {},
        "confidence_movers": [
            {
                "prediction_id": m["prediction_id"],
                "claim": m["claim"],
                "direction": m["direction"],
                "velocity": m["speed"],
                "change_7d": f"{m['change_7d']:+.3f}",
                "significance": m["latest_trigger"],
            }
            for m in movers
        ],
        "entity_spotlight": [],
        "pattern_breaks": [],
        "convergence_signals": [],
    }


def format_trend_brief_for_agents(trend_results: Dict[str, Any], agent_name: str = None) -> str:
    """
    Format the trend brief as a string for injection into agent context.
    If agent_name is provided, highlights that agent's domain trends.
    """
    brief = trend_results.get("brief", {})
    if not brief:
        return ""

    sections = []
    sections.append("=" * 60)
    sections.append("TREND INTELLIGENCE BRIEF")
    sections.append(f"Computed at: {trend_results.get('computed_at', 'unknown')}")
    sections.append("=" * 60)

    # Headline
    headline = brief.get("headline", "")
    if headline:
        sections.append(f"\nHEADLINE: {headline}\n")

    # Critical alerts
    alerts = brief.get("critical_alerts", [])
    if alerts:
        sections.append("CRITICAL ALERTS:")
        for a in alerts:
            urgency = a.get("urgency", "medium").upper()
            sections.append(f"  [{urgency}] {a.get('domain', '?')}: {a.get('alert', '')}")
            sections.append(f"    Velocity: {a.get('velocity', '?')} | Implication: {a.get('implication', '')}")

    # Domain-specific trend (if agent specified)
    domain_map = {
        "economist": "economic",
        "geopolitical": "geopolitical",
        "investor": "market",
        "political": "political",
        "sentiment": "sentiment",
    }

    if agent_name and agent_name in domain_map:
        domain_key = domain_map[agent_name]
        domain_trend = brief.get("domain_trends", {}).get(domain_key, "")
        if domain_trend:
            sections.append(f"\nYOUR DOMAIN TREND ({domain_key.upper()}):")
            sections.append(f"  {domain_trend}")

    # Confidence movers
    movers = brief.get("confidence_movers", [])
    if movers:
        sections.append("\nFASTEST-MOVING PREDICTIONS:")
        for m in movers[:7]:
            sections.append(
                f"  {m.get('prediction_id', '?')}: {m.get('direction', '?')} ({m.get('velocity', '?')}) "
                f"[7d: {m.get('change_7d', '?')}] — {m.get('claim', '')[:80]}"
            )

    # Entity spotlight
    entities = brief.get("entity_spotlight", [])
    if entities:
        sections.append("\nENTITY SPOTLIGHT:")
        for e in entities[:5]:
            cross = " [CROSS-DOMAIN]" if e.get("cross_domain") else ""
            sections.append(f"  {e.get('entity', '?')}: {e.get('trend', '')}{cross}")

    # Pattern breaks
    breaks = brief.get("pattern_breaks", [])
    if breaks:
        sections.append("\nPATTERN BREAKS:")
        for b in breaks[:3]:
            sections.append(f"  {b.get('what', '?')}")
            sections.append(f"    Baseline: {b.get('baseline', '?')} → Now: {b.get('current', '?')}")

    # Convergence signals
    convergence = brief.get("convergence_signals", [])
    if convergence:
        sections.append("\nCROSS-DOMAIN CONVERGENCE:")
        for c in convergence[:3]:
            domains = ", ".join(c.get("domains", []))
            sections.append(f"  [{domains}]: {c.get('signal', '')}")

    sections.append("\n" + "=" * 60)
    return "\n".join(sections)
