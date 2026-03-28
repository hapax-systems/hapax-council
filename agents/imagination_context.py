"""Imagination context formatter — salience-graded Current Thoughts for conversation LLM.

Reads the imagination stream and formats recent fragments as a prompt section,
grading each by salience so the LLM knows what is background vs active thought.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STREAM_PATH = Path("/dev/shm/hapax-imagination/stream.jsonl")
MAX_FRAGMENTS = 5
ACTIVE_THRESHOLD = 0.4


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_imagination_context(stream_path: Path | None = None) -> str:
    """Format recent imagination fragments as a 'Current Thoughts' prompt section.

    Args:
        stream_path: Override path to stream.jsonl (default: STREAM_PATH).

    Returns:
        Formatted prompt section string.
    """
    path = stream_path or STREAM_PATH
    fragments = _read_recent_fragments(path)

    if not fragments:
        return "## Current Thoughts\n\n(mind is quiet)"

    lines: list[str] = ["## Current Thoughts"]
    for frag in fragments:
        salience = frag.get("salience", 0.0)
        narrative = frag.get("narrative", "")
        continuation = frag.get("continuation", False)

        if salience < ACTIVE_THRESHOLD:
            prefix = "(background)"
        else:
            prefix = "(active thought)"

        marker = " (continuing)" if continuation else ""
        lines.append(f"\n- {prefix}{marker} {narrative}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_recent_fragments(path: Path) -> list[dict]:
    """Read the last MAX_FRAGMENTS lines from the stream, skipping malformed JSON."""
    if not path.exists():
        return []

    try:
        text = path.read_text().strip()
    except OSError:
        log.warning("Failed to read imagination stream at %s", path)
        return []

    if not text:
        return []

    raw_lines = text.splitlines()
    tail = raw_lines[-MAX_FRAGMENTS:]

    fragments: list[dict] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            fragments.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            # Silently skip malformed lines
            pass

    return fragments
