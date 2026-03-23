"""
GDELT Project integration — global events updated every 15 minutes.
THE critical data source: free, unlimited, richest global event coverage.

Parses GDELT Event exports and GKG (Global Knowledge Graph) for:
- Event codes, actors, locations, tone, source URLs
- Themes, organizations, persons from GKG
"""

import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# GDELT v2 export URLs
GDELT_LAST_UPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_GKG_LAST_UPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate-gkg.txt"

# CAMEO event codes that matter for intelligence analysis
SIGNIFICANT_CAMEO_ROOTS = {
    "01": "MAKE PUBLIC STATEMENT",
    "02": "APPEAL",
    "03": "EXPRESS INTENT TO COOPERATE",
    "04": "CONSULT",
    "05": "ENGAGE IN DIPLOMATIC COOPERATION",
    "06": "ENGAGE IN MATERIAL COOPERATION",
    "07": "PROVIDE AID",
    "08": "YIELD",
    "09": "INVESTIGATE",
    "10": "DEMAND",
    "11": "DISAPPROVE",
    "12": "REJECT",
    "13": "THREATEN",
    "14": "PROTEST",
    "15": "EXHIBIT MILITARY POSTURE",
    "16": "REDUCE RELATIONS",
    "17": "COERCE",
    "18": "ASSAULT",
    "19": "FIGHT",
    "20": "ENGAGE IN UNCONVENTIONAL MASS VIOLENCE",
}

# Higher Goldstein scale magnitude = more significant
SEVERITY_THRESHOLDS = {
    "critical": 7.0,
    "significant": 4.0,
    "notable": 2.0,
}

# GDELT export column indices (v2 format)
GDELT_COLS = {
    "global_event_id": 0,
    "day": 1,
    "month_year": 2,
    "year": 3,
    "fraction_date": 4,
    "actor1_code": 5,
    "actor1_name": 6,
    "actor1_country": 7,
    "actor1_known_group": 8,
    "actor1_ethnic": 9,
    "actor1_religion1": 10,
    "actor1_religion2": 11,
    "actor1_type1": 12,
    "actor1_type2": 13,
    "actor1_type3": 14,
    "actor2_code": 15,
    "actor2_name": 16,
    "actor2_country": 17,
    "actor2_known_group": 18,
    "actor2_ethnic": 19,
    "actor2_religion1": 20,
    "actor2_religion2": 21,
    "actor2_type1": 22,
    "actor2_type2": 23,
    "actor2_type3": 24,
    "is_root_event": 25,
    "event_code": 26,
    "event_base_code": 27,
    "event_root_code": 28,
    "quad_class": 29,
    "goldstein_scale": 30,
    "num_mentions": 31,
    "num_sources": 32,
    "num_articles": 33,
    "avg_tone": 34,
    "actor1_geo_type": 35,
    "actor1_geo_fullname": 36,
    "actor1_geo_country": 37,
    "actor1_geo_lat": 39,
    "actor1_geo_long": 40,
    "actor2_geo_type": 41,
    "actor2_geo_fullname": 42,
    "actor2_geo_country": 43,
    "actor2_geo_lat": 45,
    "actor2_geo_long": 46,
    "action_geo_type": 47,
    "action_geo_fullname": 48,
    "action_geo_country": 49,
    "action_geo_lat": 51,
    "action_geo_long": 52,
    "date_added": 53,
    "source_url": 54 if True else 57,  # Depends on export version
}


def _safe_float(val: str, default: float = 0.0) -> float:
    """Safely parse a float from GDELT CSV."""
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def _safe_int(val: str, default: int = 0) -> int:
    """Safely parse an int from GDELT CSV."""
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def _parse_gdelt_date(date_str: str) -> Optional[datetime]:
    """Parse GDELT date format YYYYMMDDHHMMSS or YYYYMMDD."""
    try:
        if len(date_str) >= 14:
            return datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
        elif len(date_str) >= 8:
            return datetime.strptime(date_str[:8], "%Y%m%d")
    except (ValueError, TypeError):
        pass
    return None


def _get_severity_from_goldstein(goldstein: float) -> str:
    """Map Goldstein scale magnitude to severity level."""
    magnitude = abs(goldstein)
    if magnitude >= SEVERITY_THRESHOLDS["critical"]:
        return "critical"
    elif magnitude >= SEVERITY_THRESHOLDS["significant"]:
        return "significant"
    elif magnitude >= SEVERITY_THRESHOLDS["notable"]:
        return "notable"
    return "routine"


def _get_domain_from_cameo(event_root_code: str, actor1_type: str, actor2_type: str) -> str:
    """Map CAMEO event codes and actor types to intelligence domains."""
    # Military/conflict events -> geopolitical
    if event_root_code in ("15", "18", "19", "20"):
        return "geopolitical"
    # Protests -> political or sentiment depending on actor
    if event_root_code == "14":
        return "political"
    # Diplomatic events
    if event_root_code in ("03", "04", "05", "06", "07", "08"):
        if any(t in (actor1_type, actor2_type) for t in ("GOV", "MIL", "IGO")):
            return "geopolitical"
        return "political"
    # Threats, coercion -> geopolitical
    if event_root_code in ("13", "17"):
        return "geopolitical"
    # Demands, disapprovals, rejections
    if event_root_code in ("10", "11", "12", "16"):
        if any(t in (actor1_type, actor2_type) for t in ("BUS", "MNC")):
            return "economic"
        return "political"
    # Public statements -> sentiment
    if event_root_code in ("01", "02"):
        return "sentiment"
    return "geopolitical"


def _build_raw_text(row: List[str]) -> str:
    """Build a human-readable summary from GDELT row data."""
    actor1 = row[GDELT_COLS["actor1_name"]] or "Unknown Actor"
    actor2 = row[GDELT_COLS["actor2_name"]] or "Unknown Actor"
    event_code = row[GDELT_COLS["event_code"]] if len(row) > GDELT_COLS["event_code"] else ""
    root_code = row[GDELT_COLS["event_root_code"]] if len(row) > GDELT_COLS["event_root_code"] else ""
    event_desc = SIGNIFICANT_CAMEO_ROOTS.get(root_code, f"Event code {event_code}")
    location = ""
    if len(row) > GDELT_COLS["action_geo_fullname"]:
        location = row[GDELT_COLS["action_geo_fullname"]]

    parts = [f"{actor1} → {actor2}: {event_desc}"]
    if location:
        parts.append(f"Location: {location}")

    goldstein = _safe_float(row[GDELT_COLS["goldstein_scale"]] if len(row) > GDELT_COLS["goldstein_scale"] else "")
    if goldstein != 0:
        parts.append(f"Goldstein: {goldstein:.1f}")

    tone = _safe_float(row[GDELT_COLS["avg_tone"]] if len(row) > GDELT_COLS["avg_tone"] else "")
    if tone != 0:
        parts.append(f"Tone: {tone:.2f}")

    num_sources = _safe_int(row[GDELT_COLS["num_sources"]] if len(row) > GDELT_COLS["num_sources"] else "")
    if num_sources > 0:
        parts.append(f"Sources: {num_sources}")

    source_url = ""
    if len(row) > 57:
        source_url = row[57]
    elif len(row) > 54:
        source_url = row[54]
    if source_url:
        parts.append(f"URL: {source_url}")

    return " | ".join(parts)


def _extract_entities(row: List[str]) -> List[Dict[str, str]]:
    """Extract actor entities from GDELT row."""
    entities = []
    actor1_name = row[GDELT_COLS["actor1_name"]] if len(row) > GDELT_COLS["actor1_name"] else ""
    actor2_name = row[GDELT_COLS["actor2_name"]] if len(row) > GDELT_COLS["actor2_name"] else ""
    actor1_country = row[GDELT_COLS["actor1_country"]] if len(row) > GDELT_COLS["actor1_country"] else ""
    actor2_country = row[GDELT_COLS["actor2_country"]] if len(row) > GDELT_COLS["actor2_country"] else ""
    actor1_type = row[GDELT_COLS["actor1_type1"]] if len(row) > GDELT_COLS["actor1_type1"] else ""
    actor2_type = row[GDELT_COLS["actor2_type1"]] if len(row) > GDELT_COLS["actor2_type1"] else ""

    if actor1_name:
        entities.append({
            "name": actor1_name,
            "type": _map_actor_type(actor1_type),
            "role": "actor1",
            "country": actor1_country,
        })
    if actor2_name:
        entities.append({
            "name": actor2_name,
            "type": _map_actor_type(actor2_type),
            "role": "actor2",
            "country": actor2_country,
        })

    # Location entity
    location = row[GDELT_COLS["action_geo_fullname"]] if len(row) > GDELT_COLS["action_geo_fullname"] else ""
    if location:
        entities.append({
            "name": location,
            "type": "location",
            "role": "action_location",
        })

    return entities


def _map_actor_type(gdelt_type: str) -> str:
    """Map GDELT actor type codes to our entity types."""
    type_map = {
        "GOV": "government",
        "MIL": "military",
        "REB": "rebel",
        "OPP": "opposition",
        "PTY": "political_party",
        "EDU": "education",
        "BUS": "business",
        "MED": "media",
        "REL": "religious",
        "CVL": "civilian",
        "IGO": "intergovernmental_org",
        "NGO": "ngo",
        "MNC": "multinational_corp",
    }
    return type_map.get(gdelt_type, "unknown")


def _filter_significant_events(rows: List[List[str]], min_mentions: int = 3) -> List[List[str]]:
    """Filter to significant events based on mentions, sources, and Goldstein scale."""
    significant = []
    for row in rows:
        if len(row) < 35:
            continue

        num_mentions = _safe_int(row[GDELT_COLS["num_mentions"]])
        num_sources = _safe_int(row[GDELT_COLS["num_sources"]])
        goldstein = _safe_float(row[GDELT_COLS["goldstein_scale"]])
        is_root = row[GDELT_COLS["is_root_event"]] == "1"

        # Keep events that are either high-impact or well-sourced
        if num_mentions >= min_mentions or num_sources >= 2 or abs(goldstein) >= 4.0 or is_root:
            significant.append(row)

    return significant


async def fetch_gdelt_events(
    max_events: int = 500,
    lookback_hours: int = 4,
    timeout: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Fetch recent GDELT events.

    Strategy: Download the latest 15-min export, parse it, filter for significant events.
    For a 4-hour cron cycle, we fetch the last-update file which points to the latest export.

    Returns list of raw event dicts ready for the NLP pipeline.
    """
    events = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            # Step 1: Get the latest export file URL
            logger.info("Fetching GDELT last update manifest...")
            resp = await client.get(GDELT_LAST_UPDATE_URL)
            resp.raise_for_status()

            # Parse the manifest - format: "size hash url" per line
            export_urls = []
            for line in resp.text.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
                    export_urls.append(parts[2])

            if not export_urls:
                logger.warning("No GDELT export URLs found in manifest")
                return events

            # Step 2: Download and parse the latest export
            export_url = export_urls[0]
            logger.info(f"Downloading GDELT export: {export_url}")

            resp = await client.get(export_url)
            resp.raise_for_status()

            # Step 3: Unzip and parse CSV
            zip_data = io.BytesIO(resp.content)
            with zipfile.ZipFile(zip_data) as zf:
                csv_files = [f for f in zf.namelist() if f.endswith(".CSV")]
                if not csv_files:
                    logger.warning("No CSV files in GDELT export zip")
                    return events

                with zf.open(csv_files[0]) as f:
                    content = f.read().decode("utf-8", errors="replace")
                    reader = csv.reader(io.StringIO(content), delimiter="\t")
                    all_rows = list(reader)

            logger.info(f"Parsed {len(all_rows)} raw GDELT events")

            # Step 4: Filter for significant events
            significant = _filter_significant_events(all_rows)
            logger.info(f"Filtered to {len(significant)} significant events")

            # Step 5: Convert to our event format
            cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)

            for row in significant[:max_events]:
                try:
                    # Parse timestamp
                    date_str = row[GDELT_COLS["day"]] if len(row) > GDELT_COLS["day"] else ""
                    date_added = row[GDELT_COLS["date_added"]] if len(row) > GDELT_COLS["date_added"] else ""
                    timestamp = _parse_gdelt_date(date_added) or _parse_gdelt_date(date_str) or datetime.utcnow()

                    # Parse key fields
                    event_root_code = row[GDELT_COLS["event_root_code"]] if len(row) > GDELT_COLS["event_root_code"] else ""
                    actor1_type = row[GDELT_COLS["actor1_type1"]] if len(row) > GDELT_COLS["actor1_type1"] else ""
                    actor2_type = row[GDELT_COLS["actor2_type1"]] if len(row) > GDELT_COLS["actor2_type1"] else ""
                    goldstein = _safe_float(row[GDELT_COLS["goldstein_scale"]] if len(row) > GDELT_COLS["goldstein_scale"] else "")

                    # Determine source URL for integrity scoring
                    source_url = ""
                    if len(row) > 57:
                        source_url = row[57]
                    elif len(row) > 54:
                        source_url = row[54]

                    event_dict = {
                        "source": "gdelt",
                        "source_detail": source_url or "gdelt_export",
                        "timestamp": timestamp,
                        "domain": _get_domain_from_cameo(event_root_code, actor1_type, actor2_type),
                        "event_type": SIGNIFICANT_CAMEO_ROOTS.get(event_root_code, f"CAMEO_{event_root_code}"),
                        "severity": _get_severity_from_goldstein(goldstein),
                        "entities": _extract_entities(row),
                        "raw_text": _build_raw_text(row),
                        "metadata": {
                            "gdelt_event_id": row[GDELT_COLS["global_event_id"]] if row else "",
                            "goldstein_scale": goldstein,
                            "avg_tone": _safe_float(row[GDELT_COLS["avg_tone"]] if len(row) > GDELT_COLS["avg_tone"] else ""),
                            "num_mentions": _safe_int(row[GDELT_COLS["num_mentions"]] if len(row) > GDELT_COLS["num_mentions"] else ""),
                            "num_sources": _safe_int(row[GDELT_COLS["num_sources"]] if len(row) > GDELT_COLS["num_sources"] else ""),
                            "num_articles": _safe_int(row[GDELT_COLS["num_articles"]] if len(row) > GDELT_COLS["num_articles"] else ""),
                            "quad_class": _safe_int(row[GDELT_COLS["quad_class"]] if len(row) > GDELT_COLS["quad_class"] else ""),
                            "event_code": row[GDELT_COLS["event_code"]] if len(row) > GDELT_COLS["event_code"] else "",
                            "source_url": source_url,
                        },
                    }
                    events.append(event_dict)

                except Exception as e:
                    logger.debug(f"Error parsing GDELT row: {e}")
                    continue

        except httpx.HTTPStatusError as e:
            logger.error(f"GDELT HTTP error: {e.response.status_code}")
        except httpx.TimeoutException:
            logger.error("GDELT request timed out")
        except Exception as e:
            logger.error(f"GDELT fetch error: {e}")

    logger.info(f"GDELT: returning {len(events)} events")
    return events
