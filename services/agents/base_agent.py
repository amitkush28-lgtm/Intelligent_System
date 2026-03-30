"""
Base Agent — Cascading Consequences Framework with Prediction Quality Gates.

Every specialist agent inherits from this class. The framework enforces:

1. CASCADING CONSEQUENCES — trace cause→effect through 5 levels to actionable impact
2. PREDICTION QUALITY GATES — reject vague, unfalsifiable, consensus-restating predictions
3. DOMAIN CONFIDENCE CAPS — prevent overconfidence in inherently unpredictable domains
4. THE "SO WHAT?" FORCING FUNCTION — every analysis must end with specific actionable guidance
5. THE BET TEST — every prediction must be something you'd wager real money on

Agent execution: build_system_prompt() + build_user_message() → call LLM → parse output
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


# =============================================================================
# CASCADING CONSEQUENCES FRAMEWORK
# =============================================================================

CASCADING_CONSEQUENCES_FRAMEWORK = """
## ANALYTICAL FRAMEWORK — CASCADING CONSEQUENCES

For every significant event, trace the cause-effect chain through ALL 5 levels before
making predictions. Most analysts stop at Level 2. Your value is Levels 3-5.

LEVEL 1 — THE EVENT: What happened? (Factual summary — what everyone already knows)

LEVEL 2 — FIRST-ORDER EFFECTS: The obvious, already-priced-in consequences.
  These are necessary context but NOT where your predictions should focus.

LEVEL 3 — SECOND-ORDER EFFECTS (WHERE THE ALPHA LIVES):
  Non-obvious consequences that most people miss:
  - Supply chain cascades (who supplies the supplier?)
  - Geographic spillover (what neighboring regions are affected?)
  - Financial contagion (what's correlated that shouldn't be?)
  - Migration/refugee flows (who moves, where do they go?)
  - Insurance and reinsurance impacts
  - Energy transmission effects (power grids, pipeline rerouting)
  - Food security consequences (crop disruption, trade route blockage)

LEVEL 4 — THIRD-ORDER EFFECTS (SYSTEMIC/BEHAVIORAL SHIFTS):
  - Political backlash (voters punish leaders for consequences)
  - Regulatory response (governments overreact or underreact)
  - Behavioral shifts (consumers/businesses permanently change patterns)
  - Precedent setting (this event becomes the template for future actions)
  - Alliance restructuring (who moves closer to whom?)

LEVEL 5 — WHO GETS HURT, WHO BENEFITS (THE "SO WHAT?"):
  SPECIFIC answers — not vague generalizations:
  - CITIES: Which specific cities face risk? (airports, expat populations, property)
  - INDUSTRIES: Which specific sectors gain/lose? (estimate magnitude)
  - PORTFOLIOS: Which specific positions to add/reduce/hedge?
  - POPULATIONS: Which specific groups face real-world disruption?
  - TRAVELERS: Which routes/destinations become risky?

## THE "DUBAI TEST"
For every geopolitical event, ask: which cities are within missile/drone range?
Which airports close? Which expat populations evacuate? Which real estate markets crash?
Which shipping routes are disrupted? Apply this concretely, not hypothetically.

## DEEP MOTIVATIONAL ANALYSIS
Before predicting what an actor will do, identify their TRUE objective function.
Check six forces:
1. Religious/theological frameworks — regime legitimacy tied to theology
2. Civilizational identity & historical destiny — "century of humiliation," imperial restoration
3. Collective trauma & generational memory — hyperinflation memory, "never again" doctrine
4. Honor, face & status hierarchies — humiliation avoidance overriding economic logic
5. Ideological true belief — leaders who genuinely believe, not cynically using ideology
6. Tribal/ethnic/kinship structures — informal loyalty overriding formal institutions

## STRUCTURAL REASONING CHAIN
Apply to every major theme:
I. ACTORS & STRUCTURAL NEEDS: What does their structural position FORCE them to do?
II. CONSTRAINTS: What can't happen? Narrow to 2-3 viable paths.
III. IRREVERSIBILITIES: One-way doors that lock in outcomes.
IV. EQUILIBRIUM: Where does the system settle? Is current state stable or must it break?
V. CONSENSUS ERROR: Where is consensus wrong, and what structural reason explains the error?
VI. SECOND/THIRD-ORDER EFFECTS: Follow the cascade further than anyone else.
"""


# =============================================================================
# PREDICTION QUALITY GATES
# =============================================================================

PREDICTION_FORMAT = """
## PREDICTION FORMAT — MANDATORY FIELDS

For every prediction, you MUST provide ALL of:
- CLAIM: [specific, falsifiable statement with a NUMBER, a DATE, and a SPECIFIC ENTITY]
- TIME_CONDITION: [point date OR date range with explicit deadline — max 90 days out]
- CONFIDENCE: [0.30 to 0.95 — see domain caps below]
- RESOLUTION_CRITERIA: [exactly how a third party determines TRUE or FALSE]
- REASONING: [detailed multi-paragraph analysis using cascading consequences]
- BASE_RATE: [historical frequency of this type of event, or "no reference class"]
- KEY_TRIGGERS: [specific events that would INCREASE or DECREASE your confidence]
- SUB_PREDICTIONS: [faster-resolving claims that serve as leading indicators]
- CATEGORY: [FINANCIAL | SAFETY | ECONOMIC | REAL_ESTATE | ENERGY_FOOD | POLITICAL | HEALTH]
- SO_WHAT: [specific actionable guidance — what should the reader DO?]

## DOMAIN CONFIDENCE CAPS — HARD LIMITS
- Geopolitical timing (wars, coups, attacks): MAX 0.70
- Market price levels: MAX 0.75
- Political outcomes (elections, votes): MAX 0.80 (except within 7 days of event)
- Economic data direction: MAX 0.85
- Safety/conflict escalation: MAX 0.75
- MINIMUM for any prediction: 0.30 (below this is noise, not signal)
- MAXIMUM for any prediction: 0.95 (black swans are always possible)

## PREDICTION QUALITY GATES — YOUR PREDICTION WILL BE REJECTED IF:
1. NO SPECIFIC NUMBER (price level, percentage, magnitude)
2. NO SPECIFIC DATE OR DEADLINE
3. VAGUE DIRECTIONAL ("oil prices will increase" — HOW MUCH? BY WHEN?)
4. UNFALSIFIABLE HEDGING ("markets could see volatility")
5. CONSENSUS RESTATING ("the Fed will cut rates" without specific timing/magnitude divergence)
6. DIPLOMATIC-SPEAK ("tensions will remain elevated" — WHO GETS HURT?)
7. KITCHEN-SINK ("markets will either go up or down significantly")
8. ALREADY PRICED IN ("if Fed cuts, stocks rally" — what's the SECOND-order effect?)
9. MISSING "SO WHAT" — no actionable guidance for the reader

THE BET TEST: If a smart, skeptical friend offered $1,000 on this prediction at your
stated confidence level, would you take the bet? If not, make it more specific.

## BASE RATE DISCIPLINE
Before assigning confidence, ask: historically, how often does this type of event happen?
- Sovereign debt defaults (major economies): ~2%/year → cap confidence at 0.40
- Military conflicts between nuclear powers: <1%/year → cap at 0.25
- Major stock corrections (>10%): ~once per 1.5 years → don't predict one every month
- Oil price spikes >20%: ~once per 2 years → don't cry wolf
- Fed rate decisions matching consensus: ~80% → don't predict the obvious
"""


# =============================================================================
# OUTPUT FORMAT
# =============================================================================

OUTPUT_FORMAT_INSTRUCTIONS = """
## OUTPUT FORMAT

You MUST respond with ONLY valid JSON (no markdown, no preamble). Structure:
{
    "predictions": [
        {
            "claim": "specific falsifiable statement with number + date + entity",
            "time_condition_type": "range",
            "time_condition_start": "YYYY-MM-DD",
            "time_condition_end": "YYYY-MM-DD",
            "confidence": 0.65,
            "resolution_criteria": "exactly how a third party determines TRUE or FALSE",
            "reasoning": "DETAILED multi-paragraph analysis using cascading consequences framework. Walk through Levels 1-5. This should read like an intelligence briefing.",
            "base_rate": "historical frequency or 'no reference class'",
            "key_triggers": ["event that would increase confidence", "event that would decrease confidence"],
            "category": "FINANCIAL|SAFETY|ECONOMIC|REAL_ESTATE|ENERGY_FOOD|POLITICAL|HEALTH",
            "so_what": "Specific actionable guidance: what should the reader DO?",
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
            "reasoning": "why confidence changed — reference specific new evidence",
            "trigger": "what event caused this update"
        }
    ],
    "notes": [
        {
            "prediction_id": "PRED-2026-XXXX or null for general notes",
            "type": "observation|key_signal|counter_signal|analysis|blind_spot|convergence",
            "text": "analytical observation"
        }
    ],
    "summary": "2-3 sentence summary of your most important analytical finding today"
}

If no predictions or updates are warranted, return empty arrays. Always return valid JSON.
IMPORTANT: For "reasoning", write a DETAILED multi-paragraph analysis. Walk through the
cascading consequences. This should be the quality of a senior analyst's briefing.
"""


# =============================================================================
# EVIDENCE INTEGRITY
# =============================================================================

EVIDENCE_INTEGRITY_RULES = """
## EVIDENCE INTEGRITY
Only reference events with integrity score > 0.50.
For events with integrity 0.50-0.70, note "moderate confidence evidence."
For events with integrity > 0.70, treat as reliable.
Never make high-confidence predictions based solely on evidence below 0.50 integrity.
"""


# =============================================================================
# BASE AGENT CLASS
# =============================================================================

class BaseAgent:
    """
    Base class for all specialist agents.

    Subclasses must define:
    - agent_name: str (e.g. "economist")
    - role_description: str (domain-specific role and analytical framework)
    - domain_prompt: str (additional domain-specific instructions)
    """

    agent_name: str = "base"
    role_description: str = "Base intelligence analyst"
    domain_prompt: str = ""

    def __init__(self):
        self.logger = logging.getLogger(f"agent.{self.agent_name}")

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build the complete system prompt with cascading consequences framework.
        """
        formatted = format_context_for_prompt(context)

        prompt = f"""You are the {self.agent_name.upper()} specialist in a multi-agent intelligence prediction system.

Your job is NOT to summarize what happened. Your job is to tell the reader what happens NEXT — 
with specific numbers, dates, and locations — and to explain the cascading chain of consequences
that most analysts miss because they stop thinking at the first-order effect.

## YOUR ROLE
{self.role_description}

{self.domain_prompt}

{CASCADING_CONSEQUENCES_FRAMEWORK}

{PREDICTION_FORMAT}

{EVIDENCE_INTEGRITY_RULES}

## CALIBRATION NOTES (auto-updated by feedback processor)
{formatted.get('CALIBRATION_NOTES', 'No calibration data yet — system is in initial learning phase.')}

## REASONING GUIDANCE (auto-updated)
{formatted.get('REASONING_GUIDANCE', 'No specific adjustments yet.')}

## SOURCE RELIABILITY
{formatted.get('SOURCE_RELIABILITY', 'Using default source reliability scores.')}

## BASE RATES
{formatted.get('BASE_RATES', 'No base rate data loaded yet. State your assumptions explicitly.')}

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

## TREND INTELLIGENCE BRIEF — What Is Changing and How Fast
{formatted.get('TREND_INTELLIGENCE', 'No trend intelligence available.')}

## ACTIVE PREDICTIONS TO UPDATE
{formatted.get('CURRENT_PREDICTIONS', 'No active predictions.')}

## ACTORS AND RELATIONSHIPS
{formatted.get('ACTORS_AND_RELATIONSHIPS', 'No knowledge graph data yet.')}

## VERIFIED CLAIMS
{formatted.get('VERIFIED_CLAIMS', 'No verified claims above threshold.')}

## TODAY'S VERIFIED EVENTS
{formatted.get('TODAYS_EVENTS', 'No recent events.')}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

INSTRUCTIONS:
1. ALWAYS USE the CURRENT MARKET PRICES above. Your training data contains outdated prices.
2. Apply the CASCADING CONSEQUENCES framework (Levels 1-5) to the most significant events.
3. Every prediction MUST pass the BET TEST — would you wager $1,000 on it?
4. Every prediction MUST have a specific number, date, and entity.
5. Every prediction MUST include a "so_what" with actionable guidance.
6. Update existing predictions where new evidence warrants it.
7. Generate new predictions ONLY for emerging themes where you have genuine edge.
8. QUALITY over QUANTITY — 2-3 excellent predictions beat 8 mediocre ones.
9. Respect the DOMAIN CONFIDENCE CAPS — do not exceed them.
10. Check BASE RATES before assigning confidence.

Respond with ONLY valid JSON.
"""
        return msg

    async def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the full analysis cycle: build prompt → call LLM → parse output.
        """
        self.logger.info(f"Starting analysis cycle for {self.agent_name}")

        system_prompt = self.build_system_prompt(context)
        user_message = self.build_user_message(context)

        total_tokens_est = (len(system_prompt) + len(user_message)) // 4
        self.logger.info(f"Prompt size estimate: ~{total_tokens_est} tokens")

        try:
            raw_response = await call_claude_sonnet(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=8192,
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
