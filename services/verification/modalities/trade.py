"""
UN Comtrade API — Cross-modal verification via import/export trade data.

Verifies economic claims (sanctions, trade agreements, supply chain disruptions)
by checking actual trade flow data. Free API, no key required for basic access.

API docs: https://comtradeapi.un.org/
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://comtradeapi.un.org/public/v1/preview"

# ISO 3166 numeric codes for major trading nations
COUNTRY_CODES = {
    "united states": "842", "usa": "842", "us": "842",
    "china": "156", "prc": "156",
    "germany": "276", "japan": "392",
    "united kingdom": "826", "uk": "826",
    "france": "251", "india": "356",
    "south korea": "410", "korea": "410",
    "russia": "643", "brazil": "076",
    "canada": "124", "australia": "036",
    "mexico": "484", "indonesia": "360",
    "turkey": "792", "saudi arabia": "682",
    "iran": "364", "iraq": "368",
    "ukraine": "804", "taiwan": "490",
    "singapore": "702", "netherlands": "528",
    "italy": "380", "spain": "724",
    "egypt": "818", "nigeria": "566",
    "south africa": "710",
}

# HS commodity code categories for keyword matching
COMMODITY_KEYWORDS = {
    "oil": "27",        # Mineral fuels
    "petroleum": "27",
    "crude": "2709",
    "natural gas": "2711",
    "steel": "72",      # Iron and steel
    "iron": "72",
    "aluminum": "76",
    "copper": "74",
    "wheat": "1001",
    "grain": "10",      # Cereals
    "rice": "1006",
    "semiconductor": "8542",
    "chips": "8542",
    "electronics": "85",
    "vehicles": "87",   # Vehicles
    "arms": "93",       # Arms and ammunition
    "weapons": "93",
    "pharmaceuticals": "30",
    "fertilizer": "31",
    "rare earth": "2846",
    "lithium": "2825",
    "cotton": "52",
    "sugar": "17",
    "coffee": "0901",
    "gold": "7108",
}


def _extract_country_code(claim_text: str) -> Optional[str]:
    """Extract a country code from claim text."""
    claim_lower = claim_text.lower()
    for name, code in COUNTRY_CODES.items():
        if name in claim_lower:
            return code
    return None


def _extract_commodity_code(claim_text: str) -> Optional[str]:
    """Extract HS commodity code from claim text."""
    claim_lower = claim_text.lower()
    for keyword, code in COMMODITY_KEYWORDS.items():
        if keyword in claim_lower:
            return code
    return None


async def verify_trade_claim(
    claim_text: str,
    entities: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:
    """
    Verify a claim using UN Comtrade trade flow data.

    Checks whether trade data supports or contradicts claims about:
    - Sanctions effectiveness (trade volume changes)
    - Trade agreement impacts
    - Supply chain disruptions
    - Import/export anomalies

    Args:
        claim_text: The claim to verify
        entities: Extracted entities from the claim

    Returns:
        Verification result dict or None if not applicable
    """
    reporter_code = _extract_country_code(claim_text)
    commodity_code = _extract_commodity_code(claim_text)

    if not reporter_code:
        # Try entities
        if entities:
            for ent in entities:
                if ent.get("type") in ("GPE", "LOC", "country"):
                    code = _extract_country_code(ent.get("name", ""))
                    if code:
                        reporter_code = code
                        break

    if not reporter_code:
        logger.debug("No country found in claim for trade verification")
        return None

    try:
        params = {
            "reporterCode": reporter_code,
            "period": _get_recent_period(),
            "flowCode": "M,X",  # imports and exports
            "maxRecords": 100,
        }
        if commodity_code:
            params["cmdCode"] = commodity_code

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(BASE_URL + "/getTariffline", params=params)

            if response.status_code == 429:
                logger.warning("UN Comtrade rate limited")
                return _inconclusive("Rate limited by UN Comtrade API")

            if response.status_code != 200:
                logger.warning(f"UN Comtrade returned {response.status_code}")
                return None

            data = response.json()

        records = data.get("data", [])
        if not records:
            # Try the preview endpoint with simpler params
            return await _try_preview_endpoint(reporter_code, commodity_code, claim_text)

        return _analyze_trade_data(records, claim_text, reporter_code, commodity_code)

    except httpx.TimeoutException:
        logger.warning("UN Comtrade API timeout")
        return _inconclusive("API timeout")
    except Exception as e:
        logger.error(f"UN Comtrade verification error: {e}")
        return None


async def _try_preview_endpoint(
    reporter_code: str,
    commodity_code: Optional[str],
    claim_text: str,
) -> Optional[Dict[str, Any]]:
    """Fallback to the preview/data endpoint."""
    try:
        params = {
            "reporterCode": reporter_code,
            "period": _get_recent_period(),
            "flowCode": "M,X",
            "maxRecords": 50,
        }
        if commodity_code:
            params["cmdCode"] = commodity_code

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(BASE_URL + "/getDA", params=params)

            if response.status_code != 200:
                return None

            data = response.json()

        records = data.get("data", [])
        if not records:
            return _inconclusive("No trade data found for this country/commodity combination")

        return _analyze_trade_data(records, claim_text, reporter_code, commodity_code)

    except Exception as e:
        logger.debug(f"Preview endpoint fallback failed: {e}")
        return None


def _analyze_trade_data(
    records: list,
    claim_text: str,
    reporter_code: str,
    commodity_code: Optional[str],
) -> Dict[str, Any]:
    """Analyze trade records for verification signals."""
    claim_lower = claim_text.lower()

    total_trade_value = 0
    import_value = 0
    export_value = 0
    record_count = len(records)

    for record in records:
        value = record.get("primaryValue", 0) or record.get("cifvalue", 0) or 0
        flow = str(record.get("flowCode", ""))
        total_trade_value += value
        if flow == "M":
            import_value += value
        elif flow == "X":
            export_value += value

    # Determine verification outcome based on claim context
    corroborates = True
    confidence = 0.4  # Base confidence for having data
    finding_parts = [
        f"Trade data found: {record_count} records",
        f"Total value: ${total_trade_value:,.0f}",
    ]

    # Check for sanctions/embargo claims
    sanctions_keywords = ["sanction", "embargo", "ban", "restrict", "blockade"]
    if any(kw in claim_lower for kw in sanctions_keywords):
        if total_trade_value > 0:
            # Trade still happening — may contradict sanctions effectiveness
            if any(w in claim_lower for w in ["effective", "working", "success"]):
                corroborates = False
                confidence = 0.55
                finding_parts.append("Trade flows still active despite claimed sanctions")
            else:
                corroborates = True
                confidence = 0.45
                finding_parts.append("Trade data shows ongoing flows")
        else:
            corroborates = True
            confidence = 0.60
            finding_parts.append("No significant trade flows found — consistent with sanctions")

    # Check for trade increase/decrease claims
    elif any(w in claim_lower for w in ["increase", "surge", "boom", "grow"]):
        if total_trade_value > 0:
            corroborates = True
            confidence = 0.45
            finding_parts.append("Active trade flows found")
        else:
            corroborates = False
            confidence = 0.40
            finding_parts.append("No significant trade data to support growth claim")

    elif any(w in claim_lower for w in ["decline", "decrease", "drop", "fall", "collapse"]):
        if total_trade_value == 0 or record_count < 5:
            corroborates = True
            confidence = 0.50
            finding_parts.append("Low trade volume consistent with decline claim")
        else:
            confidence = 0.35
            finding_parts.append("Trade data present but trend unclear from snapshot")

    return {
        "modality": "trade",
        "source": "UN Comtrade",
        "corroborates": corroborates,
        "confidence": confidence,
        "finding": ". ".join(finding_parts),
        "data": {
            "record_count": record_count,
            "total_value": total_trade_value,
            "import_value": import_value,
            "export_value": export_value,
            "reporter_code": reporter_code,
            "commodity_code": commodity_code,
        },
    }


def _get_recent_period() -> str:
    """Get the most recent complete year for trade data (typically 1-2 years lag)."""
    current_year = datetime.utcnow().year
    return str(current_year - 2)


def _inconclusive(reason: str) -> Dict[str, Any]:
    """Return an inconclusive result."""
    return {
        "modality": "trade",
        "source": "UN Comtrade",
        "corroborates": True,
        "confidence": 0.15,
        "finding": f"Inconclusive: {reason}",
    }
