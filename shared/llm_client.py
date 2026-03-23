"""
LLM client wrappers for Claude Haiku (primary agents + bulk ops)
and Gemini (devil's advocate). All services use these instead of direct API calls.
"""

import json
import logging
from typing import Optional

import anthropic
from google import genai
from google.genai import types

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize clients lazily
_anthropic_client: Optional[anthropic.Anthropic] = None
_gemini_client: Optional[genai.Client] = None


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


def _get_gemini() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    return _gemini_client


async def call_claude_sonnet(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Primary agent analysis via Claude (Haiku for cost savings, Sonnet when upgraded)."""
    try:
        client = _get_anthropic()
        response = client.messages.create(
            model=settings.CLAUDE_SONNET_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except anthropic.APIError as e:
        logger.error(f"Claude Sonnet API error: {e}")
        raise
    except Exception as e:
        logger.error(f"Claude Sonnet unexpected error: {e}")
        raise


async def call_claude_haiku(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str:
    """Bulk operations via Claude Haiku — classification, sentiment, sponsored detection."""
    try:
        client = _get_anthropic()
        response = client.messages.create(
            model=settings.CLAUDE_HAIKU_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except anthropic.APIError as e:
        logger.error(f"Claude Haiku API error: {e}")
        raise
    except Exception as e:
        logger.error(f"Claude Haiku unexpected error: {e}")
        raise


async def call_gpt4o(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
) -> str:
    """Devil's advocate challenges via Gemini (different model provider = genuine adversarial tension)."""
    try:
        client = _get_gemini()
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=f"{user_message}",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        raise


async def call_claude_with_web_search(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
) -> str:
    """Claude with web search tool enabled — used by verification engine and weak signal scanner."""
    try:
        client = _get_anthropic()
        response = client.messages.create(
            model=settings.CLAUDE_SONNET_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_message}],
        )
        # Extract text content from potentially multi-block response
        text_parts = [block.text for block in response.content if hasattr(block, "text")]
        return "\n".join(text_parts)
    except anthropic.APIError as e:
        logger.error(f"Claude web search API error: {e}")
        raise
    except Exception as e:
        logger.error(f"Claude web search unexpected error: {e}")
        raise


def parse_structured_json(response_text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    text = response_text.strip()
    # Strip markdown code fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from LLM response: {e}")
        logger.debug(f"Raw response: {response_text[:500]}")
        return {}
