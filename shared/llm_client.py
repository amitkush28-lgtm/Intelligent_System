"""
LLM client wrappers for Claude Sonnet (primary agents), Claude Haiku (bulk ops),
and GPT-4o (devil's advocate). All services use these instead of direct API calls.
"""

import json
import logging
from typing import Optional

import anthropic
import openai

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize clients lazily
_anthropic_client: Optional[anthropic.Anthropic] = None
_openai_client: Optional[openai.OpenAI] = None


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


def _get_openai() -> openai.OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


async def call_claude_sonnet(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Primary agent analysis via Claude Sonnet."""
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
    """Devil's advocate challenges via GPT-4o (different model bias = genuine adversarial tension)."""
    try:
        client = _get_openai()
        response = client.chat.completions.create(
            model=settings.GPT4O_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content
    except openai.APIError as e:
        logger.error(f"GPT-4o API error: {e}")
        raise
    except Exception as e:
        logger.error(f"GPT-4o unexpected error: {e}")
        raise


async def call_claude_with_web_search(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
) -> str:
    """Claude Sonnet with web search tool enabled — used by verification engine and weak signal scanner."""
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
