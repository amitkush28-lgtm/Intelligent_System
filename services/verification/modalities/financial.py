"""
World Bank API — Cross-modal verification via global development indicators.

Verifies economic claims using World Bank open data (GDP, inflation, FDI,
poverty, debt, trade balance, etc.). Free API, no key required.

API docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.worldbank.org/v2"

# ISO2 country codes for keyword extraction
COUNTRY_CODES_ISO2 = {
    "united states": "US", "usa": "US", "us": "US",
    "china": "CN", "prc": "CN",
    "germany": "DE", "japan": "JP",
    "united kingdom": "GB", "uk": "GB", "britain": "GB",
    "france": "FR", "india": "IN",
    "south korea": "KR", "korea": "KR",
    "russia": "RU", "brazil": "BR",
    "canada": "CA", "australia": "AU",
    "mexico": "MX", "indonesia": "ID",
    "turkey": "TR", "saudi arabia": "SA",
    "iran": "IR", "iraq": "IQ",
    "ukraine": "UA", "nigeria": "NG",
    "south africa": "ZA", "egypt": "EG",
    "argentina": "AR", "colombia": "CO",
    "thailand": "TH", "vietnam": "VN",
    "philippines": "PH", "pakistan": "PK",
    "bangladesh": "BD", "malaysia": "MY",
    "chile": "CL", "peru": "PE",
    "poland": "PL", "kenya": "KE",
    "ethiopia": "ET", "world": "WLD",
}

# World Bank indicator codes mapped to claim keywords
INDICATOR_MAP = {
    # GDP & growth
    "gdp": "NY.GDP.MKTP.CD",
    "gdp growth": "NY.GDP.MKTP.KD.ZG",
    "gdp per capita": "NY.GDP.PCAP.CD",
    "economic growth": "NY.GDP.MKTP.KD.ZG",
    "recession": "NY.GDP.MKTP.KD.ZG",
    "economy": "NY.GDP.MKTP.CD",
    # Inflation
    "inflation": "FP.CPI.TOTL.ZG",
    "consumer price": "FP.CPI.TOTL.ZG",
    "cpi": "FP.CPI.TOTL.ZG",
    # Trade
    "trade": "NE.TRD.GNFS.ZS",
    "exports": "NE.EXP.GNFS.ZS",
    "imports": "NE.IMP.GNFS.ZS",
    "trade balance": "NE.RSB.GNFS.ZS",
    "current account": "BN.CAB.XOKA.CD",
    # Investment
    "fdi": "BX.KLT.DINV.CD.WD",
    "foreign investment": "BX.KLT.DINV.CD.WD",
    "investment": "NE.GDI.TOTL.ZS",
    # Debt
    "debt": "GC.DOD.TOTL.GD.ZS",
    "government debt": "GC.DOD.TOTL.GD.ZS",
    "external debt": "DT.DOD.DECT.CD",
    # Employment
    "unemployment": "SL.UEM.TOTL.ZS",
    "employment": "SL.EMP.TOTL.SP.ZS",
    "labor": "SL.TLF.TOTL.IN",
    # Poverty
    "poverty": "SI.POV.DDAY",
    "inequality": "SI.POV.GINI",
    "gini": "SI.POV.GINI",
    # Aid
    "aid": "DT.ODA.ODAT.CD",
    "development aid": "DT.ODA.ODAT.CD",
    "foreign aid": "DT.ODA.ODAT.CD",
    # Energy
    "energy": "EG.USE.PCAP.KG.OE",
    "electricity": "EG.ELC.ACCS.ZS",
    "renewable": "EG.FEC.RNEW.ZS",
    # Population
    "population": "SP.POP.TOTL",
    "population growth": "SP.POP.GROW",
    "urbanization": "SP.URB.TOTL.IN.ZS",
}


def _extract_country(text: str) -> Optional[str]:
    """Extract ISO2 country code from text."""
    text_lower = text.lower()
    for name, code in COUNTRY_CODES_ISO2.items():
        if name in text_lower:
            return code
    return None


def _extract_indicator(text: str) -> Optional[str]:
    """Extract best-matching World Bank indicator code."""
    text_lower = text.lower()
    # Try longest match first
    matches = []
    for keyword, indicator in INDICATOR_MAP.items():
        if keyword in text_lower:
            matches.append((len(keyword), indicator))
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]
    return None


async def verify_financial_claim(
    claim_text: str,
    entities: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:
    """
    Verify an economic claim using World Bank development indicators.

    Checks official data for GDP growth, inflation, trade, FDI, debt,
    poverty, employment, and other macroeconomic indicators.

    Args:
        claim_text: The claim to verify
        entities: Extracted entities from the claim

    Returns:
        Verification result dict or None if not applicable
    """
    country_code = _extract_country(claim_text)
    indicator_code = _extract_indicator(claim_text)

    if not country_code:
        if entities:
            for ent in entities:
                if ent.get("type") in ("GPE", "LOC", "country"):
                    code = _extract_country(ent.get("name", ""))
                    if code:
                        country_code = code
                        break

    if not country_code or not indicator_code:
        logger.debug("Cannot extract country/indicator for World Bank verification")
        return None

    try:
        # Fetch last 5 years of data to see trends
        current_year = datetime.utcnow().year
        date_range = f"{current_year - 5}:{current_year}"

        url = f"{BASE_URL}/country/{country_code}/indicator/{indicator_code}"
        params = {
            "format": "json",
            "date": date_range,
            "per_page": 10,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)

            if response.status_code == 429:
                logger.warning("World Bank API rate limited")
                return None

            if response.status_code != 200:
                logger.warning(f"World Bank API returned {response.status_code}")
                return None

            data = response.json()

        # World Bank API returns [metadata, data_array]
        if not isinstance(data, list) or len(data) < 2:
            return _inconclusive("Unexpected API response format")

        records = data[1]
        if not records:
            return _inconclusive(f"No data for {country_code}/{indicator_code}")

        return _analyze_indicator_data(records, claim_text, country_code, indicator_code)

    except httpx.TimeoutException:
        logger.warning("World Bank API timeout")
        return None
    except Exception as e:
        logger.error(f"World Bank verification error: {e}")
        return None


def _analyze_indicator_data(
    records: list,
    claim_text: str,
    country_code: str,
    indicator_code: str,
) -> Dict[str, Any]:
    """Analyze World Bank indicator data for claim verification."""
    claim_lower = claim_text.lower()

    # Extract valid data points (sorted by year)
    data_points = []
    indicator_name = ""
    for record in records:
        value = record.get("value")
        year = record.get("date", "")
        if value is not None:
            data_points.append({"year": year, "value": float(value)})
        if not indicator_name:
            indicator_name = record.get("indicator", {}).get("value", indicator_code)

    if not data_points:
        return _inconclusive(f"No valid data points for {indicator_name}")

    data_points.sort(key=lambda x: x["year"])

    latest = data_points[-1]
    finding_parts = [
        f"{indicator_name}: {latest['value']:.2f} ({latest['year']})",
    ]

    # Calculate trend if we have enough data
    trend = None
    if len(data_points) >= 2:
        first = data_points[0]["value"]
        last = data_points[-1]["value"]
        if first != 0:
            pct_change = ((last - first) / abs(first)) * 100
            trend = "increasing" if pct_change > 2 else "decreasing" if pct_change < -2 else "stable"
            finding_parts.append(
                f"Trend ({data_points[0]['year']}-{data_points[-1]['year']}): "
                f"{pct_change:+.1f}% ({trend})"
            )

    # Match claim direction to data trend
    corroborates = True
    confidence = 0.45

    growth_words = ["grow", "increase", "surge", "rise", "boom", "expand", "improve"]
    decline_words = ["decline", "decrease", "drop", "fall", "collapse", "shrink", "worsen", "recession"]

    claims_growth = any(w in claim_lower for w in growth_words)
    claims_decline = any(w in claim_lower for w in decline_words)

    if trend and claims_growth:
        if trend == "increasing":
            corroborates = True
            confidence = 0.60
            finding_parts.append("Data trend supports growth claim")
        elif trend == "decreasing":
            corroborates = False
            confidence = 0.55
            finding_parts.append("Data trend contradicts growth claim")
        else:
            confidence = 0.35
            finding_parts.append("Data shows stability, not clear growth")

    elif trend and claims_decline:
        if trend == "decreasing":
            corroborates = True
            confidence = 0.60
            finding_parts.append("Data trend supports decline claim")
        elif trend == "increasing":
            corroborates = False
            confidence = 0.55
            finding_parts.append("Data trend contradicts decline claim")
        else:
            confidence = 0.35
            finding_parts.append("Data shows stability, not clear decline")

    return {
        "modality": "financial",
        "source": "World Bank",
        "corroborates": corroborates,
        "confidence": confidence,
        "finding": ". ".join(finding_parts),
        "data": {
            "country": country_code,
            "indicator": indicator_code,
            "indicator_name": indicator_name,
            "latest_value": latest["value"],
            "latest_year": latest["year"],
            "trend": trend,
            "data_points": len(data_points),
        },
    }


def _inconclusive(reason: str) -> Dict[str, Any]:
    """Return inconclusive result."""
    return {
        "modality": "financial",
        "source": "World Bank",
        "corroborates": True,
        "confidence": 0.15,
        "finding": f"Inconclusive: {reason}",
    }
