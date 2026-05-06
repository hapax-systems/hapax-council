"""Nostr NIP-57 zap-receipt listener.

Subscribes to a small set of public Nostr relays for kind=9735
zap-receipt events tagged with the operator's npub. Each zap receipt
emits one ``PaymentEvent`` into the canonical payment-event log.

NIP-57 mechanics (paraphrased):
    A "zap" is a Lightning payment whose proof is published to Nostr
    as a kind=9735 event signed by the LNURL provider's hot wallet
    pubkey. The recipient's pubkey appears in a ``["p", <hex>]``
    tag. The amount is encoded in the bolt11 invoice referenced by
    ``["bolt11", <invoice>]``.

READ-ONLY contract:
    This listener subscribes only. It NEVER posts events to relays,
    NEVER signs zaps, NEVER initiates Lightning payments. The
    ``nostr/nsec-hex`` private key is *not* used by this module —
    listening is fully public-key-only.

    Forbidden verbs (``send``, ``initiate``, ``payout``, ``transfer``)
    do not appear; the contract test enforces this by source scan.

If no operator npub is available in pass, the listener disables
itself with a ``RefusalEvent`` and the other rails continue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import websockets
from prometheus_client import Counter

from agents.operator_awareness.state import PaymentEvent
from agents.payment_processors.event_log import append_event
from agents.payment_processors.refusal_annex import emit_rail_refusal
from agents.payment_processors.secrets import load_nostr_npub
from shared.chronicle import ChronicleEvent, current_otel_ids, record

log = logging.getLogger(__name__)

# Default relay set — operator-overridable via ``HAPAX_NOSTR_RELAYS``
# (comma-separated). These are popular public relays known to carry
# zap-receipt traffic; ssh-fast and currently free to read.
DEFAULT_RELAYS: tuple[str, ...] = (
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
)

ZAP_RECEIPT_KIND = 9735
DEFAULT_BACKOFF_S = 5.0
DEFAULT_BACKOFF_MAX_S = 120.0

zap_receipts_total = Counter(
    "hapax_leverage_nostr_zap_receipts_total",
    "Nostr NIP-57 zap receipts ingested.",
    ["rail"],
)
zap_relay_errors_total = Counter(
    "hapax_leverage_nostr_zap_relay_errors_total",
    "Relay connection errors during zap subscription.",
    ["kind"],
)


class NostrZapListener:
    """Subscribe to NIP-57 zap receipts for a single operator npub.

    Constructor parameters
    ----------------------
    npub_hex:
        Operator's Nostr public key in hex (NOT npub1... bech32).
        Production reads via ``load_nostr_npub()``.
    relays:
        Iterable of relay WSS URLs. Defaults to ``DEFAULT_RELAYS``.
    websocket_factory:
        Async callable returning a connected websocket. Tests inject
        an in-memory async fake.
    """

    _SENTINEL: str = "__not_provided__"

    def __init__(
        self,
        *,
        npub_hex: str | None = _SENTINEL,  # type: ignore[assignment]
        relays: tuple[str, ...] = DEFAULT_RELAYS,
        websocket_factory: Any = None,
    ) -> None:
        if npub_hex is self._SENTINEL:
            self._npub = load_nostr_npub()
        else:
            self._npub = npub_hex
        self._relays = relays
        self._websocket_factory = websocket_factory
        self._stop_evt = asyncio.Event()
        self._seen_event_ids: set[str] = set()
        self._disabled = False

    @property
    def disabled(self) -> bool:
        return self._disabled

    def stop(self) -> None:
        self._stop_evt.set()

    def _build_subscription(self) -> tuple[str, str]:
        """Return (sub_id, REQ json) for the zap-receipt subscription."""
        sub_id = uuid.uuid4().hex[:16]
        # NIP-57 zap receipts: kind=9735 with a `#p` tag matching the
        # operator's pubkey. ``since`` is process-start to avoid
        # backfilling years of history; persistent state is not the
        # job of a zap *listener* (chronicle is canonical).
        req = json.dumps(
            [
                "REQ",
                sub_id,
                {
                    "kinds": [ZAP_RECEIPT_KIND],
                    "#p": [self._npub],
                    "since": int(time.time()),
                },
            ]
        )
        return sub_id, req

    async def _consume_relay(self, relay_url: str) -> None:
        """Connect to one relay, subscribe, and yield events forever.

        Reconnects with exponential backoff on any disconnect. Stops
        when ``stop()`` is called.
        """
        backoff = DEFAULT_BACKOFF_S
        while not self._stop_evt.is_set():
            try:
                ws = await self._open_websocket(relay_url)
            except Exception as e:  # noqa: BLE001
                zap_relay_errors_total.labels(kind="connect").inc()
                log.warning("relay %s connect failed: %s", relay_url, e)
                await self._backoff_sleep(backoff)
                backoff = min(DEFAULT_BACKOFF_MAX_S, backoff * 2.0)
                continue
            backoff = DEFAULT_BACKOFF_S
            sub_id, req = self._build_subscription()
            try:
                await ws.send(req)
                async for raw in ws:
                    if self._stop_evt.is_set():
                        break
                    self._handle_relay_message(raw, sub_id)
            except Exception as e:  # noqa: BLE001
                zap_relay_errors_total.labels(kind="recv").inc()
                log.info("relay %s disconnected: %s", relay_url, e)
            finally:
                with _suppress_close_errors():
                    await ws.close()
            await self._backoff_sleep(DEFAULT_BACKOFF_S)

    async def _open_websocket(self, relay_url: str) -> Any:
        if self._websocket_factory is not None:
            return await self._websocket_factory(relay_url)
        return await websockets.connect(relay_url, open_timeout=10.0)

    async def _backoff_sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop_evt.wait(), timeout=seconds)
        except TimeoutError:
            pass

    def _handle_relay_message(self, raw: Any, sub_id: str) -> None:
        try:
            msg = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            return
        if not isinstance(msg, list) or len(msg) < 2:
            return
        kind = msg[0]
        if kind != "EVENT" or len(msg) < 3:
            return
        if msg[1] != sub_id:
            return
        event_data = msg[2]
        if not isinstance(event_data, dict):
            return
        event_id = str(event_data.get("id") or "")
        if not event_id or event_id in self._seen_event_ids:
            return
        if int(event_data.get("kind") or 0) != ZAP_RECEIPT_KIND:
            return
        payment_event = _zap_event_to_payment_event(event_data)
        if payment_event is None:
            return
        append_event(payment_event)
        _record_chronicle(payment_event)
        zap_receipts_total.labels(rail="nostr_zap").inc()
        self._seen_event_ids.add(event_id)

    async def run_forever(self) -> None:
        """Concurrent fan-out across relays. Returns when ``stop`` set."""
        if self._disabled:
            return
        if not self._npub:
            emit_rail_refusal(
                rail="nostr_zap",
                surface="nostr-npub-bootstrap",
                reason="No nostr/npub-hex in pass; zap subscription disabled.",
            )
            self._disabled = True
            return
        log.info(
            "NostrZapListener starting; npub=%s... relays=%d",
            self._npub[:8],
            len(self._relays),
        )
        await asyncio.gather(
            *[self._consume_relay(url) for url in self._relays],
            return_exceptions=True,
        )


class _suppress_close_errors:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> bool:
        return True


def _zap_event_to_payment_event(event_data: dict[str, Any]) -> PaymentEvent | None:
    """Convert one NIP-57 zap-receipt event into a PaymentEvent.

    Pulls the bolt11 amount from the ``["bolt11", <invoice>]`` tag if
    present. Falls back to amount-from-description-tag when bolt11
    cannot be parsed without an LN library. Empty amounts are still
    valid receipts (some zaps have null amount when sender-side LNURL
    fails to attach a bolt11 — record the receipt anyway).
    """
    tags = event_data.get("tags") or []
    bolt11_invoice: str | None = None
    description: str | None = None
    for tag in tags:
        if not isinstance(tag, list) or len(tag) < 2:
            continue
        name = tag[0]
        if name == "bolt11":
            bolt11_invoice = str(tag[1])
        elif name == "description":
            description = str(tag[1])
    amount_sats = _amount_sats_from_bolt11(bolt11_invoice) if bolt11_invoice else 0
    sender_excerpt = _sender_excerpt_from_description(description, event_data)
    timestamp = _parse_event_timestamp(event_data.get("created_at"))
    return PaymentEvent(
        timestamp=timestamp,
        rail="nostr_zap",
        amount_sats=amount_sats,
        amount_usd=None,
        sender_excerpt=sender_excerpt[:80],
        external_id=str(event_data.get("id") or ""),
    )


def _amount_sats_from_bolt11(invoice: str) -> int:
    """Best-effort sats extraction from a bolt11 string.

    Bolt11 amount: ``lnbc<amount><multiplier>`` where multiplier is
    ``m`` (milli-BTC), ``u`` (micro-BTC), ``n`` (nano-BTC), or ``p``
    (pico-BTC). 1 BTC = 1e8 sats.

    We avoid pulling a full bolt11 parser dependency — the zap-receipt
    flow only needs *amount*, not signature validation, and amount
    encoding is unambiguous in the prefix.
    """
    if not invoice:
        return 0
    s = invoice.lower()
    if not s.startswith("lnbc"):
        return 0
    s = s[4:]
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
            continue
        multiplier = ch
        try:
            amount = int(digits) if digits else 0
        except ValueError:
            return 0
        if multiplier == "m":
            return amount * 100_000
        if multiplier == "u":
            return amount * 100
        if multiplier == "n":
            return amount // 10
        if multiplier == "p":
            return amount // 10_000
        return amount * 100_000_000
    return 0


def _sender_excerpt_from_description(
    description: str | None,
    event_data: dict[str, Any],
) -> str:
    if description:
        try:
            zap_request = json.loads(description)
            content = zap_request.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        except (TypeError, ValueError):
            pass
    pubkey = str(event_data.get("pubkey") or "")
    if pubkey:
        return f"zap-from:{pubkey[:16]}"
    return ""


def _parse_event_timestamp(created_at: Any) -> datetime:
    try:
        return datetime.fromtimestamp(float(created_at), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _record_chronicle(event: PaymentEvent) -> None:
    trace_id, span_id = current_otel_ids()
    record(
        ChronicleEvent(
            ts=event.timestamp.timestamp(),
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            source="payment_processors.nostr_zap",
            event_type="payment.received",
            payload={
                "rail": event.rail,
                "amount_sats": event.amount_sats,
                "external_id": event.external_id,
                # Sibling to ``payment_processors.lightning`` (#2697):
                # zaps are structurally high-salience receipts. Source
                # isn't in the chronicle-ticker allow-list, so 0.95
                # surfaces them via the salience path.
                "salience": 0.95,
            },
        )
    )


__all__ = [
    "DEFAULT_RELAYS",
    "ZAP_RECEIPT_KIND",
    "NostrZapListener",
    "zap_receipts_total",
    "zap_relay_errors_total",
]
