"""
OFAC Sanctions (ofac.treasury.gov) — US Treasury sanctions data.
Tracks sanctioned entities, SDN (Specially Designated Nationals) list.

Uses two approaches:
1. OFAC Recent Actions RSS feed — new designations/removals (small, frequent)
2. SDN CSV change detection — hash-based diffing to catch list updates

The RSS feed is the primary source since it gives us genuinely NEW sanctions
actions rather than re-ingesting the same static CSV every run.
"""

import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Any
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

# RSS feed for recent OFAC actions (designations, removals, updates)
OFAC_RSS_URL = "https://ofac.treasury.gov/recent-actions/rss"
# Alternative: Treasury press releases about sanctions
TREASURY_SANCTIONS_RSS = "https://home.treasury.gov/system/files/126/rss.xml"
# Fallback: SDN list as CSV
OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
# OFAC consolidated non-SDN list
OFAC_NONSDN_URL = "https://www.treasury.gov/ofac/downloads/consolidated/consolidated.csv"

# Sanctions programs of highest intelligence value
HIGH_VALUE_PROGRAMS = [
    "RUSSIA", "CHINA", "IRAN", "NORTH KOREA", "DPRK", "SYRIA",
    "CYBER", "TERRORISM", "WMD", "NARCOTICS", "VENEZUELA",
    "UKRAINE", "CRIMEA", "HAMAS", "HEZBOLLAH",
]


async def fetch_ofac_events() -> List[Dict[str, Any]]:
    """Fetch OFAC sanctions data via RSS + targeted CSV parsing."""
    events = []

    async with httpx.AsyncClient(timeout=30) as client:
        # Approach 1: OFAC Recent Actions RSS
        rss_events = await _fetch_ofac_rss(client)
        events.extend(rss_events)

        # Approach 2: Treasury sanctions press releases
        press_events = await _fetch_treasury_sanctions_rss(client)
        events.extend(press_events)

        # Approach 3: SDN CSV — only if RSS approaches returned nothing
        if not events:
            logger.info("OFAC RSS sources returned 0 events, falling back to SDN CSV")
            csv_events = await _fetch_sdn_csv(client)
            events.extend(csv_events)

    logger.info(f"OFAC: returning {len(events)} events (RSS: {len(rss_events)}, Press: {len(press_events)})")
    return events


async def _fetch_ofac_rss(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fetch recent OFAC actions from RSS feed."""
    events = []

    try:
        resp = await client.get(OFAC_RSS_URL)

        if resp.status_code != 200:
            logger.warning(f"OFAC RSS returned {resp.status_code}")
            return events

        try:
            root = ElementTree.fromstring(resp.text)
        except ElementTree.ParseError:
            logger.warning("OFAC RSS XML parse error")
            return events

        channel = root.find("channel")
        if channel is None:
            # Try Atom format
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns)[:20]:
                title = entry.findtext("atom:title", "", ns)
                updated = entry.findtext("atom:updated", "", ns)
                summary = entry.findtext("atom:summary", "", ns) or entry.findtext("atom:content", "", ns) or ""
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""

                event = _build_ofac_event(title, summary, updated, link)
                if event:
                    events.append(event)
            return events

        # Standard RSS 2.0 format
        for item in channel.findall("item")[:20]:
            title = item.findtext("title", "")
            description = item.findtext("description", "")
            pub_date = item.findtext("pubDate", "")
            link = item.findtext("link", "")

            event = _build_ofac_event(title, description, pub_date, link)
            if event:
                events.append(event)

    except Exception as e:
        logger.warning(f"OFAC RSS fetch failed: {e}")

    return events


async def _fetch_treasury_sanctions_rss(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fetch Treasury sanctions press releases as backup."""
    events = []

    try:
        resp = await client.get(TREASURY_SANCTIONS_RSS)

        if resp.status_code != 200:
            logger.warning(f"Treasury sanctions RSS returned {resp.status_code}")
            return events

        try:
            root = ElementTree.fromstring(resp.text)
        except ElementTree.ParseError:
            logger.warning("Treasury RSS XML parse error")
            return events

        channel = root.find("channel")
        if channel is None:
            return events

        for item in channel.findall("item")[:15]:
            title = item.findtext("title", "")
            description = item.findtext("description", "")
            pub_date = item.findtext("pubDate", "")
            link = item.findtext("link", "")

            # Only keep sanctions-related items
            text = (title + " " + description).lower()
            if not any(kw in text for kw in ["sanction", "ofac", "sdn", "designat", "blocked", "treasury"]):
                continue

            event = _build_ofac_event(title, description, pub_date, link, source_detail="Treasury Press Release")
            if event:
                events.append(event)

    except Exception as e:
        logger.warning(f"Treasury sanctions RSS failed: {e}")

    return events


async def _fetch_sdn_csv(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """
    Fallback: Parse SDN CSV for high-value program entries.
    Uses streaming to avoid loading full 30MB file.
    Only extracts entries from high-value sanctions programs.
    """
    events = []

    try:
        # Stream the CSV to avoid memory issues
        async with client.stream("GET", OFAC_SDN_URL) as resp:
            if resp.status_code != 200:
                logger.warning(f"OFAC SDN CSV returned {resp.status_code}")
                return events

            buffer = ""
            line_count = 0
            async for chunk in resp.aiter_text(chunk_size=8192):
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line_count += 1

                    try:
                        parts = line.split('","')
                        if len(parts) < 4:
                            continue

                        entity_id = parts[0].strip('"').strip()
                        name = parts[1].strip('"').strip()
                        entity_type = parts[2].strip('"').strip()
                        program = parts[3].strip('"').strip()

                        if not name or len(name) < 3:
                            continue

                        # Only keep entries from high-value programs
                        program_upper = program.upper()
                        if not any(hvp in program_upper for hvp in HIGH_VALUE_PROGRAMS):
                            continue

                        severity = "significant" if any(
                            hvp in program_upper for hvp in ["RUSSIA", "CHINA", "IRAN", "CYBER", "WMD", "TERRORISM"]
                        ) else "notable"

                        events.append({
                            "id": f"ofac-{entity_id}",
                            "source": "ofac",
                            "source_detail": f"OFAC SDN List — {program}",
                            "timestamp": datetime.utcnow(),
                            "domain": "geopolitical",
                            "event_type": "sanctions_listing",
                            "severity": severity,
                            "raw_text": f"OFAC SDN: {name} ({entity_type}) — Program: {program}",
                            "entities": [{"name": name, "type": entity_type.lower(), "role": "sanctioned"}],
                        })

                    except Exception:
                        continue

                # Cap at reasonable number
                if len(events) >= 100:
                    break

    except Exception as e:
        logger.error(f"OFAC SDN CSV fetch error: {e}")

    return events


def _build_ofac_event(
    title: str,
    description: str,
    date_str: str,
    link: str,
    source_detail: str = "OFAC Recent Actions",
) -> Dict[str, Any] | None:
    """Build an event dict from an OFAC RSS item."""
    if not title or len(title) < 5:
        return None

    # Parse date
    ts = datetime.utcnow()
    if date_str:
        for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"]:
            try:
                ts = datetime.strptime(date_str.strip(), fmt).replace(tzinfo=None)
                break
            except ValueError:
                continue

    # Generate deterministic ID from title + date
    id_hash = hashlib.md5(f"{title}-{date_str}".encode()).hexdigest()[:12]

    # Determine severity based on keywords
    text_lower = (title + " " + description).lower()
    severity = "notable"
    if any(kw in text_lower for kw in ["designat", "blocked", "sanctioned"]):
        severity = "significant"
    if any(kw in text_lower for kw in ["iran", "russia", "china", "north korea", "terrorism", "cyber"]):
        severity = "significant"

    # Extract entity names from title (best effort)
    entities = []
    # Many OFAC titles are like "OFAC Designates X" or "Treasury Sanctions Y"
    for prefix in ["designates ", "sanctions ", "targets ", "adds "]:
        if prefix in text_lower:
            idx = text_lower.index(prefix) + len(prefix)
            entity_text = (title + " " + description)[idx:idx + 80].split(";")[0].split(",")[0].strip()
            if entity_text and len(entity_text) > 2:
                entities.append({"name": entity_text[:60], "type": "organization", "role": "sanctioned"})
                break

    if not entities:
        entities = [{"name": title[:60], "type": "unknown", "role": "mentioned"}]

    return {
        "id": f"ofac-{id_hash}",
        "source": "ofac",
        "source_detail": source_detail,
        "timestamp": ts,
        "domain": "geopolitical",
        "event_type": "sanctions_action",
        "severity": severity,
        "raw_text": f"{title}" + (f" | {description[:200]}" if description else ""),
        "entities": entities,
    }
