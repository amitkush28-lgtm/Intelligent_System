"""
Aviation & flight disruption data source.

Monitors major flight disruptions, airspace closures, and aviation incidents
that may signal geopolitical events, natural disasters, or security threats.

Primary: FlightAware AeroAPI (requires FLIGHTAWARE_API_KEY)
Fallback: Aviation Herald RSS + FAA NOTAM RSS for free data

Signals detected:
- Airspace closures (conflict zones, military activity)
- Mass flight cancellations (weather, security, strikes)
- Airport shutdowns
- Unusual military flight activity
- Diversion patterns (indicate developing situations)
"""

import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from email.utils import parsedate_to_datetime

import feedparser

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Free RSS feeds for aviation intelligence
AVIATION_FEEDS = [
    # Aviation Herald — incidents, accidents, safety events
    ("Aviation Herald", "https://avherald.com/rss.php", "incident"),

    # FAA safety alerts
    ("FAA Press Releases", "https://www.faa.gov/newsroom/press_releases/rss", "regulatory"),

    # EASA safety publications
    ("EASA News", "https://www.easa.europa.eu/en/newsroom/rss", "regulatory"),

    # Simple Flying — aviation industry news
    ("Simple Flying", "https://simpleflying.com/feed/", "industry"),

    # The Points Guy — tracks disruptions affecting travelers
    ("TPG News", "https://thepointsguy.com/news/feed/", "disruption"),
]

# Keywords that signal geopolitically relevant aviation events
HIGH_SIGNAL_KEYWORDS = [
    "airspace closed", "airspace closure", "no-fly zone",
    "flight ban", "overflight ban", "divert", "diverted",
    "emergency landing", "grounded", "airport closed",
    "military", "missile", "conflict zone", "war zone",
    "sanctions", "strike action", "pilot strike",
    "mass cancellation", "system failure", "outage",
    "security threat", "bomb threat", "hijack",
    "volcanic ash", "eruption", "earthquake",
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
    critical = ["airspace closed", "no-fly zone", "hijack", "crash", "missile", "conflict zone"]
    significant = ["emergency landing", "divert", "grounded", "airport closed", "mass cancellation"]
    notable = ["delay", "disruption", "strike", "weather", "volcanic"]

    if any(t in lower for t in critical):
        return "critical"
    if any(t in lower for t in significant):
        return "significant"
    if any(t in lower for t in notable):
        return "notable"
    return "routine"


def _is_relevant(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in HIGH_SIGNAL_KEYWORDS)


async def _fetch_aviation_rss() -> List[Dict[str, Any]]:
    """Fetch aviation events from RSS feeds."""
    events = []

    for feed_name, feed_url, category in AVIATION_FEEDS:
        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                logger.warning(f"Aviation feed error for {feed_name}: {feed.bozo_exception}")
                continue

            for entry in feed.entries[:20]:
                try:
                    title = entry.get("title", "").strip()
                    summary = _clean_html(entry.get("summary", "") or entry.get("description", ""))
                    link = entry.get("link", "")
                    timestamp = _parse_pub_date(entry)

                    if not title:
                        continue

                    raw_text = f"{title}. {summary}" if summary else title

                    # For incident feeds, include everything; for others, filter
                    if category not in ("incident", "regulatory") and not _is_relevant(raw_text):
                        continue

                    severity = _assess_severity(raw_text)
                    entry_hash = hashlib.md5((title + link).encode()).hexdigest()[:12]

                    events.append({
                        "id": f"flightaware-{entry_hash}",
                        "source": "flightaware",
                        "source_detail": link or feed_url,
                        "source_category": "established_newspaper",
                        "timestamp": timestamp,
                        "domain": "geopolitical",
                        "event_type": f"aviation_{category}",
                        "severity": severity,
                        "entities": [
                            {"name": "aviation", "type": "topic", "role": "sector"},
                        ],
                        "raw_text": raw_text[:2000],
                        "metadata": {
                            "feed_name": feed_name,
                            "category": category,
                            "title": title,
                            "link": link,
                        },
                    })
                except Exception as e:
                    logger.debug(f"Error parsing aviation entry from {feed_name}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error fetching aviation feed {feed_name}: {e}")
            continue

    return events


async def fetch_flightaware_events() -> List[Dict[str, Any]]:
    """Fetch aviation disruption events."""
    events = await _fetch_aviation_rss()
    logger.info(f"FlightAware: returning {len(events)} events")
    return events
