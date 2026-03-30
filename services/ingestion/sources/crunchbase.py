"""
Crunchbase / startup & venture capital data source.

Uses the free Crunchbase Basic API (rate limited) to track:
- Major funding rounds (Series B+ or $50M+)
- Notable acquisitions
- IPOs and SPACs
- Unicorn milestones

Requires: CRUNCHBASE_API_KEY in environment.
Falls back to TechCrunch RSS if API key not available.
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import feedparser

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# TechCrunch RSS feeds as free fallback
TECHCRUNCH_FEEDS = [
    ("TC Startups", "https://techcrunch.com/category/startups/feed/", "startups"),
    ("TC Venture", "https://techcrunch.com/category/venture/feed/", "venture"),
    ("TC AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "ai"),
]

# Minimum funding threshold to be considered significant (in USD)
MIN_FUNDING_AMOUNT = 50_000_000  # $50M

# Keywords that indicate significant startup/VC events
SIGNAL_KEYWORDS = [
    "series c", "series d", "series e", "series f",
    "ipo", "spac", "acquisition", "acquired",
    "unicorn", "decacorn", "valuation",
    "layoff", "shutdown", "pivot",
    "ai", "artificial intelligence", "machine learning",
    "defense tech", "biotech", "fintech", "climate tech",
    "$1 billion", "$500 million", "$100 million",
    "billion", "raises",
]


def _clean_html(text: str) -> str:
    import re
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _parse_pub_date(entry: dict) -> datetime:
    from email.utils import parsedate_to_datetime
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


def _assess_severity(text: str) -> str:
    lower = text.lower()
    if any(t in lower for t in ["ipo", "acquisition", "billion", "shutdown", "layoff"]):
        return "significant"
    if any(t in lower for t in ["series c", "series d", "unicorn", "$500 million", "$100 million"]):
        return "notable"
    return "routine"


def _is_relevant(text: str) -> bool:
    """Check if the article is relevant to our intelligence scope."""
    lower = text.lower()
    return any(kw in lower for kw in SIGNAL_KEYWORDS)


async def _fetch_via_rss() -> List[Dict[str, Any]]:
    """Fallback: fetch startup/VC news from TechCrunch RSS."""
    events = []

    for feed_name, feed_url, category in TECHCRUNCH_FEEDS:
        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                logger.warning(f"Feed error for {feed_name}: {feed.bozo_exception}")
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

                    entry_hash = hashlib.md5((title + link).encode()).hexdigest()[:12]
                    events.append({
                        "id": f"crunchbase-{entry_hash}",
                        "source": "crunchbase",
                        "source_detail": link or feed_url,
                        "source_category": "established_newspaper",
                        "timestamp": timestamp,
                        "domain": "economic",
                        "event_type": "funding_round",
                        "severity": severity,
                        "entities": [
                            {"name": category, "type": "topic", "role": "category"},
                        ],
                        "raw_text": raw_text[:2000],
                        "metadata": {
                            "feed_name": feed_name,
                            "category": category,
                            "title": title,
                            "link": link,
                            "source_method": "rss_fallback",
                        },
                    })
                except Exception as e:
                    logger.debug(f"Error parsing entry from {feed_name}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error fetching {feed_name}: {e}")
            continue

    return events


async def _fetch_via_api() -> List[Dict[str, Any]]:
    """Fetch from Crunchbase API (if key available)."""
    api_key = getattr(settings, 'CRUNCHBASE_API_KEY', '') or ''
    if not api_key:
        return []

    events = []
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Search for recent large funding rounds
            url = "https://api.crunchbase.com/api/v4/searches/funding_rounds"
            headers = {"X-cb-user-key": api_key}
            payload = {
                "field_ids": [
                    "identifier", "funded_organization_identifier",
                    "money_raised", "announced_on", "investment_type",
                    "lead_investor_identifiers",
                ],
                "order": [{"field_id": "announced_on", "sort": "desc"}],
                "query": [
                    {"type": "predicate", "field_id": "money_raised",
                     "operator_id": "gte", "values": [MIN_FUNDING_AMOUNT]},
                    {"type": "predicate", "field_id": "announced_on",
                     "operator_id": "gte", "values": [
                         (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
                     ]},
                ],
                "limit": 20,
            }

            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("entities", []):
                    props = item.get("properties", {})
                    org = props.get("funded_organization_identifier", {})
                    org_name = org.get("value", "Unknown") if isinstance(org, dict) else str(org)
                    amount = props.get("money_raised", {})
                    amount_usd = amount.get("value_usd", 0) if isinstance(amount, dict) else 0
                    round_type = props.get("investment_type", "funding_round")
                    announced = props.get("announced_on", "")

                    try:
                        timestamp = datetime.strptime(announced, "%Y-%m-%d") if announced else datetime.utcnow()
                    except ValueError:
                        timestamp = datetime.utcnow()

                    amount_str = f"${amount_usd / 1_000_000:.0f}M" if amount_usd else "undisclosed"
                    raw_text = f"{org_name} raised {amount_str} in {round_type}"
                    round_hash = hashlib.md5((org_name + announced + round_type).encode()).hexdigest()[:12]

                    events.append({
                        "id": f"crunchbase-{round_hash}",
                        "source": "crunchbase",
                        "source_detail": f"https://www.crunchbase.com/funding_round/{item.get('uuid', '')}",
                        "source_category": "verified_social_media",
                        "timestamp": timestamp,
                        "domain": "economic",
                        "event_type": "funding_round",
                        "severity": "significant" if amount_usd >= 100_000_000 else "notable",
                        "entities": [
                            {"name": org_name, "type": "organization", "role": "funded"},
                        ],
                        "raw_text": raw_text,
                        "metadata": {
                            "amount_usd": amount_usd,
                            "round_type": round_type,
                            "org_name": org_name,
                            "source_method": "api",
                        },
                    })
            else:
                logger.warning(f"Crunchbase API returned {resp.status_code}: {resp.text[:200]}")

    except ImportError:
        logger.warning("httpx not installed — skipping Crunchbase API")
    except Exception as e:
        logger.error(f"Crunchbase API error: {e}")

    return events


async def fetch_crunchbase_events() -> List[Dict[str, Any]]:
    """Fetch startup/VC events from Crunchbase API or RSS fallback."""
    # Try API first, fall back to RSS
    events = await _fetch_via_api()

    if not events:
        logger.info("Crunchbase API not available, using TechCrunch RSS fallback")
        events = await _fetch_via_rss()

    logger.info(f"Crunchbase: returning {len(events)} events")
    return events
