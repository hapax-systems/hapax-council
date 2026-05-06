"""Lightning Network receive-rail via Alby access-token polling.

Polls Alby's REST API at ``https://api.getalby.com/invoices/incoming``
with a Bearer access token. Each polling tick lists incoming invoices
since the last cursor and emits one ``PaymentEvent`` per *settled*
invoice not yet seen.

READ-ONLY contract:
    This module never calls ``POST /v2/payments`` or any sender path.
    There is no method named ``send``, ``initiate``, ``payout``, or
    ``transfer``. The contract test in
    ``tests/payment_processors/test_read_only_contract.py`` enforces
    this by source scan.

Credential bootstrap:
    ``pass insert lightning/alby-access-token`` (one-time)

If the token is missing OR Alby returns 401 (token expired,
operator-physical OAuth UI flow needed), the receiver emits one
``RefusalEvent`` to the canonical refusal log and disables itself.
Other rails (Nostr Zap, Liberapay) continue.

Idempotency:
    Each Alby invoice has a stable ``payment_hash`` field which we
    use as the ``external_id``. The aggregator deduplicates on
    ``(rail, external_id)``, so re-poll overlap is harmless.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from prometheus_client import Counter

from agents.operator_awareness.state import PaymentEvent
from agents.payment_processors.event_log import append_event
from agents.payment_processors.refusal_annex import emit_rail_refusal
from agents.payment_processors.secrets import load_alby_token
from shared.chronicle import ChronicleEvent, current_otel_ids, record

log = logging.getLogger(__name__)

ALBY_API_BASE = "https://api.getalby.com"
ALBY_INVOICES_PATH = "/invoices/incoming"
DEFAULT_POLL_INTERVAL_S = 30.0

# Per-rail metrics — `rail` label is fixed at "lightning" so the
# alerting query is consistent across the three rails (the spec
# names ``hapax_leverage_lightning_receipts_total{rail}`` with the
# label included for symmetry with the Liberapay metric).
lightning_receipts_total = Counter(
    "hapax_leverage_lightning_receipts_total",
    "Lightning Network receipts ingested via Alby polling.",
    ["rail"],
)
lightning_poll_errors_total = Counter(
    "hapax_leverage_lightning_poll_errors_total",
    "Lightning poll errors (network / 5xx / parse).",
    ["kind"],
)


class LightningReceiver:
    """Alby access-token poller for incoming Lightning invoices.

    Constructor parameters
    ----------------------
    token:
        Alby access token. Production reads via ``load_alby_token()``;
        tests inject a fixture string.
    poll_interval_s:
        Seconds between polls (5s floor to bound load).
    http_client:
        httpx.Client for tests to mock the transport.
    """

    _SENTINEL: str = "__not_provided__"

    def __init__(
        self,
        *,
        token: str | None = _SENTINEL,  # type: ignore[assignment]
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        http_client: httpx.Client | None = None,
    ) -> None:
        # Sentinel pattern: when no `token` kwarg is passed at all, fall
        # back to `load_alby_token()`. When the caller explicitly passes
        # `token=None`, honor that — tests rely on this distinction to
        # exercise the "credentials missing" code path.
        if token is self._SENTINEL:
            self._token = load_alby_token()
        else:
            self._token = token
        self._poll_interval_s = max(5.0, poll_interval_s)
        self._http = http_client
        self._stop_evt = threading.Event()
        self._seen_hashes: set[str] = set()
        self._disabled = False

    @property
    def disabled(self) -> bool:
        return self._disabled

    def _client(self) -> httpx.Client:
        if self._http is not None:
            return self._http
        return httpx.Client(timeout=10.0, base_url=ALBY_API_BASE)

    def poll_once(self) -> int:
        """Poll Alby once and emit any newly-settled invoices.

        Returns the number of new events emitted. Failures (network,
        non-2xx) increment ``lightning_poll_errors_total`` and return
        0; the receiver does not raise.
        """
        if self._disabled:
            return 0
        if not self._token:
            self._disable_with_refusal(
                surface="alby-token-bootstrap",
                reason="No alby-access-token in pass; rail disabled until pass insert.",
            )
            return 0
        client = self._client()
        try:
            response = client.get(
                ALBY_INVOICES_PATH,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=10.0,
            )
        except httpx.HTTPError as e:
            log.warning("Alby poll network error: %s", e)
            lightning_poll_errors_total.labels(kind="network").inc()
            return 0
        if response.status_code == 401:
            # Token rejected — most likely operator-physical OAuth UI
            # flow needed. Emit refusal annex and disable.
            self._disable_with_refusal(
                surface="alby-401",
                reason="Alby returned 401; OAuth UI re-auth required (operator-physical).",
            )
            return 0
        if response.status_code >= 500:
            lightning_poll_errors_total.labels(kind="server").inc()
            return 0
        if response.status_code >= 400:
            lightning_poll_errors_total.labels(kind="client").inc()
            log.warning("Alby poll client error: %s %s", response.status_code, response.text[:200])
            return 0
        try:
            payload = response.json()
        except ValueError:
            lightning_poll_errors_total.labels(kind="parse").inc()
            return 0
        return self._ingest(payload)

    def _ingest(self, payload: Any) -> int:
        """Convert the Alby invoices array into PaymentEvents."""
        invoices = payload if isinstance(payload, list) else payload.get("invoices") or []
        emitted = 0
        for raw in invoices:
            if not isinstance(raw, dict):
                continue
            if not _is_settled(raw):
                continue
            payment_hash = str(raw.get("payment_hash") or raw.get("identifier") or "").strip()
            if not payment_hash or payment_hash in self._seen_hashes:
                continue
            event = _alby_invoice_to_event(raw, payment_hash)
            if event is None:
                continue
            append_event(event)
            _record_chronicle(event)
            lightning_receipts_total.labels(rail="lightning").inc()
            self._seen_hashes.add(payment_hash)
            emitted += 1
        return emitted

    def _disable_with_refusal(self, *, surface: str, reason: str) -> None:
        emit_rail_refusal(rail="lightning", surface=surface, reason=reason)
        self._disabled = True

    def run_forever(self) -> None:
        """Blocking loop: poll then sleep. Returns on SIGTERM/SIGINT."""
        log.info("LightningReceiver starting; interval=%.1fs", self._poll_interval_s)
        while not self._stop_evt.is_set():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001
                log.exception("Lightning poll tick raised; continuing")
            self._stop_evt.wait(self._poll_interval_s)

    def stop(self) -> None:
        self._stop_evt.set()


def _is_settled(invoice: dict[str, Any]) -> bool:
    """Return True when an Alby invoice payload represents a settled receipt.

    Alby exposes ``state`` ("SETTLED" or "settled") and a
    ``settled`` boolean depending on API version. Be liberal in what
    we accept.
    """
    state = str(invoice.get("state") or "").lower()
    if state in ("settled", "complete", "paid"):
        return True
    return invoice.get("settled") is True


def _alby_invoice_to_event(invoice: dict[str, Any], payment_hash: str) -> PaymentEvent | None:
    amount_msat = invoice.get("amount") or invoice.get("amount_msat") or 0
    try:
        amount_sats = int(amount_msat) // 1000 if int(amount_msat) >= 1000 else int(amount_msat)
    except (TypeError, ValueError):
        amount_sats = 0
    settled_at = (
        invoice.get("settled_at") or invoice.get("created_at") or invoice.get("creation_date")
    )
    timestamp = _parse_timestamp(settled_at)
    memo = str(invoice.get("memo") or invoice.get("description") or "")[:80]
    fiat_value = invoice.get("fiat_in_cents")
    amount_usd: float | None = None
    if isinstance(fiat_value, int | float):
        amount_usd = float(fiat_value) / 100.0
    return PaymentEvent(
        timestamp=timestamp,
        rail="lightning",
        amount_sats=amount_sats,
        amount_usd=amount_usd,
        sender_excerpt=memo,
        external_id=payment_hash,
    )


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str) and value:
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _record_chronicle(event: PaymentEvent) -> None:
    """Mirror the receipt event to the chronicle for observability."""
    trace_id, span_id = current_otel_ids()
    record(
        ChronicleEvent(
            ts=event.timestamp.timestamp(),
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            source="payment_processors.lightning",
            event_type="payment.received",
            payload={
                "rail": event.rail,
                "amount_sats": event.amount_sats,
                "external_id": event.external_id,
                # Payments are structurally high-salience — every receipt
                # is rare and operator-relevant. 0.95 lands above the
                # chronicle-ticker 0.7 floor and just below the synthetic
                # ceiling so genuinely critical events can still rank
                # above. Source ``payment_processors.lightning`` isn't in
                # the ticker allow-list, so salience is the surfacing path.
                "salience": 0.95,
            },
        )
    )


def _now_unix() -> float:
    return time.time()


__all__ = [
    "ALBY_API_BASE",
    "ALBY_INVOICES_PATH",
    "DEFAULT_POLL_INTERVAL_S",
    "LightningReceiver",
    "lightning_poll_errors_total",
    "lightning_receipts_total",
]
