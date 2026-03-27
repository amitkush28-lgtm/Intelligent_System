"""
Master Strategist Agent — Synthesis agent that runs AFTER all 5 specialists.

Reconciles disagreements between specialists, produces final predictions with
cross-agent confidence weighting, identifies convergence (multiple agents flagging
same risk), contradiction (agents disagreeing), and blind spots (thin coverage areas).
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

logger = logging.getLogger(__name__)
settings = get_settings()


class MasterAgent(BaseAgent):
    agent_name = "master"

    role_description = """You are the MASTER STRATEGIST — the synthesis agent in a multi-agent intelligence system.

You run AFTER all 5 specialist agents (Geopolitical, Economist, Investor, Political, Sentiment) and receive their outputs. Your role is NOT to duplicate their analysis but to:

1. CONVERGENCE DETECTION: Where do multiple agents flag the same risk from different angles? Convergence across domains is the strongest possible signal.

2. CONTRADICTION RESOLUTION: Where do agents disagree? Analyze WHY they disagree — different data, different frameworks, different time horizons — and produce a synthesized probability.

3. BLIND SPOT IDENTIFICATION: What are the specialists NOT covering? Look for:
   - Cross-domain risks that fall between specialist boundaries
   - Tail risks no individual specialist flags
   - Interaction effects between domains (e.g., geopolitical tension + monetary tightening)
   - Second-order effects that cross domain boundaries

4. CONFIDENCE WEIGHTING: Adjust specialist predictions based on each agent's calibration track record. An economist with good calibration on inflation predictions gets more weight than one with poor calibration.

5. DECISION RELEVANCE: Translate the prediction portfolio into actionable intelligence. What decisions should a reader make based on the combined analysis?

You produce THREE types of output:
- SYNTHESIS PREDICTIONS: new predictions that emerge from cross-domain analysis
- ADJUSTED PREDICTIONS: specialist predictions you modify based on synthesis
- STRATEGIC NOTES: observations about the system's overall analytical posture"""

    domain_prompt = """## MASTER STRATEGIST-SPECIFIC GUIDANCE

Your unique value is pattern recognition ACROSS domains:

CONVERGENCE PATTERNS TO WATCH:
- Economist sees credit tightening + Geopolitical sees sanctions escalation = amplified economic impact
- Sentiment sees narrative shift + Political sees legislative movement = policy change imminent
- Investor sees positioning extreme + Economist sees data inflection = market dislocation risk
- Geopolitical sees alliance shift + Sentiment sees public opinion change = strategic realignment

CONTRADICTION RESOLUTION FRAMEWORK:
When agents disagree:
1. Identify the specific factual or analytical disagreement
2. Check which agent's domain is primary for this question
3. Check calibration history — who has been more accurate in this type of call?
4. Consider time horizon — are they predicting different timeframes?
5. Consider the possibility BOTH are right about different aspects

BLIND SPOT DETECTION:
- Run a "pre-mortem": if we are catastrophically wrong in 6 months, what would we wish we'd watched?
- Check for "missing dogs" — what SHOULD agents be predicting that they aren't?
- Look for domains with thin prediction coverage
- Identify assumptions shared by ALL agents (groupthink risk)

DECISION RELEVANCE:
- For each high-confidence prediction, specify: who should act, what action, when
- Identify "options" — low-cost preparations that pay off across multiple scenarios
- Flag "inertia traps" — situations where doing nothing has high hidden cost"""

    async def analyze(
        self,
        context: Dict[str, Any],
        specialist_outputs: Dict[str, Dict[str, Any]] = None,
        db=None,
    ) -> Dict[str, Any]:
        """
        Master analysis with specialist outputs injected.

        Unlike specialist agents, the master receives all specialist outputs
        and performs cross-domain synthesis.
        """
        self.logger.info("Master Strategist starting synthesis")

        # Build specialist summary
        specialist_summary = self._build_specialist_summary(specialist_outputs or {})

        # Get all predictions grouped by agent for convergence/contradiction detection
        all_predictions = {}
        if db:
            all_predictions = get_all_agent_predictions_for_master(db)

        system_prompt = self.build_system_prompt(context)
        user_message = self._build_master_user_message(
            context, specialist_summary, all_predictions
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

        # Master doesn't trigger devil's advocate on itself — specialists do that
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
                for p in preds[:5]:
                    lines.append(
                        f"  - [{p.get('confidence', 0):.0%}] {p.get('claim', '')[:200]}"
                    )

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
                for n in notes[:3]:
                    lines.append(f"  - [{n.get('type', 'observation')}] {n.get('text', '')[:150]}")

        return "\n".join(lines)

    def _build_master_user_message(
        self,
        context: Dict[str, Any],
        specialist_summary: str,
        all_predictions: Dict[str, List[Dict[str, Any]]],
    ) -> str:
        """Build the master's user message with specialist outputs and cross-agent view."""
        formatted = format_context_for_prompt(context)

        # Build prediction convergence/divergence map
        convergence_analysis = self._detect_convergence(all_predictions)

        msg = f"""Synthesize the following specialist agent outputs and produce cross-domain analysis.

## SPECIALIST AGENT OUTPUTS (from this analysis cycle)
{specialist_summary}

## ALL ACTIVE PREDICTIONS BY AGENT
{json.dumps(all_predictions, indent=2, default=str)[:4000]}

## CONVERGENCE/DIVERGENCE ANALYSIS
{convergence_analysis}

## TODAY'S VERIFIED EVENTS (all domains)
{formatted.get('TODAYS_EVENTS', 'No recent events.')}

## VERIFIED CLAIMS (all domains)
{formatted.get('VERIFIED_CLAIMS', 'No verified claims.')}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}

Perform your synthesis:
1. Identify convergence — where multiple agents see the same risk from different angles
2. Resolve contradictions — where agents disagree, provide your synthesized assessment
3. Detect blind spots — what should agents be watching that they aren't?
4. Produce synthesis predictions that emerge from cross-domain patterns
5. Provide strategic notes on the system's analytical posture

Respond with ONLY valid JSON."""
        return msg

    def _detect_convergence(
        self, all_predictions: Dict[str, List[Dict[str, Any]]]
    ) -> str:
        """Basic convergence/divergence detection across agent predictions."""
        if not all_predictions:
            return "Insufficient predictions for convergence analysis."

        lines = []
        total = sum(len(preds) for preds in all_predictions.values())
        lines.append(f"Total active predictions: {total}")
        for agent, preds in all_predictions.items():
            lines.append(f"  {agent}: {len(preds)} predictions")

        # Check for high-confidence cluster
        high_conf = []
        for agent, preds in all_predictions.items():
            for p in preds:
                if p.get("confidence", 0) > 0.75:
                    high_conf.append(f"  [{agent}] {p.get('confidence', 0):.0%}: {p.get('claim', '')[:120]}")

        if high_conf:
            lines.append(f"\nHigh-confidence predictions ({len(high_conf)}):")
            lines.extend(high_conf[:10])
        else:
            lines.append("\nNo high-confidence predictions (>75%) currently active.")

        return "\n".join(lines)
