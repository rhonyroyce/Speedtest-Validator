"""Text utilities — LLM output sanitization and formatting.

Handles the messy reality of LLM-generated text:
- Strip <think>...</think> tags from qwen3-vl output
- Remove markdown code fences (```json ... ```)
- Clean Unicode artifacts (BOM, zero-width spaces, smart quotes)
- Extract JSON from mixed text output
- Normalize whitespace

Implementation: Claude Code Prompt 2 (Ollama Client) — shared utility
"""
import re
import json


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output.

    qwen3-vl:8b frequently wraps reasoning in think tags before JSON output.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ``` or ``` ... ```).

    LLMs often wrap JSON in code blocks even when instructed not to.
    """
    # Match ```json\n...\n``` or ```\n...\n``` (with optional language tag)
    return re.sub(r"```(?:\w+)?\s*\n?(.*?)\n?\s*```", r"\1", text, flags=re.DOTALL).strip()


def clean_unicode(text: str) -> str:
    """Remove Unicode artifacts that break JSON parsing.

    Common issues: BOM (\\ufeff), zero-width spaces (\\u200b),
    smart quotes (\u2018\u2019\u201c\u201d → ''\"\"), non-breaking spaces.
    """
    # Remove BOM and zero-width characters
    text = text.replace("\ufeff", "")
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufffe]", "", text)
    # Replace smart quotes with ASCII
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Non-breaking space → regular space
    text = text.replace("\u00a0", " ")
    return text


def extract_json(text: str) -> dict | list | None:
    """Extract and parse JSON from potentially messy LLM output.

    Applies sanitization pipeline: think tags → markdown fences → unicode → parse.
    Falls back to finding first { or [ and matching to last } or ].

    Args:
        text: Raw LLM output string

    Returns:
        Parsed JSON object/array, or None if no valid JSON found
    """
    cleaned = strip_thinking_tags(text)
    cleaned = strip_markdown_fences(cleaned)
    cleaned = clean_unicode(cleaned)

    # Try direct parse
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: find first {/[ to last }/]
    for open_char, close_char in [("{", "}"), ("[", "]")]:
        start = cleaned.find(open_char)
        end = cleaned.rfind(close_char)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                continue

    return None


def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into single spaces, strip edges."""
    return re.sub(r"\s+", " ", text).strip()


def truncate_for_cell(text: str, max_chars: int = 32767) -> str:
    """Truncate text to fit in an Excel cell (max 32,767 characters).

    Preserves complete sentences where possible.

    Args:
        text: Input text
        max_chars: Maximum character count (Excel limit = 32767)

    Returns:
        Truncated text with '...' suffix if truncated
    """
    if len(text) <= max_chars:
        return text
    truncated = text[: max_chars - 3]
    # Try to break at last sentence boundary
    last_period = truncated.rfind(".")
    if last_period > max_chars * 0.8:
        return truncated[: last_period + 1]
    return truncated + "..."
