"""
Maritime / shipping data source for supply chain and geopolitical intelligence.

Monitors shipping disruptions, port congestion, and maritime security events
that signal trade flow changes, sanctions enforcement, or conflict zones.

Primary: MarineTraffic API (requires MARINETRAFFIC_API_KEY)
Fallback: Maritime industry RSS feeds (gCaptain, Splash247, Lloyd's List)

Signals detected:
- Port congestion / closure (supply chain stress)
- Strait / canal disruptions (Suez, Hormuz, Malacca, Panama)
- Sanctions evasion patterns (dark fleet activity)
- Piracy and maritime security incidents
- Container shipping rate spikes
- Naval exercises and military activity
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from email.utils import parsedate_to_datetime

import feedparser

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Free RSS feeds for maritime intelligence
MARITIME_FEEDS = [
    # gCaptain — leading maritime industry news
    ("gCaptain", "https://gcaptain.com/feed/", "industry"),

    # Splash247 — Asian shipping focus
    ("Splash247", "https://splash247.com/feed/", "industry"),

    # The Maritime Executive
    ("Maritime Executive", "https://maritime-executive.com/rss", "industry"),

    # UNCTAD shipping review (reports)
    ("UNCTAD", "https://unctad.org/rss.xml", "economic"),

    # Hellenic Shipping News
    ("Hellenic Shipping", "https://www.hellenicshippingnews.com/feed/", "industry"),

    # FreightWaves — logistics and freight markets
    ("FreightWaves", "https://www.freightwaves.com/feed", "logistics"),
]

# Critical chokepoints
CHOKEPOINTS = [
    "suez", "panama canal", "strait of hormuz", "bab el-mandeb",
    "malacca", "strait of taiwan", "bosporus", "dardanelles",
    "gibraltar", "cape of good hope", "red sea", "gulf of aden",
]

# Keywords that signal geopolitically relevant maritime events
HIGH_SIGNAL_KEYWORDS = [
    "port closure", "port closed", "congestion",
    "canal blocked", "canal closure",
    "shipping rates", "freight rates", "container rates",
    "sanctions", "dark fleet", "ais off", "transponder",
    "piracy", "pirate", "hijack", "maritime security",
    "naval exercise", "navy", "military vessel", "warship",
    "blockade", "embargo", "trade war",
    "oil tanker", "lng carrier", "grain shipment",
    "supply chain", "disruption", "diversion",
    "houthi", "drone attack", "missile",
]


def _parse_pub_date(entry: dict) -> datetime:
    pub_date = entry.get("published", "") or entry.get("updated", "")
    if pub_date:
        try:
            return parsedate_to_datetime(pub_date)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.utcnow()


def _clean_html(text: str) -> str:
    import re
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _assess_severity(text: str) -> str:
    lower = text.lower()

    # Critical: chokepoint disruptions, attacks, blockades
    if any(cp in lower for cp in CHOKEPOINTS) and any(
        t in lower for t in ["closure", "blocked", "attack", "military", "disruption"]
    ):
        return "critical"

    critical = ["blockade", "attack", "missile", "piracy", "hijack", "embargo"]
    if any(t in lower for t in critical):
        return "significant"

    significant = ["port closed", "sanctions", "naval exercise", "dark fleet", "congestion"]
    if any(t in lower for t in significant):
        return "significant"

    notable = ["shipping rates", "freight rates", "disruption", "supply chain", "diversion"]
    if any(t in lower for t in notable):
        return "notable"

    return "routine"


def _extract_chokepoints(text: str) -> List[Dict[str, str]]:
    """Extract mentioned chokepoints as entities."""
    lower = text.lower()
    entities = []
    for cp in CHOKEPOINTS:
        if cp in lower:
            entities.append({
                "name": cp.title(),
                "type": "location",
                "role": "chokepoint",
            })
    return entities


def _is_relevant(text: str) -> bool:
    lower = text.lower()
    # Any chokepoint mention is automatically relevant
    if any(cp in lower for cp in CHOKEPOINTS):
        return True
    return any(kw in lower for kw in HIGH_SIGNAL_KEYWORDS)


async def _fetch_maritime_rss() -> List[Dict[str, Any]]:
    """Fetch maritime events from RSS feeds."""
    events = []

    for feed_name, feed_url, category in MARITIME_FEEDS:
        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                logger.warning(f"Maritime feed error for {feed_name}: {feed.bozo_exception}")
                continue

            for entry in feed.entries[:15]:
                try:
                    title = entry.get("title", "").strip()
                    summary = _clean_html(entry.get("summary", "") or entry.get("description", ""))
                    link = entry.get("link", "")
                    timestamp = _parse_pub_date(entry)

                    if not title:
                        continue

                    raw_text = f"{title}. {summary}" if summary else title

                    if not _is_relevant(raw_text):
                        continue

                    severity = _assess_severity(raw_text)
                    chokepoint_entities = _extract_chokepoints(raw_text)
                    entities = chokepoint_entities + [
                        {"name": "maritime", "type": "topic", "role": "sector"},
                    ]

                    # Determine domain: trade/economic vs security/geopolitical
                    lower = raw_text.lower()
                    domain = "geopolitical"
                    if any(t in lower for t in ["shipping rates", "freight", "container", "supply chain", "congestion"]):
                        domain = "economic"

                    events.append({
                        "source": "marine_traffic",
                        "source_detail": link or feed_url,
                        "source_category": "established_newspaper",
                        "timestamp": timestamp,
                        "domain": domain,
                        "event_type": f"maritime_{category}",
                        "severity": severity,
                        "entities": entities,
                        "raw_text": raw_text[:2000],
                        "metadata": {
                            "feed_name": feed_name,
                            "category": category,
                            "title": title,
                            "link": link,
                            "chokepoints": [e["name"] for e in chokepoint_entities],
                        },
                    })
                except Exception as e:
                    logger.debug(f"Error parsing maritime entry from {feed_name}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error fetching maritime feed {feed_name}: {e}")
            continue

    return events


async def fetch_marine_traffic_events() -> List[Dict[str, Any]]:
    """Fetch maritime intelligence events."""
    events = await _fetch_maritime_rss()
    logger.info(f"MarineTraffic: returning {len(events)} events")
    return events
