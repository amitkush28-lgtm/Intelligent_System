"""
NewsData.io API — 200 credits/day free tier.
News articles with category/country/language filters.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

NEWSDATA_BASE_URL = "https://newsdata.io/api/1/latest"

# Categories to monitor
CATEGORIES = ["politics", "business", "world", "top"]

# Languages
LANGUAGES = ["en"]


async def fetch_newsdata_events(
    max_results: int = 50,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Fetch latest news from NewsData.io API.
    Returns list of event dicts.
    """
    if not settings.NEWSDATA_API_KEY:
        logger.warning("NEWSDATA_API_KEY not set, skipping NewsData source")
        return []

    events = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        for category in CATEGORIES:
            try:
                params = {
                    "apikey": settings.NEWSDATA_API_KEY,
                    "category": category,
                    "language": ",".join(LANGUAGES),
                    "size": min(max_results // len(CATEGORIES), 10),
                }

                resp = await client.get(NEWSDATA_BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") != "success":
                    logger.warning(f"NewsData API error for {category}: {data.get('message', 'unknown')}")
                    continue

                articles = data.get("results", [])

                for article in articles:
                    try:
                        title = article.get("title", "").strip()
                        description = article.get("description", "") or ""
                        content = article.get("content", "") or ""
                        link = article.get("link", "")
                        pub_date = article.get("pubDate", "")
                        source_id = article.get("source_id", "")
                        source_name = article.get("source_name", source_id)
                        country = article.get("country", [])
                        keywords = article.get("keywords") or []

                        if not title:
                            continue

                        # Parse timestamp
                        timestamp = datetime.utcnow()
                        if pub_date:
                            try:
                                timestamp = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                            except (ValueError, TypeError):
                                pass

                        # Build raw text
                        raw_text = title
                        if description:
                            raw_text += f". {description}"

                        # Build entities from keywords and metadata
                        entities = []
                        for kw in keywords[:5]:
                            if kw and len(kw) > 2:
                                entities.append({"name": kw, "type": "topic", "role": "keyword"})
                        if isinstance(country, list):
                            for c in country[:3]:
                                entities.append({"name": c, "type": "nation", "role": "country"})
                        elif country:
                            entities.append({"name": country, "type": "nation", "role": "country"})

                        events.append({
                            "source": "newsdata",
                            "source_detail": link or f"newsdata.io/{source_name}",
                            "source_category": "regional_outlet",
                            "timestamp": timestamp,
                            "domain": "",  # Will be classified
                            "event_type": "news_article",
                            "severity": "",  # Will be classified
                            "entities": entities,
                            "raw_text": raw_text,
                            "metadata": {
                                "source_name": source_name,
                                "category": category,
                                "link": link,
                                "country": country,
                                "keywords": keywords,
                                "image_url": article.get("image_url", ""),
                            },
                        })
                    except Exception as e:
                        logger.debug(f"Error parsing NewsData article: {e}")
                        continue

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("NewsData rate limit reached")
                    break
                logger.error(f"NewsData HTTP error for {category}: {e.response.status_code}")
            except httpx.TimeoutException:
                logger.warning(f"NewsData timeout for {category}")
            except Exception as e:
                logger.error(f"NewsData error for {category}: {e}")

    logger.info(f"NewsData: returning {len(events)} events")
    return events
