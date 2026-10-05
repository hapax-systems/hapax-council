"""CHANC evidence events — ``han.mail.*`` into the coordination log, keyed digests only (SPEC §4).

§4 is a privacy invariant, not a formatting preference. These events are institutional records and
are permanent, so a bare hash of low-entropy personal content is dictionary-reversible. Every
payload therefore carries the **keyed** digest — the HMAC of the content digest under the keeper
key — and nothing subject-specific enters the log at all: no plain content digest, no sender
address, no subject, no body.

Discipline, matching ``shared/coord_projection``'s best-effort observability mirrors:

* **off by default.** No-op unless an ``event_log`` is injected or ``HAPAX_CHANC_EVIDENCE`` is set,
  so an ordinary pull, a test, or a sandboxed run never writes the coordination log;
* **best-effort.** Never raises. The intake record and the receipt are the authoritative surfaces;
  this mirror is observability, and it is load-bearing for no invariant. A dead ledger must not
  break the pull or lose a receipt.

The event store itself is the estate's existing one (``shared/coord_event_log``): this module adds a
vocabulary, not a schema, a store or a projection.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime

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

__all__ = (
    "ACTOR",
    "CANON_CHANC_INTAKE",
    "CANON_CHANC_RECEIPT_ISSUED",
    "CHANC_EVIDENCE_ENV",
    "emit_intake",
    "emit_receipt_issued",
    "intake_event_id",
    "receipt_issued_event_id",
)


def _domain_digest(domain: str, value: str) -> str:
    return hashlib.sha256(f"{domain}\0{value}".encode()).hexdigest()


def intake_event_id(*, keyed_digest: str) -> str:
    """Deterministic id for one message's intake event. Idempotent by construction."""
    return f"han-mail-intake-{_domain_digest(CANON_CHANC_INTAKE, keyed_digest)}"


def receipt_issued_event_id(*, keyed_digest: str, receipt_id: str) -> str:
    """Deterministic id for one receipt issuance. Distinct from the intake of the same message."""
    return f"han-mail-receipt-{_domain_digest(CANON_CHANC_RECEIPT_ISSUED, f'{keyed_digest}\0{receipt_id}')}"


def _valid_keyed(keyed_digest: object) -> str | None:
    """A keyed digest or nothing. There is no fallback to the plain digest, ever."""
    return keyed_digest if isinstance(keyed_digest, str) and _KEYED_RE.match(keyed_digest) else None


def _emit(event: CoordEvent, event_log: CoordEventLog | None) -> AppendReceipt | None:
    if event_log is None and not os.environ.get(CHANC_EVIDENCE_ENV):
        return None
    try:
        log = event_log if event_log is not None else default_event_log()
        return log.append(event, writer=CoordWriter.daemon())
    except DuplicateEventError:
        return None  # An idempotent retry of the same event, not a failure.
    except Exception:
        return None  # Best-effort: never break the pull over an observability mirror.


def emit_intake(
    *,
    keyed_digest: str,
    handle: str,
    terms_digest: str,
    issued_at: str,
    event_log: CoordEventLog | None = None,
) -> AppendReceipt | None:
    """Mirror one intake into the coord log. Keyed digest and handles only."""
    keyed = _valid_keyed(keyed_digest)
    if keyed is None:
        return None
    try:
        event = CoordEvent(
            event_id=intake_event_id(keyed_digest=keyed),
            timestamp=str(issued_at),
            event_type=CANON_CHANC_INTAKE,
            actor=ACTOR,
            subject=keyed,
            payload={
                "keyed_digest": keyed,
                "handle": str(handle),
                "terms_digest": str(terms_digest),
            },
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
    """Mirror one receipt issuance into the coord log. Keyed digest and the receipt id only."""
    keyed = _valid_keyed(keyed_digest)
    if keyed is None:
        return None
    try:
        event = CoordEvent(
            event_id=receipt_issued_event_id(keyed_digest=keyed, receipt_id=str(receipt_id)),
            timestamp=_now_iso(),
            event_type=CANON_CHANC_RECEIPT_ISSUED,
            actor=ACTOR,
            subject=keyed,
            payload={"keyed_digest": keyed, "receipt_id": str(receipt_id)},
        )
    except Exception:
        return None
    return _emit(event, event_log)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
