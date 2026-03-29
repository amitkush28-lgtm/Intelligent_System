"""
LLM client wrappers for Claude (agents), Gemini (devil's advocate), and web search.
All services use these instead of direct API calls.
"""

import json
import logging
from typing import Optional

import anthropic

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_anthropic_client: Optional[anthropic.Anthropic] = None


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


async def call_claude_sonnet(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 8192,
    temperature: float = 0.3,
) -> str:
    """Primary agent analysis via Claude (Sonnet or Haiku depending on config)."""
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
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """Bulk operations via Claude Haiku."""
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


async def call_devil_advocate(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
) -> str:
    """Devil's advocate via Gemini (different model = genuine adversarial tension)."""
    try:
        from google import genai
        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-04-17",
            contents=f"{system_prompt}\n\n{user_message}",
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        raise


async def call_gpt4o(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
) -> str:
    """Alias for devil_advocate — uses Gemini."""
    return await call_devil_advocate(system_prompt, user_message, max_tokens, temperature)


async def call_claude_with_web_search(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 8192,
) -> str:
    """Claude with web search tool enabled."""
    try:
        client = _get_anthropic()
        response = client.messages.create(
            model=settings.CLAUDE_SONNET_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_message}],
        )
        text_parts = [block.text for block in response.content if hasattr(block, "text")]
        return "\n".join(text_parts)
    except anthropic.APIError as e:
        logger.error(f"Claude web search API error: {e}")
        raise
    except Exception as e:
        logger.error(f"Claude web search unexpected error: {e}")
        raise


def parse_structured_json(response_text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences and mixed content."""
    import re

    text = response_text.strip()

    # Strategy 1: Try direct parse (clean response)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from markdown code fences
    fence_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find the largest JSON object in the response
    # Look for { ... } blocks and try to parse them
    brace_depth = 0
    start_idx = None
    best_json = None
    best_len = 0

    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                start_idx = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and start_idx is not None:
                candidate = text[start_idx:i + 1]
                if len(candidate) > best_len:
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            best_json = parsed
                            best_len = len(candidate)
                    except json.JSONDecodeError:
                        pass
                start_idx = None

    if best_json:
        return best_json

    # Strategy 4: Strip common prefixes/suffixes and retry
    for prefix in ["```json", "```", "Here is the JSON:", "Here's the analysis:"]:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):]
    for suffix in ["```"]:
        if text.endswith(suffix):
            text = text[:-len(suffix)]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from LLM response: {e}")
        logger.debug(f"Raw response: {response_text[:500]}")
        return {}
