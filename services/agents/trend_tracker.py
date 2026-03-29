"""
Trend Tracker Service — Weekly analysis of slow-moving structural variables.

Tracks acceleration/deceleration in key metrics that matter for Tier 1 structural theses.
Runs weekly (Sunday) as part of the scheduler or on-demand via API.

Monitors:
- De-dollarization: USD share in reserves, SWIFT transaction share, gold purchases
- AI capability: Benchmark scores, training costs, model sizes, deployment rates
- Energy transition: Renewable capacity additions, EV sales, fossil fuel investment
- Demographics: Migration patterns, labor force participation, urbanization
- Geopolitical alignment: Trade flow shifts, diplomatic realignments, military spending
- Financial stress: Credit spreads, bank lending, sovereign debt ratios

For each metric, tracks:
- Current value and direction (up/down/flat)
- Rate of change (accelerating/decelerating/steady)
- Deviation from historical baseline
- Implications for active predictions and theses
"""

import logging
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from shared.config import get_settings
from shared.database import get_db_session
from shared.llm_client import call_claude_with_web_search, call_claude_haiku, parse_structured_json
from shared.models import Event
from shared.utils import setup_logging

logger = setup_logging("trend_tracker")
settings = get_settings()


# ============================================
# STRUCTURAL VARIABLES TO TRACK
# ============================================

TRACKED_VARIABLES = {
    "de_dollarization": {
        "label": "De-Dollarization Pace",
        "domain": "economic",
        "description": "USD share of global reserves, SWIFT usage, bilateral currency agreements, central bank gold purchases",
        "search_queries": [
            "USD share global reserves 2026",
            "BRICS currency settlement system latest",
            "central bank gold purchases quarterly",
            "de-dollarization trend data",
        ],
        "acceleration_signal": "New bilateral currency agreements, accelerating central bank gold purchases, declining USD reserve share",
        "deceleration_signal": "Failed BRICS currency initiatives, increased USD usage in trade settlement, dollar strengthening trend",
    },
    "ai_capability": {
        "label": "AI Capability Advancement",
        "domain": "technology",
        "description": "Frontier model benchmarks, training compute costs, model efficiency improvements, enterprise adoption rates",
        "search_queries": [
            "AI benchmark scores latest 2026",
            "LLM training cost trends",
            "AI enterprise adoption rate 2026",
            "AI model efficiency breakthroughs",
        ],
        "acceleration_signal": "Faster capability gains per dollar of training compute, rapid enterprise adoption, new capability emergences",
        "deceleration_signal": "Benchmark score plateaus, scaling law diminishing returns, enterprise adoption slower than forecast",
    },
    "energy_transition": {
        "label": "Energy Transition Pace",
        "domain": "economic",
        "description": "Renewable capacity additions, EV sales share, fossil fuel investment, grid-scale battery deployment, nuclear SMR progress",
        "search_queries": [
            "global renewable energy capacity 2026",
            "electric vehicle sales share latest",
            "nuclear SMR approvals 2026",
            "fossil fuel investment trend",
        ],
        "acceleration_signal": "Record renewable installations, EV sales growing faster than forecast, nuclear SMR construction starts",
        "deceleration_signal": "Renewable installation slowdown, EV demand plateau, continued fossil fuel investment growth",
    },
    "china_trajectory": {
        "label": "China Economic Trajectory",
        "domain": "economic",
        "description": "Real GDP growth proxies, property sector health, export competitiveness, technology self-sufficiency, capital flows",
        "search_queries": [
            "China GDP growth actual 2026",
            "China property market latest",
            "China semiconductor self-sufficiency progress",
            "China capital outflows data",
        ],
        "acceleration_signal": "Property sector stabilization, export growth acceleration, technology breakthroughs in chips/AI",
        "deceleration_signal": "Continued property deflation, export deceleration, capital flight, demographic headwinds intensifying",
    },
    "geopolitical_fragmentation": {
        "label": "Global Economic Fragmentation",
        "domain": "geopolitical",
        "description": "Trade flow realignment, supply chain reshoring, technology export controls, alliance formation",
        "search_queries": [
            "global trade fragmentation 2026",
            "reshoring nearshoring trends latest",
            "technology export controls update",
            "BRICS expansion trade agreements",
        ],
        "acceleration_signal": "New export controls, accelerating reshoring investment, expanding sanctions regimes, trade bloc hardening",
        "deceleration_signal": "Trade normalization, sanctions relaxation, cross-bloc investment resuming, diplomatic breakthroughs",
    },
    "financial_stress": {
        "label": "Global Financial Stress",
        "domain": "market",
        "description": "Credit spreads, sovereign debt sustainability, bank lending standards, commercial real estate, shadow banking",
        "search_queries": [
            "credit spreads high yield 2026",
            "sovereign debt crisis risks 2026",
            "commercial real estate defaults latest",
            "bank lending standards survey",
        ],
        "acceleration_signal": "Widening credit spreads, sovereign downgrades, CRE default wave, bank tightening",
        "deceleration_signal": "Spread compression, debt restructuring success, CRE stabilization, lending loosening",
    },
    "climate_impact": {
        "label": "Climate Impact Acceleration",
        "domain": "geopolitical",
        "description": "Extreme weather frequency, agricultural disruption, climate migration, insurance market stress, adaptation spending",
        "search_queries": [
            "extreme weather events 2026 statistics",
            "global food price index latest",
            "climate insurance losses 2026",
            "climate migration trends",
        ],
        "acceleration_signal": "Record extreme weather, crop failures, insurance market withdrawal, forced migration events",
        "deceleration_signal": "Fewer extreme events than forecast, successful adaptation measures, stable food production",
    },
    "defense_spending": {
        "label": "Global Defense Spending Trend",
        "domain": "geopolitical",
        "description": "Military budget changes, weapons procurement, defense tech investment, NATO spending compliance",
        "search_queries": [
            "global military spending 2026",
            "NATO defense spending GDP 2026",
            "defense technology investment trends",
            "arms race indicators latest",
        ],
        "acceleration_signal": "Broad-based spending increases, new weapons programs, conscription debates, defense tech boom",
        "deceleration_signal": "Peace dividend discussions, defense budget cuts, arms control agreements, threat reduction",
    },
}


TREND_ANALYSIS_SYSTEM = """You are a structural trend analyst for an intelligence prediction system.

Your job is to assess the RATE OF CHANGE of a specific structural variable — not just its level, but whether it is ACCELERATING, DECELERATING, or STEADY relative to the past 6-12 months.

Respond with ONLY valid JSON:
{
    "current_assessment": "2-3 sentence summary of the current state of this variable",
    "direction": "ACCELERATING" | "DECELERATING" | "STEADY",
    "confidence_in_direction": 65,
    "key_data_points": [
        "Specific data point 1 with number and date",
        "Specific data point 2 with number and date",
        "Specific data point 3 with number and date"
    ],
    "change_from_6_months_ago": "What has materially changed in the last 6 months",
    "surprise_factor": "What about this trend would surprise most observers",
    "implications": [
        "Specific implication 1 for predictions/investments",
        "Specific implication 2"
    ],
    "watch_items": [
        "Specific upcoming event/data release to watch",
        "Another thing to watch"
    ],
    "severity": "high" | "medium" | "low"
}"""


async def _analyze_single_variable(
    variable_key: str,
    variable_config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Analyze a single structural variable using web search."""
    try:
        search_context = " | ".join(variable_config["search_queries"])

        user_message = f"""Analyze the current state and RATE OF CHANGE of this structural variable:

VARIABLE: {variable_config['label']}
DESCRIPTION: {variable_config['description']}

SEARCH FOR: {search_context}

ACCELERATION WOULD LOOK LIKE: {variable_config['acceleration_signal']}
DECELERATION WOULD LOOK LIKE: {variable_config['deceleration_signal']}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

Instructions:
1. Search for the most recent data on this variable
2. Assess whether the trend is ACCELERATING, DECELERATING, or STEADY vs 6 months ago
3. Provide specific data points with numbers and dates
4. Identify what would surprise most observers
5. List concrete implications for investment and strategic decisions

Respond with ONLY valid JSON."""

        response = await call_claude_with_web_search(
            system_prompt=TREND_ANALYSIS_SYSTEM,
            user_message=user_message,
            max_tokens=4096,
        )

        result = parse_structured_json(response)
        if result:
            result["variable_key"] = variable_key
            result["variable_label"] = variable_config["label"]
            result["domain"] = variable_config["domain"]
            result["analyzed_at"] = datetime.utcnow().isoformat()
        return result

    except Exception as e:
        logger.error(f"Failed to analyze variable {variable_key}: {e}")
        return None


def _create_trend_events(analyses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert trend analyses into events for the ingestion pipeline."""
    events = []

    for analysis in analyses:
        if not analysis:
            continue

        direction = analysis.get("direction", "STEADY")
        label = analysis.get("variable_label", "Unknown")
        severity = analysis.get("severity", "low")
        domain = analysis.get("domain", "economic")

        # Only create events for non-steady trends or high-severity assessments
        if direction == "STEADY" and severity == "low":
            continue

        key_points = analysis.get("key_data_points", [])
        implications = analysis.get("implications", [])

        raw_text = (
            f"Trend Tracker: {label} is {direction}. "
            f"{analysis.get('current_assessment', '')} "
            f"Key data: {'; '.join(key_points[:3])}. "
            f"Surprise factor: {analysis.get('surprise_factor', 'N/A')}. "
            f"Implications: {'; '.join(implications[:2])}."
        )

        events.append({
            "source": "trend_tracker",
            "source_detail": "internal/trend_tracker",
            "timestamp": datetime.utcnow(),
            "domain": domain,
            "event_type": "structural_trend",
            "severity": severity,
            "entities": [
                {"name": label, "type": "trend_variable", "role": "subject"},
                {"name": "Trend Tracker", "type": "system", "role": "source"},
            ],
            "raw_text": raw_text,
            "metadata": {
                "variable_key": analysis.get("variable_key"),
                "direction": direction,
                "confidence": analysis.get("confidence_in_direction"),
                "key_data_points": key_points,
                "implications": implications,
                "watch_items": analysis.get("watch_items", []),
                "change_from_6_months": analysis.get("change_from_6_months_ago"),
            },
        })

    return events


async def _generate_trend_summary(analyses: List[Dict[str, Any]]) -> Optional[str]:
    """Generate a summary of all trend analyses for the newsletter."""
    if not analyses:
        return None

    try:
        summary_parts = []
        for a in analyses:
            if not a:
                continue
            direction_emoji = {"ACCELERATING": "⬆️", "DECELERATING": "⬇️", "STEADY": "➡️"}.get(a.get("direction", ""), "")
            summary_parts.append(
                f"{direction_emoji} {a.get('variable_label', '?')}: {a.get('direction', '?')} "
                f"({a.get('confidence_in_direction', '?')}% confidence). "
                f"{a.get('current_assessment', '')}"
            )

        return "\n\n".join(summary_parts)
    except Exception as e:
        logger.error(f"Failed to generate trend summary: {e}")
        return None


async def run_weekly_trend_analysis(
    variables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run the weekly trend tracker analysis.

    Args:
        variables: Optional list of specific variable keys to analyze.
                   If None, analyzes all tracked variables.

    Returns:
        Stats dict with analysis results.
    """
    stats = {
        "variables_analyzed": 0,
        "accelerating": [],
        "decelerating": [],
        "steady": [],
        "events_created": 0,
        "errors": [],
    }

    logger.info("=" * 60)
    logger.info("TREND TRACKER: Weekly analysis starting")
    logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    # Select variables to analyze
    if variables:
        to_analyze = {k: v for k, v in TRACKED_VARIABLES.items() if k in variables}
    else:
        to_analyze = TRACKED_VARIABLES

    analyses = []

    for var_key, var_config in to_analyze.items():
        logger.info(f"Analyzing: {var_config['label']}...")
        try:
            result = await _analyze_single_variable(var_key, var_config)
            if result:
                analyses.append(result)
                stats["variables_analyzed"] += 1

                direction = result.get("direction", "STEADY")
                label = result.get("variable_label", var_key)

                if direction == "ACCELERATING":
                    stats["accelerating"].append(label)
                elif direction == "DECELERATING":
                    stats["decelerating"].append(label)
                else:
                    stats["steady"].append(label)

                logger.info(f"  → {label}: {direction} ({result.get('confidence_in_direction', '?')}% confidence)")
            else:
                stats["errors"].append(f"No result for {var_key}")
        except Exception as e:
            logger.error(f"Error analyzing {var_key}: {e}")
            stats["errors"].append(f"{var_key}: {str(e)[:100]}")

    # Create events from analyses
    trend_events = _create_trend_events(analyses)
    stats["events_created"] = len(trend_events)

    # Persist trend events to database
    if trend_events:
        try:
            from shared.utils import generate_event_id
            with get_db_session() as db:
                for event_data in trend_events:
                    event_id = generate_event_id(
                        event_data["source"],
                        event_data["raw_text"],
                        event_data["timestamp"],
                    )

                    existing = db.query(Event).filter(Event.id == event_id).first()
                    if existing:
                        continue

                    db_event = Event(
                        id=event_id,
                        source=event_data["source"],
                        source_reliability=0.70,  # Internal analysis source
                        timestamp=event_data["timestamp"],
                        domain=event_data["domain"],
                        event_type=event_data.get("event_type"),
                        severity=event_data.get("severity"),
                        entities=event_data.get("entities"),
                        raw_text=event_data["raw_text"],
                        integrity_score=0.70,
                    )
                    db.add(db_event)

                db.commit()
                logger.info(f"Persisted {len(trend_events)} trend events to database")
        except Exception as e:
            logger.error(f"Failed to persist trend events: {e}")
            stats["errors"].append(f"DB persistence: {str(e)[:100]}")

    # Generate newsletter summary
    summary = await _generate_trend_summary(analyses)
    stats["newsletter_summary"] = summary
    stats["full_analyses"] = analyses

    logger.info("=" * 60)
    logger.info(f"TREND TRACKER COMPLETE")
    logger.info(f"  Analyzed: {stats['variables_analyzed']}")
    logger.info(f"  Accelerating: {', '.join(stats['accelerating']) or 'None'}")
    logger.info(f"  Decelerating: {', '.join(stats['decelerating']) or 'None'}")
    logger.info(f"  Steady: {', '.join(stats['steady']) or 'None'}")
    logger.info(f"  Events created: {stats['events_created']}")
    if stats["errors"]:
        logger.warning(f"  Errors: {len(stats['errors'])}")
    logger.info("=" * 60)

    return stats
