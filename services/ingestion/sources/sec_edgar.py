"""
SEC EDGAR — Free API for fund holdings (13F), company filings, insider trades.
Primary data for the Investor agent. 10 requests/second, no key needed.
API docs: https://efts.sec.gov/LATEST/search-index?q=...
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://efts.sec.gov/LATEST"
HEADERS = {"User-Agent": "IntelligenceSystem/1.0 (research@example.com)"}


async def fetch_sec_edgar_events() -> List[Dict[str, Any]]:
    """Fetch recent SEC filings relevant to market intelligence."""
    events = []

    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            # Recent full-text search for market-moving filings
            for query, filing_type in [
                ("merger acquisition", "8-K"),
                ("bankruptcy restructuring", "8-K"),
                ("executive departure", "8-K"),
                ("guidance revision", "8-K"),
            ]:
                try:
                    resp = await client.get(
                        f"{EDGAR_BASE}/search-index",
                        params={
                            "q": query,
                            "dateRange": "custom",
                            "startdt": (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d"),
                            "enddt": datetime.utcnow().strftime("%Y-%m-%d"),
                            "forms": filing_type,
                        },
                    )

                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    hits = data.get("hits", {}).get("hits", [])

                    for hit in hits[:10]:
                        source = hit.get("_source", {})
                        entity = source.get("entity_name", "Unknown")
                        form = source.get("form_type", filing_type)
                        filed = source.get("file_date", "")
                        description = source.get("display_names", [query])[0] if source.get("display_names") else query

                        events.append({
                            "id": f"edgar-{hit.get('_id', '')}",
                            "source": "sec_edgar",
                            "source_detail": f"SEC EDGAR {form}",
                            "timestamp": datetime.fromisoformat(filed) if filed else datetime.utcnow(),
                            "domain": "market",
                            "event_type": f"sec_filing_{form.lower().replace('-', '')}",
                            "severity": "notable",
                            "raw_text": f"{entity}: {form} filing — {description}",
                            "entities": [{"name": entity, "type": "organization", "role": "filer"}],
                        })
                except Exception as e:
                    logger.debug(f"EDGAR query '{query}' failed: {e}")
                    continue

    except Exception as e:
        logger.error(f"SEC EDGAR fetch error: {e}")

    logger.info(f"SEC EDGAR: returning {len(events)} events")
    return events
