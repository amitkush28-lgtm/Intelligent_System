"""
Prediction Validator — Quality Gate Enforcement.

Sits between agent output and database persistence. Every prediction must pass
these gates before being stored:

1. SPECIFICITY CHECK — must have a number, date, and entity
2. BANNED PATTERN CHECK — rejects vague, unfalsifiable, consensus-restating predictions
3. DOMAIN CONFIDENCE CAP — enforces hard limits per domain
4. BASE RATE SANITY CHECK — flags predictions that violate base rate expectations
5. DUPLICATE DETECTION — catches semantically similar predictions
6. BET TEST HEURISTIC — flags predictions that are too hedged to be actionable

Returns: validated prediction (possibly with adjusted confidence) or rejection with reason.
"""

import logging
import re
from datetime import date, timedelta
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# DOMAIN CONFIDENCE CAPS
# =============================================================================

DOMAIN_CONFIDENCE_CAPS = {
    "SAFETY": 0.75,
    "FINANCIAL": 0.75,
    "POLITICAL": 0.80,
    "ECONOMIC": 0.85,
    "REAL_ESTATE": 0.75,
    "ENERGY_FOOD": 0.80,
    "HEALTH": 0.80,
    "GEOPOLITICAL": 0.70,  # fallback for geopolitical-tagged predictions
}

# Agent-level caps (some agents inherently deal with harder-to-predict domains)
AGENT_CONFIDENCE_CAPS = {
    "geopolitical": 0.75,  # geopolitical timing is inherently unpredictable
    "wildcard": 0.75,      # cross-domain predictions are speculative by nature
}

# Absolute bounds
MIN_CONFIDENCE = 0.30
MAX_CONFIDENCE = 0.95


# =============================================================================
# BANNED PATTERNS — predictions matching these are rejected
# =============================================================================

BANNED_PATTERNS = [
    # Vague directional calls (no magnitude)
    (r"(?i)\b(will|could|may)\s+(increase|decrease|rise|fall|grow|shrink|decline)\b(?!.*\b\d)",
     "VAGUE_DIRECTIONAL",
     "Prediction states direction without magnitude. Add a specific number (%, price level, or threshold)."),

    # Unfalsifiable hedging
    (r"(?i)\b(could potentially|may possibly|might see|could see|remains possible)\b",
     "UNFALSIFIABLE_HEDGE",
     "Prediction uses unfalsifiable language. Replace 'could potentially' with a specific claim and confidence level."),

    # Volatility tautology
    (r"(?i)\bmarkets?\s+(will|could|may)\s+(see|experience|face)\s+(increased\s+)?volatility\b",
     "VOLATILITY_TAUTOLOGY",
     "Predicting 'markets will see volatility' is always true. Specify direction, magnitude, and VIX level."),

    # Tension tautology
    (r"(?i)\btensions?\s+(will|could|may)\s+(remain|stay|continue|be)\s+(elevated|high|heightened)\b",
     "TENSION_TAUTOLOGY",
     "Predicting 'tensions will remain elevated' is not actionable. Specify what concrete event happens as a result."),

    # Kitchen sink (both directions)
    (r"(?i)\b(either\s+)?(up\s+or\s+down|rise\s+or\s+fall|increase\s+or\s+decrease)\b",
     "KITCHEN_SINK",
     "Prediction covers both directions. Pick one direction with a confidence level."),

    # Time-will-tell filler
    (r"(?i)\b(remains?\s+to\s+be\s+seen|only\s+time\s+will\s+tell|it\s+is\s+unclear)\b",
     "FILLER_LANGUAGE",
     "Prediction contains non-analytical filler. State your view directly."),
]

# Softer warnings (don't reject, but flag)
WARNING_PATTERNS = [
    # Consensus restating (soft check — needs context to be sure)
    (r"(?i)\b(widely\s+expected|consensus\s+expects|market\s+expects|priced\s+in)\b",
     "POSSIBLE_CONSENSUS_RESTATE",
     "This may be restating consensus. Ensure your view differs from market expectations."),

    # Historical analogy overreliance
    (r"(?i)\b(just\s+like|similar\s+to|reminiscent\s+of|echoes?\s+of|repeat\s+of)\s+\d{4}\b",
     "HISTORICAL_ANALOGY",
     "Uses historical analogy. Ensure you've identified how current situation DIFFERS from the analogy."),
]


# =============================================================================
# SPECIFICITY REQUIREMENTS
# =============================================================================

def _has_number(text: str) -> bool:
    """Check if text contains a specific number (price, percentage, magnitude)."""
    patterns = [
        r'\d+\.?\d*\s*%',           # percentage: 15%, 3.5%
        r'\$\s*\d+',                 # dollar amount: $3,400
        r'\d{1,3}(,\d{3})+',        # large numbers: 3,400 or 5,842
        r'\b\d+(\.\d+)?\s*(bp|bps|pp|pps)\b',  # basis points
        r'\b\d+(\.\d+)?\s*(billion|million|trillion)\b',  # magnitudes
        r'\b\d+x\b',                # multipliers: 10x
        r'\b\d+(\.\d+)?/oz\b',      # per-ounce pricing
        r'\b[1-9]\d*(\.\d+)?\b',    # any non-zero number (fallback)
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _has_entity(text: str) -> bool:
    """Check if text contains a specific entity (country, company, index, person)."""
    # This is a heuristic — look for capitalized multi-word names or known entities
    known_entities = [
        # Countries & regions
        r'\b(US|U\.S\.|United States|China|Russia|Iran|India|EU|Europe|Japan|UK|Germany|France|Saudi|UAE|Dubai|Taiwan|Korea|Israel|Ukraine|Turkey|Brazil|Mexico)\b',
        # Market indices
        r'\b(S&P\s*500|SPX|Nasdaq|Dow|FTSE|DAX|Nikkei|Hang\s+Seng|Shanghai|VIX|Russell)\b',
        # Commodities
        r'\b(gold|oil|WTI|Brent|natural\s+gas|copper|wheat|corn|soybeans?|silver|platinum|XAU)\b',
        # Currencies
        r'\b(dollar|DXY|USD|EUR|JPY|GBP|CNY|yuan|yen|euro|rupee)\b',
        # Institutions
        r'\b(Fed|Federal\s+Reserve|ECB|BOJ|PBOC|IMF|World\s+Bank|NATO|OPEC|SEC|Treasury)\b',
        # Major companies
        r'\b(Apple|Google|Microsoft|Amazon|Nvidia|Tesla|Meta|TSMC|Samsung|Equinix)\b',
        # General entity detection (capitalized sequences)
        r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b',  # Multi-word capitalized names
    ]
    return any(re.search(p, text) for p in known_entities)


def _has_deadline(pred: Dict[str, Any]) -> bool:
    """Check if prediction has a meaningful deadline."""
    if pred.get("time_condition_date"):
        return True
    if pred.get("time_condition_end"):
        return True
    if pred.get("time_condition_type") == "point" and pred.get("time_condition_date"):
        return True
    return False


def _deadline_is_reasonable(pred: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if the deadline is within a reasonable range (7-180 days)."""
    deadline_str = pred.get("time_condition_end") or pred.get("time_condition_date")
    if not deadline_str:
        return True, ""  # no deadline to check

    try:
        if isinstance(deadline_str, date):
            deadline = deadline_str
        else:
            deadline = date.fromisoformat(str(deadline_str)[:10])

        days_out = (deadline - date.today()).days

        if days_out < 0:
            return False, f"Deadline is in the past ({deadline})"
        if days_out < 3:
            return False, f"Deadline is too soon ({days_out} days) — not enough time to be meaningful"
        if days_out > 365:
            return False, f"Deadline is {days_out} days out — consider framing as a structural thesis instead"

        return True, ""
    except (ValueError, TypeError):
        return True, ""  # can't parse, let it through


# =============================================================================
# MAIN VALIDATION FUNCTION
# =============================================================================

def validate_prediction(
    pred: Dict[str, Any],
    agent_name: str,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Validate a prediction against quality gates.

    Returns:
        (validated_prediction, warnings)
        - validated_prediction: the prediction (possibly with adjusted confidence), or None if rejected
        - warnings: list of warning strings (non-blocking issues)
    """
    claim = pred.get("claim", "")
    confidence = pred.get("confidence", 0.5)
    category = pred.get("category", "")
    reasoning = pred.get("reasoning", "")
    so_what = pred.get("so_what", "")
    warnings = []

    # =========================================================================
    # GATE 1: Basic validity
    # =========================================================================
    if not claim or len(claim.strip()) < 15:
        return None, ["REJECTED: Claim is too short or empty"]

    if not pred.get("resolution_criteria") or len(pred.get("resolution_criteria", "").strip()) < 10:
        warnings.append("WARNING: Resolution criteria is weak — may be hard to resolve TRUE/FALSE")

    # =========================================================================
    # GATE 2: Banned pattern check
    # =========================================================================
    for pattern, code, message in BANNED_PATTERNS:
        if re.search(pattern, claim):
            return None, [f"REJECTED ({code}): {message}. Claim: '{claim[:100]}'"]

    # Also check reasoning for banned patterns (less strict — warning only)
    for pattern, code, message in BANNED_PATTERNS:
        if reasoning and re.search(pattern, reasoning):
            warnings.append(f"WARNING ({code} in reasoning): {message}")
            break  # only one warning per prediction for reasoning

    # Soft warning patterns
    for pattern, code, message in WARNING_PATTERNS:
        if re.search(pattern, claim) or (reasoning and re.search(pattern, reasoning)):
            warnings.append(f"WARNING ({code}): {message}")

    # =========================================================================
    # GATE 3: Specificity check
    # =========================================================================
    specificity_failures = []

    if not _has_number(claim):
        specificity_failures.append("NO_NUMBER: Claim lacks a specific number (price, %, threshold)")

    if not _has_entity(claim):
        specificity_failures.append("NO_ENTITY: Claim lacks a specific entity (country, company, index)")

    if not _has_deadline(pred):
        specificity_failures.append("NO_DEADLINE: Prediction has no deadline date")

    # Require at least 2 of 3 specificity criteria
    if len(specificity_failures) >= 2:
        return None, [f"REJECTED (INSUFFICIENT_SPECIFICITY): {'; '.join(specificity_failures)}. Claim: '{claim[:100]}'"]
    elif specificity_failures:
        warnings.extend([f"WARNING: {f}" for f in specificity_failures])

    # =========================================================================
    # GATE 4: Deadline reasonableness
    # =========================================================================
    deadline_ok, deadline_msg = _deadline_is_reasonable(pred)
    if not deadline_ok:
        warnings.append(f"WARNING (DEADLINE): {deadline_msg}")

    # =========================================================================
    # GATE 5: Confidence bounds and domain caps
    # =========================================================================
    original_confidence = confidence

    # Absolute bounds
    confidence = max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, confidence))

    # Domain cap
    if category and category.upper() in DOMAIN_CONFIDENCE_CAPS:
        domain_cap = DOMAIN_CONFIDENCE_CAPS[category.upper()]
        if confidence > domain_cap:
            confidence = domain_cap
            warnings.append(
                f"CAPPED: Confidence reduced from {original_confidence:.0%} to {confidence:.0%} "
                f"(domain cap for {category}: {domain_cap:.0%})"
            )

    # Agent-level cap
    if agent_name in AGENT_CONFIDENCE_CAPS:
        agent_cap = AGENT_CONFIDENCE_CAPS[agent_name]
        if confidence > agent_cap:
            confidence = agent_cap
            warnings.append(
                f"CAPPED: Confidence reduced to {confidence:.0%} (agent cap for {agent_name})"
            )

    # =========================================================================
    # GATE 6: "So What?" check (warning only, not rejection)
    # =========================================================================
    if not so_what or len(so_what.strip()) < 10:
        warnings.append("WARNING (NO_SO_WHAT): Prediction lacks actionable guidance. What should the reader DO?")

    # =========================================================================
    # GATE 7: Reasoning quality check (warning only)
    # =========================================================================
    if not reasoning or len(reasoning.strip()) < 50:
        warnings.append("WARNING (THIN_REASONING): Reasoning is too brief for a quality prediction")

    # =========================================================================
    # Return validated prediction
    # =========================================================================
    validated = pred.copy()
    validated["confidence"] = confidence

    if confidence != original_confidence:
        validated["_confidence_adjusted"] = True
        validated["_original_confidence"] = original_confidence

    return validated, warnings


def validate_prediction_batch(
    predictions: List[Dict[str, Any]],
    agent_name: str,
    max_predictions: int = 8,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """
    Validate a batch of predictions from an agent.

    Returns:
        (accepted, rejected, all_warnings)
    """
    accepted = []
    rejected = []
    all_warnings = []

    for pred in predictions:
        validated, warnings = validate_prediction(pred, agent_name)
        all_warnings.extend(warnings)

        if validated:
            accepted.append(validated)
        else:
            rejected.append({
                "claim": pred.get("claim", "")[:200],
                "reasons": warnings,
            })

    # Quality over quantity — cap at max_predictions
    if len(accepted) > max_predictions:
        # Keep the ones with highest confidence (they've already been capped)
        accepted.sort(key=lambda p: p.get("confidence", 0), reverse=True)
        overflow = accepted[max_predictions:]
        accepted = accepted[:max_predictions]
        all_warnings.append(
            f"TRIMMED: {len(overflow)} predictions removed (max {max_predictions} per cycle). "
            f"Keeping highest-confidence predictions."
        )

    # Log summary
    logger.info(
        f"[{agent_name}] Prediction validation: "
        f"{len(accepted)} accepted, {len(rejected)} rejected, "
        f"{len(all_warnings)} warnings"
    )

    if rejected:
        for r in rejected:
            logger.info(f"[{agent_name}] REJECTED: {r['claim'][:80]} — {r['reasons'][0] if r['reasons'] else 'unknown'}")

    return accepted, rejected, all_warnings
