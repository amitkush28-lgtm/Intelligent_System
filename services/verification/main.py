"""
Verification Engine — Cross-modal claim verification pipeline.

Consumes claims from Redis verification_needed queue (BRPOP), runs them
through cross-modal verification modalities, applies Bayesian integrity
scoring, checks for sponsored content, and updates Postgres.

Also runs an hourly cron to re-check UNVERIFIED claims that may have
new data available.

Queue payload format (from ingestion worker):
{
    "claim_id": str,
    "claim_text": str,
    "event_id": str,
    "source": str,
    "initial_integrity": float,
    "severity": str,
    "queued_at": str (ISO datetime)
}
"""

import asyncio
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import redis
from sqlalchemy import and_

from shared.config import get_settings
from shared.database import get_db_session
from shared.models import Claim, Event, SourceReliability
from shared.utils import setup_logging

from services.verification.scoring import (
    compute_updated_integrity,
    apply_sponsored_penalty,
    determine_verification_status,
)
from services.verification.sponsored_detector import (
    detect_sponsored_content,
    should_flag_sponsored,
)
from services.verification.modalities import (
    MODALITY_REGISTRY,
    get_modalities_for_domain,
)

logger = setup_logging("verification")
settings = get_settings()

# Configuration
QUEUE_NAME = "verification_needed"
BRPOP_TIMEOUT = 10  # seconds to wait for queue items
MAX_CLAIMS_PER_RUN = 200  # safety limit per cron run
RECHECK_WINDOW_HOURS = 48  # re-check unverified claims within this window
RECHECK_BATCH_SIZE = 50  # max claims to re-check per cron cycle


def _get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client with connection handling."""
    try:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
        )
        client.ping()
        return client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        return None


async def verify_single_claim(
    claim_data: Dict[str, Any],
    db_session=None,
) -> Dict[str, Any]:
    """
    Run the full verification pipeline for a single claim.

    Pipeline:
    1. Load claim and associated event from DB
    2. Determine applicable modalities based on domain
    3. Run each modality check (with error isolation)
    4. Run sponsored content detection
    5. Apply Bayesian scoring
    6. Update claim in Postgres
    7. Update source reliability

    Returns stats dict about what was done.
    """
    claim_id = claim_data.get("claim_id", "")
    claim_text = claim_data.get("claim_text", "")
    event_id = claim_data.get("event_id", "")
    source = claim_data.get("source", "")
    initial_integrity = claim_data.get("initial_integrity", 0.5)
    severity = claim_data.get("severity", "routine")

    stats = {
        "claim_id": claim_id,
        "modalities_checked": 0,
        "corroborations": 0,
        "contradictions": 0,
        "sponsored_check": False,
        "error": None,
    }

    logger.info(f"Verifying claim {claim_id}: {claim_text[:80]}...")

    try:
        if db_session:
            return await _run_verification(
                claim_id, claim_text, event_id, source,
                initial_integrity, severity, db_session, stats,
            )
        else:
            with get_db_session() as db:
                return await _run_verification(
                    claim_id, claim_text, event_id, source,
                    initial_integrity, severity, db, stats,
                )
    except Exception as e:
        logger.error(f"Verification failed for {claim_id}: {e}")
        logger.debug(traceback.format_exc())
        stats["error"] = str(e)[:200]
        return stats


async def _run_verification(
    claim_id: str,
    claim_text: str,
    event_id: str,
    source: str,
    initial_integrity: float,
    severity: str,
    db,
    stats: Dict[str, Any],
) -> Dict[str, Any]:
    """Core verification logic with DB session."""

    # Step 1: Load claim from DB
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        logger.warning(f"Claim {claim_id} not found in database — creating record")
        claim = Claim(
            id=claim_id,
            event_id=event_id if event_id else None,
            claim_text=claim_text,
            initial_source=source,
            initial_integrity=initial_integrity,
            current_integrity=initial_integrity,
            verification_status="UNVERIFIED",
            corroboration_count=0,
            contradiction_count=0,
            independent_source_count=1,
        )
        db.add(claim)
        db.flush()

    # Step 2: Get event for domain info and entities
    domain = "geopolitical"
    entities = []
    event = None

    if claim.event_id:
        event = db.query(Event).filter(Event.id == claim.event_id).first()
        if event:
            domain = event.domain or "geopolitical"
            entities = event.entities or []

    # Step 3: Run applicable modality checks
    modality_names = get_modalities_for_domain(domain)
    verification_results = []

    for modality_name in modality_names:
        verifier = MODALITY_REGISTRY.get(modality_name)
        if not verifier:
            continue

        try:
            result = await verifier(
                claim_text=claim_text,
                entities=entities,
                domain=domain,
                severity=severity,
                source=source,
            )
            if result:
                verification_results.append(result)
                stats["modalities_checked"] += 1
                logger.debug(
                    f"  {modality_name}: {'corroborates' if result.get('corroborates') else 'contradicts'} "
                    f"(confidence={result.get('confidence', 0):.2f})"
                )
        except Exception as e:
            logger.warning(f"Modality {modality_name} failed for {claim_id}: {e}")
            continue

    # Step 4: Sponsored content detection
    sponsored_result = None
    raw_text = ""
    if event and event.raw_text:
        raw_text = event.raw_text

    if raw_text and severity in ("notable", "significant", "critical"):
        try:
            sponsored_result = await detect_sponsored_content(
                text=raw_text,
                source=source,
                claim_text=claim_text,
            )
            stats["sponsored_check"] = True
        except Exception as e:
            logger.warning(f"Sponsored detection failed for {claim_id}: {e}")

    # Step 5: Bayesian scoring
    current_integrity = claim.current_integrity or initial_integrity
    provenance = claim.provenance_trace or []
    existing_cross_modal = claim.cross_modal_sources or []

    new_integrity, corr_count, contra_count, applied_results = compute_updated_integrity(
        current_integrity=current_integrity,
        verification_results=verification_results,
        provenance_trace=provenance,
        existing_cross_modal=existing_cross_modal,
    )

    stats["corroborations"] = corr_count
    stats["contradictions"] = contra_count

    # Apply sponsored penalty if detected
    sponsored_flag = False
    sponsored_reasoning = None

    if sponsored_result:
        flag, reason = should_flag_sponsored(sponsored_result)
        if flag:
            sponsored_flag = True
            sponsored_reasoning = reason
            new_integrity = apply_sponsored_penalty(
                new_integrity,
                sponsored_result.get("confidence", 0.0),
            )

    # Step 6: Determine verification status
    total_corr = (claim.corroboration_count or 0) + corr_count
    total_contra = (claim.contradiction_count or 0) + contra_count
    verification_status = determine_verification_status(
        new_integrity, total_corr, total_contra, sponsored_flag,
    )

    # Step 7: Update claim in Postgres
    updated_cross_modal = list(existing_cross_modal)
    for ar in applied_results:
        updated_cross_modal.append({
            "modality": ar["modality"],
            "source": ar["source"],
            "finding": ar["finding"],
            "corroborates": ar["corroborates"],
            "confidence": ar["confidence"],
            "timestamp": ar["timestamp"],
        })

    existing_evidence = claim.evidence_chain or []
    updated_evidence = list(existing_evidence)
    for ar in applied_results:
        updated_evidence.append({
            "source": ar["source"],
            "integrity": ar["confidence"],
            "corroborates": ar["corroborates"],
            "detail": ar["finding"],
            "timestamp": ar["timestamp"],
        })

    claim.current_integrity = new_integrity
    claim.verification_status = verification_status
    claim.cross_modal_sources = updated_cross_modal
    claim.evidence_chain = updated_evidence
    claim.corroboration_count = total_corr
    claim.contradiction_count = total_contra
    claim.sponsored_flag = sponsored_flag
    if sponsored_reasoning:
        claim.sponsored_reasoning = sponsored_reasoning
    if verification_status != "UNVERIFIED":
        claim.verified_at = datetime.utcnow()

    db.flush()

    # Step 8: Update source reliability
    _update_source_reliability(db, source, domain, verification_status)

    logger.info(
        f"Claim {claim_id} verified: status={verification_status}, "
        f"integrity={new_integrity:.4f}, "
        f"+{corr_count}/-{contra_count} modalities, "
        f"sponsored={sponsored_flag}"
    )

    stats["new_integrity"] = new_integrity
    stats["verification_status"] = verification_status
    return stats


def _update_source_reliability(
    db,
    source_name: str,
    domain: str,
    verification_status: str,
) -> None:
    """Update the SourceReliability table based on verification outcome."""
    if not source_name or verification_status == "UNVERIFIED":
        return

    try:
        sr = db.query(SourceReliability).filter(
            and_(
                SourceReliability.source_name == source_name,
                SourceReliability.domain == domain,
            )
        ).first()

        if not sr:
            sr = SourceReliability(
                source_name=source_name,
                domain=domain,
                total_claims=0,
                verified_accurate=0,
                verified_inaccurate=0,
                reliability_score=0.50,
            )
            db.add(sr)

        sr.total_claims = (sr.total_claims or 0) + 1

        if verification_status in ("CORROBORATED", "PARTIALLY_VERIFIED"):
            sr.verified_accurate = (sr.verified_accurate or 0) + 1
        elif verification_status in ("CONTRADICTED",):
            sr.verified_inaccurate = (sr.verified_inaccurate or 0) + 1

        # Recalculate reliability score
        total = sr.verified_accurate + sr.verified_inaccurate
        if total > 0:
            sr.reliability_score = round(sr.verified_accurate / total, 4)

        sr.last_updated = datetime.utcnow()
        db.flush()

    except Exception as e:
        logger.warning(f"Failed to update source reliability for {source_name}: {e}")


async def _process_queue(redis_client: redis.Redis) -> Dict[str, Any]:
    """
    Process claims from the Redis verification_needed queue.
    Uses BRPOP for blocking reads. Processes until queue is empty
    or MAX_CLAIMS_PER_RUN is reached.
    """
    stats = {
        "claims_processed": 0,
        "corroborations_total": 0,
        "contradictions_total": 0,
        "errors": 0,
        "statuses": {},
    }

    for _ in range(MAX_CLAIMS_PER_RUN):
        try:
            result = redis_client.brpop(QUEUE_NAME, timeout=BRPOP_TIMEOUT)
            if not result:
                logger.info("Queue empty, stopping")
                break

            _, payload = result
            claim_data = json.loads(payload)

            claim_stats = await verify_single_claim(claim_data)
            stats["claims_processed"] += 1
            stats["corroborations_total"] += claim_stats.get("corroborations", 0)
            stats["contradictions_total"] += claim_stats.get("contradictions", 0)

            status = claim_stats.get("verification_status", "unknown")
            stats["statuses"][status] = stats["statuses"].get(status, 0) + 1

            if claim_stats.get("error"):
                stats["errors"] += 1

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in queue: {e}")
            stats["errors"] += 1
        except Exception as e:
            logger.error(f"Error processing queue item: {e}")
            logger.debug(traceback.format_exc())
            stats["errors"] += 1

    return stats


async def _recheck_unverified_claims() -> Dict[str, Any]:
    """
    Hourly cron: re-check claims that are still UNVERIFIED.
    Picks up claims that had no applicable modalities initially but
    might now have data available.
    """
    stats = {"rechecked": 0, "updated": 0, "errors": 0}

    try:
        cutoff = datetime.utcnow() - timedelta(hours=RECHECK_WINDOW_HOURS)

        with get_db_session() as db:
            unverified = (
                db.query(Claim)
                .filter(
                    and_(
                        Claim.verification_status == "UNVERIFIED",
                        Claim.created_at >= cutoff,
                    )
                )
                .order_by(Claim.created_at.desc())
                .limit(RECHECK_BATCH_SIZE)
                .all()
            )

            if not unverified:
                logger.info("No unverified claims to recheck")
                return stats

            logger.info(f"Re-checking {len(unverified)} unverified claims")

            for claim in unverified:
                try:
                    claim_data = {
                        "claim_id": claim.id,
                        "claim_text": claim.claim_text,
                        "event_id": claim.event_id or "",
                        "source": claim.initial_source,
                        "initial_integrity": claim.initial_integrity,
                        "severity": "notable",
                    }

                    result = await verify_single_claim(claim_data, db_session=db)
                    stats["rechecked"] += 1

                    if result.get("verification_status") != "UNVERIFIED":
                        stats["updated"] += 1

                except Exception as e:
                    logger.warning(f"Recheck failed for {claim.id}: {e}")
                    stats["errors"] += 1

            db.commit()

    except Exception as e:
        logger.error(f"Recheck batch failed: {e}")
        stats["errors"] += 1

    return stats


async def _publish_completion(
    redis_client: Optional[redis.Redis],
    stats: Dict[str, Any],
) -> None:
    """Publish verification_complete to Redis."""
    if not redis_client:
        return

    try:
        payload = json.dumps({
            "event": "verification_complete",
            "timestamp": datetime.utcnow().isoformat(),
            "stats": stats,
        })
        redis_client.lpush("verification_complete", payload)
        logger.info("Published verification_complete to Redis")
    except Exception as e:
        logger.warning(f"Failed to publish verification_complete: {e}")


async def run_async():
    """Main async entry point for the verification engine."""
    run_start = time.time()
    logger.info("=" * 60)
    logger.info("Verification Engine starting")
    logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    combined_stats = {
        "run_start": datetime.utcnow().isoformat(),
        "queue_stats": {},
        "recheck_stats": {},
        "errors": [],
    }

    redis_client = _get_redis_client()

    try:
        # Phase 1: Process queue
        if redis_client:
            logger.info("PHASE 1: Processing verification queue...")
            queue_stats = await _process_queue(redis_client)
            combined_stats["queue_stats"] = queue_stats
            logger.info(
                f"Queue processing: {queue_stats['claims_processed']} claims, "
                f"{queue_stats['corroborations_total']} corroborations, "
                f"{queue_stats['contradictions_total']} contradictions, "
                f"{queue_stats['errors']} errors"
            )
        else:
            logger.warning("Redis unavailable — skipping queue processing")
            combined_stats["errors"].append("Redis unavailable")

        # Phase 2: Re-check unverified claims
        logger.info("PHASE 2: Re-checking unverified claims...")
        recheck_stats = await _recheck_unverified_claims()
        combined_stats["recheck_stats"] = recheck_stats
        logger.info(
            f"Recheck: {recheck_stats['rechecked']} checked, "
            f"{recheck_stats['updated']} updated"
        )

        # Phase 3: Publish completion
        await _publish_completion(redis_client, combined_stats)

    except Exception as e:
        logger.error(f"Verification run failed: {e}")
        logger.error(traceback.format_exc())
        combined_stats["errors"].append(str(e))
    finally:
        if redis_client:
            try:
                redis_client.close()
            except Exception:
                pass

    elapsed = time.time() - run_start
    combined_stats["run_duration_seconds"] = round(elapsed, 1)
    combined_stats["run_end"] = datetime.utcnow().isoformat()

    logger.info("=" * 60)
    logger.info(f"Verification Engine complete in {elapsed:.1f}s")
    q = combined_stats.get("queue_stats", {})
    r = combined_stats.get("recheck_stats", {})
    logger.info(f"  Queue claims:   {q.get('claims_processed', 0)}")
    logger.info(f"  Rechecked:      {r.get('rechecked', 0)} ({r.get('updated', 0)} updated)")
    if combined_stats["errors"]:
        logger.warning(f"  Errors:         {len(combined_stats['errors'])}")
    logger.info("=" * 60)

    return combined_stats


def run():
    """Synchronous entry point for Railway cron."""
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
