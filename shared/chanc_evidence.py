"""CHANC evidence events — ``han.mail.*`` into the coordination log, keyed digests only (SPEC §4).

§4 is a privacy invariant, not a formatting preference. These events are institutional records and
are permanent, so a bare hash of low-entropy personal content is dictionary-reversible. Every
payload therefore carries the **keyed** digest — the HMAC of the content digest under the keeper
key — and nothing subject-specific enters the log at all: no plain content digest, no sender
address, no subject, no body, and neither the sender's withdrawal handle nor the receipt id that
embeds its prefix (the log has no delete path, and those two rejoin a withdrawn sender).

The emitter checks the SHAPE of what it is handed (64 lowercase hex, a valid handle, a tz-aware
ISO timestamp, a receipt id); whether the 64-hex value is the keyed digest rather than the plain
one is the caller's duty.

Discipline:

* **off by default.** No-op unless an ``event_log`` is injected or ``HAPAX_CHANC_EVIDENCE`` is set to
  a truthy spelling (``1``/``true``/``yes``/``on``, the receipt switch's rule), so an ordinary pull, a
  test, or a sandboxed run never writes the coordination log. ``main()``'s armed receipt path
  injects the canonical log, so arming receipts arms the intake event with them;
* **never raises.** A dead ledger never breaks the pull;
* **the intake event is an evidence ref.** ``IntakeRecord.intake_event_id`` cites it, so it is part of
  the binding: when the mirror is armed, the pull sends no receipt until ``emit_intake`` returns a
  receipt (canonical append, or the event is already there) and retries it on later pulls. The
  ``receipt.issued`` event stays best-effort observability.

The event store itself is the estate's existing one (``shared/coord_event_log``): this module adds a
vocabulary, not a schema, a store or a projection.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime

from shared import chanc
from shared.coord_event_log import (
    AppendReceipt,
    CoordEvent,
    CoordEventLog,
    CoordWriter,
    DuplicateEventError,
    default_event_log,
)

CANON_CHANC_INTAKE = "han.mail.intake"
CANON_CHANC_RECEIPT_ISSUED = "han.mail.receipt.issued"
#: The env switch for the best-effort mirror, in the same spirit as HAPAX_COORD_EVIDENCE_MIRROR.
CHANC_EVIDENCE_ENV = "HAPAX_CHANC_EVIDENCE"
ACTOR = "han-mail-pull"

_KEYED_RE = re.compile(r"\A[0-9a-f]{64}\Z")
#: ``chanc.receipt_id``: second-resolution UTC stamp, then the handle's 16-hex prefix.
_RECEIPT_ID_RE = re.compile(r"\A[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}\Z")
#: The receipt switch's truthy spellings; anything else, ``0`` and ``false`` included, is off.
_ARMED = frozenset({"1", "true", "yes", "on"})

__all__ = (
    "ACTOR",
    "CANON_CHANC_INTAKE",
    "CANON_CHANC_RECEIPT_ISSUED",
    "CHANC_EVIDENCE_ENV",
    "emit_intake",
    "emit_receipt_issued",
    "evidence_armed",
    "intake_event_id",
    "receipt_issued_event_id",
)


def _domain_digest(domain: str, value: str) -> str:
    return hashlib.sha256(f"{domain}\0{value}".encode()).hexdigest()


def intake_event_id(*, keyed_digest: str) -> str:
    """Deterministic id for one message's intake event. Idempotent by construction."""
    return f"han-mail-intake-{_domain_digest(CANON_CHANC_INTAKE, keyed_digest)}"


def receipt_issued_event_id(*, keyed_digest: str) -> str:
    """Deterministic id for one message's receipt issuance (one receipt per message). Distinct from
    the intake of the same message. Over the keyed digest alone: no handle-derived input."""
    return f"han-mail-receipt-{_domain_digest(CANON_CHANC_RECEIPT_ISSUED, keyed_digest)}"


def _valid_keyed(keyed_digest: object) -> str | None:
    """A 64-lowercase-hex value or nothing. Shape only: keyedness is the caller's duty. There is no
    fallback to any other value, ever."""
    return keyed_digest if isinstance(keyed_digest, str) and _KEYED_RE.match(keyed_digest) else None


def _coord_timestamp(issued_at: object) -> str | None:
    """A tz-aware ISO timestamp in the coord log's ``Z`` form, or nothing."""
    try:
        parsed = datetime.fromisoformat(str(issued_at))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def evidence_armed() -> bool:
    """True only for a truthy ``HAPAX_CHANC_EVIDENCE``; unset, empty, ``0`` or ``false`` is off."""
    return os.environ.get(CHANC_EVIDENCE_ENV, "").strip().lower() in _ARMED


def _emit(event: CoordEvent, event_log: CoordEventLog | None) -> AppendReceipt | None:
    """A receipt when the event is in the canonical log (appended now or already there), else None:
    disarmed, or the ledger refused. Never raises."""
    if event_log is None and not evidence_armed():
        return None
    try:
        log = event_log if event_log is not None else default_event_log()
        try:
            receipt = log.append(event, writer=CoordWriter.daemon())
            return None if getattr(receipt, "appended", True) is False else receipt
        except DuplicateEventError:
            # Already recorded (a retry of the same deterministic event): a receipt, not a failure.
            return AppendReceipt(
                event_id=event.event_id,
                appended=True,
                spooled=False,
                sequence=None,
                db_path=log.db_path,
                jsonl_path=log.jsonl_path,
            )
    except Exception:
        return None  # Never break the pull over the ledger; the caller decides what None blocks.


def emit_intake(
    *,
    keyed_digest: str,
    handle: str,
    terms_digest: str,
    issued_at: str,
    event_log: CoordEventLog | None = None,
) -> AppendReceipt | None:
    """Record one intake in the coord log: the keyed digest and the public terms digest only.

    ``handle`` is shape-checked so a swapped argument is refused, and is never written. Returns the
    append receipt, or None when disarmed, refused for shape, or the ledger failed.
    """
    keyed = _valid_keyed(keyed_digest)
    terms = _valid_keyed(terms_digest)
    timestamp = _coord_timestamp(issued_at)
    if keyed is None or terms is None or timestamp is None or not chanc.is_valid_handle(handle):
        return None
    try:
        event = CoordEvent(
            event_id=intake_event_id(keyed_digest=keyed),
            timestamp=timestamp,
            event_type=CANON_CHANC_INTAKE,
            actor=ACTOR,
            subject=keyed,
            payload={"keyed_digest": keyed, "terms_digest": terms},
        )
    except Exception:
        return None
    return _emit(event, event_log)


def emit_receipt_issued(
    *,
    keyed_digest: str,
    receipt_id: str,
    event_log: CoordEventLog | None = None,
) -> AppendReceipt | None:
    """Mirror one receipt issuance into the coord log: the keyed digest only.

    ``receipt_id`` is shape-checked and never written: it embeds the handle's prefix.
    """
    keyed = _valid_keyed(keyed_digest)
    if keyed is None or not (isinstance(receipt_id, str) and _RECEIPT_ID_RE.match(receipt_id)):
        return None
    try:
        event = CoordEvent(
            event_id=receipt_issued_event_id(keyed_digest=keyed),
            timestamp=_now_iso(),
            event_type=CANON_CHANC_RECEIPT_ISSUED,
            actor=ACTOR,
            subject=keyed,
            payload={"keyed_digest": keyed},
        )
    except Exception:
        return None
    return _emit(event, event_log)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
