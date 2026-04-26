"""Category C processor — SUPPRESS opt-out replies.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §3.C.

Detection happens upstream in :func:`agents.mail_monitor.classifier.classify` —
this processor assumes the message has already been categorised as
:data:`Category.C_SUPPRESS`. Its job is the persistence side:

1. Append an ``initiator=target_optout`` entry to the
   ``contact-suppression-list.yaml`` keyed by sender's email domain
   (and ORCID, when known via prior cold-contact registry).
2. Append a ``kind=suppress`` refusal-brief log line so the operator
   sidebar increments ``awareness.mail.suppress_count_1h``.
3. Apply ``messages.modify`` to mark the message read and remove
   ``INBOX`` (idempotent).

Load-bearing: the cold-contact daemons consult this list before any
outbound send; without this processor, opt-out replies cannot
populate the suppression list automatically.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from prometheus_client import Counter

from agents.mail_monitor.audit import audit_call
from agents.mail_monitor.processors.refusal_feedback import emit_refusal_feedback
from shared.contact_suppression import append_entry as suppression_append

log = logging.getLogger(__name__)

SUPPRESS_PROCESSED_COUNTER = Counter(
    "hapax_mail_monitor_suppress_processed_total",
    "Suppress processor invocations by outcome.",
    labelnames=("result",),
)
for _result in ("ok", "no_sender", "api_error", "duplicate"):
    SUPPRESS_PROCESSED_COUNTER.labels(result=_result)


# ``alice@example.com`` → ``example.com``. Tolerates common variants
# like display-name-prefixed addresses (``"Alice" <alice@x.com>``) by
# preferring the bracketed form when present.
_ANGLE_ADDR_RE = re.compile(r"<([^>]+)>")


def _extract_domain(sender: str | None) -> str | None:
    if not sender:
        return None
    bracketed = _ANGLE_ADDR_RE.search(sender)
    addr = bracketed.group(1) if bracketed else sender
    addr = addr.strip().lower()
    if "@" not in addr:
        return None
    domain = addr.split("@", 1)[1].strip()
    return domain or None


def process_suppress(service: Any, message: dict[str, Any]) -> bool:
    """Persist the SUPPRESS opt-out and finalize Gmail-side handling.

    Returns ``True`` on full success (entry written + Gmail mutation
    applied). Returns ``False`` on any sub-step failure; each failure
    mode increments a labelled counter.
    """
    from googleapiclient.errors import HttpError

    sender = message.get("sender")
    domain = _extract_domain(sender)
    message_id = message.get("id") or message.get("messageId")
    orcid = message.get("orcid")  # populated when prior cold-contact registry knows the target

    if not domain and not orcid:
        SUPPRESS_PROCESSED_COUNTER.labels(result="no_sender").inc()
        log.warning(
            "suppress processor: message %s has neither parseable sender domain "
            "nor known ORCID; skipping",
            message_id,
        )
        return False

    entry = suppression_append(
        orcid=orcid,
        email_domain=domain,
        reason="mail-monitor SUPPRESS reply",
        initiator="target_optout",
        message_id=message_id,
    )

    # Refusal-brief log entry. ``emit_refusal_feedback`` already
    # SHA-1-hashes sender + subject before writing — spec §6 redaction.
    emit_refusal_feedback(message, kind="suppress")

    # Gmail-side: mark read + remove INBOX. Idempotent — the message
    # might already be in this state if filter B fired.
    if service is not None:
        try:
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={
                    "removeLabelIds": ["INBOX", "UNREAD"],
                },
            ).execute()
        except HttpError as exc:
            SUPPRESS_PROCESSED_COUNTER.labels(result="api_error").inc()
            audit_call(
                "messages.modify",
                message_id=message_id,
                label="Hapax/Suppress",
                result="error",
            )
            log.warning(
                "suppress processor Gmail mutation failed for %s: %s",
                message_id,
                exc,
            )
            return False
        audit_call(
            "messages.modify",
            message_id=message_id,
            label="Hapax/Suppress",
            result="ok",
        )

    # ``suppression_append`` is idempotent — when the entry already
    # existed it returns the prior entry unchanged. We can detect that
    # by comparing the returned message_id against ours.
    if entry.message_id is not None and entry.message_id != message_id:
        SUPPRESS_PROCESSED_COUNTER.labels(result="duplicate").inc()
    else:
        SUPPRESS_PROCESSED_COUNTER.labels(result="ok").inc()
    return True
