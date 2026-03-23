"""
Orphan event detection.

Scan recent events (last 7 days) for "orphans" — events no agent claimed as relevant.
An orphan is an event where no prediction references it
(via ConfidenceTrail.event_ref or Note linkage).
Write orphan events as WeakSignal rows with strength based on event severity.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set

from shared.database import get_db_session
from shared.models import Event, ConfidenceTrail, Note, WeakSignal

logger = logging.getLogger(__name__)

# How far back to scan for orphan events
ORPHAN_LOOKBACK_DAYS = 7

# Severity to signal strength mapping
SEVERITY_STRENGTH_MAP = {
    "critical": "HIGH",
    "significant": "HIGH",
    "notable": "MEDIUM",
    "routine": "LOW",
}


def scan_orphan_events() -> Dict[str, Any]:
    """
    Scan recent events and identify those not referenced by any prediction.
    Write orphan events as weak signals.
    """
    stats = {
        "events_scanned": 0,
        "orphans_found": 0,
        "signals_created": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            cutoff = datetime.utcnow() - timedelta(days=ORPHAN_LOOKBACK_DAYS)

            # Get all recent events
            recent_events = (
                db.query(Event)
                .filter(Event.created_at >= cutoff)
                .all()
            )
            stats["events_scanned"] = len(recent_events)

            if not recent_events:
                logger.info("No recent events to scan for orphans")
                return stats

            # Get all event_refs from confidence trail entries (recent)
            referenced_event_ids: Set[str] = set()

            trail_refs = (
                db.query(ConfidenceTrail.event_ref)
                .filter(
                    ConfidenceTrail.event_ref.isnot(None),
                    ConfidenceTrail.created_at >= cutoff,
                )
                .all()
            )
            for (ref,) in trail_refs:
                if ref:
                    referenced_event_ids.add(ref)

            # Also check notes that might reference events
            # Notes don't have an event_ref column, but text might contain event IDs
            # For now, rely on confidence trail references

            # Find orphans
            orphans = [
                event for event in recent_events
                if event.id not in referenced_event_ids
            ]
            stats["orphans_found"] = len(orphans)

            # Filter to interesting orphans (not routine)
            interesting_orphans = [
                e for e in orphans
                if e.severity in ("critical", "significant", "notable")
            ]

            # Check for duplicates — don't re-report orphans already flagged
            existing_signals = set()
            recent_signals = (
                db.query(WeakSignal)
                .filter(
                    WeakSignal.signal.contains("[ORPHAN]"),
                    WeakSignal.detected_at >= cutoff,
                )
                .all()
            )
            for sig in recent_signals:
                # Extract event ID from signal text if present
                for event in recent_events:
                    if event.id in sig.signal:
                        existing_signals.add(event.id)

            # Create weak signals for new orphans
            for event in interesting_orphans:
                if event.id in existing_signals:
                    continue

                try:
                    _create_orphan_signal(db, event)
                    stats["signals_created"] += 1
                except Exception as e:
                    logger.error(f"Error creating orphan signal for event {event.id}: {e}")
                    stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Orphan scan failed: {e}")
        stats["errors"] += 1

    if stats["orphans_found"] > 0:
        logger.info(
            f"Orphan scan: scanned={stats['events_scanned']}, "
            f"orphans={stats['orphans_found']}, "
            f"signals_created={stats['signals_created']}"
        )

    return stats


def _create_orphan_signal(db, event: Event) -> None:
    """Create a weak signal entry for an orphan event."""
    strength = SEVERITY_STRENGTH_MAP.get(event.severity, "LOW")

    # Build descriptive signal text
    entities_text = ""
    if event.entities:
        entity_names = [
            e.get("name", "unknown") for e in event.entities[:5]
            if isinstance(e, dict)
        ]
        if entity_names:
            entities_text = f" Entities: {', '.join(entity_names)}."

    source_text = f"Source: {event.source} (reliability: {event.source_reliability:.2f})."

    signal_text = (
        f"[ORPHAN] Unclaimed {event.severity or 'unknown'} {event.domain} event: "
        f"{_truncate(event.raw_text or 'No text', 200)}. "
        f"{entities_text} {source_text} "
        f"Event ID: {event.id}. "
        f"No agent referenced this event in any prediction or analysis."
    )

    weak_signal = WeakSignal(
        signal=signal_text[:2000],
        strength=strength,
        status="unattributed",
        detected_at=datetime.utcnow(),
    )
    db.add(weak_signal)

    logger.debug(f"Created orphan signal for event {event.id} ({event.severity})")


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
