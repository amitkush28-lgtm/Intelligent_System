"""
RSS feed aggregator for major news outlets.
Sources: BBC, Al Jazeera, Reuters, NYT, Guardian, FT headlines.
No API keys needed — uses feedparser library.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from email.utils import parsedate_to_datetime

import feedparser

logger = logging.getLogger(__name__)

# RSS feed configuration: (name, url, source_category)
RSS_FEEDS = [
    # Wire services / Major outlets
    ("Reuters World", "https://feeds.reuters.com/Reuters/worldNews", "reuters"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", "reuters"),
    ("AP Top News", "https://rsshub.app/apnews/topics/apf-topnews", "ap"),

    # BBC
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml", "established_newspaper"),
    ("BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml", "established_newspaper"),
    ("BBC Politics", "http://feeds.bbci.co.uk/news/politics/rss.xml", "established_newspaper"),

    # Al Jazeera
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "established_newspaper"),

    # NYT
    ("NYT World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "established_newspaper"),
    ("NYT Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "established_newspaper"),
    ("NYT Politics", "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml", "established_newspaper"),

    # Guardian
    ("Guardian World", "https://www.theguardian.com/world/rss", "established_newspaper"),
    ("Guardian Business", "https://www.theguardian.com/uk/business/rss", "established_newspaper"),

    # FT (limited free RSS)
    ("FT World", "https://www.ft.com/world?format=rss", "established_newspaper"),

    # Think tanks (bonus)
    ("Brookings", "https://www.brookings.edu/feed/", "think_tank"),
    ("CFR", "https://www.cfr.org/rss/publication", "think_tank"),
]


def _parse_pub_date(entry: dict) -> datetime:
    """Parse publication date from RSS entry."""
    pub_date = entry.get("published", "") or entry.get("updated", "")
    if pub_date:
        try:
            return parsedate_to_datetime(pub_date)
        except Exception:
            pass
        # Try ISO format
        try:
            return datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.utcnow()


def _clean_html(text: str) -> str:
    """Remove HTML tags from text."""
    import re
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _extract_feed_entities(entry: dict) -> List[Dict[str, str]]:
    """Extract basic entities from RSS entry metadata."""
    entities = []

    # Categories/tags often indicate topics
    tags = entry.get("tags", [])
    for tag in tags:
        term = tag.get("term", "")
        if term and len(term) > 2:
            entities.append({
                "name": term,
                "type": "topic",
                "role": "tag",
            })

    # Author
    author = entry.get("author", "")
    if author and author not in ("", "Reuters", "AP", "BBC", "NYT"):
        entities.append({
            "name": author,
            "type": "person",
            "role": "author",
        })

    return entities[:10]  # Cap at 10


async def fetch_rss_events(
    feeds: Optional[List[tuple]] = None,
    max_per_feed: int = 20,
) -> List[Dict[str, Any]]:
    """
    Fetch and parse all configured RSS feeds.
    Returns list of event dicts.
    """
    target_feeds = feeds or RSS_FEEDS
    events = []

    for feed_name, feed_url, source_category in target_feeds:
        try:
            logger.debug(f"Fetching RSS feed: {feed_name}")
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                logger.warning(f"RSS feed error for {feed_name}: {feed.bozo_exception}")
                continue

            for entry in feed.entries[:max_per_feed]:
                try:
                    title = entry.get("title", "").strip()
                    summary = _clean_html(entry.get("summary", "") or entry.get("description", ""))
                    link = entry.get("link", "")
                    timestamp = _parse_pub_date(entry)

                    if not title:
                        continue

                    raw_text = f"{title}. {summary}" if summary else title

                    events.append({
                        "source": "rss",
                        "source_detail": link or feed_url,
                        "source_category": source_category,
                        "timestamp": timestamp,
                        "domain": "",  # Will be classified by classifier
                        "event_type": "news_article",
                        "severity": "",  # Will be classified
                        "entities": _extract_feed_entities(entry),
                        "raw_text": raw_text,
                        "metadata": {
                            "feed_name": feed_name,
                            "title": title,
                            "link": link,
                            "author": entry.get("author", ""),
                        },
                    })
                except Exception as e:
                    logger.debug(f"Error parsing RSS entry from {feed_name}: {e}")
                    continue

            logger.debug(f"RSS {feed_name}: {min(len(feed.entries), max_per_feed)} entries")

        except Exception as e:
            logger.warning(f"Error fetching RSS feed {feed_name}: {e}")
            continue

    logger.info(f"RSS: returning {len(events)} events from {len(target_feeds)} feeds")
    return events
