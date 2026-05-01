"""Operator-awareness state spine (per ``awareness-state-stream-canonical``).

Single canonical state surface that all ambient operator-awareness
consumers subscribe to. On-disk canon at
``/dev/shm/hapax-awareness/state.json``; push channel via
``/api/awareness/stream`` SSE.

Surfaces are pure read-only subscribers — no surface mutates the
store, no surface holds operator-side acknowledge state. MAPE-K
Knowledge layer: one knowledge store, many readers, no read-back
loops. Stale-state TTL 90s; surfaces dim when stale rather than
display empty.

The full spine ships in this package:

- :mod:`agents.operator_awareness.state` — state model + atomic writer.
- :class:`agents.operator_awareness.aggregator.Aggregator` — pulls from
  the wired sources per tick.
- :mod:`agents.operator_awareness.runner` — 30s tick loop, mounted via
  ``systemd/units/hapax-operator-awareness.service``.
- :mod:`agents.operator_awareness.public_filter` — public-safe filter
  consulted by the omg.lol fanout.
- :mod:`agents.operator_awareness.omg_lol_fanout` — hourly public-safe
  summary post (mounted via ``systemd/units/hapax-omg-lol-fanout``).
- :mod:`agents.operator_awareness.weekly_review` — Sunday 04:00 weekly
  rollup (separate timer).
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
