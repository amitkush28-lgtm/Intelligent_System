"""
Sponsored Content Detector.

Uses Claude Haiku to analyze article text for PR language patterns,
financial relationships, coordinated campaign indicators, and other
signs that content may be sponsored or promotional rather than
independent journalism.

Uses shared/llm_client.py call_claude_haiku() for cost-efficient bulk ops.
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple

from shared.llm_client import call_claude_haiku, parse_structured_json

logger = logging.getLogger(__name__)

SPONSORED_DETECTION_SYSTEM_PROMPT = """You are a media integrity analyst specializing in detecting sponsored content, advertorials, and PR-driven articles disguised as independent journalism.

Analyze the provided text and assess whether it appears to be sponsored content, a press release rewrite, or promotional material.

Look for these indicators:
1. PROMOTIONAL LANGUAGE: Superlatives without evidence ("industry-leading", "revolutionary", "best-in-class"), marketing buzzwords, product placement
2. SINGLE-SOURCE BIAS: Article heavily features one company/product without balance, no critical perspectives, no competitive comparison
3. PR STRUCTURE: Follows press release format (dateline, boilerplate, executive quotes), includes stock ticker, forward-looking statements disclaimer
4. FINANCIAL RELATIONSHIPS: Mentions of partnerships, sponsorships, affiliations that could create bias
5. COORDINATED INDICATORS: Unusually similar language across multiple outlets (suggests same PR firm), timing clusters around product launches/earnings
6. ATTRIBUTION GAPS: Claims without independent verification, unattributed statistics, vague sourcing ("experts say")
7. CALL TO ACTION: Links to purchase, download, sign up, or visit a commercial site

Respond ONLY with a JSON object (no markdown, no commentary):
{
    "is_sponsored": true/false,
    "confidence": 0.0-1.0,
    "indicators_found": ["indicator1", "indicator2"],
    "reasoning": "Brief explanation",
    "severity": "none|low|medium|high"
}"""


async def detect_sponsored_content(
    text: str,
    source: str = "",
    claim_text: str = "",
) -> Dict[str, Any]:
    """
    Analyze text for sponsored content indicators using Claude Haiku.

    Args:
        text: Article or claim text to analyze
        source: Source name for context
        claim_text: The specific claim being verified

    Returns:
        Dict with keys: is_sponsored, confidence, indicators_found,
        reasoning, severity
    """
    if not text or len(text.strip()) < 50:
        return {
            "is_sponsored": False,
            "confidence": 0.0,
            "indicators_found": [],
            "reasoning": "Text too short for meaningful analysis",
            "severity": "none",
        }

    # Truncate very long texts to keep Haiku costs low
    analysis_text = text[:3000]

    user_message = f"""Analyze this text for sponsored content indicators:

Source: {source}
Related claim: {claim_text}

Text to analyze:
---
{analysis_text}
---

Respond with JSON only."""

    try:
        response = await call_claude_haiku(
            system_prompt=SPONSORED_DETECTION_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=512,
            temperature=0.1,
        )

        result = parse_structured_json(response)

        if not result:
            logger.warning("Failed to parse sponsored detection response")
            return _default_result("Failed to parse LLM response")

        # Validate and normalize the response
        return {
            "is_sponsored": bool(result.get("is_sponsored", False)),
            "confidence": float(result.get("confidence", 0.0)),
            "indicators_found": result.get("indicators_found", []),
            "reasoning": str(result.get("reasoning", "")),
            "severity": result.get("severity", "none"),
        }

    except Exception as e:
        logger.error(f"Sponsored detection failed: {e}")
        return _default_result(f"Detection error: {str(e)[:100]}")


async def batch_detect_sponsored(
    items: list,
) -> list:
    """
    Run sponsored detection on a batch of items.

    Each item should have 'text', optional 'source' and 'claim_text'.
    Processes sequentially to respect Haiku rate limits.

    Returns list of result dicts in same order as input.
    """
    results = []
    for item in items:
        result = await detect_sponsored_content(
            text=item.get("text", ""),
            source=item.get("source", ""),
            claim_text=item.get("claim_text", ""),
        )
        results.append(result)
    return results


def should_flag_sponsored(result: Dict[str, Any], threshold: float = 0.6) -> Tuple[bool, str]:
    """
    Determine if a sponsored detection result should flag the claim.

    Args:
        result: Output from detect_sponsored_content()
        threshold: Minimum confidence to flag

    Returns:
        Tuple of (should_flag, reasoning)
    """
    if not result.get("is_sponsored", False):
        return False, "No sponsored indicators detected"

    confidence = result.get("confidence", 0.0)
    if confidence < threshold:
        return False, f"Sponsored confidence ({confidence:.2f}) below threshold ({threshold})"

    severity = result.get("severity", "none")
    if severity in ("none", "low") and confidence < 0.75:
        return False, f"Low severity with moderate confidence — not flagging"

    reasoning = result.get("reasoning", "Sponsored content detected")
    indicators = result.get("indicators_found", [])
    flag_reason = f"{reasoning} Indicators: {', '.join(indicators[:5])}"

    return True, flag_reason


def _default_result(reason: str) -> Dict[str, Any]:
    """Return safe default when detection fails."""
    return {
        "is_sponsored": False,
        "confidence": 0.0,
        "indicators_found": [],
        "reasoning": reason,
        "severity": "none",
    }
