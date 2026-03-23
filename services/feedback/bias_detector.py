"""
Statistical bias detection.

Every hour: run statistical tests for overconfidence, underconfidence,
domain-specific blind spots. Generate specific actionable adjustment text.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

import numpy as np
from scipy import stats as scipy_stats

from shared.database import get_db_session
from shared.models import Prediction, CalibrationScore
from shared.utils import confidence_bucket

logger = logging.getLogger(__name__)

AGENTS = ["geopolitical", "economist", "investor", "political", "sentiment", "master"]

# Minimum sample size for statistical tests
MIN_SAMPLE_SIZE = 5

# Significance level for statistical tests
ALPHA = 0.10  # More lenient early on when data is sparse


class BiasDetection:
    """A detected bias with actionable adjustment text."""

    def __init__(
        self,
        agent: str,
        bias_type: str,
        domain: Optional[str],
        confidence_range: Optional[str],
        severity: str,
        description: str,
        adjustment_text: str,
        statistical_detail: Optional[str] = None,
    ):
        self.agent = agent
        self.bias_type = bias_type  # overconfidence|underconfidence|domain_blind_spot|extremity_aversion
        self.domain = domain
        self.confidence_range = confidence_range
        self.severity = severity  # low|medium|high
        self.description = description
        self.adjustment_text = adjustment_text
        self.statistical_detail = statistical_detail


def run_bias_detection() -> Dict[str, Any]:
    """
    Run comprehensive bias detection across all agents.
    Returns stats and a list of detected biases.
    """
    stats = {
        "agents_analyzed": 0,
        "biases_detected": 0,
        "errors": 0,
    }
    all_biases: List[BiasDetection] = []

    try:
        with get_db_session() as db:
            # Fetch all resolved predictions with outcomes
            resolved = (
                db.query(Prediction)
                .filter(
                    Prediction.status.in_(
                        ["RESOLVED_TRUE", "RESOLVED_FALSE", "EXPIRED"]
                    ),
                    Prediction.resolved_outcome.isnot(None),
                )
                .all()
            )

            if len(resolved) < MIN_SAMPLE_SIZE:
                logger.info(
                    f"Only {len(resolved)} resolved predictions — "
                    f"need {MIN_SAMPLE_SIZE} for bias detection"
                )
                return stats

            for agent in AGENTS:
                agent_preds = [p for p in resolved if p.agent == agent]
                if len(agent_preds) < MIN_SAMPLE_SIZE:
                    continue

                stats["agents_analyzed"] += 1

                try:
                    # 1. Overall overconfidence/underconfidence test
                    biases = _detect_calibration_bias(agent, agent_preds)
                    all_biases.extend(biases)

                    # 2. Per-bucket bias detection
                    bucket_biases = _detect_bucket_bias(agent, agent_preds)
                    all_biases.extend(bucket_biases)

                    # 3. Domain-specific blind spots
                    domain_biases = _detect_domain_blind_spots(agent, agent_preds)
                    all_biases.extend(domain_biases)

                    # 4. Extremity aversion (avoiding 0-10% and 90-100%)
                    extremity_biases = _detect_extremity_aversion(agent, agent_preds)
                    all_biases.extend(extremity_biases)

                except Exception as e:
                    logger.error(f"Bias detection error for agent {agent}: {e}")
                    stats["errors"] += 1

            stats["biases_detected"] = len(all_biases)

    except Exception as e:
        logger.error(f"Failed to run bias detection: {e}")
        stats["errors"] += 1

    if all_biases:
        logger.info(
            f"Bias detection: analyzed={stats['agents_analyzed']}, "
            f"biases_found={stats['biases_detected']}"
        )
        for bias in all_biases:
            logger.info(
                f"  [{bias.agent}] {bias.bias_type} ({bias.severity}): "
                f"{bias.description}"
            )

    return {"stats": stats, "biases": all_biases}


def _detect_calibration_bias(
    agent: str, predictions: List[Prediction]
) -> List[BiasDetection]:
    """
    Test if agent is systematically overconfident or underconfident
    using a calibration test.
    """
    biases = []

    confidences = np.array([p.current_confidence for p in predictions])
    outcomes = np.array(
        [1.0 if p.resolved_outcome else 0.0 for p in predictions]
    )

    mean_confidence = float(np.mean(confidences))
    mean_outcome = float(np.mean(outcomes))
    diff = mean_confidence - mean_outcome

    # Use a one-sample t-test on the calibration residuals
    residuals = confidences - outcomes
    if len(residuals) >= MIN_SAMPLE_SIZE:
        t_stat, p_value = scipy_stats.ttest_1samp(residuals, 0.0)

        if p_value < ALPHA and abs(diff) > 0.05:
            if diff > 0:
                bias_type = "overconfidence"
                severity = "high" if diff > 0.15 else "medium" if diff > 0.08 else "low"
                adj_pp = round(diff * 100)
                adjustment = (
                    f"You are systematically overconfident. "
                    f"Your average confidence is {mean_confidence:.0%} but actual resolution "
                    f"rate is {mean_outcome:.0%}. "
                    f"Consider reducing confidence by ~{adj_pp}pp across all predictions."
                )
            else:
                bias_type = "underconfidence"
                severity = "high" if abs(diff) > 0.15 else "medium" if abs(diff) > 0.08 else "low"
                adj_pp = round(abs(diff) * 100)
                adjustment = (
                    f"You are systematically underconfident. "
                    f"Your average confidence is {mean_confidence:.0%} but actual resolution "
                    f"rate is {mean_outcome:.0%}. "
                    f"Consider increasing confidence by ~{adj_pp}pp across all predictions."
                )

            biases.append(BiasDetection(
                agent=agent,
                bias_type=bias_type,
                domain=None,
                confidence_range=None,
                severity=severity,
                description=(
                    f"Mean confidence {mean_confidence:.2f} vs actual rate "
                    f"{mean_outcome:.2f} (diff={diff:+.2f})"
                ),
                adjustment_text=adjustment,
                statistical_detail=f"t={t_stat:.2f}, p={p_value:.4f}, n={len(predictions)}",
            ))

    return biases


def _detect_bucket_bias(
    agent: str, predictions: List[Prediction]
) -> List[BiasDetection]:
    """
    Detect bias in specific confidence ranges.
    E.g., "In 30-40% range, you resolve TRUE 60% — adjust upward by ~15pp"
    """
    biases = []

    # Group by bucket
    buckets: Dict[str, List[Prediction]] = defaultdict(list)
    for pred in predictions:
        bucket = confidence_bucket(pred.current_confidence)
        buckets[bucket].append(pred)

    for bucket_name, bucket_preds in sorted(buckets.items()):
        if len(bucket_preds) < MIN_SAMPLE_SIZE:
            continue

        predicted_avg = np.mean([p.current_confidence for p in bucket_preds])
        actual_avg = np.mean(
            [1.0 if p.resolved_outcome else 0.0 for p in bucket_preds]
        )
        diff = float(predicted_avg - actual_avg)

        if abs(diff) > 0.10:  # Significant miscalibration in this bucket
            if diff > 0:
                adj_pp = round(abs(diff) * 100)
                adjustment = (
                    f"In the {bucket_name} confidence range, your predictions "
                    f"resolve TRUE only {actual_avg:.0%} of the time. "
                    f"Adjust downward by ~{adj_pp}pp when predicting in this range."
                )
                bias_type = "overconfidence"
            else:
                adj_pp = round(abs(diff) * 100)
                adjustment = (
                    f"In the {bucket_name} range, you resolve TRUE {actual_avg:.0%} "
                    f"of the time — adjust upward by ~{adj_pp}pp."
                )
                bias_type = "underconfidence"

            severity = "high" if abs(diff) > 0.20 else "medium"
            biases.append(BiasDetection(
                agent=agent,
                bias_type=bias_type,
                domain=None,
                confidence_range=bucket_name,
                severity=severity,
                description=(
                    f"Bucket {bucket_name}: predicted_avg={predicted_avg:.2f}, "
                    f"actual_avg={actual_avg:.2f}, n={len(bucket_preds)}"
                ),
                adjustment_text=adjustment,
            ))

    return biases


def _detect_domain_blind_spots(
    agent: str, predictions: List[Prediction]
) -> List[BiasDetection]:
    """
    Detect if an agent performs significantly worse in specific domains
    compared to their overall performance.
    """
    biases = []

    agent_domain_map = {
        "geopolitical": "geopolitical",
        "economist": "economic",
        "investor": "market",
        "political": "political",
        "sentiment": "sentiment",
    }

    # Group by inferred domain
    domain_preds: Dict[str, List[Prediction]] = defaultdict(list)
    for pred in predictions:
        domain = agent_domain_map.get(pred.agent, "other")
        domain_preds[domain].append(pred)

    if not domain_preds:
        return biases

    # Calculate overall Brier score
    all_brier = [
        p.brier_score for p in predictions
        if p.brier_score is not None
    ]
    if not all_brier:
        return biases

    overall_brier = np.mean(all_brier)

    # Compare each domain to overall
    for domain, preds in domain_preds.items():
        domain_brier = [p.brier_score for p in preds if p.brier_score is not None]
        if len(domain_brier) < MIN_SAMPLE_SIZE:
            continue

        domain_brier_avg = float(np.mean(domain_brier))
        diff = domain_brier_avg - overall_brier

        # Domain is significantly worse than overall
        if diff > 0.05 and len(domain_brier) >= MIN_SAMPLE_SIZE:
            # Mann-Whitney U test for significance
            other_brier = [
                p.brier_score for p in predictions
                if p.brier_score is not None
                and agent_domain_map.get(p.agent) != domain
            ]
            if len(other_brier) >= MIN_SAMPLE_SIZE:
                try:
                    u_stat, p_value = scipy_stats.mannwhitneyu(
                        domain_brier, other_brier, alternative="greater"
                    )
                    if p_value < ALPHA:
                        biases.append(BiasDetection(
                            agent=agent,
                            bias_type="domain_blind_spot",
                            domain=domain,
                            confidence_range=None,
                            severity="high" if diff > 0.10 else "medium",
                            description=(
                                f"Domain '{domain}' Brier={domain_brier_avg:.3f} "
                                f"vs overall={overall_brier:.3f}"
                            ),
                            adjustment_text=(
                                f"Your predictions in the {domain} domain are significantly "
                                f"less accurate (Brier {domain_brier_avg:.3f}) than your overall "
                                f"performance ({overall_brier:.3f}). "
                                f"Apply extra scrutiny to {domain} predictions and consider "
                                f"wider confidence intervals."
                            ),
                            statistical_detail=f"U={u_stat:.1f}, p={p_value:.4f}",
                        ))
                except Exception:
                    pass  # Not enough variation for statistical test

    return biases


def _detect_extremity_aversion(
    agent: str, predictions: List[Prediction]
) -> List[BiasDetection]:
    """
    Detect if agent avoids extreme confidence values (near 0% or 100%)
    when the evidence warrants them.
    """
    biases = []

    # Check for compression toward 50%
    confidences = [p.current_confidence for p in predictions]
    outcomes = [1.0 if p.resolved_outcome else 0.0 for p in predictions]

    # Look at predictions that resolved clearly (TRUE) but had middling confidence
    true_preds = [
        p for p in predictions
        if p.resolved_outcome is True and p.current_confidence < 0.70
    ]
    false_preds = [
        p for p in predictions
        if p.resolved_outcome is False and p.current_confidence > 0.30
    ]

    total = len(predictions)
    if total < MIN_SAMPLE_SIZE * 2:
        return biases

    # High rate of true outcomes at low confidence = extremity aversion
    true_rate_at_low_conf = len(true_preds) / total if total > 0 else 0
    false_rate_at_high_conf = len(false_preds) / total if total > 0 else 0

    if true_rate_at_low_conf > 0.30 and len(true_preds) >= MIN_SAMPLE_SIZE:
        avg_conf = np.mean([p.current_confidence for p in true_preds])
        biases.append(BiasDetection(
            agent=agent,
            bias_type="extremity_aversion",
            domain=None,
            confidence_range="low",
            severity="medium",
            description=(
                f"{len(true_preds)} predictions resolved TRUE with "
                f"avg confidence {avg_conf:.0%} (should have been higher)"
            ),
            adjustment_text=(
                f"You show reluctance to assign high confidence. "
                f"{len(true_preds)} of your predictions resolved TRUE but had "
                f"average confidence of only {avg_conf:.0%}. "
                f"When evidence is strong, be willing to push confidence above 70%."
            ),
        ))

    return biases


def format_biases_as_calibration_notes(biases: List[BiasDetection]) -> str:
    """
    Format detected biases into calibration notes text suitable for
    injection into agent prompts.
    """
    if not biases:
        return ""

    lines = ["## CALIBRATION ADJUSTMENTS (auto-generated by feedback processor)\n"]

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    sorted_biases = sorted(biases, key=lambda b: severity_order.get(b.severity, 3))

    for i, bias in enumerate(sorted_biases, 1):
        severity_tag = f"[{bias.severity.upper()}]"
        lines.append(f"{i}. {severity_tag} {bias.adjustment_text}")
        if bias.confidence_range:
            lines.append(f"   Range: {bias.confidence_range}")
        if bias.domain:
            lines.append(f"   Domain: {bias.domain}")
        lines.append("")

    return "\n".join(lines)


def format_biases_as_reasoning_guidance(biases: List[BiasDetection]) -> str:
    """
    Format detected biases into reasoning guidance text.
    More prescriptive than calibration notes — tells agent HOW to reason differently.
    """
    if not biases:
        return ""

    lines = ["## REASONING GUIDANCE (auto-generated)\n"]

    # Group biases by type for clearer guidance
    by_type: Dict[str, List[BiasDetection]] = defaultdict(list)
    for bias in biases:
        by_type[bias.bias_type].append(bias)

    if "overconfidence" in by_type:
        lines.append("### Overconfidence Correction")
        lines.append(
            "Before finalizing any prediction, ask: 'What would have to be true "
            "for this to fail?' List at least 2 failure modes."
        )
        for bias in by_type["overconfidence"]:
            if bias.confidence_range:
                lines.append(f"- {bias.adjustment_text}")
        lines.append("")

    if "underconfidence" in by_type:
        lines.append("### Underconfidence Correction")
        lines.append(
            "When multiple independent signals converge, allow confidence to rise "
            "above your comfort zone. Check: are you hedging out of caution rather "
            "than evidence?"
        )
        for bias in by_type["underconfidence"]:
            if bias.confidence_range:
                lines.append(f"- {bias.adjustment_text}")
        lines.append("")

    if "domain_blind_spot" in by_type:
        lines.append("### Domain-Specific Warnings")
        for bias in by_type["domain_blind_spot"]:
            lines.append(f"- {bias.adjustment_text}")
        lines.append("")

    if "extremity_aversion" in by_type:
        lines.append("### Extremity Aversion")
        lines.append(
            "You tend to compress predictions toward the middle. "
            "When evidence is overwhelming, use extreme confidence values (>80% or <20%)."
        )
        lines.append("")

    return "\n".join(lines)
