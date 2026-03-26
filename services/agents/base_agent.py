"""
Base Agent — Implements the 7-question structural reasoning chain.

Every specialist agent inherits from this class. The chain:
1. What happened? (Event summary and significance)
2. Why does it matter? (Second/third-order effects)
3. What are the base rates? (Historical frequency of similar events)
4. What are key actors' motivations? (Deep motivational analysis - 6 forces)
5. What would change my mind? (Key triggers and invalidation criteria)
6. What's my confidence? (Explicit probability with reasoning)
7. What predictions follow? (Structured predictions with resolution criteria)

Each question builds on previous answers. Uses call_claude_sonnet() for analysis.
"""

import json
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional

from shared.llm_client import call_claude_sonnet, parse_structured_json
from shared.config import get_settings
from services.agents.context_builder import format_context_for_prompt
from services.agents.output_parser import parse_agent_output, check_devil_advocate_trigger

logger = logging.getLogger(__name__)
settings = get_settings()


# The 7-question structural reasoning chain (Part 3 of the brief)
STRUCTURAL_REASONING_CHAIN = """
## ANALYTICAL FRAMEWORK — THE 7-QUESTION CHAIN

Apply this to every major theme before making predictions:

I. ACTORS & STRUCTURAL NEEDS: Who are the actors and what does their structural position FORCE them to do? Distinguish stated positions from structural imperatives.

I-b. DEEP MOTIVATIONS (CRITICAL): Before constraints analysis, identify the TRUE objective function. Check six forces:
1. Religious/theological frameworks — regime legitimacy tied to theology
2. Civilizational identity & historical destiny — "century of humiliation," imperial restoration
3. Collective trauma & generational memory — hyperinflation memory, "never again" doctrine
4. Honor, face & status hierarchies — humiliation avoidance overriding economic logic
5. Ideological true belief — leaders who genuinely believe, not cynically using ideology
6. Tribal/ethnic/kinship structures — informal loyalty overriding formal institutions

II. CONSTRAINTS: What can't happen? Narrow infinite possibilities to 2-3 viable paths. Include identity constraints from I-b.

III. IRREVERSIBILITIES: One-way doors that lock in outcomes regardless of future events.

IV. EQUILIBRIUM: Given true objective functions + constraints, where does the system settle? Is current state stable or must it break?

V. CONSENSUS ERROR: Where is consensus wrong, and what structural reason explains the error?

VI. SECOND/THIRD-ORDER EFFECTS: Follow the cascade further than anyone else. Does the policy produce the opposite of its intended effect at the third order?
"""

PREDICTION_FORMAT = """
## PREDICTION FORMAT

For every prediction, you MUST provide ALL of:
- CLAIM: [specific, falsifiable statement]
- TIME_CONDITION: [point date OR date range with explicit deadline]
- CONFIDENCE: [0.0 to 1.0, decimal]
- RESOLUTION_CRITERIA: [exactly how we determine TRUE or FALSE]
- REASONING: [structured argument referencing the 7-question chain]
- BASE_RATE: [historical frequency if available, or "no reference class"]
- KEY_TRIGGERS: [specific events that would change this prediction up or down]
- SUB_PREDICTIONS: [faster-resolving claims that serve as leading indicators]
"""

OUTPUT_FORMAT_INSTRUCTIONS = """
## OUTPUT FORMAT

You MUST respond with ONLY valid JSON (no markdown, no preamble). Structure:
{
    "predictions": [
        {
            "claim": "specific falsifiable statement",
            "time_condition_type": "range",
            "time_condition_start": "YYYY-MM-DD",
            "time_condition_end": "YYYY-MM-DD",
            "confidence": 0.65,
            "resolution_criteria": "exactly how we know TRUE or FALSE",
            "reasoning": "structured argument using 7-question chain",
            "base_rate": "historical frequency or 'no reference class'",
            "key_triggers": ["event that would increase confidence", "event that would decrease confidence"],
            "sub_predictions": [
                {
                    "claim": "faster-resolving leading indicator",
                    "time_condition_type": "point",
                    "time_condition_date": "YYYY-MM-DD",
                    "confidence": 0.70,
                    "resolution_criteria": "how we verify this sub-prediction"
                }
            ]
        }
    ],
    "prediction_updates": [
        {
            "prediction_id": "PRED-2026-XXXX",
            "new_confidence": 0.72,
            "reasoning": "why confidence changed",
            "trigger": "what event caused this update"
        }
    ],
    "notes": [
        {
            "prediction_id": "PRED-2026-XXXX or null for general notes",
            "type": "observation|key_signal|counter_signal|analysis",
            "text": "analytical observation"
        }
    ],
    "summary": "2-3 sentence summary of your analysis"
}

If no predictions or updates are warranted, return empty arrays. Always return valid JSON.
"""

EVIDENCE_INTEGRITY_RULES = """
## EVIDENCE INTEGRITY

Only reference events with integrity score > 0.50.
For events with integrity 0.50-0.70, note "moderate confidence evidence."
For events with integrity > 0.70, treat as reliable.
Never make high-confidence prediction moves based on evidence below 0.50 integrity.
"""


class BaseAgent:
    """
    Base class for all specialist agents.

    Subclasses must define:
    - agent_name: str (e.g. "economist")
    - role_description: str (domain-specific role)
    - domain_prompt: str (additional domain-specific instructions)
    """

    agent_name: str = "base"
    role_description: str = "Base intelligence analyst"
    domain_prompt: str = ""

    def __init__(self):
        self.logger = logging.getLogger(f"agent.{self.agent_name}")

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build the complete system prompt from template + context.
        Follows the agent prompt template from Part 7 of the brief.
        """
        formatted = format_context_for_prompt(context)

        prompt = f"""You are the {self.agent_name.upper()} specialist in a multi-agent intelligence system.

## YOUR ROLE
{self.role_description}

{self.domain_prompt}

{STRUCTURAL_REASONING_CHAIN}

{PREDICTION_FORMAT}

{EVIDENCE_INTEGRITY_RULES}

## CALIBRATION NOTES (auto-updated by feedback processor)
{formatted.get('CALIBRATION_NOTES', 'No calibration data yet.')}

## REASONING GUIDANCE (auto-updated)
{formatted.get('REASONING_GUIDANCE', 'No specific adjustments yet.')}

## SOURCE RELIABILITY
{formatted.get('SOURCE_RELIABILITY', 'Using default source reliability scores.')}

## BASE RATES
{formatted.get('BASE_RATES', 'No base rate data loaded yet.')}

{OUTPUT_FORMAT_INSTRUCTIONS}
"""
        return prompt

    def build_user_message(self, context: Dict[str, Any]) -> str:
        """
        Build the user message containing today's events, active predictions, etc.
        """
        formatted = format_context_for_prompt(context)

        msg = f"""Analyze the following intelligence and produce predictions.

## CURRENT MARKET PRICES (LIVE DATA — USE THESE, NOT MEMORIZED PRICES)
{formatted.get('CURRENT_MARKET_DATA', 'No live market data available. DO NOT cite specific prices from memory.')}

## CROSS-DOMAIN SIGNALS FROM OTHER AGENTS
{formatted.get('CROSS_DOMAIN_SIGNALS', 'No cross-domain signals yet.')}

## ACTIVE PREDICTIONS TO UPDATE
{formatted.get('CURRENT_PREDICTIONS', 'No active predictions.')}

## ACTORS AND RELATIONSHIPS
{formatted.get('ACTORS_AND_RELATIONSHIPS', 'No knowledge graph data yet.')}

## VERIFIED CLAIMS
{formatted.get('VERIFIED_CLAIMS', 'No verified claims above threshold.')}

## TODAY'S VERIFIED EVENTS
{formatted.get('TODAYS_EVENTS', 'No recent events.')}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

CRITICAL: When making predictions involving specific prices, rates, or levels, you MUST use the CURRENT MARKET PRICES above. Your training data contains outdated prices. Always ground predictions in live data.

Apply the 7-question structural reasoning chain to the most significant events. Update existing predictions where warranted. Generate new predictions for emerging themes.

IMPORTANT: For the "reasoning" field, write a DETAILED multi-paragraph analysis like an intelligence briefing for a senior policymaker.

Respond with ONLY valid JSON.
"""
        return msg

    async def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the full analysis cycle: build prompt → call LLM → parse output.

        Returns parsed agent output with:
        - new_predictions, prediction_updates, notes, summary
        - devil_advocate_triggers
        - analysis_metadata
        """
        self.logger.info(f"Starting analysis cycle for {self.agent_name}")

        system_prompt = self.build_system_prompt(context)
        user_message = self.build_user_message(context)

        # Log prompt size for monitoring
        total_tokens_est = (len(system_prompt) + len(user_message)) // 4
        self.logger.info(f"Prompt size estimate: ~{total_tokens_est} tokens")

        try:
            raw_response = await call_claude_sonnet(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=4096,
                temperature=0.3,
            )

            self.logger.debug(f"Raw response length: {len(raw_response)}")

        except Exception as e:
            self.logger.error(f"LLM call failed for {self.agent_name}: {e}")
            self.logger.debug(traceback.format_exc())
            return {
                "new_predictions": [],
                "prediction_updates": [],
                "notes": [],
                "summary": f"Analysis failed: {str(e)[:100]}",
                "raw_valid": False,
                "devil_advocate_triggers": [],
                "analysis_metadata": {
                    "agent": self.agent_name,
                    "timestamp": datetime.utcnow().isoformat(),
                    "error": str(e)[:200],
                },
            }

        # Parse the structured output
        parsed = parse_agent_output(raw_response, self.agent_name)

        # Check for devil's advocate triggers
        existing_predictions = context.get("active_predictions", [])
        devil_triggers = check_devil_advocate_trigger(
            self.agent_name, parsed, existing_predictions
        )
        parsed["devil_advocate_triggers"] = devil_triggers

        if devil_triggers:
            self.logger.info(
                f"Devil's advocate triggered for {len(devil_triggers)} items: "
                f"{[t['trigger_reasons'] for t in devil_triggers]}"
            )

        # Add metadata
        parsed["analysis_metadata"] = {
            "agent": self.agent_name,
            "timestamp": datetime.utcnow().isoformat(),
            "prompt_tokens_est": total_tokens_est,
            "response_length": len(raw_response),
        }

        return parsed

    def get_domain_events_filter(self) -> List[str]:
        """Return list of event domains this agent cares about."""
        from services.agents.context_builder import AGENT_DOMAINS
        return AGENT_DOMAINS.get(self.agent_name, ["economic"])
