"""
Google Trends API — Free.
Tracks search interest trends as pre-news signals.
Rising search interest in niche topics precedes mainstream coverage by 3-6 months.
"""

import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

# Keywords organized by domain — monitored for breakout signals
TREND_KEYWORD_GROUPS = {
    "geopolitical": [
        "war", "military buildup", "nuclear threat", "sanctions",
        "coup", "martial law", "refugee crisis", "border conflict",
        "Taiwan invasion", "NATO expansion", "BRICS currency",
    ],
    "economic": [
        "bank run", "recession", "inflation", "rate cut",
        "debt ceiling", "currency crisis", "housing crash",
        "unemployment", "stagflation", "credit crunch",
    ],
    "market": [
        "stock market crash", "bitcoin crash", "gold price",
        "bond yields", "market bubble", "short squeeze",
        "IPO market", "crypto regulation", "commodity shortage",
    ],
    "technology": [
        "AI regulation", "artificial intelligence", "quantum computing",
        "deepfake", "autonomous weapons", "brain computer interface",
        "nuclear fusion", "lab grown meat", "gene editing",
    ],
    "health": [
        "bird flu", "pandemic", "vaccine", "drug shortage",
        "antimicrobial resistance", "mpox", "disease outbreak",
        "hospital capacity", "WHO emergency",
    ],
    "energy_climate": [
        "energy crisis", "oil shortage", "natural gas price",
        "solar power", "nuclear energy", "grid failure",
        "heat wave", "wildfire", "flood", "drought",
    ],
}

# Google Trends uses a relative interest score (0-100)
# We flag significant week-over-week increases
BREAKOUT_THRESHOLD_PCT = 100  # 100% increase = doubled interest
NOTABLE_THRESHOLD_PCT = 50   # 50% increase = notable rise

# SerpAPI or similar for trends data (free tier available)
GOOGLE_TRENDS_API_BASE = "https://serpapi.com/search"


def _classify_domain(keyword: str, keyword_domain: str) -> str:
    """Map keyword group to event domain."""
    domain_map = {
        "geopolitical": "geopolitical",
        "economic": "economic",
        "market": "market",
        "technology": "technology",
        "health": "health",
        "energy_climate": "economic",
    }
    return domain_map.get(keyword_domain, "sentiment")


def _calculate_trend_change(current: int, previous: int) -> float:
    """Calculate percentage change between two interest scores."""
    if previous <= 0:
        return 0.0 if current <= 0 else 999.0
    return ((current - previous) / previous) * 100


async def fetch_google_trends_events(
    timeout: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Fetch trending search data from Google Trends.

    Uses pytrends library for interest over time data.
    Falls back to direct trending searches API if pytrends fails.

    Returns list of event dicts for keywords showing significant changes.
    """
    events = []

    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 30))

        for domain, keywords in TREND_KEYWORD_GROUPS.items():
            # Process keywords in batches of 5 (pytrends limit)
            for i in range(0, len(keywords), 5):
                batch = keywords[i:i + 5]

                try:
                    pytrends.build_payload(
                        batch,
                        cat=0,
                        timeframe="now 7-d",  # Last 7 days for WoW comparison
                        geo="",  # Worldwide
                    )

                    interest_df = pytrends.interest_over_time()

                    if interest_df is None or interest_df.empty:
                        continue

                    for keyword in batch:
                        if keyword not in interest_df.columns:
                            continue

                        series = interest_df[keyword]
                        if len(series) < 2:
                            continue

                        # Compare most recent period to previous
                        # Split into two halves for WoW comparison
                        midpoint = len(series) // 2
                        recent_avg = series.iloc[midpoint:].mean()
                        previous_avg = series.iloc[:midpoint].mean()

                        current_value = int(series.iloc[-1])
                        pct_change = _calculate_trend_change(recent_avg, previous_avg)

                        # Only flag significant changes
                        if pct_change < NOTABLE_THRESHOLD_PCT:
                            continue

                        # Determine severity based on change magnitude
                        if pct_change >= BREAKOUT_THRESHOLD_PCT:
                            severity = "high"
                            signal_type = "BREAKOUT"
                        else:
                            severity = "medium"
                            signal_type = "RISING"

                        raw_text = (
                            f"Google Trends {signal_type}: '{keyword}' search interest "
                            f"{'more than doubled' if pct_change >= BREAKOUT_THRESHOLD_PCT else f'up {pct_change:.0f}%'} "
                            f"over the past week. Current interest score: {current_value}/100. "
                            f"Week-over-week change: +{pct_change:.0f}%. "
                            f"This is a {domain} domain signal suggesting growing public attention."
                        )

                        date_str = datetime.utcnow().strftime("%Y-%m-%d")
                        trend_id = hashlib.md5((keyword + date_str).encode()).hexdigest()[:12]
                        events.append({
                            "id": f"gtrends-{trend_id}",
                            "source": "google_trends",
                            "source_detail": f"trends.google.com/trends/explore?q={keyword.replace(' ', '+')}",
                            "timestamp": datetime.utcnow(),
                            "domain": _classify_domain(keyword, domain),
                            "event_type": "trend_signal",
                            "severity": severity,
                            "entities": [
                                {"name": keyword, "type": "topic", "role": "trend_subject"},
                                {"name": "Google Trends", "type": "organization", "role": "source"},
                            ],
                            "raw_text": raw_text,
                            "metadata": {
                                "keyword": keyword,
                                "keyword_domain": domain,
                                "current_interest": current_value,
                                "recent_avg": round(recent_avg, 1),
                                "previous_avg": round(previous_avg, 1),
                                "pct_change": round(pct_change, 1),
                                "signal_type": signal_type,
                            },
                        })

                except Exception as e:
                    logger.debug(f"Error fetching trends for batch {batch}: {e}")
                    continue

    except ImportError:
        logger.warning("pytrends not installed. Falling back to trending searches via API.")
        events = await _fetch_trending_searches_fallback(timeout)
    except Exception as e:
        logger.error(f"Google Trends fetch error: {e}")
        events = await _fetch_trending_searches_fallback(timeout)

    logger.info(f"Google Trends: returning {len(events)} trend signals")
    return events


async def _fetch_trending_searches_fallback(timeout: float = 30.0) -> List[Dict[str, Any]]:
    """Fallback: fetch Google daily trending searches via direct API."""
    events = []

    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 30))

        trending = pytrends.trending_searches(pn="united_states")

        if trending is not None and not trending.empty:
            for idx, row in trending.iterrows():
                topic = str(row.iloc[0]) if len(row) > 0 else ""
                if not topic:
                    continue

                raw_text = f"Google Trends: '{topic}' is trending in United States today."
                date_str = datetime.utcnow().strftime("%Y-%m-%d")
                trending_id = hashlib.md5((topic + date_str).encode()).hexdigest()[:12]

                events.append({
                    "id": f"gtrends-{trending_id}",
                    "source": "google_trends",
                    "source_detail": f"trends.google.com/trends/trendingsearches/daily?geo=US",
                    "timestamp": datetime.utcnow(),
                    "domain": "sentiment",
                    "event_type": "trending_search",
                    "severity": "routine",
                    "entities": [
                        {"name": topic, "type": "topic", "role": "trending"},
                        {"name": "Google Trends", "type": "organization", "role": "source"},
                    ],
                    "raw_text": raw_text,
                    "metadata": {
                        "topic": topic,
                        "region": "US",
                        "signal_type": "DAILY_TRENDING",
                    },
                })
    except Exception as e:
        logger.warning(f"Trending searches fallback also failed: {e}")

    return events
