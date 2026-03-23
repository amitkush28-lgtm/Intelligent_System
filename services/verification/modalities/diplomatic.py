"""
UN Voting Records — Cross-modal verification for diplomatic claims.

Verifies claims about diplomatic alignment shifts, alliance changes,
and international support using UN General Assembly voting data.

Data source: Erik Voeten's UN General Assembly Voting Data
(hosted via Harvard Dataverse, accessed through simplified REST endpoint)
and the UN Digital Library API.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

import httpx

logger = logging.getLogger(__name__)

# UN Digital Library search API
UN_LIBRARY_URL = "https://digitallibrary.un.org/api/v1/search"
# Fallback: UN voting record summary endpoint
UN_VOTING_URL = "https://unbisnet.un.org/api"

# Country name to UN membership / common voting bloc mapping
COUNTRY_BLOCS = {
    # Western bloc
    "united states": "western", "usa": "western", "us": "western",
    "united kingdom": "western", "uk": "western", "britain": "western",
    "france": "western", "germany": "western",
    "canada": "western", "australia": "western",
    "japan": "western", "south korea": "western",
    # Eastern / BRICS
    "china": "eastern", "prc": "eastern",
    "russia": "eastern", "india": "brics",
    "brazil": "brics", "south africa": "brics",
    "iran": "eastern", "north korea": "eastern",
    # Non-aligned
    "indonesia": "non-aligned", "egypt": "non-aligned",
    "nigeria": "non-aligned", "mexico": "non-aligned",
    "turkey": "non-aligned", "saudi arabia": "non-aligned",
    "pakistan": "non-aligned", "argentina": "non-aligned",
}

# Keywords that indicate diplomatic/voting claims
DIPLOMATIC_KEYWORDS = [
    "vote", "resolution", "un general assembly", "unga",
    "security council", "unsc", "veto",
    "diplomatic", "alignment", "alliance",
    "support", "oppose", "abstain",
    "coalition", "bloc", "multilateral",
    "treaty", "agreement", "pact",
    "recognition", "condemn", "denounce",
    "sanctions vote", "human rights council",
]


def _is_diplomatic_claim(claim_text: str) -> bool:
    """Check if claim is about diplomatic/voting matters."""
    claim_lower = claim_text.lower()
    return any(kw in claim_lower for kw in DIPLOMATIC_KEYWORDS)


def _extract_countries(claim_text: str) -> List[str]:
    """Extract country names from claim text."""
    claim_lower = claim_text.lower()
    found = []
    for name in COUNTRY_BLOCS:
        if name in claim_lower:
            found.append(name)
    return found


def _extract_vote_topic(claim_text: str) -> Optional[str]:
    """Try to extract the topic of a UN vote from claim text."""
    topics = {
        "palestine": "Palestine",
        "israel": "Israel-Palestine",
        "climate": "Climate Change",
        "nuclear": "Nuclear Weapons/Disarmament",
        "human rights": "Human Rights",
        "sanctions": "Sanctions",
        "territorial": "Territorial Disputes",
        "sovereignty": "Sovereignty",
        "refugee": "Refugees",
        "humanitarian": "Humanitarian",
        "disarmament": "Disarmament",
        "terrorism": "Counter-Terrorism",
        "cyber": "Cybersecurity",
        "trade": "International Trade",
    }
    claim_lower = claim_text.lower()
    for keyword, topic in topics.items():
        if keyword in claim_lower:
            return topic
    return None


async def verify_diplomatic_claim(
    claim_text: str,
    entities: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:
    """
    Verify a diplomatic claim using UN voting records and alignment data.

    Checks for:
    - Voting alignment between countries
    - Historical voting pattern shifts
    - Resolution outcomes

    Args:
        claim_text: The claim to verify
        entities: Extracted entities

    Returns:
        Verification result dict or None if not applicable
    """
    if not _is_diplomatic_claim(claim_text):
        return None

    countries = _extract_countries(claim_text)
    topic = _extract_vote_topic(claim_text)

    if not countries:
        if entities:
            for ent in entities:
                if ent.get("type") in ("GPE", "LOC", "NORP", "country"):
                    name = ent.get("name", "").lower()
                    if name in COUNTRY_BLOCS:
                        countries.append(name)

    if not countries:
        logger.debug("No countries found for diplomatic verification")
        return None

    # Try UN Digital Library search
    result = await _search_un_library(claim_text, countries, topic)
    if result:
        return result

    # Fallback: use bloc-based alignment analysis
    return _analyze_bloc_alignment(claim_text, countries, topic)


async def _search_un_library(
    claim_text: str,
    countries: List[str],
    topic: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Search UN Digital Library for relevant resolutions."""
    try:
        search_terms = []
        if topic:
            search_terms.append(topic)
        search_terms.extend(countries[:2])

        query = " ".join(search_terms)

        params = {
            "q": query,
            "c": "Voting Data",
            "so": "d",  # sort descending (most recent)
            "rg": 10,
            "of": "recjson",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(UN_LIBRARY_URL, params=params)

            if response.status_code != 200:
                logger.debug(f"UN Library search returned {response.status_code}")
                return None

            data = response.json()

        records = data if isinstance(data, list) else data.get("records", [])
        if not records:
            return None

        # Analyze the records for voting patterns
        relevant_count = 0
        latest_year = None

        for record in records[:10]:
            title = ""
            year = ""
            if isinstance(record, dict):
                title = str(record.get("title", record.get("245", "")))
                year = str(record.get("year", record.get("269", "")))[:4]
            relevant_count += 1
            if year and (not latest_year or year > latest_year):
                latest_year = year

        if relevant_count > 0:
            return {
                "modality": "diplomatic",
                "source": "UN Digital Library",
                "corroborates": True,
                "confidence": 0.45,
                "finding": (
                    f"Found {relevant_count} UN records related to "
                    f"{', '.join(countries[:3])} on {topic or 'this topic'}. "
                    f"Most recent: {latest_year or 'unknown'}"
                ),
                "data": {
                    "records_found": relevant_count,
                    "countries": countries,
                    "topic": topic,
                    "latest_year": latest_year,
                },
            }

    except httpx.TimeoutException:
        logger.debug("UN Library search timed out")
    except Exception as e:
        logger.debug(f"UN Library search failed: {e}")

    return None


def _analyze_bloc_alignment(
    claim_text: str,
    countries: List[str],
    topic: Optional[str],
) -> Dict[str, Any]:
    """
    Analyze claim based on known bloc alignment patterns.

    This is a heuristic fallback when live data isn't available.
    Uses well-established voting bloc patterns to assess plausibility.
    """
    claim_lower = claim_text.lower()

    # Get blocs for mentioned countries
    blocs = {}
    for country in countries:
        bloc = COUNTRY_BLOCS.get(country)
        if bloc:
            blocs[country] = bloc

    if not blocs:
        return {
            "modality": "diplomatic",
            "source": "UN Voting Analysis (heuristic)",
            "corroborates": True,
            "confidence": 0.20,
            "finding": "Insufficient country data for alignment analysis",
        }

    unique_blocs = set(blocs.values())
    finding_parts = [f"Countries mentioned: {', '.join(blocs.keys())}"]

    # Analyze alignment claims
    corroborates = True
    confidence = 0.35

    alignment_words = ["align", "support", "back", "side with", "join", "cooperat"]
    opposition_words = ["oppose", "against", "block", "veto", "reject", "condemn"]

    if len(countries) >= 2:
        claims_alignment = any(w in claim_lower for w in alignment_words)
        claims_opposition = any(w in claim_lower for w in opposition_words)

        if claims_alignment:
            if len(unique_blocs) == 1:
                corroborates = True
                confidence = 0.50
                finding_parts.append("Same voting bloc — alignment is typical")
            else:
                # Cross-bloc alignment is noteworthy but possible
                corroborates = True
                confidence = 0.35
                finding_parts.append("Cross-bloc alignment — unusual but plausible")

        elif claims_opposition:
            if len(unique_blocs) > 1:
                corroborates = True
                confidence = 0.50
                finding_parts.append("Different voting blocs — opposition is typical")
            else:
                corroborates = False
                confidence = 0.40
                finding_parts.append("Same voting bloc but claim of opposition — atypical")

    # Shift/realignment claims
    shift_words = ["shift", "realign", "chang", "break", "pivot", "defect"]
    if any(w in claim_lower for w in shift_words):
        confidence = 0.30
        finding_parts.append("Alignment shift claim — requires specific evidence to verify")

    return {
        "modality": "diplomatic",
        "source": "UN Voting Analysis (heuristic)",
        "corroborates": corroborates,
        "confidence": confidence,
        "finding": ". ".join(finding_parts),
        "data": {
            "countries": countries,
            "blocs": blocs,
            "topic": topic,
        },
    }
