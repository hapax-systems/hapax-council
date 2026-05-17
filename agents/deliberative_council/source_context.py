"""Resolve source_ref strings into source_context content.

Parses references like:
  - "agents/visual_layer_aggregator/aggregator.py:1165"
  - "agents/hapax_daimonion/_perception_state_writer.py:256-291"
  - "shared/eigenform_logger.py"
  - "docs/research/2026-04-24-universal-bayesian-claim-confidence.md"
  - "hapax-constitution/axioms/registry.yaml"

Returns the file content (or line range) truncated to a budget so it
fits in the council prompt without blowing context.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_MAX_CONTEXT_CHARS = 8000
_LINE_REF_PATTERN = re.compile(r"^(.+?):(\d+)(?:-(\d+))?$")


def resolve_source_context(
    source_ref: str,
    *,
    workspace_root: Path | None = None,
    max_chars: int = _MAX_CONTEXT_CHARS,
) -> str:
    """Read source content referenced by source_ref.

    Returns empty string on failure (missing file, unreadable, etc).
    """
    root = workspace_root if workspace_root is not None else _WORKSPACE_ROOT

    file_path_str = source_ref
    start_line: int | None = None
    end_line: int | None = None

    match = _LINE_REF_PATTERN.match(source_ref)
    if match:
        file_path_str = match.group(1)
        start_line = int(match.group(2))
        end_line = int(match.group(3)) if match.group(3) else None

    candidate = root / file_path_str
    if not candidate.exists():
        for parent_name in ("hapax-constitution", "hapax-officium"):
            alt = root.parent / parent_name / file_path_str.removeprefix(f"{parent_name}/")
            if alt.exists():
                candidate = alt
                break

    if not candidate.exists() or not candidate.is_file():
        log.debug("source_ref not resolvable: %s", source_ref)
        return ""

    try:
        content = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        log.debug("source_ref unreadable: %s", source_ref)
        return ""

    if start_line is not None:
        lines = content.splitlines()
        if end_line is not None:
            window = max(0, end_line - start_line + 40)
            start = max(0, start_line - 10)
            end = min(len(lines), start_line + window)
        else:
            start = max(0, start_line - 20)
            end = min(len(lines), start_line + 40)
        content = "\n".join(f"{i + start + 1}: {line}" for i, line in enumerate(lines[start:end]))

    if len(content) > max_chars:
        content = content[:max_chars] + "\n... [truncated]"

    return content


def populate_source_context(
    text: str,
    source_ref: str,
    metadata: dict | None = None,
    *,
    workspace_root: Path | None = None,
) -> str:
    """Auto-populate source_context for a CouncilInput at submission.

    Called by the deliberate() entrypoint when source_context is empty.
    """
    context = resolve_source_context(source_ref, workspace_root=workspace_root)
    if not context:
        log.debug("No source context resolved for %s", source_ref)
    return context
