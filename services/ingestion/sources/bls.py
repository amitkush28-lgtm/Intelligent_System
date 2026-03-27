"""
BLS API (bls.gov/developers) — Granular US labor data.
500 requests/day free. No key needed for v1 (25 requests/day).
Key series: nonfarm payrolls, unemployment rate, CPI components, PPI.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

BLS_BASE = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

# Key labor/price series
KEY_SERIES = {
    "CES0000000001": "Total nonfarm payrolls",
    "LNS14000000": "Unemployment rate",
    "CUUR0000SA0": "CPI-U all items (urban)",
    "CUUR0000SA0L1E": "CPI-U less food and energy (core)",
    "WPUFD4": "PPI final demand",
    "CES0500000003": "Average hourly earnings (private)",
    "JTS000000000000000QUL": "Quits rate (JOLTS)",
    "LNS12300000": "Employment-population ratio",
}


async def fetch_bls_events() -> List[Dict[str, Any]]:
    """Fetch latest BLS economic data releases."""
    events = []
    current_year = datetime.utcnow().year

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for series_id, description in KEY_SERIES.items():
                try:
                    resp = await client.get(
                        f"{BLS_BASE}{series_id}",
                        params={
                            "startyear": str(current_year - 1),
                            "endyear": str(current_year),
                        },
                    )

                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    if data.get("status") != "REQUEST_SUCCEEDED":
                        continue

                    series_data = data.get("Results", {}).get("series", [])
                    if not series_data:
                        continue

                    observations = series_data[0].get("data", [])
                    if not observations:
                        continue

                    # Get latest two observations for comparison
                    latest = observations[0]
                    previous = observations[1] if len(observations) > 1 else None

                    value = latest.get("value", "N/A")
                    period = latest.get("periodName", "")
                    year = latest.get("year", "")

                    change_text = ""
                    if previous:
                        try:
                            change = float(value) - float(previous.get("value", 0))
                            direction = "up" if change > 0 else "down"
                            change_text = f" ({direction} {abs(change):.1f} from prior period)"
                        except (ValueError, TypeError):
                            pass

                    events.append({
                        "id": f"bls-{series_id}-{year}-{latest.get('period', '')}",
                        "source": "bls",
                        "source_detail": f"BLS {series_id}",
                        "timestamp": datetime.utcnow(),
                        "domain": "economic",
                        "event_type": "economic_data_release",
                        "severity": "notable",
                        "raw_text": f"{description}: {value} ({period} {year}){change_text}",
                        "entities": [{"name": "BLS", "type": "organization", "role": "publisher"}],
                    })
                except Exception as e:
                    logger.debug(f"BLS series {series_id} failed: {e}")
                    continue

    except Exception as e:
        logger.error(f"BLS fetch error: {e}")

    logger.info(f"BLS: returning {len(events)} events")
    return events
