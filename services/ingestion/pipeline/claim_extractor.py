"""
Extract factual claims from events. Each claim becomes a row in the claims
table with initial integrity score (from shared/utils.py get_initial_source_integrity).
For significant claims, publish to Redis verification_needed queue.
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from shared.models import Claim
from shared.utils import generate_claim_id, get_initial_source_integrity
from services.ingestion.pipeline.nlp import extract_claims_from_text

logger = logging.getLogger(__name__)

# Integrity threshold above which claims are considered significant
# and should be queued for cross-modal verification
VERIFICATION_THRESHOLD = 0.45

# Source name mappings for integrity scoring
SOURCE_INTEGRITY_MAP = {
    # Wire services
    "reuters": "reuters",
    "ap news": "ap",
    "associated press": "ap",
    # Established newspapers
    "bbc": "established_newspaper",
    "nyt": "established_newspaper",
    "new york times": "established_newspaper",
    "guardian": "established_newspaper",
    "the guardian": "established_newspaper",
    "washington post": "established_newspaper",
    "financial times": "established_newspaper",
    "ft": "established_newspaper",
    "wsj": "established_newspaper",
    "wall street journal": "established_newspaper",
    "al jazeera": "established_newspaper",
    "economist": "established_newspaper",
    # Government / official
    "fred": "government_statement",
    "bls": "government_statement",
    "census": "government_statement",
    "sec": "government_statement",
    "federal reserve": "government_statement",
    "treasury": "government_statement",
    "propublica": "established_newspaper",
    # Think tanks
    "brookings": "think_tank",
    "csis": "think_tank",
    "cfr": "think_tank",
    "rand": "think_tank",
    "chatham house": "think_tank",
    # Data providers (treated as established)
    "gdelt": "regional_outlet",
    "acled": "established_newspaper",
    "polymarket": "verified_social_media",
    "twelve_data": "government_statement",
    "cftc": "government_statement",
    "newsdata": "regional_outlet",
    # RSS aggregated
    "rss": "regional_outlet",
}


def _resolve_source_category(source: str, source_detail: str = "") -> str:
    """Map a source name to its integrity category."""
    source_lower = source.lower()
    detail_lower = (source_detail or "").lower()

    # Check source detail first (more specific, e.g., actual URL domain)
    for key, category in SOURCE_INTEGRITY_MAP.items():
        if key in detail_lower:
            return category

    # Then check source name
    for key, category in SOURCE_INTEGRITY_MAP.items():
        if key in source_lower:
            return category

    return source_lower  # Fall through to get_initial_source_integrity's fuzzy matching


def extract_and_create_claims(
    event: Dict[str, Any],
    db: Session,
    redis_client: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Extract factual claims from an event and persist them.

    For each claim:
    1. Generate a deterministic claim ID
    2. Calculate initial integrity based on source
    3. Create Claim row in database
    4. If integrity >= threshold, publish to verification_needed queue

    Returns list of claim dicts that were created.
    """
    raw_text = event.get("raw_text", "")
    event_id = event.get("id", "")
    source = event.get("source", "unknown")
    source_detail = event.get("source_detail", "")
    severity = event.get("severity", "routine")

    if not raw_text:
        return []

    # Extract claims using NLP
    claim_texts = extract_claims_from_text(raw_text)

    if not claim_texts:
        return []

    # Resolve source category for integrity scoring
    source_category = _resolve_source_category(source, source_detail)
    initial_integrity = get_initial_source_integrity(source_category)

    created_claims = []

    for claim_text in claim_texts:
        try:
            claim_id = generate_claim_id(claim_text, source)

            # Check if claim already exists
            existing = db.query(Claim.id).filter(Claim.id == claim_id).first()
            if existing:
                continue

            claim = Claim(
                id=claim_id,
                event_id=event_id,
                claim_text=claim_text,
                initial_source=source,
                initial_integrity=initial_integrity,
                current_integrity=initial_integrity,
                verification_status="UNVERIFIED",
                corroboration_count=0,
                contradiction_count=0,
                independent_source_count=1,
                cross_modal_sources=None,
                provenance_trace=[{
                    "source": source,
                    "source_detail": source_detail,
                    "timestamp": datetime.utcnow().isoformat(),
                    "integrity": initial_integrity,
                }],
                evidence_chain=None,
                sponsored_flag=False,
            )

            db.add(claim)

            claim_dict = {
                "id": claim_id,
                "event_id": event_id,
                "claim_text": claim_text,
                "source": source,
                "initial_integrity": initial_integrity,
                "severity": severity,
            }
            created_claims.append(claim_dict)

            # Publish significant claims to verification queue
            is_significant = (
                initial_integrity >= VERIFICATION_THRESHOLD
                and severity in ("significant", "critical", "notable")
            )

            if is_significant and redis_client:
                try:
                    verification_payload = json.dumps({
                        "claim_id": claim_id,
                        "claim_text": claim_text,
                        "event_id": event_id,
                        "source": source,
                        "initial_integrity": initial_integrity,
                        "severity": severity,
                        "queued_at": datetime.utcnow().isoformat(),
                    })
                    redis_client.lpush("verification_needed", verification_payload)
                    logger.debug(f"Queued claim {claim_id} for verification")
                except Exception as e:
                    logger.warning(f"Failed to queue claim {claim_id} for verification: {e}")

        except Exception as e:
            logger.warning(f"Error creating claim from event {event_id}: {e}")
            continue

    if created_claims:
        logger.debug(f"Extracted {len(created_claims)} claims from event {event_id}")

    return created_claims


def extract_claims_batch(
    events: List[Dict[str, Any]],
    db: Session,
    redis_client: Optional[Any] = None,
) -> int:
    """
    Extract claims from a batch of events.
    Returns total number of claims created.
    """
    total_claims = 0

    for event in events:
        try:
            claims = extract_and_create_claims(event, db, redis_client)
            total_claims += len(claims)
        except Exception as e:
            logger.warning(f"Error extracting claims from event {event.get('id', '?')}: {e}")
            continue

    logger.info(f"Claim extraction complete: {total_claims} claims from {len(events)} events")
    return total_claims
