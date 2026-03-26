"""
OFAC Sanctions List (ofac.treasury.gov) — US Treasury sanctions data.
Free CSV download. Tracks sanctioned entities, SDN list changes.
Useful for geopolitical and market analysis.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

# OFAC publishes a consolidated XML/CSV of the SDN list
OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_CHANGES_URL = "https://www.treasury.gov/resource-center/sanctions/SDN-List/Pages/changes.aspx"


async def fetch_ofac_events() -> List[Dict[str, Any]]:
    """Fetch recent OFAC sanctions list data."""
    events = []

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(OFAC_SDN_URL)

            if resp.status_code != 200:
                logger.warning(f"OFAC HTTP {resp.status_code}")
                return events

            lines = resp.text.strip().split("\n")

            # Parse recent entries (SDN CSV format: id, name, type, program, ...)
            # We look at the last 50 entries as proxy for recent additions
            recent_lines = lines[-50:] if len(lines) > 50 else lines

            for line in recent_lines:
                try:
                    parts = line.split('","')
                    if len(parts) < 4:
                        continue

                    entity_id = parts[0].strip('"')
                    name = parts[1].strip('"')
                    entity_type = parts[2].strip('"')
                    program = parts[3].strip('"')

                    if not name or len(name) < 3:
                        continue

                    events.append({
                        "id": f"ofac-{entity_id}",
                        "source": "ofac",
                        "source_detail": "OFAC SDN List",
                        "timestamp": datetime.utcnow(),
                        "domain": "geopolitical",
                        "event_type": "sanctions_listing",
                        "severity": "notable",
                        "raw_text": f"OFAC SDN listing: {name} ({entity_type}) — Program: {program}",
                        "entities": [{"name": name, "type": entity_type.lower(), "role": "sanctioned"}],
                    })
                except Exception:
                    continue

    except Exception as e:
        logger.error(f"OFAC fetch error: {e}")

    logger.info(f"OFAC: returning {len(events)} events")
    return events
