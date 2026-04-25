"""OMG operator-referent + legal-name leak guard.

AUDIT-05 protective wrapper for the OMG cascade outward-publishing
surface. Every templated post that may interpolate the operator's
name passes through :func:`safe_render` before publish:

  1. ``{operator}`` placeholders are substituted with one of the four
     ratified non-formal referents (``OperatorReferentPicker``,
     directive ``su-non-formal-referent-001``).
  2. Rendered output is scanned for the operator's legal-name pattern
     (supplied by argument or by ``HAPAX_OPERATOR_NAME`` env var). Any
     match raises :class:`OperatorNameLeak` so the publish path is
     fail-closed against silent leaks.

This anchors the ``interpersonal_transparency`` axiom (weight 88) at
the outward-publish boundary. The picker keeps non-formal contexts
(livestream narration, social posts, OMG surfaces) free of legal-name
exposure; this guard catches the case where LLM-generated content or
template authoring would otherwise have slipped a real name through.

Spec: `docs/operations/2026-04-25-workstream-realignment-v4-audit-incorporated.md` AUDIT-05.
Picker: ``shared/operator_referent.py``.
"""

from __future__ import annotations

import os
import re
from typing import Final

from shared.operator_referent import OperatorReferentPicker

REFERENT_TOKEN: Final[str] = "{operator}"
ENV_OPERATOR_LEGAL_NAME: Final[str] = "HAPAX_OPERATOR_NAME"


class OperatorNameLeak(ValueError):
    """Raised when ``safe_render`` detects the operator's legal name in
    rendered output. Subclasses :class:`ValueError` so callers that
    already ``except ValueError`` around publish calls inherit the
    fail-closed default without code changes."""


def _resolve_legal_name_pattern(explicit: str | None) -> str | None:
    """Pick the pattern to scan for, or ``None`` to disable the scan.

    Caller-supplied wins; env var fills in absent. Empty string in
    either disables — an empty pattern would match every string and
    create a meaningless raise.
    """
    if explicit:
        return explicit
    env_value = os.environ.get(ENV_OPERATOR_LEGAL_NAME, "")
    if env_value:
        return env_value
    return None


def safe_render(
    text: str,
    *,
    segment_id: str | None,
    legal_name_pattern: str | None = None,
) -> str:
    """Render ``text`` safely for outward publication.

    Substitutes the ``{operator}`` token (if any) with the picker's
    sticky-per-``segment_id`` referent, then scans the result for the
    legal-name pattern.

    Parameters
    ----------
    text:
        The template / pre-render string.
    segment_id:
        Sticky seed for the referent picker. ``None`` uses the
        stochastic picker (suitable for one-off / out-of-band callers
        that do not need per-call consistency).
    legal_name_pattern:
        Plain string (case-insensitive) to scan for in the rendered
        output. Falls back to ``HAPAX_OPERATOR_NAME`` env var if not
        supplied. Empty / unset disables the scan.

    Raises
    ------
    OperatorNameLeak
        If a legal-name pattern is in effect AND it matches the
        rendered text. The matched substring is included in the
        message for triage; callers must NOT re-emit the exception
        message into broadcast.
    """
    rendered = _substitute_referent(text, segment_id=segment_id)
    pattern = _resolve_legal_name_pattern(legal_name_pattern)
    if pattern:
        match = re.search(re.escape(pattern), rendered, flags=re.IGNORECASE)
        if match is not None:
            raise OperatorNameLeak(f"legal-name leak detected: matched {match.group(0)!r}")
    return rendered


def _substitute_referent(text: str, *, segment_id: str | None) -> str:
    if REFERENT_TOKEN not in text:
        return text
    if segment_id is None:
        referent = OperatorReferentPicker.pick()
    else:
        referent = OperatorReferentPicker.pick_for_vod_segment(segment_id)
    return text.replace(REFERENT_TOKEN, referent)


__all__ = [
    "ENV_OPERATOR_LEGAL_NAME",
    "OperatorNameLeak",
    "REFERENT_TOKEN",
    "safe_render",
]
