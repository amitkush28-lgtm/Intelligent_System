"""
MarineTraffic AIS — Ship tracking for trade/blockade/sanctions claim verification.

Verifies claims about naval blockades, trade disruptions, sanctions enforcement,
port congestion, and shipping route changes using AIS vessel tracking data.

Uses publicly available AIS data endpoints. MarineTraffic free tier provides
limited vessel positions; premium tiers offer historical tracks and port calls.
"""

import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

import httpx

logger = logging.getLogger(__name__)

# MarineTraffic API (requires API key for most endpoints)
MT_API_BASE = "https://services.marinetraffic.com/api"

# Keywords indicating shipping-verifiable claims
SHIPPING_KEYWORDS = [
    "blockade", "naval", "shipping", "maritime",
    "port", "harbor", "harbour",
    "cargo", "tanker", "vessel", "ship",
    "trade route", "shipping lane",
    "strait", "canal", "suez", "hormuz", "malacca", "bosphorus",
    "sanctions", "embargo",
    "piracy", "naval exercise",
    "fleet", "carrier", "warship", "destroyer", "submarine",
    "oil tanker", "lng", "container",
    "supply chain", "freight",
    "coast guard", "navy",
    "smuggling", "trafficking",
]

# Major shipping chokepoints with coordinates
SHIPPING_CHOKEPOINTS = {
    "suez canal": {"lat": 30.46, "lon": 32.35, "region": "Middle East"},
    "strait of hormuz": {"lat": 26.57, "lon": 56.25, "region": "Persian Gulf"},
    "strait of malacca": {"lat": 2.50, "lon": 101.50, "region": "Southeast Asia"},
    "bab el mandeb": {"lat": 12.58, "lon": 43.33, "region": "Red Sea"},
    "bosphorus": {"lat": 41.12, "lon": 29.05, "region": "Black Sea"},
    "panama canal": {"lat": 9.08, "lon": -79.68, "region": "Central America"},
    "gibraltar": {"lat": 35.97, "lon": -5.35, "region": "Mediterranean"},
    "danish straits": {"lat": 55.60, "lon": 12.60, "region": "Baltic Sea"},
    "taiwan strait": {"lat": 24.00, "lon": 119.00, "region": "East Asia"},
    "south china sea": {"lat": 12.00, "lon": 114.00, "region": "East Asia"},
}

# Major ports
MAJOR_PORTS = {
    "shanghai": {"lat": 31.23, "lon": 121.47},
    "singapore": {"lat": 1.29, "lon": 103.85},
    "rotterdam": {"lat": 51.92, "lon": 4.48},
    "los angeles": {"lat": 33.74, "lon": -118.27},
    "long beach": {"lat": 33.77, "lon": -118.19},
    "busan": {"lat": 35.10, "lon": 129.04},
    "hong kong": {"lat": 22.28, "lon": 114.17},
    "dubai": {"lat": 25.27, "lon": 55.30},
    "hamburg": {"lat": 53.55, "lon": 9.97},
    "antwerp": {"lat": 51.22, "lon": 4.40},
    "felixstowe": {"lat": 51.96, "lon": 1.35},
    "odesa": {"lat": 46.48, "lon": 30.72},
    "sevastopol": {"lat": 44.62, "lon": 33.53},
    "novorossiysk": {"lat": 44.72, "lon": 37.77},
    "jeddah": {"lat": 21.49, "lon": 39.19},
    "mumbai": {"lat": 18.95, "lon": 72.84},
    "yokohama": {"lat": 35.44, "lon": 139.64},
}


def _is_shipping_claim(claim_text: str) -> bool:
    """Check if claim involves shipping or maritime activity."""
    claim_lower = claim_text.lower()
    return any(kw in claim_lower for kw in SHIPPING_KEYWORDS)


def _extract_maritime_location(
    claim_text: str,
) -> Optional[Dict[str, Any]]:
    """Extract maritime location from claim."""
    claim_lower = claim_text.lower()

    for name, info in SHIPPING_CHOKEPOINTS.items():
        if name in claim_lower:
            return {"name": name, "type": "chokepoint", **info}

    for name, info in MAJOR_PORTS.items():
        if name in claim_lower:
            return {"name": name, "type": "port", **info}

    return None


async def verify_shipping_claim(
    claim_text: str,
    entities: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:
    """
    Verify a shipping/maritime claim using AIS vessel tracking data.

    Checks vessel positions and movements near relevant chokepoints and ports
    to verify claims about blockades, trade disruptions, and naval activity.

    Args:
        claim_text: The claim to verify
        entities: Extracted entities

    Returns:
        Verification result dict or None if not applicable
    """
    if not _is_shipping_claim(claim_text):
        return None

    location = _extract_maritime_location(claim_text)
    api_key = os.environ.get("MARINETRAFFIC_API_KEY", "")

    # Try API if key is available
    if api_key and location:
        result = await _query_marinetraffic(api_key, location, claim_text)
        if result:
            return result

    # Fallback: contextual assessment based on known maritime patterns
    return _maritime_assessment(claim_text, location, entities)


async def _query_marinetraffic(
    api_key: str,
    location: Dict[str, Any],
    claim_text: str,
) -> Optional[Dict[str, Any]]:
    """Query MarineTraffic API for vessel positions near a location."""
    try:
        # PS07: Get vessels in area
        lat = location["lat"]
        lon = location["lon"]

        url = (
            f"{MT_API_BASE}/exportVessels/v:8/{api_key}"
            f"/MINLAT:{lat - 1}/MAXLAT:{lat + 1}"
            f"/MINLON:{lon - 1}/MAXLON:{lon + 1}"
            f"/protocol:jsono"
        )

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url)

            if response.status_code == 402:
                logger.debug("MarineTraffic: insufficient credits")
                return None

            if response.status_code != 200:
                logger.debug(f"MarineTraffic returned {response.status_code}")
                return None

            data = response.json()

        vessels = data if isinstance(data, list) else []
        return _analyze_vessel_data(vessels, location, claim_text)

    except httpx.TimeoutException:
        logger.warning("MarineTraffic API timeout")
        return None
    except Exception as e:
        logger.debug(f"MarineTraffic query error: {e}")
        return None


def _analyze_vessel_data(
    vessels: list,
    location: Dict[str, Any],
    claim_text: str,
) -> Dict[str, Any]:
    """Analyze vessel data for claim verification."""
    claim_lower = claim_text.lower()
    vessel_count = len(vessels)

    # Categorize vessels by type
    cargo = sum(1 for v in vessels if str(v.get("SHIP_TYPE", "")).startswith("7"))
    tankers = sum(1 for v in vessels if str(v.get("SHIP_TYPE", "")).startswith("8"))
    military = sum(1 for v in vessels if str(v.get("SHIP_TYPE", "")).startswith("3"))

    finding_parts = [
        f"AIS data at {location['name']}: {vessel_count} vessels detected",
        f"Cargo: {cargo}, Tankers: {tankers}, Military/other: {military}",
    ]

    corroborates = True
    confidence = 0.50

    # Blockade claims: fewer commercial vessels supports it
    if "blockade" in claim_lower:
        if cargo + tankers < 5:
            corroborates = True
            confidence = 0.60
            finding_parts.append("Low commercial traffic consistent with blockade")
        else:
            corroborates = False
            confidence = 0.55
            finding_parts.append("Active commercial traffic inconsistent with blockade")

    # Naval buildup claims
    elif any(w in claim_lower for w in ["naval", "fleet", "warship", "carrier"]):
        if military > 3:
            corroborates = True
            confidence = 0.60
            finding_parts.append("Elevated military vessel presence detected")
        else:
            confidence = 0.35
            finding_parts.append("Limited military vessel presence in AIS data")

    # Trade disruption claims
    elif any(w in claim_lower for w in ["disruption", "congestion", "delay"]):
        if vessel_count > 50:
            corroborates = True
            confidence = 0.55
            finding_parts.append("High vessel density may indicate congestion")
        else:
            confidence = 0.35
            finding_parts.append("Normal vessel density observed")

    return {
        "modality": "shipping",
        "source": "MarineTraffic AIS",
        "corroborates": corroborates,
        "confidence": confidence,
        "finding": ". ".join(finding_parts),
        "data": {
            "location": location["name"],
            "vessel_count": vessel_count,
            "cargo": cargo,
            "tankers": tankers,
            "military": military,
        },
    }


def _maritime_assessment(
    claim_text: str,
    location: Optional[Dict[str, Any]],
    entities: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Contextual assessment when MarineTraffic API is unavailable.

    Uses known maritime patterns and chokepoint significance to assess
    claim plausibility.
    """
    claim_lower = claim_text.lower()
    confidence = 0.25
    finding_parts = []

    if location:
        loc_name = location["name"]
        loc_type = location.get("type", "unknown")
        region = location.get("region", "")

        finding_parts.append(f"Claim involves {loc_type}: {loc_name} ({region})")

        if loc_type == "chokepoint":
            confidence = 0.35
            finding_parts.append(
                "Major shipping chokepoint — disruptions here have documented global impact"
            )
        elif loc_type == "port":
            confidence = 0.30
            finding_parts.append("Major port — vessel activity data would be informative")
    else:
        finding_parts.append("Maritime claim without specific location identified")

    # Assess claim type
    if "blockade" in claim_lower:
        finding_parts.append(
            "Blockade claims are verifiable via AIS tracking of commercial vessel traffic"
        )
    elif any(w in claim_lower for w in ["sanctions", "embargo"]):
        finding_parts.append(
            "Sanctions compliance verifiable via vessel tracking and port call patterns"
        )

    return {
        "modality": "shipping",
        "source": "Maritime Assessment (no API key)",
        "corroborates": True,
        "confidence": confidence,
        "finding": ". ".join(finding_parts),
        "data": {
            "location": location["name"] if location else None,
            "assessment": "contextual_only",
        },
    }
