"""Liberapay sponsorship receive-rail.

Polls Liberapay's authenticated transactions API at
``https://liberapay.com/{username}/wallet/payins/public.json``. Each
new completed pay-in emits one ``PaymentEvent`` into the canonical
payment-event log.

Liberapay uses HTTP Basic auth with the operator's web-UI username
and password (no API token product, per the spec). Credentials are
stored in pass:

    pass insert liberapay/username
    pass insert liberapay/password

READ-ONLY contract:
    This receiver never calls payout/withdraw/transfer endpoints. The
    contract test in ``tests/payment_processors/test_read_only_contract.py``
    enforces no method named ``send``, ``initiate``, ``payout``, or
    ``transfer`` exists.

KYC threshold:
    Liberapay's KYC threshold is approximately €10,000/year. The
    threshold-monitor metric ``hapax_leverage_liberapay_threshold_proximity``
    tracks year-to-date receipts; when proximity > 0.8 the rail emits
    a refusal-brief annex urging the operator to demote the rail to
    CONDITIONAL_ENGAGE before the next ingest could trigger
    operator-physical KYC. Far below threshold for current scale.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

import httpx
from prometheus_client import Counter, Gauge

from agents.operator_awareness.state import PaymentEvent
from agents.payment_processors.event_log import append_event
from agents.payment_processors.refusal_annex import emit_rail_refusal
from agents.payment_processors.secrets import load_liberapay_credentials
from shared.chronicle import ChronicleEvent, current_otel_ids, record

log = logging.getLogger(__name__)

LIBERAPAY_API_BASE = "https://liberapay.com"
DEFAULT_POLL_INTERVAL_S = 300.0  # 5 minutes — Liberapay traffic is low-volume
KYC_EUR_THRESHOLD = 10_000.0
KYC_PROXIMITY_REFUSAL_FLOOR = 0.8

liberapay_receipts_total = Counter(
    "hapax_leverage_liberapay_receipts_total",
    "Liberapay sponsorship receipts ingested.",
)
liberapay_poll_errors_total = Counter(
    "hapax_leverage_liberapay_poll_errors_total",
    "Liberapay poll errors (network / 5xx / parse).",
    ["kind"],
)
liberapay_threshold_proximity = Gauge(
    "hapax_leverage_liberapay_threshold_proximity",
    "Year-to-date Liberapay receipts as fraction of KYC threshold.",
)


class LiberapayReceiver:
    """HTTP Basic auth poller for Liberapay sponsorship pay-ins.

    Constructor parameters
    ----------------------
    credentials:
        ``(username, password)`` tuple. Production reads via
        ``load_liberapay_credentials()``; tests inject a fixture pair.
    poll_interval_s:
        Seconds between polls (60s floor).
    http_client:
        httpx.Client for tests to mock the transport.
    """

    _SENTINEL: tuple[str, str] = ("__not_provided__", "__not_provided__")

    def __init__(
        self,
        *,
        credentials: tuple[str, str] | None = _SENTINEL,  # type: ignore[assignment]
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        http_client: httpx.Client | None = None,
    ) -> None:
        if credentials is self._SENTINEL:
            self._credentials = load_liberapay_credentials()
        else:
            self._credentials = credentials
        self._poll_interval_s = max(60.0, poll_interval_s)
        self._http = http_client
        self._stop_evt = threading.Event()
        self._seen_ids: set[str] = set()
        self._ytd_eur: float = 0.0
        self._disabled = False

    @property
    def disabled(self) -> bool:
        return self._disabled

    def _client(self) -> httpx.Client:
        if self._http is not None:
            return self._http
        return httpx.Client(timeout=15.0, base_url=LIBERAPAY_API_BASE)

    def poll_once(self) -> int:
        """Poll Liberapay once and emit any newly-completed pay-ins.

        Returns the number of new events emitted. On any failure the
        per-error counter is incremented and the function returns 0
        without raising.
        """
        if self._disabled:
            return 0
        if not self._credentials:
            self._disable_with_refusal(
                surface="liberapay-credentials-bootstrap",
                reason=(
                    "No liberapay/username + liberapay/password in pass; "
                    "rail disabled until pass insert."
                ),
            )
            return 0
        username, password = self._credentials
        url = f"/{username}/wallet/payins/public.json"
        client = self._client()
        try:
            response = client.get(url, auth=(username, password), timeout=15.0)
        except httpx.HTTPError as e:
            log.warning("Liberapay poll network error: %s", e)
            liberapay_poll_errors_total.labels(kind="network").inc()
            return 0
        if response.status_code == 401:
            self._disable_with_refusal(
                surface="liberapay-401",
                reason="Liberapay 401; password rotated? Re-insert via pass and restart.",
            )
            return 0
        if response.status_code == 403:
            # Possibly KYC blockage — operator-physical UI flow likely.
            self._disable_with_refusal(
                surface="liberapay-403-kyc",
                reason="Liberapay 403; operator-physical KYC may be required.",
            )
            return 0
        if response.status_code >= 500:
            liberapay_poll_errors_total.labels(kind="server").inc()
            return 0
        if response.status_code >= 400:
            liberapay_poll_errors_total.labels(kind="client").inc()
            return 0
        try:
            payload = response.json()
        except ValueError:
            liberapay_poll_errors_total.labels(kind="parse").inc()
            return 0
        return self._ingest(payload)

    def _ingest(self, payload: Any) -> int:
        """Convert Liberapay pay-ins payload into PaymentEvents."""
        payins = payload if isinstance(payload, list) else payload.get("payins") or []
        emitted = 0
        for raw in payins:
            if not isinstance(raw, dict):
                continue
            if not _is_completed(raw):
                continue
            payin_id = str(raw.get("id") or raw.get("uuid") or "").strip()
            if not payin_id or payin_id in self._seen_ids:
                continue
            event = _liberapay_payin_to_event(raw, payin_id)
            if event is None:
                continue
            append_event(event)
            _record_chronicle(event)
            liberapay_receipts_total.inc()
            self._seen_ids.add(payin_id)
            self._update_threshold_proximity(event)
            emitted += 1
        return emitted

    def _update_threshold_proximity(self, event: PaymentEvent) -> None:
        """Update YTD EUR running total and the proximity gauge.

        When proximity crosses 0.8 (=€8k of the €10k threshold), emit
        one refusal-brief annex so the operator demotes the rail to
        CONDITIONAL_ENGAGE before the next pay-in could push the
        annual total over the line.
        """
        if event.amount_eur is not None:
            self._ytd_eur += float(event.amount_eur)
        proximity = self._ytd_eur / KYC_EUR_THRESHOLD if KYC_EUR_THRESHOLD > 0 else 0.0
        liberapay_threshold_proximity.set(proximity)
        if proximity >= KYC_PROXIMITY_REFUSAL_FLOOR:
            emit_rail_refusal(
                rail="liberapay",
                surface="liberapay-kyc-proximity",
                reason=(
                    f"YTD Liberapay receipts {self._ytd_eur:.2f} EUR; "
                    f"proximity {proximity:.2f} ≥ {KYC_PROXIMITY_REFUSAL_FLOOR}; "
                    "demote to CONDITIONAL_ENGAGE."
                ),
            )

    def _disable_with_refusal(self, *, surface: str, reason: str) -> None:
        emit_rail_refusal(rail="liberapay", surface=surface, reason=reason)
        self._disabled = True

    def run_forever(self) -> None:
        """Blocking poll loop. Returns on SIGTERM/SIGINT."""
        log.info("LiberapayReceiver starting; interval=%.1fs", self._poll_interval_s)
        while not self._stop_evt.is_set():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001
                log.exception("Liberapay poll tick raised; continuing")
            self._stop_evt.wait(self._poll_interval_s)

    def stop(self) -> None:
        self._stop_evt.set()


def _is_completed(payin: dict[str, Any]) -> bool:
    status = str(payin.get("status") or payin.get("state") or "").lower()
    return status in ("succeeded", "completed", "settled", "executed")


def _liberapay_payin_to_event(payin: dict[str, Any], payin_id: str) -> PaymentEvent | None:
    amount = payin.get("amount") or payin.get("net_amount") or {}
    if isinstance(amount, dict):
        amount_value = amount.get("amount") or amount.get("value")
        currency = str(amount.get("currency") or "EUR").upper()
    else:
        amount_value = amount
        currency = "EUR"
    try:
        amount_float = float(amount_value) if amount_value is not None else 0.0
    except (TypeError, ValueError):
        amount_float = 0.0
    amount_eur = amount_float if currency == "EUR" else None
    timestamp = _parse_payin_timestamp(payin.get("ctime") or payin.get("timestamp"))
    excerpt = str(payin.get("description") or payin.get("memo") or "")[:80]
    return PaymentEvent(
        timestamp=timestamp,
        rail="liberapay",
        amount_sats=None,
        amount_usd=None,
        amount_eur=amount_eur,
        sender_excerpt=excerpt,
        external_id=payin_id,
    )


def _parse_payin_timestamp(value: Any) -> datetime:
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
    trace_id, span_id = current_otel_ids()
    record(
        ChronicleEvent(
            ts=event.timestamp.timestamp(),
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            source="payment_processors.liberapay",
            event_type="payment.received",
            payload={
                "rail": event.rail,
                "amount_eur": event.amount_eur,
                "external_id": event.external_id,
                # Sibling to ``payment_processors.lightning`` (#2697)
                # and ``payment_processors.nostr_zap`` (#2706). Source
                # isn't in the chronicle-ticker allow-list, so 0.95
                # surfaces sponsorship receipts via the salience path.
                "salience": 0.95,
            },
        )
    )


__all__ = [
    "DEFAULT_POLL_INTERVAL_S",
    "KYC_EUR_THRESHOLD",
    "KYC_PROXIMITY_REFUSAL_FLOOR",
    "LIBERAPAY_API_BASE",
    "LiberapayReceiver",
    "liberapay_poll_errors_total",
    "liberapay_receipts_total",
    "liberapay_threshold_proximity",
]
