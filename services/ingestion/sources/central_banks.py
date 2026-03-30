"""
Central bank RSS/Atom feeds — monetary policy signals from major central banks.

Sources: Federal Reserve, ECB, Bank of England, Bank of Japan, People's Bank of China,
Reserve Bank of Australia, Bank of Canada, Swiss National Bank.

No API keys required — uses public RSS feeds and feedparser.

Signals detected:
- Interest rate decisions and forward guidance
- Quantitative easing/tightening announcements
- Financial stability warnings
- Inflation targeting updates
- Currency intervention signals
"""

import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from email.utils import parsedate_to_datetime

import feedparser

logger = logging.getLogger(__name__)


# (feed_name, feed_url, bank_code, region)
CENTRAL_BANK_FEEDS = [
    # Federal Reserve
    ("Fed Press Releases", "https://www.federalreserve.gov/feeds/press_all.xml", "FED", "US"),
    ("Fed Speeches", "https://www.federalreserve.gov/feeds/speeches.xml", "FED", "US"),

    # European Central Bank
    ("ECB Press Releases", "https://www.ecb.europa.eu/rss/press.html", "ECB", "EU"),

    # Bank of England
    ("BoE News", "https://www.bankofengland.co.uk/rss/news", "BOE", "UK"),
    ("BoE Publications", "https://www.bankofengland.co.uk/rss/publications", "BOE", "UK"),

    # Bank of Canada
    ("BoC Publications", "https://www.bankofcanada.ca/feed/", "BOC", "CA"),

    # Reserve Bank of Australia
    ("RBA Media Releases", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml", "RBA", "AU"),

    # Swiss National Bank
    ("SNB Press Releases", "https://www.snb.ch/en/rss/mmr-pressemitteilungen", "SNB", "CH"),

    # IMF (international monetary oversight)
    ("IMF News", "https://www.imf.org/en/News/rss", "IMF", "INTL"),

    # BIS (Bank for International Settlements)
    ("BIS Press Releases", "https://www.bis.org/doclist/press_rss.htm", "BIS", "INTL"),
]


# Keywords that signal high-impact monetary policy events
HIGH_IMPACT_KEYWORDS = [
    "interest rate", "rate decision", "basis points", "rate hike", "rate cut",
    "quantitative easing", "quantitative tightening", "asset purchase",
    "inflation target", "price stability", "financial stability",
    "forward guidance", "taper", "balance sheet", "monetary policy",
    "emergency", "intervention", "systemic risk", "stress test",
    "recession", "stagflation", "currency", "exchange rate",
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
    """Determine severity based on keyword presence."""
    lower = text.lower()
    critical_terms = ["emergency", "systemic risk", "crisis", "intervention", "extraordinary"]
    significant_terms = ["rate decision", "rate hike", "rate cut", "basis points", "quantitative"]
    notable_terms = ["inflation", "forward guidance", "policy", "stability", "taper"]

    if any(t in lower for t in critical_terms):
        return "critical"
    if any(t in lower for t in significant_terms):
        return "significant"
    if any(t in lower for t in notable_terms):
        return "notable"
    return "routine"


async def fetch_central_bank_events(
    feeds: Optional[List[tuple]] = None,
    max_per_feed: int = 15,
) -> List[Dict[str, Any]]:
    """Fetch and parse all central bank RSS feeds."""
    target_feeds = feeds or CENTRAL_BANK_FEEDS
    events = []

    for feed_name, feed_url, bank_code, region in target_feeds:
        try:
            logger.debug(f"Fetching central bank feed: {feed_name}")
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                logger.warning(f"Central bank feed error for {feed_name}: {feed.bozo_exception}")
                continue

            for entry in feed.entries[:max_per_feed]:
                try:
                    title = entry.get("title", "").strip()
                    summary = _clean_html(entry.get("summary", "") or entry.get("description", ""))
                    link = entry.get("link", "")
                    timestamp = _parse_pub_date(entry)

                    if not title:
                        continue

                    raw_text = f"[{bank_code}] {title}. {summary}" if summary else f"[{bank_code}] {title}"
                    severity = _assess_severity(raw_text)

                    # Only include items with monetary policy relevance
                    lower_text = raw_text.lower()
                    is_relevant = any(kw in lower_text for kw in HIGH_IMPACT_KEYWORDS)

                    # Always include from primary central banks even if keywords don't match
                    is_primary_bank = bank_code in ("FED", "ECB", "BOE")

                    if not is_relevant and not is_primary_bank:
                        continue

                    title_hash = hashlib.md5(title.encode()).hexdigest()[:12]
                    events.append({
                        "id": f"cb-{bank_code}-{title_hash}",
                        "source": "central_bank",
                        "source_detail": link or feed_url,
                        "source_category": "government_statement",
                        "timestamp": timestamp,
                        "domain": "economic",
                        "event_type": "monetary_policy",
                        "severity": severity,
                        "entities": [
                            {"name": bank_code, "type": "organization", "role": "issuer"},
                            {"name": region, "type": "location", "role": "jurisdiction"},
                        ],
                        "raw_text": raw_text[:2000],
                        "metadata": {
                            "feed_name": feed_name,
                            "bank_code": bank_code,
                            "region": region,
                            "title": title,
                            "link": link,
                        },
                    })
                except Exception as e:
                    logger.debug(f"Error parsing central bank entry from {feed_name}: {e}")
                    continue

            logger.debug(f"Central bank {feed_name}: processed {min(len(feed.entries), max_per_feed)} entries")

        except Exception as e:
            logger.warning(f"Error fetching central bank feed {feed_name}: {e}")
            continue

    logger.info(f"CentralBanks: returning {len(events)} events from {len(target_feeds)} feeds")
    return events
