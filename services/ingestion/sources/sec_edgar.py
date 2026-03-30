"""
SEC EDGAR — Free API for fund holdings (13F), company filings, insider trades.
Primary data for the Investor agent. 10 requests/second, no key needed.

Uses three approaches for robustness:
1. EFTS full-text search API (efts.sec.gov)
2. EDGAR RSS feeds for recent filings
3. Submissions API for company-specific data (data.sec.gov)

Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

# SEC requires a descriptive User-Agent with contact info
HEADERS = {"User-Agent": "IntelligenceSystem/1.0 (amit.kush28@gmail.com)"}

# EDGAR RSS feeds for recent filings by form type
EDGAR_RSS_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"

# EFTS full-text search
EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"

# Market-moving form types and their significance
FORM_TYPES = {
    "8-K": {"severity": "notable", "domain": "market", "desc": "Current report (material events)"},
    "13F-HR": {"severity": "notable", "domain": "market", "desc": "Institutional holdings report"},
    "4": {"severity": "notable", "domain": "market", "desc": "Insider trading disclosure"},
    "SC 13D": {"severity": "significant", "domain": "market", "desc": "Beneficial ownership (activist)"},
}

# Keywords that signal market-moving 8-K content
MARKET_MOVING_KEYWORDS = [
    "merger", "acquisition", "bankruptcy", "restructur", "layoff",
    "CEO", "executive", "guidance", "restat", "delisting", "default",
    "investigation", "settlement", "recall", "cybersecurity", "breach",
]


async def fetch_sec_edgar_events() -> List[Dict[str, Any]]:
    """Fetch recent SEC filings via multiple approaches for robustness."""
    events = []
    seen_ids = set()

    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        # Approach 1: EFTS full-text search for market-moving keywords
        efts_events = await _fetch_efts_search(client)
        for e in efts_events:
            if e["id"] not in seen_ids:
                events.append(e)
                seen_ids.add(e["id"])

        # Approach 2: EDGAR RSS feeds for recent filings by form type
        rss_events = await _fetch_rss_filings(client)
        for e in rss_events:
            if e["id"] not in seen_ids:
                events.append(e)
                seen_ids.add(e["id"])

    logger.info(f"SEC EDGAR: returning {len(events)} events (EFTS: {len(efts_events)}, RSS: {len(rss_events)})")
    return events


async def _fetch_efts_search(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Full-text search via EFTS API."""
    events = []

    queries = [
        ("merger OR acquisition", "8-K"),
        ("bankruptcy OR restructuring OR default", "8-K"),
        ("CEO OR \"executive officer\" OR departure", "8-K"),
        ("guidance OR restatement OR revision", "8-K"),
    ]

    for query, form_type in queries:
        try:
            resp = await client.get(
                EFTS_BASE,
                params={
                    "q": query,
                    "dateRange": "custom",
                    "startdt": (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d"),
                    "enddt": datetime.utcnow().strftime("%Y-%m-%d"),
                    "forms": form_type,
                },
            )

            if resp.status_code != 200:
                logger.warning(f"EFTS search returned {resp.status_code} for '{query}'")
                continue

            data = resp.json()

            # EFTS returns Elasticsearch-style response
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                # Also try alternative response format
                hits = data.get("filings", [])

            for hit in hits[:10]:
                source = hit.get("_source", hit)  # Handle both formats
                entity = source.get("entity_name", source.get("display_names", ["Unknown"])[0] if source.get("display_names") else "Unknown")
                form = source.get("form_type", form_type)
                filed = source.get("file_date", source.get("filed_at", ""))
                accession = hit.get("_id", source.get("accession_no", ""))

                if not accession:
                    accession = hashlib.md5(f"{entity}-{filed}-{form}".encode()).hexdigest()[:12]

                try:
                    ts = datetime.fromisoformat(filed) if filed else datetime.utcnow()
                except (ValueError, TypeError):
                    ts = datetime.utcnow()

                events.append({
                    "id": f"edgar-{accession}",
                    "source": "sec_edgar",
                    "source_detail": f"SEC EDGAR {form} (EFTS)",
                    "timestamp": ts,
                    "domain": "market",
                    "event_type": f"sec_filing_{form.lower().replace('-', '')}",
                    "severity": "notable",
                    "raw_text": f"{entity}: {form} filing — {query.split(' OR ')[0]}",
                    "entities": [{"name": entity, "type": "organization", "role": "filer"}],
                })

        except Exception as e:
            logger.warning(f"EFTS query '{query}' failed: {e}")
            continue

    return events


async def _fetch_rss_filings(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fetch recent filings via EDGAR RSS/Atom feeds — reliable fallback."""
    events = []

    for form_type, meta in FORM_TYPES.items():
        try:
            resp = await client.get(
                EDGAR_RSS_BASE,
                params={
                    "action": "getcompany",
                    "type": form_type,
                    "dateb": "",
                    "owner": "include",
                    "count": 20,
                    "search_text": "",
                    "output": "atom",
                },
            )

            if resp.status_code != 200:
                logger.warning(f"EDGAR RSS for {form_type} returned {resp.status_code}")
                continue

            # Parse Atom XML
            try:
                root = ElementTree.fromstring(resp.text)
            except ElementTree.ParseError as e:
                logger.warning(f"EDGAR RSS XML parse error for {form_type}: {e}")
                continue

            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns)[:15]:
                title_el = entry.find("atom:title", ns)
                updated_el = entry.find("atom:updated", ns)
                link_el = entry.find("atom:link", ns)
                summary_el = entry.find("atom:summary", ns)

                title = title_el.text if title_el is not None else ""
                updated = updated_el.text if updated_el is not None else ""
                link = link_el.get("href", "") if link_el is not None else ""
                summary = summary_el.text if summary_el is not None else ""

                if not title:
                    continue

                # Extract accession number from link or generate ID
                accession = ""
                if link:
                    # Link typically contains accession number
                    parts = link.split("/")
                    for p in reversed(parts):
                        if "-" in p and len(p) > 15:
                            accession = p.replace("-", "")
                            break
                if not accession:
                    accession = hashlib.md5(f"{title}-{updated}".encode()).hexdigest()[:16]

                # Parse timestamp
                try:
                    ts = datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else datetime.utcnow()
                except (ValueError, TypeError):
                    ts = datetime.utcnow()

                # Extract entity name from title (usually "COMPANY NAME (form_type)")
                entity = title.split("(")[0].strip() if "(" in title else title[:60]

                # For 8-K, check if it's market-moving based on summary
                severity = meta["severity"]
                if form_type == "8-K" and summary:
                    summary_lower = summary.lower()
                    if any(kw in summary_lower for kw in MARKET_MOVING_KEYWORDS):
                        severity = "significant"

                events.append({
                    "id": f"edgar-rss-{accession}",
                    "source": "sec_edgar",
                    "source_detail": f"SEC EDGAR {form_type} (RSS)",
                    "timestamp": ts,
                    "domain": meta["domain"],
                    "event_type": f"sec_filing_{form_type.lower().replace('-', '').replace(' ', '')}",
                    "severity": severity,
                    "raw_text": f"{entity}: {form_type} — {meta['desc']}" + (f" | {summary[:150]}" if summary else ""),
                    "entities": [{"name": entity, "type": "organization", "role": "filer"}],
                })

        except Exception as e:
            logger.warning(f"EDGAR RSS for {form_type} failed: {e}")
            continue

    return events
