"""Continuous-Loop Research Cadence §3.5 — attention-bid collector + driver.

The bidder (``agents.attention_bids.bidder``) scores candidate bids
and picks a winner. The dispatcher (``agents.attention_bids.dispatcher``)
delivers accepted bids to configured channels. This module is the glue
that (a) collects bids submitted by multiple producers into a single
tick window, (b) calls ``select_winner`` once per tick, (c) dispatches
the winner via the configured channel set, and (d) persists per-channel
hysteresis state across ticks so a service restart doesn't amplify
bid cadence.

The collector is a thin class — no threads, no timers internally. The
driver (``attention_bid_tick``) is a one-shot that a systemd timer or
the daimonion background loop calls on a cadence (default 60 s).

State file lives at ``/dev/shm/hapax-attention-bids/collector-state.json``
(atomic tmp+rename) and holds the ``last_delivered_at`` dict so a
systemd restart picks up the existing hysteresis without re-punishing
the operator.

Consent: bids that declare ``requires_broadcast_consent=True`` flow
through the existing bidder filter, which rejects them on public
stream modes without an active broadcast contract. Collector adds no
new consent path.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from agents.attention_bids.bidder import (
    AttentionBid,
    BidResult,
    select_winner,
)
from agents.attention_bids.dispatcher import (
    ChannelConfig,
    DispatchResult,
    default_channel_config,
    dispatch_bid,
)

log = logging.getLogger(__name__)

STATE_PATH = Path("/dev/shm/hapax-attention-bids/collector-state.json")


@dataclass(frozen=True)
class TickResult:
    """Outcome of a single ``attention_bid_tick`` call."""

    bid_result: BidResult
    dispatch_result: DispatchResult | None
    tick_epoch: float


# ── Persistent state ────────────────────────────────────────────────────────


@dataclass
class CollectorState:
    last_delivered_at: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"last_delivered_at": dict(self.last_delivered_at)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CollectorState:
        ld = raw.get("last_delivered_at", {})
        if not isinstance(ld, dict):
            ld = {}
        out: dict[str, float] = {}
        for k, v in ld.items():
            if not isinstance(k, str):
                continue
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
        return cls(last_delivered_at=out)


def load_state(path: Path | None = None) -> CollectorState:
    """Read persisted state; return empty state on missing / malformed."""
    in_path = path or STATE_PATH
    if not in_path.exists():
        return CollectorState()
    try:
        raw = json.loads(in_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.debug("attention-bid collector state unreadable", exc_info=True)
        return CollectorState()
    if not isinstance(raw, dict):
        return CollectorState()
    return CollectorState.from_dict(raw)


def save_state(state: CollectorState, *, path: Path | None = None) -> None:
    """Persist collector state atomically (tmp + rename)."""
    out_path = path or STATE_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out_path)


# ── Collector class ─────────────────────────────────────────────────────────


class BidCollector:
    """Thread-safe staging area for attention bids awaiting the next tick.

    Producers call ``submit(bid)`` from any thread; ``drain_and_select``
    consumes the staged bids atomically inside the tick.
    """

    def __init__(self) -> None:
        self._staged: list[AttentionBid] = []
        self._lock = Lock()

    def submit(self, bid: AttentionBid) -> None:
        with self._lock:
            self._staged.append(bid)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._staged)

    def drain(self) -> list[AttentionBid]:
        with self._lock:
            out = list(self._staged)
            self._staged.clear()
            return out


# ── Tick entrypoint ─────────────────────────────────────────────────────────


def attention_bid_tick(
    collector: BidCollector,
    *,
    stimmung: dict[str, Any] | None = None,
    stream_mode: str = "private",
    active_objective_ids: frozenset[str] = frozenset(),
    broadcast_contract_holders: frozenset[str] = frozenset(),
    config: ChannelConfig | None = None,
    state_path: Path | None = None,
    now_epoch: float | None = None,
) -> TickResult:
    """Drain the collector, select a winner, dispatch it, persist state.

    Returns a ``TickResult`` even when no winner is selected so callers
    can always tag the tick with the `reason` (`no_bids`, `all_filtered`,
    `below_threshold`, `accepted`).
    """
    now = now_epoch if now_epoch is not None else time.time()
    bids = collector.drain()

    result = select_winner(
        bids,
        stimmung=stimmung or {},
        active_objective_ids=active_objective_ids,
        stream_mode=stream_mode,
        broadcast_contract_holders=broadcast_contract_holders,
    )

    if result.winner is None:
        return TickResult(bid_result=result, dispatch_result=None, tick_epoch=now)

    state = load_state(state_path)
    dispatch_result = dispatch_bid(
        result.winner,
        stimmung=stimmung or {},
        now_epoch=now,
        last_delivered_at=state.last_delivered_at,
        config=config or default_channel_config(),
    )
    save_state(state, path=state_path)

    return TickResult(bid_result=result, dispatch_result=dispatch_result, tick_epoch=now)


__all__ = [
    "STATE_PATH",
    "BidCollector",
    "CollectorState",
    "TickResult",
    "attention_bid_tick",
    "load_state",
    "save_state",
]
