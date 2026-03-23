"""
Polymarket API (polymarket.com) — Free.
Prediction market odds — used for calibration comparison,
not as a primary data source for predictions.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

POLYMARKET_API_URL = "https://gamma-api.polymarket.com"


async def fetch_polymarket_events(
    max_results: int = 50,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Fetch active prediction markets from Polymarket.
    Returns list of event dicts with market odds data.
    """
    events = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            # Fetch active markets
            params = {
                "limit": max_results,
                "active": True,
                "closed": False,
                "order": "volume",
                "ascending": False,
            }

            resp = await client.get(f"{POLYMARKET_API_URL}/markets", params=params)
            resp.raise_for_status()
            markets = resp.json()

            if not isinstance(markets, list):
                markets = markets.get("data", []) if isinstance(markets, dict) else []

            for market in markets:
                try:
                    question = market.get("question", "") or market.get("title", "")
                    if not question:
                        continue

                    description = market.get("description", "") or ""
                    slug = market.get("slug", "") or market.get("condition_id", "")
                    volume = market.get("volume", 0) or market.get("volumeNum", 0)
                    liquidity = market.get("liquidity", 0) or market.get("liquidityNum", 0)
                    end_date = market.get("end_date_iso", "") or market.get("endDate", "")

                    # Get outcome prices (probabilities)
                    outcomes = market.get("outcomes", [])
                    outcome_prices = market.get("outcomePrices", [])

                    # Try to parse probability
                    yes_price = None
                    if outcome_prices:
                        try:
                            if isinstance(outcome_prices, str):
                                import json
                                outcome_prices = json.loads(outcome_prices)
                            yes_price = float(outcome_prices[0]) if outcome_prices else None
                        except (ValueError, IndexError, TypeError):
                            pass

                    raw_text = f"Prediction Market: {question}"
                    if yes_price is not None:
                        raw_text += f". Market probability: {yes_price * 100:.1f}%"
                    if volume:
                        try:
                            raw_text += f". Volume: ${float(volume):,.0f}"
                        except (ValueError, TypeError):
                            pass
                    if description:
                        raw_text += f". {description[:200]}"

                    # Parse end date
                    timestamp = datetime.utcnow()
                    resolution_date = None
                    if end_date:
                        try:
                            resolution_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass

                    entities = [{"name": "Polymarket", "type": "organization", "role": "source"}]

                    # Determine domain from question content
                    q_lower = question.lower()
                    domain = "sentiment"
                    if any(w in q_lower for w in ("president", "election", "congress", "vote", "governor")):
                        domain = "political"
                    elif any(w in q_lower for w in ("war", "military", "nato", "invasion", "sanction")):
                        domain = "geopolitical"
                    elif any(w in q_lower for w in ("gdp", "inflation", "fed", "rate", "recession")):
                        domain = "economic"
                    elif any(w in q_lower for w in ("stock", "bitcoin", "price", "market", "s&p")):
                        domain = "market"

                    events.append({
                        "source": "polymarket",
                        "source_detail": f"polymarket.com/event/{slug}" if slug else "polymarket.com",
                        "timestamp": timestamp,
                        "domain": domain,
                        "event_type": "prediction_market",
                        "severity": "routine",
                        "entities": entities,
                        "raw_text": raw_text,
                        "metadata": {
                            "question": question,
                            "yes_price": yes_price,
                            "volume": volume,
                            "liquidity": liquidity,
                            "outcomes": outcomes,
                            "resolution_date": resolution_date.isoformat() if resolution_date else None,
                            "slug": slug,
                        },
                    })
                except Exception as e:
                    logger.debug(f"Error parsing Polymarket market: {e}")
                    continue

        except httpx.HTTPStatusError as e:
            logger.error(f"Polymarket HTTP error: {e.response.status_code}")
        except httpx.TimeoutException:
            logger.warning("Polymarket request timed out")
        except Exception as e:
            logger.error(f"Polymarket fetch error: {e}")

    logger.info(f"Polymarket: returning {len(events)} events")
    return events
