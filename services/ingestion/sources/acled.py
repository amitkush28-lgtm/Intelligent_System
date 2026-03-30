"""
ACLED (acleddata.com) — Conflict event data.
Battles, protests, riots, violence against civilians, strategic developments.

Two approaches:
1. ACLED API with OAuth (requires free account: https://acleddata.com/register/)
2. Humanitarian Data Exchange (HDX) — free CSV downloads, no registration
   https://data.humdata.org/organization/acled

Set ACLED_EMAIL + ACLED_PASSWORD env vars for approach 1.
If not set, falls back to HDX.
"""

import csv
import hashlib
import io
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_API_URL = "https://acleddata.com/api/acled/read"

# HDX publishes weekly ACLED data exports as CSV
# These are the global "last 12 months" files
HDX_ACLED_API = "https://data.humdata.org/api/3/action/package_show"
HDX_ACLED_DATASET = "political-violence-events-and-fatalities"

EVENT_SEVERITY = {
    "Battles": "significant",
    "Violence against civilians": "critical",
    "Explosions/Remote violence": "significant",
    "Riots": "notable",
    "Protests": "notable",
    "Strategic developments": "notable",
}

# Regions of highest intelligence value
HIGH_VALUE_REGIONS = [
    "Middle East", "Eastern Europe", "South Asia", "East Asia",
    "Southeast Asia", "North Africa", "Sub-Saharan Africa",
]


async def _get_access_token(client: httpx.AsyncClient) -> Optional[str]:
    """Get OAuth access token using ACLED credentials."""
    email = os.environ.get("ACLED_EMAIL", "")
    password = os.environ.get("ACLED_PASSWORD", "")

    if not email or not password:
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
    """Fetch recent conflict events. Tries ACLED API first, falls back to HDX."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # Try ACLED API first (better data, more fields)
        token = await _get_access_token(client)
        if token:
            events = await _fetch_from_acled_api(client, token, lookback_days, max_results)
            if events:
                logger.info(f"ACLED: returning {len(events)} events (API)")
                return events
            logger.warning("ACLED API returned 0 events, trying HDX fallback")
        else:
            logger.info("ACLED credentials not set, using HDX fallback")

        # Fallback: HDX free data
        events = await _fetch_from_hdx(client, lookback_days, max_results)
        logger.info(f"ACLED: returning {len(events)} events (HDX)")
        return events


async def _fetch_from_acled_api(
    client: httpx.AsyncClient,
    token: str,
    lookback_days: int,
    max_results: int,
) -> List[Dict[str, Any]]:
    """Fetch from ACLED's authenticated API."""
    events = []

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
            event = _parse_acled_record(record)
            if event:
                events.append(event)

    except Exception as e:
        logger.error(f"ACLED API fetch error: {e}")

    return events


async def _fetch_from_hdx(
    client: httpx.AsyncClient,
    lookback_days: int,
    max_results: int,
) -> List[Dict[str, Any]]:
    """Fetch ACLED data from HDX (Humanitarian Data Exchange) — no auth needed."""
    events = []

    try:
        # Step 1: Get the dataset metadata to find the latest CSV URL
        resp = await client.get(
            HDX_ACLED_API,
            params={"id": HDX_ACLED_DATASET},
        )

        if resp.status_code != 200:
            logger.warning(f"HDX API returned {resp.status_code}")
            return await _fetch_hdx_direct(client, lookback_days, max_results)

        dataset = resp.json().get("result", {})
        resources = dataset.get("resources", [])

        # Find the CSV resource
        csv_url = None
        for r in resources:
            if r.get("format", "").upper() == "CSV" and "conflict" in r.get("name", "").lower():
                csv_url = r.get("url", r.get("download_url"))
                break

        if not csv_url:
            # Try any CSV
            for r in resources:
                if r.get("format", "").upper() == "CSV":
                    csv_url = r.get("url", r.get("download_url"))
                    break

        if not csv_url:
            logger.warning("No CSV resource found in HDX ACLED dataset")
            return await _fetch_hdx_direct(client, lookback_days, max_results)

        # Step 2: Download and parse the CSV
        events = await _parse_hdx_csv(client, csv_url, lookback_days, max_results)

    except Exception as e:
        logger.error(f"HDX fetch error: {e}")
        # Last resort: try direct URL
        events = await _fetch_hdx_direct(client, lookback_days, max_results)

    return events


async def _fetch_hdx_direct(
    client: httpx.AsyncClient,
    lookback_days: int,
    max_results: int,
) -> List[Dict[str, Any]]:
    """Direct HDX CSV download — hardcoded URL as last resort."""
    # HDX direct download URLs for recent conflict data
    urls = [
        "https://data.humdata.org/dataset/political-violence-events-and-fatalities/resource_download/",
        "https://data.humdata.org/dataset/ucdp-data-for-africa/resource_download/",
    ]
    for url in urls:
        try:
            events = await _parse_hdx_csv(client, url, lookback_days, max_results)
            if events:
                return events
        except Exception:
            continue
    return []


async def _parse_hdx_csv(
    client: httpx.AsyncClient,
    csv_url: str,
    lookback_days: int,
    max_results: int,
) -> List[Dict[str, Any]]:
    """Stream and parse an ACLED-format CSV from HDX."""
    events = []
    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    try:
        async with client.stream("GET", csv_url) as resp:
            if resp.status_code != 200:
                logger.warning(f"HDX CSV download returned {resp.status_code}")
                return events

            buffer = ""
            header = None
            async for chunk in resp.aiter_text(chunk_size=16384):
                buffer += chunk
                lines = buffer.split("\n")
                buffer = lines[-1]  # Keep incomplete last line

                for line in lines[:-1]:
                    if header is None:
                        # Parse header
                        reader = csv.reader(io.StringIO(line))
                        header = next(reader, None)
                        if header:
                            header = [h.strip().lower() for h in header]
                        continue

                    try:
                        reader = csv.reader(io.StringIO(line))
                        values = next(reader, None)
                        if not values or len(values) < len(header):
                            continue

                        row = dict(zip(header, values))
                        event_date = row.get("event_date", "")

                        # Only keep recent events
                        if event_date and event_date < cutoff:
                            continue

                        record = {
                            "event_id_cnty": row.get("event_id_cnty", row.get("data_id", "")),
                            "event_date": event_date,
                            "event_type": row.get("event_type", ""),
                            "sub_event_type": row.get("sub_event_type", ""),
                            "actor1": row.get("actor1", ""),
                            "actor2": row.get("actor2", ""),
                            "country": row.get("country", ""),
                            "admin1": row.get("admin1", row.get("location", "")),
                            "fatalities": row.get("fatalities", "0"),
                            "notes": row.get("notes", ""),
                        }

                        event = _parse_acled_record(record)
                        if event:
                            events.append(event)

                        if len(events) >= max_results:
                            return events

                    except Exception:
                        continue

    except Exception as e:
        logger.error(f"HDX CSV parse error: {e}")

    return events


def _parse_acled_record(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a single ACLED record into an event dict."""
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
        event_id = record.get("event_id_cnty", "")

        if not event_type or not country:
            return None

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
            for fmt in ["%Y-%m-%d", "%d %B %Y", "%d-%b-%Y"]:
                try:
                    timestamp = datetime.strptime(event_date.strip(), fmt)
                    break
                except ValueError:
                    continue

        entities = []
        if actor1:
            entities.append({"name": actor1, "type": "organization", "role": "actor1"})
        if actor2:
            entities.append({"name": actor2, "type": "organization", "role": "actor2"})
        entities.append({"name": country, "type": "nation", "role": "location"})

        # Generate ID — use event_id if available, else hash
        if not event_id:
            event_id = hashlib.md5(f"{event_date}-{event_type}-{country}-{actor1}".encode()).hexdigest()[:12]

        return {
            "id": f"acled-{event_id}",
            "source": "acled",
            "source_detail": "ACLED conflict data",
            "timestamp": timestamp,
            "domain": "geopolitical",
            "event_type": f"conflict_{event_type.lower().replace(' ', '_')}",
            "severity": severity,
            "entities": entities,
            "raw_text": raw_text,
        }
    except Exception as e:
        logger.debug(f"Error parsing ACLED event: {e}")
        return None
