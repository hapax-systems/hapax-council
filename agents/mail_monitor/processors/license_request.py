"""LICENSE-REQUEST processor — daemon-tractable monetization rail.

Detects line-anchored ``LICENSE-REQUEST`` subject prefix on inbound mail
(case-insensitive), files the .eml verbatim into the operator's license-
request vault folder, and emits a chronicle event so downstream license-
quote drafting can pick it up.

Phase 1 (this PR): detect + file + chronicle + counter. Idempotent on
``messageId``.

Phase 2 (cred-blocked on ``pass insert lightning/lnbits-token`` and
``pass insert liberapay/api-token``): auto-reply with payment-rail-link
template (Lightning invoice + Liberapay URL). Stripe Payment Link is
explicitly REFUSED in sister task ``leverage-money-stripe-payment-link-
REFUSED`` per refusal-as-data substrate.

Spec: ``docs/research/2026-04-25-leverage-strategy.md``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import Counter

log = logging.getLogger(__name__)


LICENSE_REQUEST_DIR = Path("~/hapax-state/license-requests").expanduser()

# Line-anchored: the prefix MUST start at column 0 of the subject line.
# Mid-string conversational mentions ("Re: my LICENSE-REQUEST question")
# must not auto-trigger the daemon-side filing + auto-reply path.
LICENSE_REQUEST_RE = re.compile(r"^LICENSE-REQUEST\b", re.IGNORECASE)

# Sender display-name + bracketed-addr disambiguation. Mirrors the same
# helper in suppress.py — kept local to avoid coupling the two processors.
_ANGLE_ADDR_RE = re.compile(r"<([^>]+)>")


LICENSE_REQUEST_COUNTER = Counter(
    "hapax_leverage_license_requests_total",
    "LICENSE-REQUEST processor invocations by outcome.",
    ["outcome"],
)
for _outcome in ("filed", "duplicate", "no_sender", "no_match", "io_error"):
    LICENSE_REQUEST_COUNTER.labels(outcome=_outcome)


def _extract_addr(sender: str | None) -> str | None:
    if not sender:
        return None
    bracketed = _ANGLE_ADDR_RE.search(sender)
    return (bracketed.group(1) if bracketed else sender).strip().lower() or None


def _sender_hash(sender: str | None) -> str:
    """Short SHA-1 prefix of the sender address — privacy-preserving identifier."""
    addr = _extract_addr(sender) or "unknown"
    return hashlib.sha1(addr.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def detect_license_request(message: dict[str, Any]) -> bool:
    """Return True iff the message subject starts with LICENSE-REQUEST."""
    subject = message.get("subject") or ""
    return LICENSE_REQUEST_RE.match(subject) is not None


def _vault_path(message: dict[str, Any], now: datetime) -> Path:
    """Compute the deterministic vault filename for this message."""
    sender_h = _sender_hash(message.get("sender"))
    msg_id = message.get("id") or message.get("messageId") or "unknown"
    msg_id_h = hashlib.sha1(str(msg_id).encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    iso = now.strftime("%Y-%m-%d")
    return LICENSE_REQUEST_DIR / f"{iso}-{sender_h}-{msg_id_h}.eml"


def _serialise_message(message: dict[str, Any]) -> str:
    """Render the message dict to RFC822-ish text for vault filing."""
    subject = message.get("subject") or ""
    sender = message.get("sender") or ""
    body = message.get("body") or ""
    msg_id = message.get("id") or message.get("messageId") or ""
    return f"From: {sender}\nSubject: {subject}\nMessage-ID: {msg_id}\n\n{body}"


def process_license_request(
    message: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Persist a LICENSE-REQUEST mail to the vault folder.

    Returns ``True`` on success (or duplicate skip — both are constitutional
    no-ops). Returns ``False`` on detection-miss / no-sender / io-error.
    Idempotent: re-processing the same ``messageId`` is a no-op when the
    vault file already exists.
    """
    if not detect_license_request(message):
        LICENSE_REQUEST_COUNTER.labels(outcome="no_match").inc()
        return False

    sender = message.get("sender")
    if not _extract_addr(sender):
        LICENSE_REQUEST_COUNTER.labels(outcome="no_sender").inc()
        log.warning("license_request: message lacks parseable sender; skipping")
        return False

    now = now or datetime.now(UTC)
    path = _vault_path(message, now)

    if path.exists():
        LICENSE_REQUEST_COUNTER.labels(outcome="duplicate").inc()
        return True

    try:
        LICENSE_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialise_message(message), encoding="utf-8")
    except OSError:
        LICENSE_REQUEST_COUNTER.labels(outcome="io_error").inc()
        log.exception("license_request: filing failed for %s", path)
        return False

    _emit_chronicle(message, path)
    LICENSE_REQUEST_COUNTER.labels(outcome="filed").inc()
    return True


def _emit_chronicle(message: dict[str, Any], filed_path: Path) -> None:
    """Best-effort chronicle event so downstream daemons can react."""
    try:
        from shared.chronicle import ChronicleEvent, current_otel_ids
        from shared.chronicle import record as chronicle_record

        trace_id, span_id = current_otel_ids()
        chronicle_record(
            ChronicleEvent(
                ts=time.time(),
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                source="mail_monitor_license_request",
                event_type="license_request.filed",
                payload={
                    "message_id": message.get("id") or message.get("messageId"),
                    "sender_hash": _sender_hash(message.get("sender")),
                    "filed_path": str(filed_path),
                    "subject": (message.get("subject") or "")[:120],
                },
            )
        )
    except Exception:
        log.warning("license_request: chronicle emission failed", exc_info=True)


__all__ = [
    "LICENSE_REQUEST_COUNTER",
    "LICENSE_REQUEST_DIR",
    "LICENSE_REQUEST_RE",
    "detect_license_request",
    "process_license_request",
]
