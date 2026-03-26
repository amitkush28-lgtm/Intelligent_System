"""
Twelve Data API (twelvedata.com) — 800 requests/day free tier.
Stock/forex/crypto prices. Pulls major indices (S&P 500, NASDAQ, VIX)
and tracked tickers.

CRITICAL: Always generates events for ALL instruments, not just notable moves.
Agents need current prices to avoid making predictions based on stale training data.
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
    "SPX": {"name": "S&P 500", "type": "index"},
    "IXIC": {"name": "NASDAQ Composite", "type": "index"},
    "DJI": {"name": "Dow Jones Industrial", "type": "index"},
    "VIX": {"name": "CBOE Volatility Index", "type": "index"},

    # Key stocks
    "AAPL": {"name": "Apple", "type": "stock"},
    "MSFT": {"name": "Microsoft", "type": "stock"},
    "NVDA": {"name": "NVIDIA", "type": "stock"},
    "GOOGL": {"name": "Alphabet", "type": "stock"},
    "AMZN": {"name": "Amazon", "type": "stock"},
    "TSLA": {"name": "Tesla", "type": "stock"},

    # Forex
    "EUR/USD": {"name": "Euro/Dollar", "type": "forex"},
    "GBP/USD": {"name": "Pound/Dollar", "type": "forex"},
    "USD/JPY": {"name": "Dollar/Yen", "type": "forex"},
    "USD/CNY": {"name": "Dollar/Yuan", "type": "forex"},

    # Commodities
    "XAU/USD": {"name": "Gold Spot", "type": "commodity"},
    "CL": {"name": "Crude Oil WTI", "type": "commodity"},

    # Crypto
    "BTC/USD": {"name": "Bitcoin", "type": "crypto"},
    "ETH/USD": {"name": "Ethereum", "type": "crypto"},
}


def _get_severity(pct_change: float, instrument_type: str) -> str:
    """Determine severity based on price change magnitude."""
    abs_pct = abs(pct_change)

    if instrument_type == "crypto":
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
    Returns events for ALL instruments so agents know current prices.
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
                if isinstance(data, dict) and "symbol" in data and "close" in data:
                    quotes = {data["symbol"]: data}
                elif isinstance(data, dict):
                    quotes = data
                else:
                    logger.warning(f"Unexpected Twelve Data response type: {type(data)}")
                    continue

                for symbol, quote in quotes.items():
                    try:
                        if not isinstance(quote, dict):
                            continue
                        if quote.get("status") == "error" or quote.get("code"):
                            logger.debug(f"TwelveData error for {symbol}: {quote.get('message', 'unknown')}")
                            continue

                        # Parse prices — handle string values
                        close = quote.get("close")
                        previous_close = quote.get("previous_close")
                        pct_change = quote.get("percent_change")

                        if close is None:
                            continue

                        try:
                            close = float(close)
                        except (ValueError, TypeError):
                            continue

                        try:
                            previous_close = float(previous_close) if previous_close else close
                        except (ValueError, TypeError):
                            previous_close = close

                        try:
                            pct_change = float(pct_change) if pct_change else 0.0
                        except (ValueError, TypeError):
                            if previous_close and previous_close != 0:
                                pct_change = ((close - previous_close) / previous_close) * 100
                            else:
                                pct_change = 0.0

                        volume = quote.get("volume", 0)
                        try:
                            volume = int(volume) if volume else 0
                        except (ValueError, TypeError):
                            volume = 0

                        info = INSTRUMENTS.get(symbol, {"name": symbol, "type": "stock"})
                        severity = _get_severity(pct_change, info["type"])

                        direction = "up" if pct_change > 0 else "down" if pct_change < 0 else "flat"

                        # Format price based on type
                        if info["type"] == "forex":
                            price_str = f"{close:.4f}"
                            prev_str = f"{previous_close:.4f}"
                        elif close > 1000:
                            price_str = f"{close:,.2f}"
                            prev_str = f"{previous_close:,.2f}"
                        else:
                            price_str = f"{close:.2f}"
                            prev_str = f"{previous_close:.2f}"

                        raw_text = (
                            f"CURRENT MARKET PRICE: {info['name']} ({symbol}) at {price_str}, "
                            f"{direction} {abs(pct_change):.2f}% from previous {prev_str}."
                        )
                        if volume:
                            raw_text += f" Volume: {volume:,}."

                        timestamp_str = quote.get("datetime", "")
                        try:
                            timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.utcnow()
                        except (ValueError, TypeError):
                            timestamp = datetime.utcnow()

                        # Generate unique ID based on date to avoid dedup issues
                        date_str = datetime.utcnow().strftime("%Y%m%d")
                        event_id = f"td-{symbol.replace('/', '-')}-{date_str}"

                        events.append({
                            "id": event_id,
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
                            },
                        })

                        logger.debug(f"  {symbol}: {price_str} ({pct_change:+.2f}%)")

                    except Exception as e:
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
