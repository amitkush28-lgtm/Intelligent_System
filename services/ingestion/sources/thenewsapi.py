"""
TheNewsAPI.com — Free news API with categorized articles from 80K+ sources.
Returns title, description, snippet, keywords, categories, and source URLs.
Free tier: 3 requests/day. $10/month: 100/day.
Sign up at https://www.thenewsapi.com/

For full article text, we fetch the article URL for high-priority items.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.thenewsapi.com/v1/news"

# Categories to fetch — maps to our domains
CATEGORY_QUERIES = [
    # Geopolitical & world news
    {
        "endpoint": "all",
        "params": {"categories": "politics,general", "language": "en", "limit": 50},
        "domain": "geopolitical",
    },
    # Business & economics
    {
        "endpoint": "all",
        "params": {"categories": "business", "language": "en", "limit": 50},
        "domain": "economic",
    },
    # Technology (affects markets)
    {
        "endpoint": "all",
        "params": {"categories": "tech", "language": "en", "limit": 20},
        "domain": "market",
    },
]


async def _fetch_full_text(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Attempt to fetch full article text from the source URL."""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=10)
        if resp.status_code != 200:
            return None

        html = resp.text
        # Simple extraction: get text between <p> tags
        import re
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
        if not paragraphs:
            return None

        # Clean HTML tags from paragraphs
        text_parts = []
        for p in paragraphs:
            clean = re.sub(r'<[^>]+>', '', p).strip()
            if len(clean) > 50:  # Skip short fragments
                text_parts.append(clean)

        if text_parts:
            return " ".join(text_parts[:10])  # First ~10 paragraphs
        return None

    except Exception:
        return None


async def fetch_thenewsapi_events() -> List[Dict[str, Any]]:
    """
    Fetch articles from TheNewsAPI.com.
    For high-priority articles (geopolitical/economic), attempts to get full text.
    """
    api_key = os.environ.get("THENEWSAPI_KEY", "")
    if not api_key:
        logger.warning("THENEWSAPI_KEY not set, skipping TheNewsAPI source")
        return []

    events = []
    seen_urls = set()

    async with httpx.AsyncClient(timeout=20) as client:
        for query in CATEGORY_QUERIES:
            try:
                params = {
                    "api_token": api_key,
                    **query["params"],
                }

                resp = await client.get(
                    f"{BASE_URL}/{query['endpoint']}",
                    params=params,
                )

                if resp.status_code != 200:
                    logger.warning(f"TheNewsAPI HTTP {resp.status_code} for {query['domain']}")
                    continue

                data = resp.json()
                articles = data.get("data", [])

                for article in articles:
                    try:
                        url = article.get("url", "")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)

                        title = article.get("title", "").strip()
                        description = article.get("description", "").strip()
                        snippet = article.get("snippet", "").strip()
                        keywords = article.get("keywords", "")
                        source = article.get("source", "")
                        published = article.get("published_at", "")
                        categories = article.get("categories", [])
                        image_url = article.get("image_url", "")

                        if not title:
                            continue

                        # Build raw text — use the richest content available
                        raw_text = title
                        if description and len(description) > len(title):
                            raw_text = f"{title}. {description}"
                        if snippet and len(snippet) > len(raw_text):
                            raw_text = f"{title}. {snippet}"
                        if keywords:
                            raw_text += f" [Keywords: {keywords}]"

                        # Parse timestamp
                        timestamp = datetime.utcnow()
                        if published:
                            try:
                                timestamp = datetime.fromisoformat(
                                    published.replace("Z", "+00:00")
                                )
                            except (ValueError, TypeError):
                                pass

                        # Determine severity based on source quality
                        severity = "routine"
                        high_quality_sources = [
                            "reuters.com", "bbc.com", "nytimes.com", "ft.com",
                            "wsj.com", "economist.com", "foreignpolicy.com",
                            "foreignaffairs.com", "apnews.com", "bloomberg.com",
                            "theguardian.com", "washingtonpost.com",
                        ]
                        if any(s in source.lower() for s in high_quality_sources):
                            severity = "notable"

                        # Determine domain from categories
                        domain = query["domain"]
                        if "politics" in categories:
                            domain = "political"
                        elif "business" in categories:
                            domain = "economic"

                        event_id = f"tnapi-{article.get('uuid', '')[:16]}"

                        events.append({
                            "id": event_id,
                            "source": "thenewsapi",
                            "source_detail": url,
                            "source_category": source,
                            "timestamp": timestamp,
                            "domain": domain,
                            "event_type": "news_article",
                            "severity": severity,
                            "entities": [],  # Will be extracted by NLP pipeline
                            "raw_text": raw_text,
                            "metadata": {
                                "title": title,
                                "source_name": source,
                                "url": url,
                                "image_url": image_url,
                                "categories": categories,
                                "keywords": keywords,
                            },
                        })

                    except Exception as e:
                        logger.debug(f"Error parsing TheNewsAPI article: {e}")
                        continue

                logger.debug(f"TheNewsAPI {query['domain']}: {len(articles)} articles")

            except Exception as e:
                logger.warning(f"TheNewsAPI error for {query['domain']}: {e}")
                continue

    # For top articles, try to fetch full text
    full_text_count = 0
    for event in events[:20]:  # Top 20 by order (already sorted by API)
        if event.get("severity") in ("notable", "significant"):
            url = event.get("source_detail", "")
            if url:
                full_text = await _fetch_full_text(client, url)
                if full_text and len(full_text) > len(event.get("raw_text", "")):
                    event["raw_text"] = f"{event['metadata'].get('title', '')}. {full_text}"
                    full_text_count += 1

    logger.info(
        f"TheNewsAPI: returning {len(events)} events "
        f"({full_text_count} with full text)"
    )
    return events
