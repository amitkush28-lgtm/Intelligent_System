"""
LLM client wrappers for Claude (agents), Gemini (devil's advocate), and web search.
All services use these instead of direct API calls.

IMPORTANT: All Claude calls use AsyncAnthropic to avoid blocking the FastAPI event loop.
Gemini calls are wrapped in asyncio.to_thread since the google-genai SDK is synchronous.
"""

import asyncio
import json
import logging
from typing import Optional

import anthropic

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_async_anthropic_client: Optional[anthropic.AsyncAnthropic] = None


def _get_async_anthropic() -> anthropic.AsyncAnthropic:
    global _async_anthropic_client
    if _async_anthropic_client is None:
        _async_anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _async_anthropic_client


async def call_claude_sonnet(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 8192,
    temperature: float = 0.3,
) -> str:
    """Primary agent analysis via Claude (Sonnet or Haiku depending on config)."""
    try:
        client = _get_async_anthropic()
        response = await client.messages.create(
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
        client = _get_async_anthropic()
        response = await client.messages.create(
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
    """Devil's advocate via Gemini (different model = genuine adversarial tension).
    Wrapped in asyncio.to_thread since google-genai SDK is synchronous."""
    def _sync_call():
        from google import genai
        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-04-17",
            contents=f"{system_prompt}\n\n{user_message}",
        )
        return response.text

    try:
        return await asyncio.to_thread(_sync_call)
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
        client = _get_async_anthropic()
        response = await client.messages.create(
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
    """Extract JSON from LLM response, handling markdown fences, mixed content, and truncation."""
    import re

    if not response_text or not response_text.strip():
        return {}

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
    except json.JSONDecodeError:
        pass

    # Strategy 5: Truncated JSON recovery — if the response was cut off mid-JSON,
    # try to close open structures and salvage what we can
    recovered = _recover_truncated_json(text)
    if recovered:
        return recovered

    logger.warning(f"Failed to parse JSON from LLM response after all strategies")
    logger.debug(f"Raw response (first 500 chars): {response_text[:500]}")
    logger.debug(f"Raw response (last 200 chars): {response_text[-200:]}")
    return {}


def _recover_truncated_json(text: str) -> dict:
    """
    Attempt to recover a truncated JSON response by closing open structures.
    This handles the common case where max_tokens cuts off mid-response.
    """
    # Find the start of the JSON object
    first_brace = text.find('{')
    if first_brace == -1:
        return {}

    json_text = text[first_brace:]

    # Try progressively more aggressive truncation repair
    # Step 1: Try closing with just braces/brackets
    for attempt in range(20):
        # Count open structures
        in_string = False
        escape_next = False
        open_braces = 0
        open_brackets = 0

        for ch in json_text:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                open_braces += 1
            elif ch == '}':
                open_braces -= 1
            elif ch == '[':
                open_brackets += 1
            elif ch == ']':
                open_brackets -= 1

        if open_braces == 0 and open_brackets == 0:
            # Already balanced — shouldn't be here, but try parse
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                break

        # Try to close the JSON by removing the last incomplete element and closing
        # First, trim trailing incomplete content (partial strings, trailing commas)
        trimmed = json_text.rstrip()

        # Remove trailing incomplete content
        while trimmed and trimmed[-1] in (',', ':', '"', ' ', '\n', '\r', '\t'):
            trimmed = trimmed[:-1].rstrip()

        # If we end in the middle of a string value, find and close it
        if trimmed and trimmed[-1] not in ('}', ']', '"', 'e', 'l'):
            # We're in the middle of something, try to find last complete element
            # Look for last valid JSON boundary
            for boundary in ['},', '},\n', '}\n', ']', '",', '"\n']:
                last_boundary = trimmed.rfind(boundary)
                if last_boundary > 0:
                    trimmed = trimmed[:last_boundary + len(boundary)].rstrip().rstrip(',')
                    break

        # Close remaining open structures
        closers = ']' * max(0, open_brackets) + '}' * max(0, open_braces)

        # Try various truncation points
        candidate = trimmed + closers
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                logger.info(f"Recovered truncated JSON (closed {open_braces} braces, {open_brackets} brackets)")
                return parsed
        except json.JSONDecodeError:
            pass

        # Try trimming more aggressively — remove last entry in array/object
        last_comma = trimmed.rfind(',')
        if last_comma > 0:
            json_text = trimmed[:last_comma] + closers
            try:
                parsed = json.loads(json_text)
                if isinstance(parsed, dict):
                    logger.info(f"Recovered truncated JSON by removing last incomplete element")
                    return parsed
            except json.JSONDecodeError:
                json_text = trimmed[:last_comma]
                continue

        break

    return {}
