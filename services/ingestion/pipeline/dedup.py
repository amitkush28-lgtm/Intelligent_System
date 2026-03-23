"""
Deduplication against existing events in Postgres.
Uses event ID hashing (shared/utils.py generate_event_id) plus
similarity checking on raw_text for near-duplicates.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Set, Tuple

from sqlalchemy.orm import Session

from shared.models import Event
from shared.utils import generate_event_id

logger = logging.getLogger(__name__)

# Similarity threshold for near-duplicate detection (Jaccard on word sets)
SIMILARITY_THRESHOLD = 0.70

# Time window for near-duplicate checks (hours)
DEDUP_WINDOW_HOURS = 24


def _text_to_word_set(text: str) -> Set[str]:
    """Convert text to a set of lowered, stripped words for comparison."""
    if not text:
        return set()
    # Remove common filler and very short words
    words = set()
    for w in text.lower().split():
        w = w.strip(".,;:!?\"'()-|/")
        if len(w) > 2:
            words.add(w)
    return words


def _jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Compute Jaccard similarity between two word sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def compute_event_id(event: Dict[str, Any]) -> str:
    """Compute a deterministic event ID using shared utility."""
    source = event.get("source", "unknown")
    raw_text = event.get("raw_text", "")
    timestamp = event.get("timestamp", datetime.utcnow())
    return generate_event_id(source, raw_text, timestamp)


def deduplicate_batch(
    events: List[Dict[str, Any]],
    db: Session,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Deduplicate a batch of events against:
    1. Each other (within-batch dedup by ID)
    2. Existing events in Postgres (by ID match)
    3. Near-duplicate text similarity check within time window

    Returns:
        (unique_events, duplicate_count)
    """
    if not events:
        return [], 0

    total_input = len(events)
    duplicate_count = 0

    # Step 1: Assign IDs and within-batch dedup
    seen_ids: Set[str] = set()
    id_deduped = []

    for event in events:
        event_id = compute_event_id(event)
        event["id"] = event_id

        if event_id in seen_ids:
            duplicate_count += 1
            continue
        seen_ids.add(event_id)
        id_deduped.append(event)

    logger.debug(f"Within-batch dedup: {total_input} -> {len(id_deduped)} events")

    # Step 2: Check against Postgres for existing IDs
    if id_deduped:
        batch_ids = [e["id"] for e in id_deduped]
        # Query in chunks to avoid very large IN clauses
        existing_ids: Set[str] = set()
        chunk_size = 500
        for i in range(0, len(batch_ids), chunk_size):
            chunk = batch_ids[i:i + chunk_size]
            try:
                rows = db.query(Event.id).filter(Event.id.in_(chunk)).all()
                existing_ids.update(r[0] for r in rows)
            except Exception as e:
                logger.error(f"Error checking existing events: {e}")

        db_deduped = []
        for event in id_deduped:
            if event["id"] in existing_ids:
                duplicate_count += 1
                continue
            db_deduped.append(event)

        logger.debug(f"DB dedup: {len(id_deduped)} -> {len(db_deduped)} events ({len(existing_ids)} existing)")
    else:
        db_deduped = id_deduped

    # Step 3: Near-duplicate text similarity within time window
    if db_deduped:
        cutoff = datetime.utcnow() - timedelta(hours=DEDUP_WINDOW_HOURS)
        try:
            recent_events = (
                db.query(Event.raw_text, Event.source)
                .filter(Event.created_at >= cutoff)
                .limit(2000)
                .all()
            )
            recent_word_sets = [
                (_text_to_word_set(r.raw_text), r.source)
                for r in recent_events
                if r.raw_text
            ]
        except Exception as e:
            logger.error(f"Error fetching recent events for similarity check: {e}")
            recent_word_sets = []

        similarity_deduped = []
        for event in db_deduped:
            event_words = _text_to_word_set(event.get("raw_text", ""))
            is_near_dup = False

            # Only check similarity for events from the same source
            event_source = event.get("source", "")
            for recent_words, recent_source in recent_word_sets:
                if event_source == recent_source:
                    similarity = _jaccard_similarity(event_words, recent_words)
                    if similarity >= SIMILARITY_THRESHOLD:
                        is_near_dup = True
                        break

            # Also check within the current batch
            if not is_near_dup:
                for prev_event in similarity_deduped:
                    if prev_event.get("source") == event_source:
                        prev_words = _text_to_word_set(prev_event.get("raw_text", ""))
                        if _jaccard_similarity(event_words, prev_words) >= SIMILARITY_THRESHOLD:
                            is_near_dup = True
                            break

            if is_near_dup:
                duplicate_count += 1
            else:
                similarity_deduped.append(event)

        logger.debug(f"Similarity dedup: {len(db_deduped)} -> {len(similarity_deduped)} events")
        final_events = similarity_deduped
    else:
        final_events = db_deduped

    logger.info(
        f"Dedup complete: {total_input} input -> {len(final_events)} unique "
        f"({duplicate_count} duplicates removed)"
    )
    return final_events, duplicate_count
