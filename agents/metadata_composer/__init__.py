"""Research-instrument metadata composer.

Pure state-in → prose-out module producing title / description / tags /
chapter markers / cross-surface post variants for autonomous YouTube
publication. Honors scientific register, GEAL post-HARDM framing, and the
``MonetizationRiskGate``.

Spec: ``~/.cache/hapax/relay/context/2026-04-23-youtube-boost-G3-research-instrument-composer-spec.md``
cc-task: ytb-008
"""

from agents.metadata_composer.chapters import ChapterMarker
from agents.metadata_composer.composer import (
    ComposedMetadata,
    MetadataPublicClaimGateResult,
    Scope,
    compose_metadata,
)

__all__ = [
    "ChapterMarker",
    "ComposedMetadata",
    "MetadataPublicClaimGateResult",
    "Scope",
    "compose_metadata",
]
