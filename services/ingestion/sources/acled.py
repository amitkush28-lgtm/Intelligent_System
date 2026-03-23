"""
ACLED (acleddata.com) — Free for non-commercial use.
Conflict event data with geocoding: battles, protests, riots,
violence against civilians, strategic developments.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

ACLED_BASE_URL = "https://api.acleddata.com/acled/read"

# ACLED event types and their severity mappings
EVENT_SEVERITY = {
    "Battles": "significant",
    "Violence against civilians": "critical",
    "Explosions/Remote violence": "significant",
    "Riots": "notable",
    "Protests": "notable",
    "Strategic developments": "notable",
}


async def fetch_acled_events(
    lookback_days: int = 7,
    max_results: int = 200,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Fetch recent conflict events from ACLED.
    ACLED's free API allows access without a key for limited queries.
    Returns list of event dicts.
    """
    events = []
    start_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            params = {
                "event_date": start_date,
                "event_date_where": ">=",
                "limit": max_results,
                "page": 1,
            }

            resp = await client.get(ACLED_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            records = data.get("data", [])
            if not records:
                logger.info("ACLED: no records returned")
                return events

            for record in records:
                try:
                    event_type = record.get("event_type", "Unknown")
                    sub_event_type = record.get("sub_event_type", "")
                    actor1 = record.get("actor1", "Unknown")
                    actor2 = record.get("actor2", "")
                    location = record.get("location", "")
                    country = record.get("country", "")
                    notes = record.get("notes", "")
                    fatalities = int(record.get("fatalities", 0) or 0)
                    event_date = record.get("event_date", "")
                    source = record.get("source", "")
                    source_scale = record.get("source_scale", "")

                    # Build raw text
                    raw_text = f"Conflict Event: {event_type}"
                    if sub_event_type:
                        raw_text += f" ({sub_event_type})"
                    raw_text += f". {actor1}"
                    if actor2:
                        raw_text += f" vs {actor2}"
                    if location and country:
                        raw_text += f" in {location}, {country}"
                    elif country:
                        raw_text += f" in {country}"
                    if fatalities > 0:
                        raw_text += f". Fatalities: {fatalities}"
                    if notes:
                        raw_text += f". {notes[:300]}"

                    # Parse timestamp
                    timestamp = datetime.utcnow()
                    if event_date:
                        try:
                            timestamp = datetime.strptime(event_date, "%Y-%m-%d")
                        except ValueError:
                            pass

                    severity = EVENT_SEVERITY.get(event_type, "notable")
                    if fatalities > 10:
                        severity = "critical"
                    elif fatalities > 0:
                        severity = "significant"

                    entities = [{"name": actor1, "type": "organization", "role": "actor1"}]
                    if actor2:
                        entities.append({"name": actor2, "type": "organization", "role": "actor2"})
                    if country:
                        entities.append({"name": country, "type": "nation", "role": "location"})
                    if location:
                        entities.append({"name": location, "type": "location", "role": "location"})

                    lat = record.get("latitude", "")
                    lon = record.get("longitude", "")

                    events.append({
                        "source": "acled",
                        "source_detail": f"acleddata.com",
                        "timestamp": timestamp,
                        "domain": "geopolitical",
                        "event_type": f"conflict_{event_type.lower().replace(' ', '_')}",
                        "severity": severity,
                        "entities": entities,
                        "raw_text": raw_text,
                        "metadata": {
                            "acled_event_type": event_type,
                            "sub_event_type": sub_event_type,
                            "fatalities": fatalities,
                            "country": country,
                            "location": location,
                            "latitude": lat,
                            "longitude": lon,
                            "source": source,
                            "source_scale": source_scale,
                        },
                    })
                except Exception as e:
                    logger.debug(f"Error parsing ACLED record: {e}")
                    continue

        except httpx.HTTPStatusError as e:
            logger.error(f"ACLED HTTP error: {e.response.status_code}")
        except httpx.TimeoutException:
            logger.warning("ACLED request timed out")
        except Exception as e:
            logger.error(f"ACLED fetch error: {e}")

    logger.info(f"ACLED: returning {len(events)} events")
    return events
