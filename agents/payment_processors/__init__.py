"""Receive-only payment rails — Lightning, Nostr Zaps (NIP-57), Liberapay.

This package implements three independent receive-only rails that
emit ``PaymentEvent`` records into a JSONL log. The
``MonetizationAggregator`` tails the log and updates the
``MonetizationBlock`` of the awareness state spine.

CONSTITUTIONAL CONTRACT — read-only rails:
    Every receiver is structurally incapable of *initiating* value
    transfer. There is no method named ``send``, ``initiate``,
    ``payout``, or ``transfer`` anywhere in this package. The
    contract is enforced by ``tests/payment_processors/test_read_only_contract.py``,
    which scans the package source for forbidden verbs.

Operator credentials (loaded via ``pass show <key>`` at startup):

- ``lightning/alby-access-token`` — Alby invoices/transactions API
- ``nostr/nsec-hex`` — operator's Nostr private key (signing kind-0
  metadata only; receivers do not sign zaps)
- ``nostr/npub-hex`` — operator's Nostr public key (subscription target)
- ``liberapay/username``, ``liberapay/password`` — HTTP Basic auth

If a rail's API path requires operator-physical interaction (e.g.,
Alby OAuth UI flow), that rail emits a ``RefusalEvent`` to
``/dev/shm/hapax-refusals/log.jsonl`` and disables itself rather
than blocking the others.
"""

from agents.payment_processors.event_log import (
    DEFAULT_PAYMENT_LOG_PATH,
    append_event,
    tail_events,
)
from agents.payment_processors.monetization_aggregator import (
    MonetizationAggregator,
    build_monetization_block,
)

__all__ = [
    "DEFAULT_PAYMENT_LOG_PATH",
    "MonetizationAggregator",
    "append_event",
    "build_monetization_block",
    "tail_events",
]
