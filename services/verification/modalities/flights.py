"""
ADS-B Exchange — Flight tracking for military/diplomatic movement verification.

Verifies claims about military aircraft deployments, diplomatic flights,
airspace closures, and aviation anomalies using ADS-B transponder data.

API: https://www.adsbexchange.com/data/
Free tier provides limited real-time aircraft positions.
"""

import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

import httpx

logger = logging.getLogger(__name__)

ADSB_API_BASE = "https://adsbexchange.com/api/aircraft/v2"
ADSB_RAPIDAPI = "https://adsbexchange-com1.p.rapidapi.com/v2"

# Keywords for flight-verifiable claims
FLIGHT_KEYWORDS = [
    "aircraft", "airplane", "plane", "flight",
    "air force", "fighter jet", "bomber", "drone", "uav",
    "airspace", "no-fly zone", "flight ban",
    "diplomatic flight", "state visit",
    "air defense", "anti-aircraft",
    "aerial", "airstrike", "bombing",
    "military aircraft", "surveillance",
    "evacuation flight", "humanitarian flight",
    "air traffic", "aviation",
    "cargo plane", "transport aircraft",
    "refueling", "tanker aircraft",
    "awacs", "reconnaissance",
    "helicopter", "rotorcraft",
]

# Military aircraft type designators
MILITARY_TYPES = {
    "F-35", "F-22", "F-16", "F-15", "F-18",
    "B-52", "B-1", "B-2", "B-21",
    "C-17", "C-130", "C-5", "C-40",
    "KC-135", "KC-46", "KC-10",
    "E-3", "E-8", "E-2", "RC-135",
    "P-8", "MQ-9", "RQ-4",
    "Su-27", "Su-30", "Su-34", "Su-35", "Su-57",
    "Tu-95", "Tu-160", "Il-76",
    "J-20", "J-16", "Y-20",
    "Eurofighter", "Rafale", "Typhoon", "Gripen",
    "A400M", "Chinook", "Apache", "Black Hawk",
}

# Regions of interest with bounding boxes
REGIONS = {
    "eastern europe": {"lat1": 44, "lon1": 22, "lat2": 56, "lon2": 40},
    "ukraine": {"lat1": 44, "lon1": 22, "lat2": 53, "lon2": 40},
    "taiwan strait": {"lat1": 22, "lon1": 117, "lat2": 26, "lon2": 121},
    "south china sea": {"lat1": 5, "lon1": 105, "lat2": 22, "lon2": 120},
    "persian gulf": {"lat1": 23, "lon1": 47, "lat2": 30, "lon2": 57},
    "middle east": {"lat1": 28, "lon1": 33, "lat2": 38, "lon2": 48},
    "korean peninsula": {"lat1": 33, "lon1": 124, "lat2": 43, "lon2": 131},
    "baltic": {"lat1": 53, "lon1": 14, "lat2": 60, "lon2": 30},
    "arctic": {"lat1": 66, "lon1": -180, "lat2": 90, "lon2": 180},
    "gaza": {"lat1": 31, "lon1": 34, "lat2": 32, "lon2": 35},
}


def _is_flight_claim(claim_text: str) -> bool:
    """Check if claim involves aviation or flight tracking."""
    claim_lower = claim_text.lower()
    return any(kw in claim_lower for kw in FLIGHT_KEYWORDS)


def _extract_region(claim_text: str) -> Optional[Dict[str, Any]]:
    """Extract region of interest from claim."""
    claim_lower = claim_text.lower()
    for name, bbox in REGIONS.items():
        if name in claim_lower:
            return {"name": name, **bbox}

    # Try common country names
    country_regions = {
        "russia": "eastern europe",
        "china": "south china sea",
        "taiwan": "taiwan strait",
        "iran": "persian gulf",
        "north korea": "korean peninsula",
        "israel": "middle east",
        "syria": "middle east",
    }
    for country, region in country_regions.items():
        if country in claim_lower:
            return {"name": region, **REGIONS[region]}

    return None


async def verify_flight_claim(
    claim_text: str,
    entities: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:
    """
    Verify claims about military/diplomatic flights using ADS-B data.

    Checks aircraft positions and types in relevant airspace to verify
    claims about military deployments, airspace activity, and flight patterns.

    Args:
        claim_text: The claim to verify
        entities: Extracted entities

    Returns:
        Verification result dict or None if not applicable
    """
    if not _is_flight_claim(claim_text):
        return None

    region = _extract_region(claim_text)
    api_key = os.environ.get("ADSBEXCHANGE_API_KEY", "")
    rapidapi_key = os.environ.get("RAPIDAPI_KEY", "")

    # Try API query if credentials available
    if (api_key or rapidapi_key) and region:
        result = await _query_adsb(api_key, rapidapi_key, region, claim_text)
        if result:
            return result

    # Fallback: contextual assessment
    return _flight_assessment(claim_text, region, entities)


async def _query_adsb(
    api_key: str,
    rapidapi_key: str,
    region: Dict[str, Any],
    claim_text: str,
) -> Optional[Dict[str, Any]]:
    """Query ADS-B Exchange for aircraft in region."""
    try:
        lat_center = (region["lat1"] + region["lat2"]) / 2
        lon_center = (region["lon1"] + region["lon2"]) / 2

        if rapidapi_key:
            url = f"{ADSB_RAPIDAPI}/lat/{lat_center}/lon/{lon_center}/dist/250/"
            headers = {
                "X-RapidAPI-Key": rapidapi_key,
                "X-RapidAPI-Host": "adsbexchange-com1.p.rapidapi.com",
            }
        else:
            url = f"{ADSB_API_BASE}/lat/{lat_center}/lon/{lon_center}/dist/250/"
            headers = {"api-auth": api_key}

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 429:
                logger.warning("ADS-B Exchange rate limited")
                return None

            if response.status_code != 200:
                logger.debug(f"ADS-B Exchange returned {response.status_code}")
                return None

            data = response.json()

        aircraft_list = data.get("ac", [])
        return _analyze_aircraft_data(aircraft_list, region, claim_text)

    except httpx.TimeoutException:
        logger.warning("ADS-B Exchange timeout")
        return None
    except Exception as e:
        logger.debug(f"ADS-B Exchange error: {e}")
        return None


def _analyze_aircraft_data(
    aircraft: list,
    region: Dict[str, Any],
    claim_text: str,
) -> Dict[str, Any]:
    """Analyze ADS-B aircraft data for claim verification."""
    claim_lower = claim_text.lower()
    total = len(aircraft)

    # Categorize aircraft
    military_count = 0
    commercial_count = 0
    unknown_count = 0

    for ac in aircraft:
        ac_type = str(ac.get("t", "")).upper()
        category = str(ac.get("category", ""))
        flight = str(ac.get("flight", "")).strip().upper()

        is_military = (
            any(mt in ac_type for mt in MILITARY_TYPES)
            or flight.startswith(("RCH", "JAKE", "DUKE", "EVAC", "RRR"))
            or category in ("A6", "A7")  # Military categories
        )

        if is_military:
            military_count += 1
        elif category in ("A1", "A2", "A3", "A4", "A5"):
            commercial_count += 1
        else:
            unknown_count += 1

    finding_parts = [
        f"ADS-B data for {region['name']}: {total} aircraft detected",
        f"Military: {military_count}, Commercial: {commercial_count}, Other: {unknown_count}",
    ]

    corroborates = True
    confidence = 0.45

    # Military buildup/deployment claims
    if any(w in claim_lower for w in ["deployment", "buildup", "mobiliz", "military aircraft"]):
        if military_count > 5:
            corroborates = True
            confidence = 0.60
            finding_parts.append("Elevated military aircraft presence detected")
        elif military_count > 0:
            confidence = 0.40
            finding_parts.append("Some military aircraft present")
        else:
            corroborates = False
            confidence = 0.40
            finding_parts.append("No military aircraft detected on ADS-B")

    # Airspace closure claims
    elif any(w in claim_lower for w in ["no-fly", "airspace clos", "flight ban"]):
        if total < 5:
            corroborates = True
            confidence = 0.55
            finding_parts.append("Very low air traffic consistent with restrictions")
        else:
            corroborates = False
            confidence = 0.50
            finding_parts.append("Active air traffic inconsistent with closure claim")

    return {
        "modality": "flights",
        "source": "ADS-B Exchange",
        "corroborates": corroborates,
        "confidence": confidence,
        "finding": ". ".join(finding_parts),
        "data": {
            "region": region["name"],
            "total_aircraft": total,
            "military": military_count,
            "commercial": commercial_count,
        },
    }


def _flight_assessment(
    claim_text: str,
    region: Optional[Dict[str, Any]],
    entities: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Contextual flight assessment when API is unavailable."""
    claim_lower = claim_text.lower()
    confidence = 0.20
    finding_parts = []

    if region:
        finding_parts.append(f"Claim involves airspace over: {region['name']}")
        confidence = 0.25
    else:
        finding_parts.append("Aviation claim without specific region identified")

    # Assess claim type plausibility
    if any(w in claim_lower for w in ["military aircraft", "fighter", "bomber"]):
        finding_parts.append(
            "Military aircraft claims verifiable via ADS-B but military often fly without transponders"
        )
        confidence = min(confidence, 0.20)
    elif any(w in claim_lower for w in ["airspace", "no-fly", "flight ban"]):
        finding_parts.append(
            "Airspace restrictions verifiable via commercial traffic patterns in ADS-B data"
        )
    elif any(w in claim_lower for w in ["diplomatic flight", "state visit"]):
        finding_parts.append(
            "Diplomatic flights often use government callsigns trackable via ADS-B"
        )

    return {
        "modality": "flights",
        "source": "ADS-B Assessment (no API key)",
        "corroborates": True,
        "confidence": confidence,
        "finding": ". ".join(finding_parts),
        "data": {
            "region": region["name"] if region else None,
            "assessment": "contextual_only",
        },
    }
