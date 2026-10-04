"""CHANC minimal core — receipted hrl-han@ intake and withdrawal (c1-chanc-build1-20261004).

SPEC: ``frame/chanc-minimal-20261004/SPEC.md`` §4–§6, with the seat rulings
(``lanebus/dev1/20261004T161719Z-…``):

- **D4 (handle):** a RANDOM 256-bit handle plus a salted commitment — NOT the content digest.
  A content-derived handle can be guessed against a known message; a random handle cannot, and the
  salted commitment binds the handle to the intake for proof without being a reversible content hash.
- **§4 (evidence keying):** event payloads carry a KEYED digest — HMAC of the content digest under a
  keeper-held key — never the plain content hash (a bare hash of low-entropy personal content is
  dictionary-reversible and the log is permanent).
- **§6 (withdrawal):** the classifier reads for authority ONLY (a) a syntactically valid handle and
  (b) whether it resolves to a recorded intake; everything else is data. Corroboration (recorded
  from-address + transport alignment) is channel corroboration, never person authentication; a
  granted deletion needs confirmation plus a grace window. A sending address alone never deletes.
- **Operator 2026-10-04:** no answer window and no new register commitment — the classifier makes no
  response-time promise. The 7-day grace is an internal parameter of the withdrawal mechanism only.

This module is PURE: no I/O, no sending, no store writes, no clock of its own. The Worker
(``han_mail_pull``), the reply path, and the coord-log emitter call it; receipt emission, evidence
events and the public terms are the other build-1 components.
"""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256

#: §6 disposition codes. One spelling of the pending-precondition code: ``no_pending`` (seat ruling).
YES = "yes"
NO_RECORD = "no_record"
NO_PUBLISHED = "no_published"
NO_PENDING = "no_pending"
RETENTION_LIVE = "retention_live"
UNRESOLVED = "unresolved"
PENDING = "pending"

#: The grace window after a confirmed withdrawal before deletion — an INTERNAL parameter only,
#: never stated as a public promise (operator 2026-10-04). §11 proposed value.
DEFAULT_GRACE = timedelta(days=7)

#: A handle is the full 256-bit value as lowercase hex (random; D4).
_HANDLE_RE = re.compile(r"\A[0-9a-f]{64}\Z")
#: A content digest (quarantine filename / receipt) is likewise 64 lowercase hex.
_DIGEST_RE = re.compile(r"\A[0-9a-f]{64}\Z")


def generate_handle() -> str:
    """A fresh RANDOM 256-bit handle (D4). Not derived from the message, so it cannot be guessed
    against a known message."""
    return secrets.token_hex(32)


def is_valid_handle(handle: object) -> bool:
    """Syntactic validity only — one of the two things §6 reads for authority."""
    return isinstance(handle, str) and bool(_HANDLE_RE.match(handle))


def keyed_digest(content_digest: str, *, key: bytes) -> str:
    """§4 evidence keying: HMAC-SHA256 of the content digest under a keeper-held key. The log
    carries this, never the plain content hash."""
    if not _DIGEST_RE.match(content_digest):
        raise ValueError("content_digest must be 64 lowercase hex characters")
    return hmac.new(key, content_digest.encode("ascii"), sha256).hexdigest()


def salted_commitment(content_digest: str, *, salt: bytes, key: bytes) -> str:
    """D4 salted commitment binding a random handle's intake to the message, under a per-record
    salt and the keeper key — not a reversible content hash."""
    if not _DIGEST_RE.match(content_digest):
        raise ValueError("content_digest must be 64 lowercase hex characters")
    return hmac.new(key, salt + content_digest.encode("ascii"), sha256).hexdigest()


def verify_commitment(content_digest: str, commitment: str, *, salt: bytes, key: bytes) -> bool:
    """Constant-time check that a stored commitment matches the message (integrity/proof)."""
    try:
        expected = salted_commitment(content_digest, salt=salt, key=key)
    except ValueError:
        return False
    return hmac.compare_digest(expected, commitment)


@dataclass(frozen=True)
class IntakeRecord:
    """The resolvable state of one recorded intake. Carries no message bytes and no plain content
    hash beyond what resolution needs; the plain digest lives only in the quarantine filename (until
    deletion) and the sender's receipt."""

    handle: str
    from_address: str  # the address recorded at intake (for channel corroboration)
    receipt_id: str  # the intake receipt the sender holds (evidence ref)
    intake_event_id: str  # the han.mail.intake coordination event (evidence ref)
    bytes_present: bool = True  # the .eml/.json still in quarantine
    correction_ref: str | None = None  # the correction this message proposes
    correction_resolved: bool = False  # whether that correction is resolved
    published_with_permission: bool = False  # quoted in a published correction WITH permission
    permission_record: str | None = None  # the receipted permission handle, if any
    withdrawn: bool = False  # a prior withdrawal already deleted + tombstoned this


@dataclass(frozen=True)
class WithdrawalRequest:
    """A message to hrl-han@ citing a handle. Attacker-chosen content; data until classified."""

    cited_handle: object
    from_address: str
    transport_aligned: bool  # DKIM alignment / equivalent transport check passed at receipt
    confirmed_at: datetime | None = None  # the sender's confirmation reply to our confirmation


@dataclass(frozen=True)
class Disposition:
    """A classification outcome. ``evidence_refs`` are the intake receipt id, disposition event ids
    and any publication/permission reference — never submitter content. ``rate_limited`` marks the
    constant-shape ``no_record`` reply so the responder throttles it (it cannot be used to probe
    which digests exist)."""

    code: str
    reason: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    rate_limited: bool = False


def _corroborated(request: WithdrawalRequest, record: IntakeRecord) -> bool:
    """Channel corroboration (§6 precondition 2): the request arrives from the recorded address and
    passes transport alignment. NOT person authentication — a weaker check the grace window offsets.
    A shared mailbox passes this but still never deletes without confirmation+grace."""
    return request.transport_aligned and request.from_address == record.from_address


def classify_withdrawal(
    request: WithdrawalRequest,
    record: IntakeRecord | None,
    *,
    now: datetime,
    grace: timedelta = DEFAULT_GRACE,
    no_record_allowed: bool = True,
) -> Disposition:
    """Classify a withdrawal per §6. ``record`` is the result of resolving the cited handle (None if
    it resolves to nothing). ``no_record_allowed`` is the rate-limiter's verdict for the constant
    shape reply — when False the (still constant) reply is marked rate_limited so the responder
    suppresses it. The classifier never deletes and never answers yes on a sending address alone."""
    # (a) syntactic validity and (b) resolution are the ONLY things read for authority. A bad
    # handle or one that resolves to nothing — including a replayed handle whose intake was already
    # withdrawn — gets the one constant-shape, rate-limited reply, so the reply cannot probe which
    # digests exist.
    if (
        not is_valid_handle(request.cited_handle)
        or record is None
        or (record.withdrawn and not record.bytes_present)
    ):
        return Disposition(
            NO_RECORD,
            "handle resolves to no live intake",
            rate_limited=not no_record_allowed,
        )

    refs = (record.receipt_id, record.intake_event_id)

    # Contradictory store state is never forced into an action (§6 unresolved).
    if record.bytes_present and record.withdrawn:
        return Disposition(UNRESOLVED, "contradictory store state", evidence_refs=refs)

    # Already quoted in a published correction WITH the sender's permission: the answer is no, and
    # names the constraint. If the permission record is missing, the branch cannot be taken and the
    # answer is no_pending with the missing precondition named (§6).
    if record.published_with_permission:
        if record.permission_record:
            return Disposition(
                NO_PUBLISHED,
                "already quoted in a published correction with permission",
                evidence_refs=(*refs, record.permission_record),
            )
        return Disposition(
            NO_PENDING,
            "published-with-permission claimed but the permission record is missing",
            evidence_refs=refs,
        )

    # The correction the message proposes is still open: kept until that correction is resolved;
    # names the correction's record reference. No response-time promise (operator 2026-10-04).
    if record.correction_ref is not None and not record.correction_resolved:
        return Disposition(
            RETENTION_LIVE,
            "kept until the proposed correction is resolved",
            evidence_refs=(*refs, record.correction_ref),
        )

    # A deletable intake. Channel corroboration gates even reaching confirmation; missing or failed
    # corroboration (spoofed address, wrong address, unaligned transport) is pending + escalation,
    # never a silent yes and never deletion on a sending address alone.
    if not _corroborated(request, record):
        return Disposition(
            PENDING,
            "channel corroboration incomplete; escalated to a human-reachable path",
            evidence_refs=refs,
        )

    # Corroborated: confirmation plus the internal grace window. Deletion only after the sender's
    # confirmation reply AND the grace has elapsed.
    if request.confirmed_at is None:
        return Disposition(
            PENDING, "confirmation requested; awaiting the sender's reply", evidence_refs=refs
        )
    if now < request.confirmed_at + grace:
        return Disposition(PENDING, "confirmed; within the grace window", evidence_refs=refs)
    return Disposition(YES, "withdrawal granted; bytes deleted and tombstoned", evidence_refs=refs)
