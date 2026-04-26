"""Public-safe filter for omg.lol fanout (server-side redaction).

Walks an ``AwarenessState`` and zeroes out non-public sub-blocks per
each block's ``public: bool`` flag. The filter is server-side because
trusting any client to honor public flags would leak operator state
on the first misconfigured surface.

The refusals_recent block is special: refusals ARE public-by-design
per the constitutional ``feedback_full_automation_or_no_engagement``
directive (refusal-as-data is celebrated). The list passes through
unchanged regardless of any block-level public flag.
"""

from __future__ import annotations

from agents.operator_awareness.state import (
    AwarenessState,
    CrossAccountBlock,
    DaimonionBlock,
    FleetBlock,
    GovernanceBlock,
    HealthBlock,
    MarketingOutreachBlock,
    MonetizationBlock,
    MusicBlock,
    ProgrammeBlock,
    PublishingBlock,
    ResearchDispatchBlock,
    SprintBlock,
    StreamBlock,
)

# Per-block redacted-default factory map. Each entry returns a fresh
# default-instance of the corresponding block type. Keeping this
# explicit (rather than reflecting on AwarenessState fields) means
# adding a new block to the model needs an explicit decision about
# its default-redacted shape — the type system won't let a new
# block silently leak.
_BLOCK_REDACTORS = {
    "marketing_outreach": MarketingOutreachBlock,
    "research_dispatches": ResearchDispatchBlock,
    "music_soundcloud": MusicBlock,
    "publishing_pipeline": PublishingBlock,
    "health_system": HealthBlock,
    "daimonion_voice": DaimonionBlock,
    "stream": StreamBlock,
    "cross_account": CrossAccountBlock,
    "governance": GovernanceBlock,
    "content_programmes": ProgrammeBlock,
    "hardware_fleet": FleetBlock,
    "time_sprint": SprintBlock,
    "monetization": MonetizationBlock,
}


def public_filter(state: AwarenessState) -> AwarenessState:
    """Return a new AwarenessState with non-public blocks redacted.

    Each sub-block with ``public=False`` is replaced with a
    default-instance of its type (preserving schema shape so
    downstream parsers don't crash on missing fields). The
    refusals_recent list always passes through (constitutional:
    refusals ARE the public surface).

    Returns a new instance — frozen=True on AwarenessState means
    we can't mutate in place anyway.
    """
    redacted: dict[str, object] = {}
    for field_name, block_type in _BLOCK_REDACTORS.items():
        block = getattr(state, field_name)
        redacted[field_name] = block if block.public else block_type()
    return state.model_copy(update=redacted)


__all__ = ["public_filter"]
