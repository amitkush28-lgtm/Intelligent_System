"""
World Bank API (data.worldbank.org) — Global development indicators.
Free, no key needed. Tracks GDP, inflation, FDI, debt across 200+ countries.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

WB_BASE = "https://api.worldbank.org/v2"

# Key indicators for intelligence analysis
KEY_INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": ("GDP growth rate", "economic"),
    "FP.CPI.TOTL.ZG": ("Inflation (CPI)", "economic"),
    "BX.KLT.DINV.CD.WD": ("Foreign direct investment", "economic"),
    "DT.DOD.DECT.CD": ("External debt", "economic"),
    "NE.TRD.GNFS.ZS": ("Trade as % of GDP", "economic"),
    "BN.CAB.XOKA.CD": ("Current account balance", "economic"),
    "SL.UEM.TOTL.ZS": ("Unemployment rate", "economic"),
}

# Major economies to track
KEY_COUNTRIES = ["USA", "CHN", "DEU", "JPN", "GBR", "IND", "BRA", "RUS", "FRA", "KOR"]


async def fetch_world_bank_events() -> List[Dict[str, Any]]:
    """Fetch latest World Bank development indicator data."""
    events = []
    current_year = datetime.utcnow().year

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for indicator_id, (description, domain) in KEY_INDICATORS.items():
                try:
                    countries = ";".join(KEY_COUNTRIES)
                    resp = await client.get(
                        f"{WB_BASE}/country/{countries}/indicator/{indicator_id}",
                        params={
                            "format": "json",
                            "date": f"{current_year-2}:{current_year}",
                            "per_page": 50,
                        },
                    )

                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    if not isinstance(data, list) or len(data) < 2:
                        continue

                    records = data[1] or []

                    for record in records:
                        value = record.get("value")
                        if value is None:
                            continue

                        country = record.get("country", {}).get("value", "Unknown")
                        country_code = record.get("countryiso3code", "")
                        year = record.get("date", "")

                        events.append({
                            "id": f"wb-{indicator_id}-{country_code}-{year}",
                            "source": "world_bank",
                            "source_detail": f"World Bank {indicator_id}",
                            "timestamp": datetime.utcnow(),
                            "domain": domain,
                            "event_type": "development_indicator",
                            "severity": "routine",
                            "raw_text": f"{country} {description}: {value:.2f} ({year})",
                            "entities": [{"name": country, "type": "nation", "role": "subject"}],
                        })
                except Exception as e:
                    logger.debug(f"World Bank {indicator_id} failed: {e}")
                    continue

    except Exception as e:
        logger.error(f"World Bank fetch error: {e}")

    logger.info(f"World Bank: returning {len(events)} events")
    return events
