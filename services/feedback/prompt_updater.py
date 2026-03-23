"""
Prompt updater — generates calibration adjustments and updates agent_prompts table.

On bias finding: create new AgentPrompt version with updated calibration_notes
and reasoning_guidance. Increment version number, set active=True on new,
active=False on old.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from shared.database import get_db_session
from shared.models import AgentPrompt
from services.feedback.bias_detector import (
    BiasDetection,
    format_biases_as_calibration_notes,
    format_biases_as_reasoning_guidance,
)

logger = logging.getLogger(__name__)

AGENTS = ["geopolitical", "economist", "investor", "political", "sentiment", "master"]


def update_agent_prompts(biases_by_agent: Dict[str, List[BiasDetection]]) -> Dict[str, Any]:
    """
    Update agent prompts based on detected biases.
    Creates new AgentPrompt versions with updated calibration notes and reasoning guidance.

    Args:
        biases_by_agent: Dict mapping agent name to list of detected biases.

    Returns:
        Stats about what was updated.
    """
    stats = {
        "agents_updated": 0,
        "versions_created": 0,
        "agents_unchanged": 0,
        "errors": 0,
    }

    try:
        with get_db_session() as db:
            for agent in AGENTS:
                agent_biases = biases_by_agent.get(agent, [])

                try:
                    updated = _update_single_agent(db, agent, agent_biases)
                    if updated:
                        stats["agents_updated"] += 1
                        stats["versions_created"] += 1
                    else:
                        stats["agents_unchanged"] += 1
                except Exception as e:
                    logger.error(f"Error updating prompts for agent {agent}: {e}")
                    stats["errors"] += 1

            db.flush()

    except Exception as e:
        logger.error(f"Failed to update agent prompts: {e}")
        stats["errors"] += 1

    if stats["agents_updated"] > 0:
        logger.info(
            f"Prompt updates: {stats['agents_updated']} agents updated, "
            f"{stats['versions_created']} new versions created"
        )

    return stats


def _update_single_agent(
    db: Session,
    agent: str,
    biases: List[BiasDetection],
) -> bool:
    """
    Update a single agent's prompt if biases warrant changes.
    Returns True if a new version was created.
    """
    # Generate new calibration notes and reasoning guidance
    new_calibration_notes = format_biases_as_calibration_notes(biases)
    new_reasoning_guidance = format_biases_as_reasoning_guidance(biases)

    # Get current active prompt
    current_prompt = (
        db.query(AgentPrompt)
        .filter(
            AgentPrompt.agent == agent,
            AgentPrompt.active == True,
        )
        .order_by(AgentPrompt.version.desc())
        .first()
    )

    # Check if notes have actually changed
    if current_prompt:
        if (
            current_prompt.calibration_notes == new_calibration_notes
            and current_prompt.reasoning_guidance == new_reasoning_guidance
        ):
            return False  # No change needed

        # Check if we have biases but they're the same as existing
        if not biases and not current_prompt.calibration_notes:
            return False

    # If no biases detected, clear existing notes
    if not biases:
        if current_prompt and (
            current_prompt.calibration_notes or current_prompt.reasoning_guidance
        ):
            new_calibration_notes = ""
            new_reasoning_guidance = ""
        else:
            return False

    # Determine new version number
    if current_prompt:
        new_version = current_prompt.version + 1
        prompt_text = current_prompt.prompt_text
    else:
        new_version = 1
        prompt_text = f"System prompt for {agent} agent (auto-generated)"

    # Deactivate old versions
    db.query(AgentPrompt).filter(
        AgentPrompt.agent == agent,
        AgentPrompt.active == True,
    ).update({"active": False})

    # Create new version
    new_prompt = AgentPrompt(
        agent=agent,
        version=new_version,
        prompt_text=prompt_text,
        calibration_notes=new_calibration_notes if new_calibration_notes else None,
        reasoning_guidance=new_reasoning_guidance if new_reasoning_guidance else None,
        created_at=datetime.utcnow(),
        active=True,
    )
    db.add(new_prompt)

    logger.info(
        f"Created prompt version {new_version} for agent '{agent}' "
        f"with {len(biases)} bias adjustments"
    )

    return True


def get_current_prompt_versions() -> Dict[str, int]:
    """Get current active prompt version for each agent."""
    versions = {}
    try:
        with get_db_session() as db:
            for agent in AGENTS:
                prompt = (
                    db.query(AgentPrompt)
                    .filter(
                        AgentPrompt.agent == agent,
                        AgentPrompt.active == True,
                    )
                    .order_by(AgentPrompt.version.desc())
                    .first()
                )
                versions[agent] = prompt.version if prompt else 0
    except Exception as e:
        logger.error(f"Failed to get prompt versions: {e}")
    return versions
