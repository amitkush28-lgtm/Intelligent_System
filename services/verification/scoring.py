"""
Bayesian Integrity Scoring Engine.

Implements the core scoring logic for cross-modal claim verification.
Each independent cross-modal corroboration multiplies confidence upward;
contradictions multiply downward. Uses Bayes' theorem with likelihood
ratios calibrated per modality reliability.

Key invariant: only INDEPENDENT evidence counts. If two news articles
cite the same wire report, that's one source — check provenance_trace
before counting corroborations.
"""

import logging
import math
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Modality reliability weights — how much we trust each cross-modal source
# Higher = stronger signal when it corroborates or contradicts
MODALITY_RELIABILITY = {
    "satellite": 0.85,       # Sentinel-2 imagery is objective
    "shipping": 0.80,        # AIS ship tracking is hard to fake
    "flights": 0.80,         # ADS-B flight data is objective
    "trade": 0.75,           # UN Comtrade official stats
    "financial": 0.70,       # World Bank indicators
    "diplomatic": 0.70,      # UN voting records
    "nightlights": 0.75,     # NASA satellite data is objective
    "sponsored_check": 0.60, # LLM-based detection has noise
    "web_search": 0.55,      # Web search corroboration (noisy)
}

# Likelihood ratios for Bayesian updates
# P(evidence | claim_true) / P(evidence | claim_false)
# Corroboration: ratio > 1 increases posterior
# Contradiction: ratio < 1 decreases posterior
CORROBORATION_LR = {
    "satellite": 4.0,
    "shipping": 3.5,
    "flights": 3.5,
    "trade": 3.0,
    "financial": 2.5,
    "diplomatic": 2.5,
    "nightlights": 3.0,
    "sponsored_check": 2.0,
    "web_search": 1.8,
}

CONTRADICTION_LR = {
    "satellite": 0.20,
    "shipping": 0.25,
    "flights": 0.25,
    "trade": 0.30,
    "financial": 0.35,
    "diplomatic": 0.35,
    "nightlights": 0.30,
    "sponsored_check": 0.50,
    "web_search": 0.55,
}

# Integrity floor and ceiling — never go to 0 or 1
INTEGRITY_FLOOR = 0.02
INTEGRITY_CEILING = 0.98

# Sponsored content penalty
SPONSORED_PENALTY = 0.60  # Multiply current integrity by this


def bayesian_update(
    prior: float,
    likelihood_ratio: float,
) -> float:
    """
    Apply single Bayesian update.

    posterior = (prior * LR) / (prior * LR + (1 - prior))

    Args:
        prior: Current integrity score (0-1)
        likelihood_ratio: P(evidence|true) / P(evidence|false)
            > 1 for corroboration, < 1 for contradiction

    Returns:
        Updated integrity score, clamped to [FLOOR, CEILING]
    """
    if prior <= 0:
        prior = INTEGRITY_FLOOR
    if prior >= 1:
        prior = INTEGRITY_CEILING

    numerator = prior * likelihood_ratio
    denominator = numerator + (1.0 - prior)

    if denominator == 0:
        return prior

    posterior = numerator / denominator
    return max(INTEGRITY_FLOOR, min(INTEGRITY_CEILING, posterior))


def check_provenance_independence(
    new_source: str,
    new_modality: str,
    provenance_trace: Optional[List[Dict[str, Any]]],
    cross_modal_sources: Optional[List[Dict[str, Any]]],
) -> bool:
    """
    Check whether a new evidence source is independent of existing evidence.

    Independence rules:
    - Different modalities are always independent (satellite vs trade data)
    - Same modality: check if they share a common upstream source
    - News articles citing the same wire report are NOT independent

    Args:
        new_source: Source identifier for new evidence
        new_modality: Modality type of new evidence
        provenance_trace: Existing provenance chain for the claim
        cross_modal_sources: Already-applied cross-modal checks

    Returns:
        True if the new evidence is independent
    """
    if not provenance_trace and not cross_modal_sources:
        return True

    # Different modalities are always independent
    existing_modalities = set()
    if cross_modal_sources:
        for entry in cross_modal_sources:
            existing_modalities.add(entry.get("modality", ""))

    if new_modality not in existing_modalities:
        return True

    # Same modality — check for shared upstream sources
    new_source_lower = new_source.lower()
    if cross_modal_sources:
        for entry in cross_modal_sources:
            existing_source = entry.get("source", "").lower()
            # If source names overlap significantly, likely dependent
            if existing_source and (
                existing_source in new_source_lower
                or new_source_lower in existing_source
            ):
                logger.debug(
                    f"Evidence dependency detected: {new_source} ~ {entry.get('source')}"
                )
                return False

    # Check provenance trace for shared wire service origins
    if provenance_trace:
        provenance_sources = {
            p.get("source", "").lower() for p in provenance_trace
        }
        wire_services = {"reuters", "ap", "associated press", "afp"}
        new_wire = any(ws in new_source_lower for ws in wire_services)

        if new_wire:
            for ps in provenance_sources:
                if any(ws in ps for ws in wire_services):
                    if any(
                        ws in ps and ws in new_source_lower
                        for ws in wire_services
                    ):
                        logger.debug(
                            f"Wire service dependency: {new_source} shares origin with provenance"
                        )
                        return False

    return True


def compute_updated_integrity(
    current_integrity: float,
    verification_results: List[Dict[str, Any]],
    provenance_trace: Optional[List[Dict[str, Any]]] = None,
    existing_cross_modal: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[float, int, int, List[Dict[str, Any]]]:
    """
    Apply Bayesian updates from multiple cross-modal verification results.

    Only independent evidence sources contribute to the update.
    Each result dict should have:
        - modality: str (satellite, trade, financial, etc.)
        - source: str (specific data source name)
        - corroborates: bool (True = supports claim, False = contradicts)
        - confidence: float (0-1, how confident the modality check is)
        - finding: str (human-readable description)

    Args:
        current_integrity: Starting integrity score
        verification_results: List of cross-modal check results
        provenance_trace: Existing provenance for independence checks
        existing_cross_modal: Already-applied cross-modal sources

    Returns:
        Tuple of (new_integrity, corroboration_count, contradiction_count, applied_results)
    """
    integrity = current_integrity
    corroboration_count = 0
    contradiction_count = 0
    applied_results = []

    for result in verification_results:
        modality = result.get("modality", "unknown")
        source = result.get("source", "unknown")
        corroborates = result.get("corroborates", False)
        confidence = result.get("confidence", 0.5)
        finding = result.get("finding", "")

        # Check independence
        if not check_provenance_independence(
            source, modality, provenance_trace, existing_cross_modal
        ):
            logger.info(
                f"Skipping dependent evidence: {modality}/{source}"
            )
            continue

        # Get base likelihood ratio for this modality
        if corroborates:
            base_lr = CORROBORATION_LR.get(modality, 2.0)
        else:
            base_lr = CONTRADICTION_LR.get(modality, 0.40)

        # Scale likelihood ratio by check confidence
        # High confidence → use full LR; low confidence → LR closer to 1 (neutral)
        if corroborates:
            lr = 1.0 + (base_lr - 1.0) * confidence
        else:
            lr = 1.0 - (1.0 - base_lr) * confidence

        # Apply Bayesian update
        old_integrity = integrity
        integrity = bayesian_update(integrity, lr)

        if corroborates:
            corroboration_count += 1
        else:
            contradiction_count += 1

        applied_result = {
            "modality": modality,
            "source": source,
            "corroborates": corroborates,
            "confidence": round(confidence, 3),
            "finding": finding,
            "likelihood_ratio": round(lr, 3),
            "integrity_before": round(old_integrity, 4),
            "integrity_after": round(integrity, 4),
            "timestamp": datetime.utcnow().isoformat(),
        }
        applied_results.append(applied_result)

        logger.debug(
            f"Bayesian update [{modality}]: {old_integrity:.4f} -> {integrity:.4f} "
            f"(LR={lr:.3f}, {'corroborates' if corroborates else 'contradicts'})"
        )

    return (
        round(integrity, 4),
        corroboration_count,
        contradiction_count,
        applied_results,
    )


def apply_sponsored_penalty(
    current_integrity: float,
    sponsored_confidence: float,
) -> float:
    """
    Apply integrity penalty when sponsored content is detected.

    The penalty scales with detection confidence:
    - High confidence (0.9+): full penalty (multiply by SPONSORED_PENALTY)
    - Medium confidence (0.5-0.9): partial penalty
    - Low confidence (<0.5): no penalty applied

    Args:
        current_integrity: Current claim integrity
        sponsored_confidence: Confidence that content is sponsored (0-1)

    Returns:
        Updated integrity score
    """
    if sponsored_confidence < 0.5:
        return current_integrity

    # Scale penalty by confidence
    penalty_factor = SPONSORED_PENALTY + (1.0 - SPONSORED_PENALTY) * (1.0 - sponsored_confidence)
    new_integrity = current_integrity * penalty_factor

    logger.info(
        f"Sponsored penalty applied: {current_integrity:.4f} -> {new_integrity:.4f} "
        f"(confidence={sponsored_confidence:.2f}, factor={penalty_factor:.3f})"
    )

    return max(INTEGRITY_FLOOR, round(new_integrity, 4))


def determine_verification_status(
    integrity: float,
    corroboration_count: int,
    contradiction_count: int,
    sponsored_flag: bool = False,
) -> str:
    """
    Determine overall verification status from scoring results.

    Statuses:
    - CORROBORATED: integrity >= 0.65 AND at least 1 corroboration
    - CONTRADICTED: integrity < 0.35 OR contradiction_count > corroboration_count
    - LOW_CONFIDENCE: sponsored OR integrity < 0.45
    - PARTIALLY_VERIFIED: some evidence but inconclusive
    - UNVERIFIED: no cross-modal evidence found
    """
    if corroboration_count == 0 and contradiction_count == 0:
        return "UNVERIFIED"

    if sponsored_flag:
        return "LOW_CONFIDENCE"

    if contradiction_count > corroboration_count and integrity < 0.40:
        return "CONTRADICTED"

    if integrity >= 0.65 and corroboration_count >= 1:
        return "CORROBORATED"

    if integrity < 0.35:
        return "CONTRADICTED"

    if integrity < 0.45:
        return "LOW_CONFIDENCE"

    return "PARTIALLY_VERIFIED"
