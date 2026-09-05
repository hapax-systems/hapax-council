"""Monetization aggregator — derives MonetizationBlock from the event log.

Tails the canonical payment-event log and computes the fields of the
``MonetizationBlock`` (counts per rail, total sats, total EUR, last
event, dot-grid summary string).

Two roles in the wider system:

1. **Awareness source.** ``agents.operator_awareness.sources.monetization``
   imports ``build_monetization_block`` and feeds its result into the
   awareness state aggregator's ``collect()`` cycle.

2. **Long-running daemon.** ``MonetizationAggregator`` runs the three
   receiver loops (Lightning, Nostr Zap, Liberapay) concurrently so they
   append confirmed events to the canonical payment-event log. It does
   NOT write the top-level ``AwarenessState``: ``AwarenessRunner`` is the
   single canonical ``DEFAULT_STATE_PATH`` writer and reads this log via
   the monetization source each tick. The systemd unit
   ``hapax-money-rails.service`` runs this daemon for its receivers/health.

Read-only contract: this module computes counts and emits awareness
data only. There is no method that initiates payment.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from pathlib import Path

from agents.operator_awareness.state import (
    MonetizationBlock,
    PaymentEvent,
)
from agents.payment_processors.event_log import (
    DEFAULT_PAYMENT_LOG_PATH,
    tail_events,
)
from agents.payment_processors.liberapay_receiver import LiberapayReceiver
from agents.payment_processors.lightning_receiver import LightningReceiver
from agents.payment_processors.nostr_zap_listener import NostrZapListener

log = logging.getLogger(__name__)


def build_monetization_block(
    *,
    log_path: Path = DEFAULT_PAYMENT_LOG_PATH,
    public: bool = False,
) -> MonetizationBlock:
    """Compute a fresh ``MonetizationBlock`` from the event log.

    Deduplicates on ``(rail, external_id)`` so repeated polls / log
    re-reads don't double-count. Empty log → default block (zeros).
    """
    events = tail_events(log_path=log_path)
    return build_monetization_block_from_events(events, public=public)


def build_monetization_block_from_events(
    events: list[PaymentEvent], *, public: bool = False
) -> MonetizationBlock:
    """Build the awareness block from an already-captured event window."""

    seen_ids: set[tuple[str, str]] = set()
    counts: dict[str, int] = defaultdict(int)
    total_sats = 0
    total_eur = 0.0
    last: PaymentEvent | None = None
    for event in events:
        key = (event.rail, event.external_id or "")
        if event.external_id and key in seen_ids:
            continue
        seen_ids.add(key)
        counts[event.rail] += 1
        if event.amount_sats:
            total_sats += int(event.amount_sats)
        if event.amount_eur:
            total_eur += float(event.amount_eur)
        last = event
    grid = (
        f"L:{counts.get('lightning', 0)} "
        f"N:{counts.get('nostr_zap', 0)} "
        f"LP:{counts.get('liberapay', 0)}"
    )
    return MonetizationBlock(
        public=public,
        surfaces_dot_grid_compact=grid,
        last_event=last,
        lightning_receipts_count=counts.get("lightning", 0),
        nostr_zap_receipts_count=counts.get("nostr_zap", 0),
        liberapay_receipts_count=counts.get("liberapay", 0),
        total_sats_received=total_sats,
        total_eur_received=round(total_eur, 2),
    )


class MonetizationAggregator:
    """Daemon that runs the 3 receive rails (events + health only).

    It appends confirmed events to the canonical payment-event log; it does NOT
    write the top-level ``AwarenessState`` (``AwarenessRunner`` is the sole
    canonical writer — see the module docstring).

    Constructor parameters
    ----------------------
    lightning, nostr, liberapay:
        Pre-built receiver instances (tests inject mocks). Production
        wires defaults from ``pass`` credentials.
    log_path:
        Canonical payment-event log.
    """

    def __init__(
        self,
        *,
        lightning: LightningReceiver | None = None,
        nostr: NostrZapListener | None = None,
        liberapay: LiberapayReceiver | None = None,
        log_path: Path = DEFAULT_PAYMENT_LOG_PATH,
    ) -> None:
        self._lightning = lightning if lightning is not None else LightningReceiver()
        self._nostr = nostr if nostr is not None else NostrZapListener()
        self._liberapay = liberapay if liberapay is not None else LiberapayReceiver()
        self._log_path = log_path
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()
        self._lightning.stop()
        self._liberapay.stop()
        self._nostr.stop()

    async def _run_async_rails(self) -> None:
        """Run Nostr listener + sleep until stop set.

        Lightning and Liberapay run in dedicated threads (httpx.Client
        is sync); Nostr uses asyncio websockets, so it gets the event
        loop's main thread.
        """
        await self._nostr.run_forever()

    def _run_lightning(self) -> None:
        self._lightning.run_forever()

    def _run_liberapay(self) -> None:
        self._liberapay.run_forever()

    def run_forever(self) -> None:
        """Spawn the receive rails; expose events (and health) only.

        This is the systemd-driven entry point (``hapax-money-rails.service``). It
        runs the three receivers so they append confirmed events to the canonical
        payment-event log; it does NOT write the top-level ``AwarenessState``.
        ``AwarenessRunner`` (``hapax-operator-awareness.service``) is the single
        canonical writer of ``DEFAULT_STATE_PATH``; it reads this log through the
        monetization source each tick, so this daemon replacing top-level state would
        race and default unrelated blocks. Blocks until SIGTERM / SIGINT.
        """
        threads = [
            threading.Thread(target=self._run_lightning, name="lightning", daemon=True),
            threading.Thread(target=self._run_liberapay, name="liberapay", daemon=True),
        ]
        for t in threads:
            t.start()
        try:
            asyncio.run(self._run_async_rails())
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            for t in threads:
                t.join(timeout=5.0)


__all__ = [
    "MonetizationAggregator",
    "build_monetization_block",
    "build_monetization_block_from_events",
]
