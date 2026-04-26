"""Category F processor — marketing / social-platform anti-pattern mail.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §3.F.

Server-side filter D already routes these messages to ``Hapax/Discard``
and removes them from ``INBOX``. This processor exists as the post-
modify hook so the audit log records the read and the seen-set marks
the message processed. Idempotent — re-running on the same id emits a
no-op result.
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus_client import Counter

from agents.mail_monitor.audit import audit_call

log = logging.getLogger(__name__)

DISCARD_PROCESSED_COUNTER = Counter(
    "hapax_mail_monitor_discard_processed_total",
    "Discard processor invocations by outcome.",
    labelnames=("result",),
)
for _result in ("ok", "api_error"):
    DISCARD_PROCESSED_COUNTER.labels(result=_result)


def process_discard(service: Any, message_id: str, *, label: str = "Hapax/Discard") -> bool:
    """Mark the message ``Hapax/Discard``-labelled and INBOX-removed.

    Filter D installed by ``mail-monitor-004`` already does this on
    arrival; this processor re-applies the modification idempotently in
    case the message reached the daemon by a path that bypassed the
    filter (e.g. a label that the user manually applied later).
    """
    from googleapiclient.errors import HttpError

    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={
                "addLabelIds": [label],
                "removeLabelIds": ["INBOX"],
            },
        ).execute()
    except HttpError as exc:
        DISCARD_PROCESSED_COUNTER.labels(result="api_error").inc()
        audit_call(
            "messages.modify",
            message_id=message_id,
            label=label,
            result="error",
        )
        log.warning("discard processor failed for %s: %s", message_id, exc)
        return False

    DISCARD_PROCESSED_COUNTER.labels(result="ok").inc()
    audit_call(
        "messages.modify",
        message_id=message_id,
        label=label,
        result="ok",
    )
    return True
