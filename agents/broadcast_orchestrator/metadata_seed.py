"""Compose seed metadata for a new broadcast at rotation time.

Minimal seed: just enough to make YouTube accept the new broadcast.
Richer description / chapter markers / SEO tags arrive from ytb-008
(research-instrument composer) once it lands; until then we ship a
neutral research-instrument framing that respects GEAL anti-personification.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_CATEGORY_ID = "28"
DEFAULT_TAGS = (
    "ai-livestream",
    "generative-art",
    "research-instrument",
    "legomena-live",
)


@dataclass(frozen=True)
class SeedMetadata:
    title: str
    description: str
    tags: tuple[str, ...]
    category_id: str


def compose(segment_index: int, working_mode: str | None = None) -> SeedMetadata:
    """Return a minimal seed for a new broadcast.

    ``segment_index`` is the rotation counter (1, 2, 3, ...). It surfaces
    in the title for VOD navigation; downstream composers may overwrite.
    """
    title = f"Legomena Live - Segment {segment_index}"
    mode_suffix = f" - {working_mode}" if working_mode else ""
    title = title + mode_suffix
    description = (
        "Continuation of the 24/7 research-instrument livestream. This "
        "VOD covers an ~11h segment of stream activity.\n\n"
        "Metadata composes asynchronously after the segment lands; "
        "chapters, tags, and detailed description backfill within a few "
        "minutes of the rotation.\n\n"
        f"Rotation: segment {segment_index}, "
        f"started {dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')}.\n"
    )
    return SeedMetadata(
        title=title,
        description=description,
        tags=DEFAULT_TAGS,
        category_id=DEFAULT_CATEGORY_ID,
    )
