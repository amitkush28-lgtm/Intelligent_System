"""
Data Ingestion Worker — pulls from data sources, runs NLP pipeline, writes to Postgres.
Triggered by Railway cron every 4 hours (0 */4 * * *).

Orchestration flow:
1. Pull from all data sources (GDELT, FRED, RSS, NewsData, etc.)
2. NLP pipeline: entity extraction (spaCy), sentiment scoring
3. Event classification: domain + severity
4. Dedup incoming events against existing events in Postgres
5. Initial claim extraction — every factual claim becomes a row in claims table
6. Write structured events to Postgres
7. Publish ingestion_complete to Redis to trigger agent analysis
"""

import asyncio
import json
import logging
import sys
import time
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional

import redis

from shared.config import get_settings
from shared.database import get_db_session
from shared.models import Event
from shared.utils import setup_logging, get_initial_source_integrity

# Source imports — Phase 1 (Day 1)
from services.ingestion.sources.gdelt import fetch_gdelt_events
from services.ingestion.sources.fred import fetch_fred_events
from services.ingestion.sources.rss_feeds import fetch_rss_events
from services.ingestion.sources.newsdata import fetch_newsdata_events
from services.ingestion.sources.twelve_data import fetch_twelve_data_events
from services.ingestion.sources.congress_gov import fetch_congress_events
from services.ingestion.sources.acled import fetch_acled_events
from services.ingestion.sources.polymarket import fetch_polymarket_events
from services.ingestion.sources.cftc import fetch_cftc_events

# Source imports — Phase 2
from services.ingestion.sources.sec_edgar import fetch_sec_edgar_events
from services.ingestion.sources.bls import fetch_bls_events
from services.ingestion.sources.world_bank import fetch_world_bank_events
from services.ingestion.sources.ofac import fetch_ofac_events

# Pipeline imports
from services.ingestion.pipeline.nlp import enrich_event_entities
from services.ingestion.pipeline.classifier import classify_events_batch
from services.ingestion.pipeline.dedup import deduplicate_batch
from services.ingestion.pipeline.claim_extractor import extract_claims_batch

logger = setup_logging("ingestion")
settings = get_settings()


def _get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client for queue publishing."""
    try:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()
        return client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}. Queue publishing disabled.")
        return None


def _get_source_reliability(source: str, source_detail: str = "") -> float:
    """Compute source reliability for an event based on its origin."""
    source_map = {
        "gdelt": "regional_outlet",
        "fred": "government_statement",
        "rss": "established_newspaper",
        "newsdata": "regional_outlet",
        "twelve_data": "government_statement",
        "congress_gov": "government_statement",
        "acled": "established_newspaper",
        "polymarket": "verified_social_media",
        "cftc": "government_statement",
        "sec_edgar": "government_statement",
        "bls": "government_statement",
        "world_bank": "government_statement",
        "ofac": "government_statement",
    }

    category = source_map.get(source, source)

    # Try to infer from source_detail (URL) for more specific scoring
    detail_lower = (source_detail or "").lower()
    if "reuters" in detail_lower:
        return get_initial_source_integrity("reuters")
    elif "apnews" in detail_lower or "ap.org" in detail_lower:
        return get_initial_source_integrity("ap")
    elif any(n in detail_lower for n in ["bbc", "nytimes", "guardian", "ft.com", "wsj.com"]):
        return get_initial_source_integrity("established_newspaper")

    return get_initial_source_integrity(category)


async def _fetch_all_sources() -> List[Dict[str, Any]]:
    """
    Fetch events from all configured data sources.
    Each source is run independently with error isolation.
    """
    all_events: List[Dict[str, Any]] = []
    source_stats: Dict[str, int] = {}

    sources = [
        # Phase 1 — Critical
        ("GDELT", fetch_gdelt_events),
        ("FRED", fetch_fred_events),
        ("RSS", fetch_rss_events),
        ("NewsData", fetch_newsdata_events),
        ("TwelveData", fetch_twelve_data_events),
        ("Congress", fetch_congress_events),
        ("ACLED", fetch_acled_events),
        ("Polymarket", fetch_polymarket_events),
        ("CFTC", fetch_cftc_events),
        # Phase 2 — New sources
        ("SEC_EDGAR", fetch_sec_edgar_events),
        ("BLS", fetch_bls_events),
        ("WorldBank", fetch_world_bank_events),
        ("OFAC", fetch_ofac_events),
    ]

    for source_name, fetcher in sources:
        try:
            logger.info(f"Fetching from {source_name}...")
            start = time.time()
            events = await fetcher()
            elapsed = time.time() - start
            source_stats[source_name] = len(events)
            all_events.extend(events)
            logger.info(f"{source_name}: {len(events)} events in {elapsed:.1f}s")
        except Exception as e:
            logger.error(f"{source_name} failed: {e}")
            logger.debug(traceback.format_exc())
            source_stats[source_name] = 0

    logger.info(f"Source fetch complete: {len(all_events)} total events. Stats: {source_stats}")
    return all_events


def _persist_events(events: List[Dict[str, Any]], db) -> int:
    """Write events to Postgres Event table. Returns count persisted."""
    persisted = 0

    for event in events:
        try:
            event_id = event.get("id", "")
            if not event_id:
                continue

            source_reliability = _get_source_reliability(
                event.get("source", ""),
                event.get("source_detail", ""),
            )

            db_event = Event(
                id=event_id,
                source=event.get("source", "unknown"),
                source_reliability=source_reliability,
                timestamp=event.get("timestamp", datetime.utcnow()),
                domain=event.get("domain", "geopolitical"),
                event_type=event.get("event_type"),
                severity=event.get("severity"),
                entities=event.get("entities"),
                claims=None,
                raw_text=event.get("raw_text"),
                integrity_score=source_reliability,
            )

            db.add(db_event)
            persisted += 1

        except Exception as e:
            logger.warning(f"Error persisting event {event.get('id', '?')}: {e}")
            continue

    return persisted


def _publish_completion(
    redis_client: Optional[redis.Redis],
    stats: Dict[str, Any],
) -> None:
    """Publish ingestion_complete to Redis to trigger agent analysis."""
    if not redis_client:
        logger.warning("Redis not available, skipping ingestion_complete publish")
        return

    try:
        payload = json.dumps({
            "event": "ingestion_complete",
            "timestamp": datetime.utcnow().isoformat(),
            "stats": stats,
        })
        redis_client.lpush("ingestion_complete", payload)
        logger.info("Published ingestion_complete to Redis")
    except Exception as e:
        logger.error(f"Failed to publish ingestion_complete: {e}")


async def run_async():
    """Main async orchestration loop."""
    run_start = time.time()
    logger.info("=" * 60)
    logger.info("Ingestion worker starting")
    logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    stats = {
        "run_start": datetime.utcnow().isoformat(),
        "sources_fetched": 0,
        "raw_events": 0,
        "after_nlp": 0,
        "after_dedup": 0,
        "duplicates_removed": 0,
        "events_persisted": 0,
        "claims_extracted": 0,
        "errors": [],
    }

    redis_client = _get_redis_client()

    try:
        # Step 1: Fetch from all data sources
        logger.info("STEP 1: Fetching from data sources...")
        raw_events = await _fetch_all_sources()
        stats["raw_events"] = len(raw_events)

        if not raw_events:
            logger.warning("No events fetched from any source")
            stats["errors"].append("No events fetched")
            _publish_completion(redis_client, stats)
            return stats

        # Step 2: NLP enrichment (entity extraction + sentiment)
        logger.info("STEP 2: NLP enrichment...")
        for event in raw_events:
            try:
                enrich_event_entities(event)
            except Exception as e:
                logger.debug(f"NLP enrichment error: {e}")
        stats["after_nlp"] = len(raw_events)

        # Step 3: Classification (domain + severity)
        logger.info("STEP 3: Event classification...")
        classify_events_batch(raw_events)

        # Step 4: Dedup + persist + extract claims (needs DB session)
        logger.info("STEP 4: Dedup, persist, extract claims...")
        with get_db_session() as db:
            unique_events, dup_count = deduplicate_batch(raw_events, db)
            stats["after_dedup"] = len(unique_events)
            stats["duplicates_removed"] = dup_count

            persisted = _persist_events(unique_events, db)
            stats["events_persisted"] = persisted

            db.flush()

            claims_count = extract_claims_batch(unique_events, db, redis_client)
            stats["claims_extracted"] = claims_count

            db.commit()
            logger.info(f"Database commit: {persisted} events, {claims_count} claims")

        # Step 5: Publish completion
        logger.info("STEP 5: Publishing ingestion_complete...")
        _publish_completion(redis_client, stats)

    except Exception as e:
        logger.error(f"Ingestion run failed: {e}")
        logger.error(traceback.format_exc())
        stats["errors"].append(str(e))
    finally:
        if redis_client:
            try:
                redis_client.close()
            except Exception:
                pass

    elapsed = time.time() - run_start
    stats["run_duration_seconds"] = round(elapsed, 1)
    stats["run_end"] = datetime.utcnow().isoformat()

    logger.info("=" * 60)
    logger.info(f"Ingestion complete in {elapsed:.1f}s")
    logger.info(f"  Raw events:     {stats['raw_events']}")
    logger.info(f"  After dedup:    {stats['after_dedup']} ({stats['duplicates_removed']} duplicates)")
    logger.info(f"  Persisted:      {stats['events_persisted']}")
    logger.info(f"  Claims:         {stats['claims_extracted']}")
    if stats["errors"]:
        logger.warning(f"  Errors:         {len(stats['errors'])}")
    logger.info("=" * 60)

    return stats


def run():
    """Synchronous entry point for Railway cron."""
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
