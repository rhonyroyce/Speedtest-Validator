"""Text utilities — LLM output sanitization and formatting.

Handles the messy reality of LLM-generated text:
- Strip <think>...</think> tags from qwen3-vl output
- Remove markdown code fences (```json ... ```)
- Clean Unicode artifacts (BOM, zero-width spaces, smart quotes)
- Extract JSON from mixed text output
- Normalize whitespace

Implementation: Claude Code Prompt 3 (Screenshot Parser) — shared utility
"""
import re
import json


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output.

    qwen3-vl:8b frequently wraps reasoning in think tags before JSON output.
    """
    # TODO: Implement regex to strip <think>...</think> (including multiline)
    # Pattern: <think>.*?</think> with re.DOTALL flag
    raise NotImplementedError("Implement in Claude Code Prompt 3")


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ``` or ``` ... ```).

    LLMs often wrap JSON in code blocks even when instructed not to.
    """
    # TODO: Implement regex to strip ```json\n...\n``` and ```\n...\n```
    raise NotImplementedError("Implement in Claude Code Prompt 3")


def clean_unicode(text: str) -> str:
    """Remove Unicode artifacts that break JSON parsing.

    Common issues: BOM (\\ufeff), zero-width spaces (\\u200b),
    smart quotes (\u2018\u2019\u201c\u201d → ''\"\"), non-breaking spaces.
    """
    # TODO: Implement Unicode cleanup
    # - Remove BOM, zero-width chars
    # - Replace smart quotes with ASCII equivalents
    # - Normalize whitespace (NBSP → space)
    raise NotImplementedError("Implement in Claude Code Prompt 3")


def extract_json(text: str) -> dict | list | None:
    """Extract and parse JSON from potentially messy LLM output.

    Applies sanitization pipeline: think tags → markdown fences → unicode → parse.
    Falls back to finding first { or [ and matching to last } or ].

    Args:
        text: Raw LLM output string

    Returns:
        Parsed JSON object/array, or None if no valid JSON found
    """
    # TODO: Implement extraction pipeline
    # 1. strip_thinking_tags()
    # 2. strip_markdown_fences()
    # 3. clean_unicode()
    # 4. Try json.loads() on cleaned text
    # 5. If fails, find first {/[ and last }/] and try parsing that substring
    # 6. Return parsed object or None
    raise NotImplementedError("Implement in Claude Code Prompt 3")


def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into single spaces, strip edges."""
    # TODO: Implement
    raise NotImplementedError("Implement in Claude Code Prompt 3")


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
