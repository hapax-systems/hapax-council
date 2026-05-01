"""Overlay-zones content producer (Phase 1).

Authors `TextEntry` records into ``shared.text_repo`` so the
compositor's `OverlayZoneManager` displays fresh, context-aware
content without manual operator intervention.

Phase 1 ships the framework + the **Git Activity** content pillar
per the spec at
``docs/superpowers/specs/2026-04-27-overlay-zones-producer-design.md``
§3.2. Additional pillars (refusal-as-data, objective tracing, RAG)
land as separate slices that drop new ``ContentSource``
implementations into the producer.
"""

from agents.overlay_producer.git_activity import GitActivitySource
from agents.overlay_producer.producer import (
    ContentSource,
    OverlayProducer,
    ProducerTickResult,
)

__all__ = [
    "ContentSource",
    "GitActivitySource",
    "OverlayProducer",
    "ProducerTickResult",
]
