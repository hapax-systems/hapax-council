"""GEAL grounding-source → apex classifier (spec §6.3).

Maps a ``grounding_provenance`` source identifier to one of three
canonical apices (or ``"all"`` for imagination-converge events). GEAL's
G1 wavefront and G2 sub-triangle latch-and-fade paint from the
classified apex — viewers learn "top = operator-perception", "bottom-
left = memory/vault", "bottom-right = chat/world" within minutes of
exposure.

The classifier is pure prefix dispatch — a dict of prefix tokens + the
apex they resolve to. Unknown sources fall into the memory bucket
(``"bl"``) rather than raising; the render path never crashes on a
freshly-introduced source tag.

Spec: ``docs/superpowers/specs/2026-04-23-geal-spec.md`` §6.3.
"""

from __future__ import annotations

from typing import Literal

Apex = Literal["top", "bl", "br", "all"]


# Prefix → apex. Longest-matching-prefix semantics: we sort by prefix
# length descending before matching so "insightface.enrolled" wins over
# "insightface" if both were ever registered. The whole table is lower-
# cased; dispatch case-folds the source id.
_PREFIX_APEX: list[tuple[str, Apex]] = [
    # -- Operator-perception (top apex) ------------------------------------
    ("insightface", "top"),
    ("pi-noir", "top"),
    ("pi_noir", "top"),
    ("room-change", "top"),
    ("room_change", "top"),
    ("operator.gaze", "top"),
    ("operator.perception", "top"),
    ("perception.operator", "top"),
    ("ir.hand", "top"),
    ("contact-mic", "top"),
    ("contact_mic", "top"),
    # -- RAG / memory / vault (bl apex) ------------------------------------
    ("rag", "bl"),
    ("vault", "bl"),
    ("obsidian", "bl"),
    ("memory", "bl"),
    ("qdrant", "bl"),
    ("episodic", "bl"),
    ("document", "bl"),
    # -- Chat / world / music-match / soundcloud (br apex) -----------------
    ("chat", "br"),
    ("world", "br"),
    ("music", "br"),
    ("soundcloud", "br"),
    ("youtube.comment", "br"),
    # -- Imagination-converge (all three apices) ---------------------------
    ("imagination.converge", "all"),
    ("imagination.cross-source", "all"),
    ("imagination.cross_source", "all"),
]

# Prepare the dispatch table once at import: sort by prefix length
# descending so longer (more-specific) prefixes win.
_PREFIX_APEX.sort(key=lambda pair: len(pair[0]), reverse=True)


def classify_source(source_id: str) -> Apex:
    """Return the apex that should host grounding events from ``source_id``.

    Empty / unknown ids fall into the memory bucket (``"bl"``). Matching
    is case-insensitive and prefix-based — callers pass raw source
    identifiers and don't need to normalise first.
    """
    if not source_id:
        return "bl"
    needle = source_id.lower()
    for prefix, apex in _PREFIX_APEX:
        if needle.startswith(prefix):
            return apex
    return "bl"


__all__ = ["Apex", "classify_source"]
