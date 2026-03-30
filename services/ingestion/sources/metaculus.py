"""
Metaculus + Manifold Markets APIs — Free.
Calibrated crowd predictions for cross-referencing against system predictions.
Deeper coverage of geopolitical, scientific, and long-term questions than Polymarket.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

METACULUS_API_URL = "https://www.metaculus.com/api2"
MANIFOLD_API_URL = "https://api.manifold.markets/v0"

# Minimum forecaster count for Metaculus questions
MIN_FORECASTERS = 30

# Minimum liquidity for Manifold markets
MIN_MANIFOLD_LIQUIDITY = 100


def _classify_prediction_domain(title: str) -> str:
    """Classify a prediction question into an intelligence domain."""
    t = title.lower()

    if any(w in t for w in ("war", "military", "nato", "invasion", "conflict", "nuclear", "sanctions", "china", "russia", "iran", "taiwan")):
        return "geopolitical"
    if any(w in t for w in ("president", "election", "congress", "vote", "governor", "legislation", "supreme court", "parliament")):
        return "political"
    if any(w in t for w in ("gdp", "inflation", "fed", "rate", "recession", "unemployment", "trade", "tariff", "debt")):
        return "economic"
    if any(w in t for w in ("stock", "bitcoin", "crypto", "s&p", "market", "price", "gold", "oil", "commodity")):
        return "market"
    if any(w in t for w in ("ai", "artificial intelligence", "quantum", "technology", "spacex", "fusion", "robot")):
        return "technology"
    if any(w in t for w in ("pandemic", "virus", "vaccine", "disease", "health", "mortality", "who")):
        return "health"

    return "sentiment"


def _determine_severity_from_probability_change(
    current_prob: float,
    previous_prob: Optional[float] = None,
) -> str:
    """Determine event severity based on probability and recent changes."""
    if previous_prob is not None:
        change = abs(current_prob - previous_prob)
        if change > 0.15:
            return "high"
        if change > 0.08:
            return "elevated"

    # Extreme probabilities in either direction are notable
    if current_prob > 0.85 or current_prob < 0.15:
        return "elevated"

    return "routine"


async def _fetch_metaculus_questions(
    client: httpx.AsyncClient,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch active questions from Metaculus."""
    events = []

    try:
        params = {
            "limit": limit,
            "status": "open",
            "order_by": "-activity",
            "forecast_type": "binary",
            "has_group": "false",
        }

        resp = await client.get(f"{METACULUS_API_URL}/questions/", params=params)
        resp.raise_for_status()
        data = resp.json()

        questions = data.get("results", [])
        if not questions and isinstance(data, list):
            questions = data

        for q in questions:
            try:
                title = q.get("title", "") or q.get("title_short", "")
                if not title:
                    continue

                # Get forecast data
                prediction = q.get("community_prediction", {})
                if isinstance(prediction, dict):
                    probability = prediction.get("full", {}).get("q2")
                    if probability is None:
                        probability = prediction.get("q2")
                elif isinstance(prediction, (int, float)):
                    probability = float(prediction)
                else:
                    probability = None

                if probability is None:
                    continue

                forecaster_count = q.get("number_of_forecasters", 0) or 0
                if forecaster_count < MIN_FORECASTERS:
                    continue

                question_id = q.get("id", "")
                description = q.get("description", "")[:300] if q.get("description") else ""
                resolution_criteria = q.get("resolution_criteria", "")[:200] if q.get("resolution_criteria") else ""
                close_time = q.get("close_time", "") or q.get("scheduled_close_time", "")

                domain = _classify_prediction_domain(title)
                severity = _determine_severity_from_probability_change(probability)

                raw_text = (
                    f"Metaculus Prediction: {title}. "
                    f"Community probability: {probability * 100:.1f}% "
                    f"({forecaster_count} forecasters). "
                )
                if description:
                    raw_text += f"{description[:150]}"

                events.append({
                    "id": f"metaculus-{question_id}",
                    "source": "metaculus",
                    "source_detail": f"metaculus.com/questions/{question_id}",
                    "timestamp": datetime.utcnow(),
                    "domain": domain,
                    "event_type": "prediction_market",
                    "severity": severity,
                    "entities": [
                        {"name": "Metaculus", "type": "organization", "role": "source"},
                    ],
                    "raw_text": raw_text,
                    "metadata": {
                        "platform": "metaculus",
                        "question_id": question_id,
                        "title": title,
                        "probability": round(probability, 4),
                        "forecaster_count": forecaster_count,
                        "close_time": close_time,
                        "resolution_criteria": resolution_criteria[:200],
                    },
                })

            except Exception as e:
                logger.debug(f"Error parsing Metaculus question: {e}")
                continue

    except httpx.HTTPStatusError as e:
        logger.warning(f"Metaculus HTTP error: {e.response.status_code}")
    except httpx.TimeoutException:
        logger.warning("Metaculus request timed out")
    except Exception as e:
        logger.error(f"Metaculus fetch error: {e}")

    return events


async def _fetch_manifold_markets(
    client: httpx.AsyncClient,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch active markets from Manifold Markets."""
    events = []

    try:
        params = {
            "limit": limit,
            "sort": "liquidity",
            "order": "desc",
        }

        resp = await client.get(f"{MANIFOLD_API_URL}/markets", params=params)
        resp.raise_for_status()
        markets = resp.json()

        if not isinstance(markets, list):
            markets = markets.get("data", []) if isinstance(markets, dict) else []

        for market in markets:
            try:
                question = market.get("question", "") or market.get("title", "")
                if not question:
                    continue

                probability = market.get("probability")
                if probability is None:
                    continue

                # Filter out very low liquidity / engagement
                liquidity = market.get("totalLiquidity", 0) or 0
                trader_count = market.get("uniqueBettorCount", 0) or 0

                if liquidity < MIN_MANIFOLD_LIQUIDITY:
                    continue

                market_id = market.get("id", "")
                slug = market.get("slug", "")
                volume = market.get("volume", 0) or 0
                close_time = market.get("closeTime")

                domain = _classify_prediction_domain(question)
                severity = _determine_severity_from_probability_change(probability)

                raw_text = (
                    f"Manifold Markets: {question}. "
                    f"Market probability: {probability * 100:.1f}% "
                    f"({trader_count} traders, ${volume:,.0f} volume). "
                )

                events.append({
                    "id": f"manifold-{market_id}",
                    "source": "manifold",
                    "source_detail": f"manifold.markets/{slug}" if slug else f"manifold.markets",
                    "timestamp": datetime.utcnow(),
                    "domain": domain,
                    "event_type": "prediction_market",
                    "severity": severity,
                    "entities": [
                        {"name": "Manifold Markets", "type": "organization", "role": "source"},
                    ],
                    "raw_text": raw_text,
                    "metadata": {
                        "platform": "manifold",
                        "market_id": market_id,
                        "question": question,
                        "probability": round(probability, 4),
                        "liquidity": liquidity,
                        "volume": volume,
                        "trader_count": trader_count,
                        "close_time": close_time,
                        "slug": slug,
                    },
                })

            except Exception as e:
                logger.debug(f"Error parsing Manifold market: {e}")
                continue

    except httpx.HTTPStatusError as e:
        logger.warning(f"Manifold HTTP error: {e.response.status_code}")
    except httpx.TimeoutException:
        logger.warning("Manifold request timed out")
    except Exception as e:
        logger.error(f"Manifold fetch error: {e}")

    return events


async def fetch_metaculus_events(
    max_results: int = 50,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Fetch prediction market data from Metaculus and Manifold Markets.

    Returns combined events from both platforms for cross-referencing
    against the system's own predictions.
    """
    events = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # Fetch from both platforms
        metaculus_events = await _fetch_metaculus_questions(client, limit=max_results)
        manifold_events = await _fetch_manifold_markets(client, limit=max_results)

        events.extend(metaculus_events)
        events.extend(manifold_events)

    logger.info(
        f"Prediction Markets: returning {len(events)} events "
        f"(Metaculus: {len(metaculus_events)}, Manifold: {len(manifold_events)})"
    )
    return events
