"""
ACLED (acleddata.com) — Conflict event data.
Battles, protests, riots, violence against civilians, strategic developments.
Requires free myACLED account — register at https://acleddata.com/register/
Uses OAuth token authentication (new as of 2025).
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_API_URL = "https://acleddata.com/api/acled/read"

EVENT_SEVERITY = {
    "Battles": "significant",
    "Violence against civilians": "critical",
    "Explosions/Remote violence": "significant",
    "Riots": "notable",
    "Protests": "notable",
    "Strategic developments": "notable",
}


async def _get_access_token(client: httpx.AsyncClient) -> Optional[str]:
    """Get OAuth access token using ACLED credentials."""
    email = os.environ.get("ACLED_EMAIL", "")
    password = os.environ.get("ACLED_PASSWORD", "")

    if not email or not password:
        logger.warning("ACLED_EMAIL or ACLED_PASSWORD not set, skipping ACLED source")
        return None

    try:
        resp = await client.post(
            ACLED_TOKEN_URL,
            data={
                "username": email,
                "password": password,
                "grant_type": "password",
                "client_id": "acled",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code == 200:
            token_data = resp.json()
            return token_data.get("access_token")
        else:
            logger.warning(f"ACLED token request failed: HTTP {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"ACLED token error: {e}")
        return None


async def fetch_acled_events(
    lookback_days: int = 7,
    max_results: int = 200,
) -> List[Dict[str, Any]]:
    """Fetch recent conflict events from ACLED API."""
    events = []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # Step 1: Get access token
        token = await _get_access_token(client)
        if not token:
            return events

        # Step 2: Fetch events
        try:
            start_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            end_date = datetime.utcnow().strftime("%Y-%m-%d")

            resp = await client.get(
                ACLED_API_URL,
                params={
                    "_format": "json",
                    "event_date": f"{start_date}|{end_date}",
                    "event_date_where": "BETWEEN",
                    "fields": "event_id_cnty|event_date|event_type|sub_event_type|actor1|actor2|country|admin1|latitude|longitude|fatalities|notes",
                    "limit": str(max_results),
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )

            if resp.status_code != 200:
                logger.warning(f"ACLED API HTTP {resp.status_code}")
                return events

            data = resp.json()
            records = data.get("data", [])

            for record in records:
                try:
                    event_type = record.get("event_type", "")
                    sub_event = record.get("sub_event_type", "")
                    country = record.get("country", "")
                    actor1 = record.get("actor1", "")
                    actor2 = record.get("actor2", "")
                    fatalities = record.get("fatalities", 0)
                    notes = record.get("notes", "")
                    event_date = record.get("event_date", "")
                    location = record.get("admin1", "")

                    raw_text = f"{event_type}: {sub_event} in {location}, {country}"
                    if actor1:
                        raw_text += f". Actor: {actor1}"
                    if actor2:
                        raw_text += f" vs {actor2}"
                    if fatalities and int(fatalities) > 0:
                        raw_text += f". Fatalities: {fatalities}"
                    if notes:
                        raw_text += f". {notes[:200]}"

                    severity = EVENT_SEVERITY.get(event_type, "notable")
                    if fatalities and int(fatalities) > 10:
                        severity = "critical"

                    timestamp = datetime.utcnow()
                    if event_date:
                        try:
                            timestamp = datetime.strptime(event_date, "%Y-%m-%d")
                        except ValueError:
                            pass

                    entities = []
                    if actor1:
                        entities.append({"name": actor1, "type": "organization", "role": "actor1"})
                    if actor2:
                        entities.append({"name": actor2, "type": "organization", "role": "actor2"})
                    entities.append({"name": country, "type": "nation", "role": "location"})

                    events.append({
                        "id": f"acled-{record.get('event_id_cnty', '')}",
                        "source": "acled",
                        "source_detail": "ACLED conflict data",
                        "timestamp": timestamp,
                        "domain": "geopolitical",
                        "event_type": f"conflict_{event_type.lower().replace(' ', '_')}",
                        "severity": severity,
                        "entities": entities,
                        "raw_text": raw_text,
                    })
                except Exception as e:
                    logger.debug(f"Error parsing ACLED event: {e}")
                    continue

        except Exception as e:
            logger.error(f"ACLED fetch error: {e}")

    logger.info(f"ACLED: returning {len(events)} events")
    return events
