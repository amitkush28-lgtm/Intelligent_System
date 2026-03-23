"""
FRED API (fred.stlouisfed.org) — 800K+ economic time series.
Primary data source for the economist agent and has the fastest
feedback loop for prediction validation.

Key series: GDP, CPI, unemployment, Fed funds rate, yield curve, M2 money supply.
Free API, 120 requests/min.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# Key economic series to track (series_id -> description)
KEY_SERIES = {
    # GDP & Growth
    "GDP": "Gross Domestic Product (quarterly)",
    "GDPC1": "Real GDP (quarterly, chained 2017 dollars)",
    "A191RL1Q225SBEA": "Real GDP growth rate (quarterly, annualized)",

    # Inflation
    "CPIAUCSL": "Consumer Price Index (monthly, all urban)",
    "CPILFESL": "Core CPI excluding food and energy (monthly)",
    "PCEPI": "PCE Price Index (monthly)",
    "PCEPILFE": "Core PCE excluding food and energy (monthly)",

    # Labor Market
    "UNRATE": "Unemployment Rate (monthly)",
    "PAYEMS": "Total Nonfarm Payrolls (monthly)",
    "ICSA": "Initial Jobless Claims (weekly)",
    "CCSA": "Continued Claims (weekly)",
    "JTSJOL": "Job Openings (monthly, JOLTS)",

    # Interest Rates & Monetary
    "FEDFUNDS": "Federal Funds Effective Rate (daily)",
    "DFF": "Federal Funds Rate (daily)",
    "DGS10": "10-Year Treasury Yield (daily)",
    "DGS2": "2-Year Treasury Yield (daily)",
    "T10Y2Y": "10Y-2Y Yield Spread (daily)",
    "T10Y3M": "10Y-3M Yield Spread (daily)",

    # Money Supply
    "M2SL": "M2 Money Supply (monthly)",
    "BOGMBASE": "Monetary Base (biweekly)",

    # Housing
    "HOUST": "Housing Starts (monthly)",
    "PERMIT": "Building Permits (monthly)",
    "CSUSHPINSA": "Case-Shiller Home Price Index (monthly)",

    # Consumer & Business
    "RSAFS": "Retail Sales (monthly)",
    "UMCSENT": "U of Michigan Consumer Sentiment (monthly)",
    "INDPRO": "Industrial Production Index (monthly)",
    "DGORDER": "Durable Goods Orders (monthly)",

    # Trade
    "BOPGSTB": "Trade Balance (monthly)",
    "DTWEXBGS": "Trade Weighted Dollar Index (daily)",
}

# Severity mapping based on how much a release typically moves markets
HIGH_IMPACT_SERIES = {
    "UNRATE", "PAYEMS", "CPIAUCSL", "CPILFESL", "PCEPILFE",
    "GDP", "GDPC1", "A191RL1Q225SBEA", "FEDFUNDS", "DFF",
    "ICSA",
}

MEDIUM_IMPACT_SERIES = {
    "DGS10", "DGS2", "T10Y2Y", "T10Y3M", "RSAFS",
    "HOUST", "UMCSENT", "INDPRO", "DGORDER", "M2SL",
    "JTSJOL",
}


def _get_severity(series_id: str, value_change_pct: float) -> str:
    """Determine severity based on series importance and magnitude of change."""
    if series_id in HIGH_IMPACT_SERIES:
        if abs(value_change_pct) > 5.0:
            return "critical"
        elif abs(value_change_pct) > 2.0:
            return "significant"
        return "notable"
    elif series_id in MEDIUM_IMPACT_SERIES:
        if abs(value_change_pct) > 5.0:
            return "significant"
        elif abs(value_change_pct) > 2.0:
            return "notable"
        return "routine"
    return "routine"


def _compute_change(current: float, previous: float) -> Dict[str, float]:
    """Compute absolute and percentage change."""
    if previous == 0:
        return {"absolute": current, "percent": 0.0}
    pct = ((current - previous) / abs(previous)) * 100
    return {"absolute": current - previous, "percent": round(pct, 3)}


async def fetch_fred_series(
    series_id: str,
    lookback_days: int = 7,
    timeout: float = 30.0,
) -> Optional[Dict[str, Any]]:
    """
    Fetch the latest observation for a FRED series.
    Returns event dict if new data is available, None otherwise.
    """
    if not settings.FRED_API_KEY:
        logger.debug(f"FRED API key not set, skipping {series_id}")
        return None

    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    params = {
        "series_id": series_id,
        "api_key": settings.FRED_API_KEY,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
        "sort_order": "desc",
        "limit": 5,  # Get last few observations for change calculation
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(f"{FRED_BASE_URL}/series/observations", params=params)
            resp.raise_for_status()
            data = resp.json()

            observations = data.get("observations", [])
            if not observations:
                return None

            # Get latest observation
            latest = observations[0]
            value_str = latest.get("value", ".")
            if value_str == "." or not value_str:
                return None

            value = float(value_str)
            obs_date = latest.get("date", "")

            # Calculate change from previous observation
            change = {"absolute": 0, "percent": 0.0}
            if len(observations) > 1:
                prev_str = observations[1].get("value", ".")
                if prev_str and prev_str != ".":
                    prev_value = float(prev_str)
                    change = _compute_change(value, prev_value)

            description = KEY_SERIES.get(series_id, series_id)
            severity = _get_severity(series_id, change["percent"])

            # Build raw text
            direction = "increased" if change["absolute"] > 0 else "decreased" if change["absolute"] < 0 else "unchanged"
            raw_text = (
                f"FRED Economic Data Release: {description} ({series_id}). "
                f"Latest value: {value:.4g} as of {obs_date}. "
                f"Change: {direction} by {abs(change['absolute']):.4g} "
                f"({change['percent']:+.2f}%)."
            )

            return {
                "source": "fred",
                "source_detail": f"fred.stlouisfed.org/series/{series_id}",
                "timestamp": datetime.strptime(obs_date, "%Y-%m-%d") if obs_date else datetime.utcnow(),
                "domain": "economic",
                "event_type": "economic_data_release",
                "severity": severity,
                "entities": [
                    {"name": description, "type": "indicator", "role": "subject"},
                    {"name": "Federal Reserve Economic Data", "type": "organization", "role": "source"},
                ],
                "raw_text": raw_text,
                "metadata": {
                    "series_id": series_id,
                    "value": value,
                    "observation_date": obs_date,
                    "change_absolute": change["absolute"],
                    "change_percent": change["percent"],
                    "direction": direction,
                    "description": description,
                },
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"FRED rate limit hit for {series_id}")
            else:
                logger.error(f"FRED HTTP error for {series_id}: {e.response.status_code}")
            return None
        except httpx.TimeoutException:
            logger.warning(f"FRED timeout for {series_id}")
            return None
        except (ValueError, KeyError) as e:
            logger.warning(f"FRED parse error for {series_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"FRED unexpected error for {series_id}: {e}")
            return None


async def fetch_fred_events(
    series_ids: Optional[List[str]] = None,
    lookback_days: int = 7,
) -> List[Dict[str, Any]]:
    """
    Fetch latest data for all key FRED series.
    Returns list of event dicts for series with new data.
    """
    if not settings.FRED_API_KEY:
        logger.warning("FRED_API_KEY not set, skipping FRED source")
        return []

    target_series = series_ids or list(KEY_SERIES.keys())
    events = []

    logger.info(f"Fetching {len(target_series)} FRED series...")

    for series_id in target_series:
        try:
            event = await fetch_fred_series(series_id, lookback_days=lookback_days)
            if event:
                events.append(event)
        except Exception as e:
            logger.warning(f"Error fetching FRED series {series_id}: {e}")
            continue

    logger.info(f"FRED: returning {len(events)} events from {len(target_series)} series")
    return events
