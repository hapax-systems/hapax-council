"""Operator-awareness state spine (`awareness-state-stream-canonical` Phase 1).

Single canonical state surface that all ambient operator-awareness
consumers subscribe to. On-disk canon at
``/dev/shm/hapax-awareness/state.json``; push channel via
``/api/awareness/stream`` SSE (separate task).

Surfaces are pure read-only subscribers — no surface mutates the
store, no surface holds operator-side acknowledge state. MAPE-K
Knowledge layer: one knowledge store, many readers, no read-back
loops. Stale-state TTL 90s; surfaces dim when stale rather than
display empty.

This Phase-1 ship is the **state model + atomic writer only**. The
aggregator (8 sources) and runner (30s tick loop) land in follow-up
PRs once this contract is in place.
"""

from agents.operator_awareness.state import (
    DEFAULT_STATE_PATH,
    DEFAULT_TTL_S,
    AwarenessState,
    CrossAccountBlock,
    DaimonionBlock,
    FleetBlock,
    GovernanceBlock,
    HealthBlock,
    MarketingOutreachBlock,
    MonetizationBlock,
    MusicBlock,
    PaymentEvent,
    ProgrammeBlock,
    PublishingBlock,
    RefusalEvent,
    ResearchDispatchBlock,
    SprintBlock,
    StreamBlock,
    write_state_atomic,
)

__all__ = [
    "DEFAULT_STATE_PATH",
    "DEFAULT_TTL_S",
    "AwarenessState",
    "CrossAccountBlock",
    "DaimonionBlock",
    "FleetBlock",
    "GovernanceBlock",
    "HealthBlock",
    "MarketingOutreachBlock",
    "MonetizationBlock",
    "MusicBlock",
    "PaymentEvent",
    "ProgrammeBlock",
    "PublishingBlock",
    "RefusalEvent",
    "ResearchDispatchBlock",
    "SprintBlock",
    "StreamBlock",
    "write_state_atomic",
]
