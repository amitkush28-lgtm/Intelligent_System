"""
Twelve Data API (twelvedata.com) — 800 requests/day free tier.
Stock/forex/crypto prices. Pulls major indices (S&P 500, NASDAQ, VIX)
and tracked tickers.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# Key instruments to track
INSTRUMENTS = {
    # Major US indices
    "SPX": {"name": "S&P 500", "type": "index", "exchange": ""},
    "IXIC": {"name": "NASDAQ Composite", "type": "index", "exchange": ""},
    "DJI": {"name": "Dow Jones Industrial", "type": "index", "exchange": ""},
    "VIX": {"name": "CBOE Volatility Index", "type": "index", "exchange": ""},

    # Key stocks
    "AAPL": {"name": "Apple", "type": "stock", "exchange": "NASDAQ"},
    "MSFT": {"name": "Microsoft", "type": "stock", "exchange": "NASDAQ"},
    "NVDA": {"name": "NVIDIA", "type": "stock", "exchange": "NASDAQ"},
    "GOOGL": {"name": "Alphabet", "type": "stock", "exchange": "NASDAQ"},
    "AMZN": {"name": "Amazon", "type": "stock", "exchange": "NASDAQ"},
    "TSLA": {"name": "Tesla", "type": "stock", "exchange": "NASDAQ"},

    # Forex
    "EUR/USD": {"name": "Euro/Dollar", "type": "forex", "exchange": ""},
    "GBP/USD": {"name": "Pound/Dollar", "type": "forex", "exchange": ""},
    "USD/JPY": {"name": "Dollar/Yen", "type": "forex", "exchange": ""},
    "USD/CNY": {"name": "Dollar/Yuan", "type": "forex", "exchange": ""},

    # Commodities
    "GC": {"name": "Gold Futures", "type": "commodity", "exchange": "COMEX"},
    "CL": {"name": "Crude Oil WTI", "type": "commodity", "exchange": "NYMEX"},

    # Crypto
    "BTC/USD": {"name": "Bitcoin", "type": "crypto", "exchange": ""},
    "ETH/USD": {"name": "Ethereum", "type": "crypto", "exchange": ""},
}


def _get_severity(pct_change: float, instrument_type: str) -> str:
    """Determine severity based on price change magnitude."""
    abs_pct = abs(pct_change)

    if instrument_type == "crypto":
        # Crypto is more volatile, higher thresholds
        if abs_pct > 10.0:
            return "significant"
        elif abs_pct > 5.0:
            return "notable"
        return "routine"
    elif instrument_type == "index":
        if abs_pct > 3.0:
            return "critical"
        elif abs_pct > 1.5:
            return "significant"
        elif abs_pct > 0.5:
            return "notable"
        return "routine"
    else:
        if abs_pct > 5.0:
            return "significant"
        elif abs_pct > 2.0:
            return "notable"
        return "routine"


async def fetch_twelve_data_events(
    symbols: Optional[List[str]] = None,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Fetch latest price data from Twelve Data.
    Returns list of event dicts for instruments with notable moves.
    """
    if not settings.TWELVE_DATA_API_KEY:
        logger.warning("TWELVE_DATA_API_KEY not set, skipping Twelve Data source")
        return []

    target_symbols = symbols or list(INSTRUMENTS.keys())
    events = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        # Batch quote endpoint (up to 8 symbols)
        for i in range(0, len(target_symbols), 8):
            chunk = target_symbols[i:i + 8]
            symbol_str = ",".join(chunk)

            try:
                params = {
                    "symbol": symbol_str,
                    "apikey": settings.TWELVE_DATA_API_KEY,
                }

                resp = await client.get(f"{TWELVE_DATA_BASE_URL}/quote", params=params)
                resp.raise_for_status()
                data = resp.json()

                # Handle single vs multi-symbol response
                if isinstance(data, dict) and "symbol" in data:
                    # Single symbol response
                    quotes = {data["symbol"]: data}
                elif isinstance(data, dict):
                    quotes = data
                else:
                    continue

                for symbol, quote in quotes.items():
                    try:
                        if not isinstance(quote, dict) or "close" not in quote:
                            continue
                        if quote.get("status") == "error":
                            continue

                        close = float(quote.get("close", 0))
                        previous_close = float(quote.get("previous_close", close))
                        pct_change = float(quote.get("percent_change", 0))
                        volume = quote.get("volume", 0)

                        info = INSTRUMENTS.get(symbol, {
                            "name": symbol,
                            "type": "stock",
                            "exchange": "",
                        })
                        severity = _get_severity(pct_change, info["type"])

                        direction = "up" if pct_change > 0 else "down" if pct_change < 0 else "flat"
                        raw_text = (
                            f"Market Data: {info['name']} ({symbol}) closed at {close:.2f}, "
                            f"{direction} {abs(pct_change):.2f}% from previous close of {previous_close:.2f}."
                        )
                        if volume:
                            raw_text += f" Volume: {volume:,}."

                        timestamp_str = quote.get("datetime", "")
                        try:
                            timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.utcnow()
                        except (ValueError, TypeError):
                            timestamp = datetime.utcnow()

                        events.append({
                            "source": "twelve_data",
                            "source_detail": f"twelvedata.com/{symbol}",
                            "timestamp": timestamp,
                            "domain": "market",
                            "event_type": "market_data",
                            "severity": severity,
                            "entities": [
                                {"name": info["name"], "type": "instrument", "role": "subject"},
                            ],
                            "raw_text": raw_text,
                            "metadata": {
                                "symbol": symbol,
                                "instrument_type": info["type"],
                                "close": close,
                                "previous_close": previous_close,
                                "percent_change": pct_change,
                                "volume": volume,
                                "exchange": info.get("exchange", ""),
                            },
                        })
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Error parsing Twelve Data quote for {symbol}: {e}")
                        continue

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("Twelve Data rate limit hit")
                    break
                logger.error(f"Twelve Data HTTP error: {e.response.status_code}")
            except httpx.TimeoutException:
                logger.warning("Twelve Data timeout")
            except Exception as e:
                logger.error(f"Twelve Data error: {e}")

    logger.info(f"Twelve Data: returning {len(events)} events")
    return events
