"""CHANC build 1, component 3 — the withdrawal resolver and the disposition responder (§6).

**PROVISIONAL COMPOSITION.** The reply *surfacing* — pulling a withdrawal request out of an inbound
reply — is owned by ``han-mail-correction-intake-extension-20260924``, which is unstarted. This module
therefore builds the *decision* and the *answer* against :class:`chanc.IntakeRecord` and a reply-path
seam of its own (a :class:`chanc.WithdrawalRequest` in, a :class:`chanc.Disposition` and a reply out).
When the extension row lands, only the surfacing side needs reconciling; the classification contract
here should not move.

Two invariants carry the privacy and safety weight, and both are enforced rather than documented:

* **An unresolvable handle gets ONE constant-shape reply.** The subject and body are byte-identical
  for every handle that resolves to nothing, so the reply cannot be used to probe which handles
  exist (§6).
* **A store fault is ``unresolved``, never ``no_record``.** A record that cannot be read, or a store
  where two records claim the same handle, means the cited handle cannot be *proven* absent. Answering
  ``no_record`` there would be a false negative that hides a real intake, so the resolution is
  indeterminate and the classifier refuses to act (§6: classification failure is ``unresolved``,
  never an action).

The classifier itself is :func:`chanc.classify_withdrawal` — this module adds resolution and the
reply, not a second decision table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from shared import chanc, chanc_evidence

#: The one constant-shape reply for a handle that resolves to nothing. Never varies with the cited
#: handle, the sender, or the time — that is the point.
NO_RECORD_SUBJECT = "Corrections channel"
NO_RECORD_BODY = (
    "We hold no live record for that reference.\n\n"
    "If you are the sender and believe this is wrong, reply to this message and a person will look "
    "at it."
)

#: The D1 claim ceiling (§10), stated in every substantive reply.
REPLY_CLAIM_CEILING = (
    "This answer is a consistent chain over the records named above; it does not exclude deletion "
    "of the newest entries."
)

__all__ = (
    "NO_RECORD_BODY",
    "NO_RECORD_SUBJECT",
    "REPLY_CLAIM_CEILING",
    "Resolution",
    "classify_reply",
    "format_disposition_reply",
    "resolve_intake",
)


@dataclass(frozen=True)
class Resolution:
    """The result of resolving a cited handle.

    ``record`` is the resolved intake, or None. ``indeterminate`` means the store could not give a
    definite answer — a record that cannot be read, or two records claiming the same handle — and
    must never be reported as "no such handle".
    """

    record: chanc.IntakeRecord | None
    indeterminate: bool = False


def _to_record(payload: dict[str, Any]) -> chanc.IntakeRecord:
    """Project a stored create-once record onto the classifier's view of an intake."""
    receipt = payload.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    return chanc.IntakeRecord(
        handle=str(payload.get("handle", "")),
        from_address=str(payload.get("from_address", "")),
        receipt_id=str(receipt.get("receipt_id", "")),
        # The SAME evidence id the §4 emitter used: no second identifier scheme.
        intake_event_id=chanc_evidence.intake_event_id(
            keyed_digest=str(payload.get("keyed_digest", ""))
        ),
        bytes_present=bool(payload.get("bytes_present", True)),
        correction_ref=payload.get("correction_ref"),
        correction_resolved=bool(payload.get("correction_resolved", False)),
        published_with_permission=bool(payload.get("published_with_permission", False)),
        permission_record=payload.get("permission_record"),
        withdrawn=bool(payload.get("withdrawn", False)),
    )


def resolve_intake(cited_handle: object, *, records_root: Path) -> Resolution:
    """Resolve a cited handle against the create-once intake records.

    The records are keyed by the KEYED digest, so the handle is matched as a field — no second index
    is introduced. A malformed handle is refused without touching the store. Anything the store
    cannot answer definitely (unreadable record, duplicate handle) returns ``indeterminate``.
    """
    if not chanc.is_valid_handle(cited_handle):
        return Resolution(None)
    matches: list[dict[str, Any]] = []
    indeterminate = False
    for path in sorted(records_root.glob("*.json")):
        try:
            payload = json.loads(path.read_bytes())
            if not isinstance(payload, dict):
                raise ValueError("intake record is not an object")
        except (OSError, ValueError):
            # Unattributable: we cannot show this record is NOT the cited handle.
            indeterminate = True
            continue
        if payload.get("handle") == cited_handle:
            matches.append(payload)
    if indeterminate or len(matches) > 1:
        return Resolution(None, indeterminate=True)
    if not matches:
        return Resolution(None)
    return Resolution(_to_record(matches[0]))


def classify_reply(
    request: chanc.WithdrawalRequest,
    *,
    records_root: Path,
    now: datetime,
    grace: timedelta = chanc.DEFAULT_GRACE,
    no_record_allowed: bool = True,
) -> tuple[chanc.Disposition, chanc.IntakeRecord | None]:
    """Resolve then classify. The reply path's whole decision, in one call.

    Returns the disposition and the resolved record (None when nothing resolved), so the caller can
    act on the record without resolving twice.
    """
    resolution = resolve_intake(request.cited_handle, records_root=records_root)
    if resolution.indeterminate:
        return (
            chanc.Disposition(
                chanc.UNRESOLVED,
                "the intake store could not be resolved; no action was taken",
            ),
            None,
        )
    return (
        chanc.classify_withdrawal(
            request,
            resolution.record,
            now=now,
            grace=grace,
            no_record_allowed=no_record_allowed,
        ),
        resolution.record,
    )


def format_disposition_reply(disposition: chanc.Disposition) -> tuple[str, str]:
    """The §6 reply: what happened, why, and the references the sender can check.

    ``no_record`` is the constant shape and carries nothing else. Every other answer names its
    reason and its evidence refs (the sender's own receipt id, disposition event ids, and any
    publication or permission record) and states the D1 ceiling. No submitter content, and not the
    cited handle, appears in either field.
    """
    if disposition.code == chanc.NO_RECORD:
        return NO_RECORD_SUBJECT, NO_RECORD_BODY
    subject = f"Corrections channel — {disposition.code}"
    lines = [disposition.reason]
    if disposition.evidence_refs:
        lines += ["", "References: " + ", ".join(disposition.evidence_refs)]
    lines += ["", REPLY_CLAIM_CEILING]
    return subject, "\n".join(lines)
