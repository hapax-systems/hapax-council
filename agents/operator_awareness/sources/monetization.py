"""Monetization source — wires payment-event log into awareness state.

Reads the canonical payment-event log at
``/dev/shm/hapax-monetization/events.jsonl`` and returns a
``MonetizationBlock`` for the awareness aggregator to embed in the
top-level ``AwarenessState``.

This is the awareness-side adapter: the long-running daemon
(``MonetizationAggregator`` in ``agents.payment_processors``) writes
the same block more frequently than the awareness 30s tick, but
when this source is used in the awareness path the awareness
aggregator owns the block — last write wins by tick cadence (30s
each, harmless overlap).

Defaults to ``public=False`` per the spec — the operator's
amount-of-receipts is private until they explicitly opt-in to
fanout via the awareness ``public_filter`` toggle.
"""

from __future__ import annotations

import logging
from pathlib import Path

from prometheus_client import Counter

from agents.operator_awareness.state import MonetizationBlock
from agents.payment_processors.event_log import DEFAULT_PAYMENT_LOG_PATH
from agents.payment_processors.monetization_aggregator import build_monetization_block

log = logging.getLogger(__name__)

monetization_source_failures_total = Counter(
    "hapax_awareness_monetization_source_failures_total",
    "Awareness aggregator monetization-source failures (graceful degradation events).",
)


def collect_monetization_block(
    log_path: Path = DEFAULT_PAYMENT_LOG_PATH,
    *,
    public: bool = False,
) -> MonetizationBlock:
    """Build the MonetizationBlock for one awareness tick.

    Defensive: any failure logs and returns the default-empty block.
    The awareness runner relies on this contract — a broken source
    must not crash the spine.
    """
    try:
        return build_monetization_block(log_path=log_path, public=public)
    except Exception:  # noqa: BLE001
        log.exception("monetization source failed; returning default-empty block")
        monetization_source_failures_total.inc()
        return MonetizationBlock(public=public)


__all__ = [
    "collect_monetization_block",
    "monetization_source_failures_total",
]
