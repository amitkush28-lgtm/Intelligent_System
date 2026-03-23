"""
Event classification: map raw events to domain
(geopolitical/economic/market/political/sentiment) and severity
(routine/notable/significant/critical).

Uses keyword-based rules first, falls back to Claude Haiku for ambiguous cases.
"""

import logging
import re
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Domain classification keywords (checked against raw_text + entity types)
DOMAIN_KEYWORDS = {
    "geopolitical": {
        "keywords": {
            "military", "troops", "invasion", "sanctions", "nato", "un security council",
            "territorial", "sovereignty", "border", "missile", "nuclear", "defense",
            "alliance", "diplomatic", "embassy", "ceasefire", "occupation", "annex",
            "blockade", "warship", "submarine", "airspace", "weapon", "armament",
            "peacekeeping", "conflict zone", "war crime", "refugee", "displacement",
            "intelligence", "espionage", "cyber attack", "drone strike",
        },
        "entity_types": {"military", "rebel", "intergovernmental_org"},
    },
    "economic": {
        "keywords": {
            "gdp", "inflation", "interest rate", "central bank", "federal reserve",
            "monetary policy", "fiscal", "unemployment", "jobs report", "trade deficit",
            "trade surplus", "tariff", "export", "import", "currency", "exchange rate",
            "recession", "stimulus", "debt", "bond", "yield curve", "quantitative",
            "consumer price", "producer price", "retail sales", "industrial production",
            "manufacturing", "supply chain", "commodity", "oil price", "opec",
            "imf", "world bank", "economic growth", "contraction",
        },
        "entity_types": set(),
    },
    "market": {
        "keywords": {
            "stock", "equity", "s&p 500", "nasdaq", "dow jones", "market cap",
            "ipo", "merger", "acquisition", "earnings", "revenue", "profit",
            "hedge fund", "etf", "index fund", "volatility", "vix", "options",
            "futures", "short selling", "buyback", "dividend", "valuation",
            "bull market", "bear market", "correction", "rally", "crash",
            "fintech", "cryptocurrency", "bitcoin", "ethereum", "blockchain",
            "sec filing", "13f", "insider trading", "market manipulation",
        },
        "entity_types": {"business", "multinational_corp"},
    },
    "political": {
        "keywords": {
            "election", "vote", "ballot", "congress", "parliament", "legislation",
            "bill", "law", "regulation", "executive order", "supreme court",
            "judiciary", "impeach", "campaign", "primary", "caucus", "poll",
            "approval rating", "partisan", "bipartisan", "filibuster", "veto",
            "cabinet", "governor", "senator", "representative", "lobby",
            "political party", "democrat", "republican", "opposition", "coalition",
            "referendum", "constitutional", "amendment", "policy",
        },
        "entity_types": {"political_party", "opposition"},
    },
    "sentiment": {
        "keywords": {
            "public opinion", "social media", "viral", "trending", "narrative",
            "disinformation", "misinformation", "propaganda", "media bias",
            "protest movement", "grassroots", "activist", "boycott", "petition",
            "cultural", "demographic", "generation", "inequality", "polarization",
            "trust", "credibility", "conspiracy", "perception", "approval",
        },
        "entity_types": {"media"},
    },
}

# Severity classification signals
SEVERITY_SIGNALS = {
    "critical": {
        "keywords": {
            "war", "invasion", "nuclear", "crisis", "emergency", "catastroph",
            "collapse", "crash", "default", "pandemic", "martial law",
            "assassination", "coup", "revolution", "mass casualty",
        },
        "min_sources": 10,
        "min_goldstein_magnitude": 7.0,
    },
    "significant": {
        "keywords": {
            "sanction", "ceasefire", "escalat", "de-escalat", "breakthrough",
            "agreement", "treaty", "summit", "rate cut", "rate hike",
            "recession", "stimulus", "major", "unprecedented", "historic",
            "landmark", "surge", "plunge", "shock",
        },
        "min_sources": 5,
        "min_goldstein_magnitude": 4.0,
    },
    "notable": {
        "keywords": {
            "announce", "report", "increase", "decrease", "change",
            "develop", "plan", "propose", "expect", "forecast",
            "meeting", "conference", "statement", "update",
        },
        "min_sources": 3,
        "min_goldstein_magnitude": 2.0,
    },
}


def _count_keyword_matches(text: str, keywords: set) -> int:
    """Count how many keywords appear in the text."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def classify_domain(event: Dict[str, Any]) -> str:
    """
    Classify event into a domain based on text content and entities.

    Returns one of: geopolitical, economic, market, political, sentiment
    """
    # If already classified (e.g., by GDELT's CAMEO mapping), use it
    if event.get("domain") and event["domain"] in DOMAIN_KEYWORDS:
        return event["domain"]

    raw_text = event.get("raw_text", "")
    entities = event.get("entities", []) or []
    entity_types = {e.get("type", "") for e in entities}

    scores: Dict[str, float] = {}

    for domain, config in DOMAIN_KEYWORDS.items():
        keyword_score = _count_keyword_matches(raw_text, config["keywords"])
        entity_score = len(config["entity_types"] & entity_types) * 2  # Weight entity matches higher
        scores[domain] = keyword_score + entity_score

    # If we have a clear winner, use it
    if scores:
        max_score = max(scores.values())
        if max_score > 0:
            return max(scores, key=scores.get)

    # Default based on source
    source = event.get("source", "")
    source_domain_map = {
        "fred": "economic",
        "twelve_data": "market",
        "propublica": "political",
        "polymarket": "sentiment",
        "acled": "geopolitical",
        "cftc": "market",
    }
    return source_domain_map.get(source, "geopolitical")


def classify_severity(event: Dict[str, Any]) -> str:
    """
    Classify event severity: routine | notable | significant | critical

    Uses keyword presence, source count, and Goldstein scale (for GDELT).
    """
    # If already classified (e.g., by GDELT), validate/override
    existing = event.get("severity", "")

    raw_text = event.get("raw_text", "")
    metadata = event.get("metadata", {}) or {}
    num_sources = metadata.get("num_sources", 1)
    goldstein = abs(metadata.get("goldstein_scale", 0.0))

    # Score each severity level
    for severity in ("critical", "significant", "notable"):
        config = SEVERITY_SIGNALS[severity]

        keyword_match = _count_keyword_matches(raw_text, config["keywords"])
        source_match = num_sources >= config["min_sources"]
        goldstein_match = goldstein >= config["min_goldstein_magnitude"]

        # Need at least 2 of 3 signals, or strong keyword match
        signals = sum([keyword_match >= 2, source_match, goldstein_match])
        if signals >= 2 or keyword_match >= 3:
            return severity

    # If existing severity is set and not routine, keep it
    if existing and existing != "routine":
        return existing

    return "routine"


def classify_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Full event classification: sets domain and severity.
    Modifies event dict in place and returns it.
    """
    event["domain"] = classify_domain(event)
    event["severity"] = classify_severity(event)
    return event


def classify_events_batch(events: list) -> list:
    """Classify a batch of events. Returns the same list with domain/severity set."""
    for event in events:
        classify_event(event)

    # Log distribution
    domain_counts: Dict[str, int] = {}
    severity_counts: Dict[str, int] = {}
    for e in events:
        domain_counts[e["domain"]] = domain_counts.get(e["domain"], 0) + 1
        severity_counts[e["severity"]] = severity_counts.get(e["severity"], 0) + 1

    logger.info(f"Classification: domains={domain_counts}, severities={severity_counts}")
    return events
