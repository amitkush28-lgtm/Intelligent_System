"""
Statistical anomaly detection.

Use scikit-learn for anomaly detection on data patterns:
- Sudden spike in events from one source
- Unusual domain distribution
- Unexpected entity co-occurrence
- IsolationForest for outlier detection

Write anomalies as WeakSignal rows.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from collections import Counter, defaultdict

import numpy as np

from shared.database import get_db_session
from shared.models import Event, WeakSignal

logger = logging.getLogger(__name__)

# Lookback window for anomaly detection
ANOMALY_LOOKBACK_DAYS = 14

# Minimum events needed for statistical analysis
MIN_EVENTS_FOR_ANALYSIS = 20

# Z-score threshold for source spike detection
SOURCE_SPIKE_ZSCORE = 2.5

# Z-score threshold for domain distribution anomaly
DOMAIN_DIST_ZSCORE = 2.0


def detect_anomalies() -> Dict[str, Any]:
    """
    Run anomaly detection on recent event patterns.
    """
    stats = {
        "events_analyzed": 0,
        "anomalies_detected": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            cutoff = datetime.utcnow() - timedelta(days=ANOMALY_LOOKBACK_DAYS)

            events = (
                db.query(Event)
                .filter(Event.created_at >= cutoff)
                .order_by(Event.created_at)
                .all()
            )
            stats["events_analyzed"] = len(events)

            if len(events) < MIN_EVENTS_FOR_ANALYSIS:
                logger.info(
                    f"Only {len(events)} events — need {MIN_EVENTS_FOR_ANALYSIS} "
                    f"for anomaly detection"
                )
                return stats

            anomalies: List[Dict[str, Any]] = []

            # 1. Source volume spikes
            source_anomalies = _detect_source_spikes(events)
            anomalies.extend(source_anomalies)

            # 2. Domain distribution shifts
            domain_anomalies = _detect_domain_shifts(events)
            anomalies.extend(domain_anomalies)

            # 3. Severity distribution anomalies
            severity_anomalies = _detect_severity_anomalies(events)
            anomalies.extend(severity_anomalies)

            # 4. Entity co-occurrence anomalies
            entity_anomalies = _detect_entity_anomalies(events)
            anomalies.extend(entity_anomalies)

            # 5. IsolationForest on multi-dimensional event features
            isolation_anomalies = _detect_isolation_forest_anomalies(events)
            anomalies.extend(isolation_anomalies)

            # Write anomalies as weak signals
            for anomaly in anomalies:
                try:
                    _create_anomaly_signal(db, anomaly)
                    stats["anomalies_detected"] += 1
                except Exception as e:
                    logger.error(f"Error creating anomaly signal: {e}")
                    stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Anomaly detection failed: {e}")
        stats["errors"] += 1

    if stats["anomalies_detected"] > 0:
        logger.info(
            f"Anomaly detection: analyzed={stats['events_analyzed']}, "
            f"anomalies={stats['anomalies_detected']}"
        )

    return stats


def _detect_source_spikes(events: List) -> List[Dict[str, Any]]:
    """Detect sudden spikes in event volume from individual sources."""
    anomalies = []

    # Count events per source per day
    daily_source_counts: Dict[str, List[int]] = defaultdict(list)
    day_source_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for event in events:
        day_key = event.created_at.strftime("%Y-%m-%d") if event.created_at else "unknown"
        day_source_counts[day_key][event.source] += 1

    # Get all unique sources and days
    all_sources = set()
    for day_counts in day_source_counts.values():
        all_sources.update(day_counts.keys())

    days = sorted(day_source_counts.keys())

    for source in all_sources:
        daily_counts = [day_source_counts[day].get(source, 0) for day in days]

        if len(daily_counts) < 3:
            continue

        arr = np.array(daily_counts, dtype=float)
        mean_val = np.mean(arr)
        std_val = np.std(arr)

        if std_val == 0:
            continue

        # Check if the most recent day is a spike
        latest_count = arr[-1]
        z_score = (latest_count - mean_val) / std_val

        if z_score > SOURCE_SPIKE_ZSCORE and latest_count > 3:
            anomalies.append({
                "type": "source_spike",
                "description": (
                    f"Source '{source}' produced {int(latest_count)} events on {days[-1]}, "
                    f"compared to average of {mean_val:.1f}/day "
                    f"(z-score: {z_score:.1f})"
                ),
                "strength": "HIGH" if z_score > 4 else "MEDIUM",
                "detail": {
                    "source": source,
                    "count": int(latest_count),
                    "mean": float(mean_val),
                    "z_score": float(z_score),
                },
            })

    return anomalies


def _detect_domain_shifts(events: List) -> List[Dict[str, Any]]:
    """Detect unusual shifts in domain distribution."""
    anomalies = []

    if len(events) < MIN_EVENTS_FOR_ANALYSIS:
        return anomalies

    # Split events into two halves (earlier vs recent)
    midpoint = len(events) // 2
    earlier = events[:midpoint]
    recent = events[midpoint:]

    # Count domain distribution
    earlier_domains = Counter(e.domain for e in earlier if e.domain)
    recent_domains = Counter(e.domain for e in recent if e.domain)

    all_domains = set(earlier_domains.keys()) | set(recent_domains.keys())
    earlier_total = sum(earlier_domains.values()) or 1
    recent_total = sum(recent_domains.values()) or 1

    for domain in all_domains:
        earlier_pct = earlier_domains.get(domain, 0) / earlier_total
        recent_pct = recent_domains.get(domain, 0) / recent_total

        shift = recent_pct - earlier_pct

        if abs(shift) > 0.15:  # >15 percentage point shift
            direction = "increase" if shift > 0 else "decrease"
            anomalies.append({
                "type": "domain_shift",
                "description": (
                    f"Domain '{domain}' shows {abs(shift):.0%} {direction} in event share "
                    f"(from {earlier_pct:.0%} to {recent_pct:.0%})"
                ),
                "strength": "MEDIUM" if abs(shift) < 0.25 else "HIGH",
                "detail": {
                    "domain": domain,
                    "earlier_pct": float(earlier_pct),
                    "recent_pct": float(recent_pct),
                    "shift": float(shift),
                },
            })

    return anomalies


def _detect_severity_anomalies(events: List) -> List[Dict[str, Any]]:
    """Detect unusual spikes in high-severity events."""
    anomalies = []

    # Count severity per day
    day_severity: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        day_key = event.created_at.strftime("%Y-%m-%d") if event.created_at else "unknown"
        severity = event.severity or "routine"
        day_severity[day_key][severity] += 1

    days = sorted(day_severity.keys())
    if len(days) < 3:
        return anomalies

    # Track critical + significant per day
    high_severity_counts = [
        day_severity[day].get("critical", 0) + day_severity[day].get("significant", 0)
        for day in days
    ]

    arr = np.array(high_severity_counts, dtype=float)
    mean_val = np.mean(arr)
    std_val = np.std(arr)

    if std_val > 0:
        latest = arr[-1]
        z_score = (latest - mean_val) / std_val

        if z_score > DOMAIN_DIST_ZSCORE and latest > 2:
            anomalies.append({
                "type": "severity_spike",
                "description": (
                    f"{int(latest)} critical/significant events on {days[-1]}, "
                    f"compared to average of {mean_val:.1f}/day "
                    f"(z-score: {z_score:.1f})"
                ),
                "strength": "HIGH",
                "detail": {
                    "count": int(latest),
                    "mean": float(mean_val),
                    "z_score": float(z_score),
                },
            })

    return anomalies


def _detect_entity_anomalies(events: List) -> List[Dict[str, Any]]:
    """Detect unusual entity co-occurrences in recent events."""
    anomalies = []

    # Extract entity pairs from events
    pair_counts: Counter = Counter()
    entity_event_counts: Counter = Counter()

    for event in events:
        if not event.entities:
            continue

        entities = []
        for ent in event.entities:
            if isinstance(ent, dict) and "name" in ent:
                entities.append(ent["name"])

        # Count individual entities
        for ent in entities:
            entity_event_counts[ent] += 1

        # Count co-occurrence pairs
        for i, e1 in enumerate(entities):
            for e2 in entities[i + 1:]:
                pair = tuple(sorted([e1, e2]))
                pair_counts[pair] += 1

    # Find unexpected co-occurrences
    # Entities that appear together more often than expected by chance
    total_events = len(events) or 1

    for pair, count in pair_counts.most_common(20):
        e1, e2 = pair
        e1_freq = entity_event_counts.get(e1, 0) / total_events
        e2_freq = entity_event_counts.get(e2, 0) / total_events
        expected = e1_freq * e2_freq * total_events
        observed = count

        if expected > 0 and observed > expected * 3 and count >= 3:
            anomalies.append({
                "type": "entity_cooccurrence",
                "description": (
                    f"Unusual co-occurrence: '{e1}' and '{e2}' appear together "
                    f"{count} times (expected ~{expected:.1f})"
                ),
                "strength": "MEDIUM",
                "detail": {
                    "entity_1": e1,
                    "entity_2": e2,
                    "observed": count,
                    "expected": float(expected),
                },
            })

    return anomalies[:5]  # Limit to top 5


def _detect_isolation_forest_anomalies(events: List) -> List[Dict[str, Any]]:
    """
    Use IsolationForest on daily event feature vectors.
    Features: total events, domain counts, severity counts, avg integrity.
    """
    anomalies = []

    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        logger.warning("scikit-learn not available for IsolationForest")
        return anomalies

    # Build daily feature vectors
    daily_features: Dict[str, Dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    domains = ["geopolitical", "economic", "market", "political", "sentiment"]
    severities = ["routine", "notable", "significant", "critical"]

    for event in events:
        day_key = event.created_at.strftime("%Y-%m-%d") if event.created_at else "unknown"
        daily_features[day_key]["total"] += 1
        domain = event.domain or "unknown"
        daily_features[day_key][f"domain_{domain}"] += 1
        severity = event.severity or "routine"
        daily_features[day_key][f"severity_{severity}"] += 1
        if event.integrity_score is not None:
            daily_features[day_key]["integrity_sum"] += event.integrity_score
            daily_features[day_key]["integrity_count"] += 1

    days = sorted(daily_features.keys())
    if len(days) < 7:
        return anomalies

    # Build feature matrix
    feature_names = (
        ["total"]
        + [f"domain_{d}" for d in domains]
        + [f"severity_{s}" for s in severities]
        + ["avg_integrity"]
    )

    X = []
    for day in days:
        f = daily_features[day]
        integrity_count = f.get("integrity_count", 0)
        avg_integrity = (
            f.get("integrity_sum", 0) / integrity_count
            if integrity_count > 0
            else 0.5
        )

        row = (
            [f.get("total", 0)]
            + [f.get(f"domain_{d}", 0) for d in domains]
            + [f.get(f"severity_{s}", 0) for s in severities]
            + [avg_integrity]
        )
        X.append(row)

    X = np.array(X)

    if X.shape[0] < 7:
        return anomalies

    try:
        clf = IsolationForest(
            contamination=0.1,
            random_state=42,
            n_estimators=100,
        )
        predictions = clf.fit_predict(X)
        scores = clf.decision_function(X)

        # Check if the most recent days are anomalous
        for i in range(max(0, len(days) - 3), len(days)):
            if predictions[i] == -1:  # Anomaly
                day = days[i]
                f = daily_features[day]
                anomalies.append({
                    "type": "isolation_forest",
                    "description": (
                        f"Day {day} flagged as statistically anomalous "
                        f"(score: {scores[i]:.3f}). "
                        f"Total events: {int(f.get('total', 0))}, "
                        f"critical: {int(f.get('severity_critical', 0))}, "
                        f"significant: {int(f.get('severity_significant', 0))}"
                    ),
                    "strength": "MEDIUM",
                    "detail": {
                        "day": day,
                        "anomaly_score": float(scores[i]),
                        "total_events": int(f.get("total", 0)),
                    },
                })

    except Exception as e:
        logger.error(f"IsolationForest failed: {e}")

    return anomalies


def _create_anomaly_signal(db, anomaly: Dict[str, Any]) -> None:
    """Write an anomaly as a WeakSignal row."""
    signal_text = (
        f"[ANOMALY:{anomaly['type'].upper()}] {anomaly['description']}"
    )

    weak_signal = WeakSignal(
        signal=signal_text[:2000],
        strength=anomaly.get("strength", "MEDIUM"),
        status="unattributed",
        detected_at=datetime.utcnow(),
    )
    db.add(weak_signal)
