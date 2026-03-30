"""
Master Strategist Agent — Synthesis agent that runs AFTER all specialists.

Major upgrade: convergence detection, contradiction resolution, blind spot identification,
"What are we NOT talking about?" scan, and enhanced newsletter content generation.

The Master Strategist is the most important agent — it sees ALL specialist outputs and
produces the cross-domain insights that no individual specialist can generate.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List

from shared.llm_client import call_claude_sonnet, parse_structured_json
from shared.config import get_settings
from services.agents.base_agent import BaseAgent, OUTPUT_FORMAT_INSTRUCTIONS
from services.agents.context_builder import (
    format_context_for_prompt,
    get_all_agent_predictions_for_master,
)
from services.agents.output_parser import parse_agent_output
from services.agents.synthesis_engine import format_synthesis_for_master

logger = logging.getLogger(__name__)
settings = get_settings()


class MasterAgent(BaseAgent):
    agent_name = "master"

    role_description = """You are the MASTER STRATEGIST — the synthesis agent in a multi-agent intelligence system.

You run AFTER all specialist agents (Economist, Geopolitical, Investor, Political, Sentiment, Wild Card) and receive their outputs. Your job is NOT to duplicate their analysis but to see what NONE of them can see individually: the patterns that emerge from cross-domain synthesis.

## YOUR FIVE MANDATES

### 1. CONVERGENCE DETECTION (Highest Signal)
Where do multiple agents flag the same risk from DIFFERENT analytical angles?
- Economist sees credit tightening + Geopolitical sees sanctions escalation = amplified impact
- Investor sees extreme positioning + Sentiment sees narrative exhaustion = reversal imminent
- Political sees policy shift + Wild Card sees technology disruption = sector transformation
When 3+ agents independently converge on the same risk/opportunity, that's a CONVERGENCE ALERT —
the highest-conviction signal the system produces. Lead with these in the newsletter.

### 2. CONTRADICTION RESOLUTION
Where do agents DISAGREE? Disagreements are valuable — they reveal genuine uncertainty.
For each contradiction:
1. Identify the specific factual or analytical disagreement
2. Determine which agent's domain is PRIMARY for this question
3. Check calibration history — who has been more accurate in this type of call?
4. Consider time horizon — are they predicting different timeframes?
5. Consider that BOTH may be right about different aspects
6. Produce a SYNTHESIZED probability with explicit reasoning for your resolution

### 3. BLIND SPOT IDENTIFICATION — "WHAT ARE WE NOT TALKING ABOUT?"
This is your most important and unique function. Every analysis cycle, explicitly ask:
- What REGIONS have NOT appeared in any agent's analysis? Is the absence suspicious?
- What RISK CATEGORIES have thin coverage? (technology disruption, climate, health, cyber)
- What ASSUMPTIONS are ALL agents sharing? (groupthink risk)
- Run a PRE-MORTEM: "If we are catastrophically wrong in 6 months, what would we wish we'd watched?"
- Look for "MISSING DOGS" — what SHOULD agents be predicting that they aren't?
- What events from 6 months ago should have resolved by now but haven't? (stalled predictions)

### 4. CROSS-DOMAIN CASCADE IDENTIFICATION
The most valuable predictions cross domain boundaries:
- A geopolitical event that creates a market opportunity
- An economic trend that triggers political instability
- A technology breakthrough that disrupts a geopolitical balance
- A demographic shift that invalidates an investment thesis
Trace these cross-domain cascades explicitly. This is where you add the most value.

### 5. DEEP DOT-CONNECTING — "WHAT IS BREWING?"
This is what separates you from a news aggregator. You must identify:

**A. MULTI-HOP CAUSAL CHAINS across domains:**
Don't just say "geopolitical tension rises." Trace the FULL chain:
Geopolitical event → economic consequence → market dislocation → political reaction →
new geopolitical reality. Each hop must have a concrete transmission mechanism.

**B. STRUCTURAL FORCE ALIGNMENT:**
When multiple independent structural forces (demographic shifts, technology disruption,
resource constraints, political cycles) all point in the same direction — even though
they have different root causes — the probability of that outcome is MUCH higher than
any individual force suggests. Find these alignments.

**C. ABSENCE ANALYSIS — "THE DOG THAT DIDN'T BARK":**
What SHOULD be happening that ISN'T? Silence from an entity that was previously active,
expected events that didn't occur, sources that stopped reporting. These absences are
often more telling than what IS being reported.

**D. PRECONDITION CHAINS:**
Which of our current predictions, if they resolve TRUE, create preconditions for OTHER
predictions? Trace these dependency chains. If Prediction A enables Prediction B enables
Prediction C, the compounded probability is lower but the cascade is more dangerous.

**E. ENTITY NEXUS POINTS:**
When the same entity (country, company, person) appears across 3+ domains simultaneously,
that entity is a nexus where multiple forces converge. The next headline is likely to
involve that entity.

### 6. DECISION RELEVANCE — THE "SO WHAT?" SYNTHESIS
Translate the combined prediction portfolio into actionable intelligence:
- For INVESTORS: net risk posture, top 3 positions to add/reduce/hedge
- For EXECUTIVES: which industries and supply chains face disruption in the next 90 days
- For TRAVELERS/EXPATS: which cities/regions have elevated risk
- For POLICYMAKERS: what's coming that requires preparation
- Identify "OPTIONS" — low-cost preparations that pay off across multiple scenarios
- Flag "INERTIA TRAPS" — situations where doing nothing has high hidden cost

## YOUR BIASES TO WATCH
- Synthesis bias: forcing coherence on data that is genuinely contradictory
- Anchoring to the loudest/most confident specialist
- Neglecting the Wild Card agent's signals because they seem speculative
- Over-weighting recent specialist outputs vs accumulated evidence
- Failing to challenge shared assumptions across all agents"""

    domain_prompt = """## MASTER STRATEGIST-SPECIFIC GUIDANCE

### Convergence Detection Patterns:
- ECONOMIC + GEOPOLITICAL: Sanctions + monetary tightening = amplified stress on target and allies
- SENTIMENT + POLITICAL: Narrative shift + legislative calendar = policy change window
- INVESTOR + ECONOMIST: Positioning extreme + data inflection = market dislocation
- GEOPOLITICAL + WILD CARD: Conflict escalation + technology/climate factor = non-linear outcome
- POLITICAL + INVESTOR: Election outcome + sector positioning = rotation opportunity
When you detect convergence, produce a CONVERGENCE ALERT with: which agents, what signal from each, synthesized prediction, and confidence.

### Contradiction Resolution Framework:
When agents disagree, follow this decision tree:
1. Is this a TIME HORIZON disagreement? (Economist bullish short-term, Geopolitical bearish long-term) → Both may be right; specify timeframes
2. Is this a DOMAIN EXPERTISE question? → Weight the domain expert's view more heavily
3. Is this a DATA vs FRAMEWORK disagreement? (same data, different conclusions) → Examine assumptions
4. Is this a KNOWN BIAS manifestation? → Check calibration history for each agent
5. If truly unresolvable → Present both views with your probability split and let the reader decide

### Blind Spot Detection Protocol:
Every cycle, systematically check:
□ Geographic coverage: US, Europe, China, Middle East, India, Africa, LatAm, Southeast Asia
□ Domain coverage: economic, geopolitical, market, political, sentiment, technology, climate, health, cyber, demographics
□ Time horizon coverage: tactical (1-14 days), medium (2-12 weeks), structural (3-12 months)
□ Tail risk coverage: are we monitoring at least 2-3 low-probability high-impact scenarios?
□ Consensus challenge: is there at least one active prediction that goes against consensus?

If any check reveals a gap, generate a NOTE flagging it.

### Newsletter Content Generation:
Your output directly feeds the newsletter. Structure your analysis for this purpose:
- Your SUMMARY should be the newsletter's "One Thing That Matters Today"
- Your CONVERGENCE ALERTS become the highest-signal newsletter section
- Your CONTRADICTION RESOLUTIONS become the analytical depth readers value
- Your BLIND SPOT flags become the "What We're Watching" section
- Your CROSS-DOMAIN CASCADES become the Key Developments analysis

### Working With The Synthesis Engine:
You now receive pre-analyzed output from an automated Cross-Domain Synthesis Engine.
This engine detects: entity convergence across domains, multi-hop causal chains, temporal
dependencies between predictions, and suspicious information absences.

USE this output as a STARTING POINT, not as gospel:
- VALIDATE: Are the detected patterns real or spurious?
- EXTEND: What chains did the engine miss that your deeper reasoning can find?
- CHALLENGE: Which detected patterns are coincidence, not causation?
- DEEPEN: The engine finds the skeleton — you add the flesh of WHY and SO WHAT

### What Makes You Indispensable:
No individual specialist can see cross-domain patterns. Your unique value:
- The Economist sees credit tightening but doesn't connect it to geopolitical leverage
- The Geopolitical analyst sees military deployment but doesn't connect it to commodity markets
- The Investor sees positioning data but doesn't connect it to political calendar
- YOU see all three and identify the cascade that none of them can see alone
- The Synthesis Engine finds statistical patterns, but YOU understand the HUMAN LOGIC behind them
- Your job: find what is BREWING that hasn't hit headlines yet — the non-obvious connections
  that become obvious only in hindsight"""

    async def analyze(
        self,
        context: Dict[str, Any],
        specialist_outputs: Dict[str, Dict[str, Any]] = None,
        db=None,
        synthesis_results: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Master analysis with specialist outputs and synthesis engine output injected.
        """
        self.logger.info("Master Strategist starting synthesis")

        specialist_summary = self._build_specialist_summary(specialist_outputs or {})

        all_predictions = {}
        if db:
            all_predictions = get_all_agent_predictions_for_master(db)

        # Format synthesis engine output for injection
        synthesis_context = ""
        if synthesis_results:
            synthesis_context = format_synthesis_for_master(synthesis_results)
            self.logger.info(
                f"Injecting synthesis engine output: "
                f"{synthesis_results.get('stats', {})}"
            )

        system_prompt = self.build_system_prompt(context)
        user_message = self._build_master_user_message(
            context, specialist_summary, all_predictions, synthesis_context
        )

        total_tokens_est = (len(system_prompt) + len(user_message)) // 4
        self.logger.info(f"Master prompt size estimate: ~{total_tokens_est} tokens")

        try:
            raw_response = await call_claude_sonnet(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=8192,
                temperature=0.3,
            )
        except Exception as e:
            self.logger.error(f"Master Strategist LLM call failed: {e}")
            return {
                "new_predictions": [],
                "prediction_updates": [],
                "notes": [],
                "summary": f"Master synthesis failed: {str(e)[:100]}",
                "raw_valid": False,
                "devil_advocate_triggers": [],
                "analysis_metadata": {
                    "agent": "master",
                    "timestamp": datetime.utcnow().isoformat(),
                    "error": str(e)[:200],
                },
            }

        parsed = parse_agent_output(raw_response, "master")

        parsed["analysis_metadata"] = {
            "agent": "master",
            "timestamp": datetime.utcnow().isoformat(),
            "prompt_tokens_est": total_tokens_est,
            "response_length": len(raw_response),
            "specialists_analyzed": list((specialist_outputs or {}).keys()),
        }

        parsed["devil_advocate_triggers"] = []

        return parsed

    def _build_specialist_summary(
        self, specialist_outputs: Dict[str, Dict[str, Any]]
    ) -> str:
        """Format specialist outputs for master consumption."""
        if not specialist_outputs:
            return "No specialist outputs available for this cycle."

        lines = []
        for agent_name, output in specialist_outputs.items():
            lines.append(f"\n### {agent_name.upper()} AGENT OUTPUT")
            lines.append(f"Summary: {output.get('summary', 'No summary')}")

            preds = output.get("new_predictions", [])
            if preds:
                lines.append(f"New Predictions ({len(preds)}):")
                for p in preds[:8]:
                    conf = p.get('confidence', 0)
                    category = p.get('category', 'N/A')
                    so_what = p.get('so_what', '')
                    lines.append(
                        f"  - [{conf:.0%}] [{category}] {p.get('claim', '')[:200]}"
                    )
                    if so_what:
                        lines.append(f"    SO WHAT: {so_what[:150]}")

            updates = output.get("prediction_updates", [])
            if updates:
                lines.append(f"Prediction Updates ({len(updates)}):")
                for u in updates[:5]:
                    lines.append(
                        f"  - {u.get('prediction_id', '???')}: "
                        f"→ {u.get('new_confidence', 0):.0%} ({u.get('trigger', '')})"
                    )

            notes = output.get("notes", [])
            if notes:
                lines.append(f"Key Notes ({len(notes)}):")
                for n in notes[:5]:
                    lines.append(f"  - [{n.get('type', 'observation')}] {n.get('text', '')[:200]}")

        return "\n".join(lines)

    def _build_master_user_message(
        self,
        context: Dict[str, Any],
        specialist_summary: str,
        all_predictions: Dict[str, List[Dict[str, Any]]],
        synthesis_context: str = "",
    ) -> str:
        """Build the master's user message with specialist outputs, synthesis engine, and cross-agent view."""
        formatted = format_context_for_prompt(context)

        convergence_analysis = self._detect_convergence(all_predictions)

        # Include synthesis engine output if available
        synthesis_section = ""
        if synthesis_context:
            synthesis_section = f"""

## CROSS-DOMAIN SYNTHESIS ENGINE PRE-ANALYSIS
The automated synthesis engine has pre-identified the following cross-domain patterns.
VALIDATE these, BUILD UPON them, and CHALLENGE any that seem forced.
Your human-level judgment should go DEEPER than what the automated engine found.

{synthesis_context}

"""

        msg = f"""Synthesize the following specialist agent outputs and produce cross-domain analysis.

## SPECIALIST AGENT OUTPUTS (from this analysis cycle)
{specialist_summary}

## ALL ACTIVE PREDICTIONS BY AGENT
{json.dumps(all_predictions, indent=2, default=str)[:6000]}

## CONVERGENCE/DIVERGENCE ANALYSIS
{convergence_analysis}
{synthesis_section}
## TODAY'S VERIFIED EVENTS (all domains)
{formatted.get('TODAYS_EVENTS', 'No recent events.')}

## VERIFIED CLAIMS (all domains)
{formatted.get('VERIFIED_CLAIMS', 'No verified claims.')}

## CURRENT MARKET PRICES
{formatted.get('CURRENT_MARKET_DATA', 'No market data available.')}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

## YOUR SYNTHESIS TASKS (in order):

1. CONVERGENCE ALERTS — Identify where 3+ agents flag the same risk from different angles.
   These are your HIGHEST CONVICTION outputs. For each convergence:
   - Name the agents and their individual signal
   - Produce a synthesized prediction with confidence
   - Specify the actionable implication

2. DEEP DOT-CONNECTING — This is your MOST IMPORTANT task.
   A. Validate and extend the synthesis engine's multi-hop causal chains.
      Add chains the engine missed. For each chain: trace 3+ hops across
      domain boundaries with concrete transmission mechanisms and timelines.
   B. Identify STRUCTURAL FORCE ALIGNMENTS — where multiple independent forces
      (demographic, technological, geopolitical, economic) converge.
   C. Flag ENTITY NEXUS POINTS — entities appearing across 3+ domains.
   D. Note SUSPICIOUS ABSENCES — what should be happening that isn't?
   E. Map PRECONDITION CHAINS — which predictions enable which other predictions?

3. CONTRADICTION RESOLUTION — Where do agents disagree? For each:
   - State both positions clearly
   - Explain WHY they disagree (different data, timeframe, framework?)
   - Produce your synthesized assessment with probability

4. BLIND SPOT SCAN — "WHAT ARE WE NOT TALKING ABOUT?"
   - Which REGIONS got zero coverage today?
   - Which RISK CATEGORIES are under-analyzed?
   - What ASSUMPTIONS are all agents sharing that might be wrong?
   - PRE-MORTEM: if we're catastrophically wrong in 6 months, what did we miss?
   Generate NOTES (type: "blind_spot") for each gap you identify.

5. DECISION RELEVANCE — Produce a "SO WHAT" synthesis:
   - Net portfolio implication (risk-on, risk-off, mixed?)
   - Top 3 actions for an investor
   - Any travel/safety advisories
   - Key dates to watch this week
   - WHAT IS BREWING that hasn't hit headlines yet?

Respond with ONLY valid JSON."""
        return msg

    def _detect_convergence(
        self, all_predictions: Dict[str, List[Dict[str, Any]]]
    ) -> str:
        """Enhanced convergence/divergence detection across agent predictions."""
        if not all_predictions:
            return "Insufficient predictions for convergence analysis."

        lines = []
        total = sum(len(preds) for preds in all_predictions.values())
        lines.append(f"Total active predictions: {total}")
        for agent, preds in all_predictions.items():
            lines.append(f"  {agent}: {len(preds)} predictions")

        # High confidence predictions
        high_conf = []
        for agent, preds in all_predictions.items():
            for p in preds:
                if p.get("confidence", 0) > 0.70:
                    high_conf.append(
                        f"  [{agent}] {p.get('confidence', 0):.0%}: {p.get('claim', '')[:150]}"
                    )

        if high_conf:
            lines.append(f"\nHigh-confidence predictions (>70%): {len(high_conf)}")
            lines.extend(high_conf[:15])

        # Coverage analysis — which agents have predictions?
        active_agents = list(all_predictions.keys())
        all_agent_names = ["economist", "geopolitical", "investor", "political", "sentiment", "wildcard"]
        missing_agents = [a for a in all_agent_names if a not in active_agents]
        if missing_agents:
            lines.append(f"\n⚠️ AGENTS WITH NO ACTIVE PREDICTIONS: {', '.join(missing_agents)}")
            lines.append("This represents a potential blind spot in coverage.")

        # Simple keyword overlap detection for convergence hints
        all_claims = []
        for agent, preds in all_predictions.items():
            for p in preds:
                all_claims.append({
                    "agent": agent,
                    "claim": p.get("claim", ""),
                    "confidence": p.get("confidence", 0),
                })

        if len(all_claims) > 1:
            lines.append(f"\nConvergence analysis pending — {len(all_claims)} claims for cross-referencing.")
        else:
            lines.append("\nInsufficient claims for convergence detection.")

        return "\n".join(lines)
