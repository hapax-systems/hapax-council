"""Idempotent installer for the four Hapax/* Gmail labels.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §2.

The labels are the substrate every other privacy mechanism rests on
(spec §5.2 ``users.watch()`` filter, §5.3 ``messages.list`` query
gate, §5.4 audit log). Without them the rest of the daemon cannot
run — bootstrap is fail-loudly: any label create error is surfaced
to the caller as :class:`LabelBootstrapError`.

Idempotency: ``users.labels.list`` is consulted first. Labels whose
``name`` is already present are reused (the existing id is returned).
A second invocation of :func:`bootstrap_labels` against the same
account is a no-op that returns the same id mapping.
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus_client import Counter

log = logging.getLogger(__name__)

HAPAX_LABEL_NAMES: list[str] = [
    "Hapax/Verify",
    "Hapax/Suppress",
    "Hapax/Operational",
    "Hapax/Discard",
]

LABEL_INSTALLS_COUNTER = Counter(
    "hapax_mail_monitor_label_installs_total",
    "Hapax label install attempts by label and outcome.",
    labelnames=("label", "result"),
)
for _label in HAPAX_LABEL_NAMES:
    for _result in ("exists", "created", "error"):
        LABEL_INSTALLS_COUNTER.labels(label=_label, result=_result)


class LabelBootstrapError(RuntimeError):
    """Raised when a Hapax/* label cannot be created or fetched."""


def bootstrap_labels(service: Any) -> dict[str, str]:
    """Ensure all four ``Hapax/*`` labels exist; return name → id mapping.

    ``service`` is an authenticated ``gmail v1`` discovery client (the
    return value of :func:`agents.mail_monitor.oauth.build_gmail_service`).

    Each call:

    1. Lists current labels via ``users.labels.list``.
    2. For each name in :data:`HAPAX_LABEL_NAMES`:

       - if present: emit ``result="exists"`` to the counter, reuse the id;
       - if missing: ``users.labels.create`` it (``labelShow`` /
         ``show`` visibility), emit ``result="created"``.

    3. Returns ``{name: id}`` for all four. The mapping is consumed by
       :func:`agents.mail_monitor.filter_bootstrap.bootstrap_filters`,
       which translates label names to ids in filter actions.

    Raises :class:`LabelBootstrapError` if any label cannot be created
    or read. Bootstrap is fail-loud — there's no graceful degradation
    if labels go missing.
    """
    from googleapiclient.errors import HttpError

    try:
        existing = service.users().labels().list(userId="me").execute().get("labels", [])
    except HttpError as exc:
        for name in HAPAX_LABEL_NAMES:
            LABEL_INSTALLS_COUNTER.labels(label=name, result="error").inc()
        raise LabelBootstrapError(f"users.labels.list failed: {exc}") from exc

    name_to_id: dict[str, str] = {label["name"]: label["id"] for label in existing}
    result_map: dict[str, str] = {}

    for name in HAPAX_LABEL_NAMES:
        if name in name_to_id:
            LABEL_INSTALLS_COUNTER.labels(label=name, result="exists").inc()
            result_map[name] = name_to_id[name]
            continue
        body = {
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        try:
            created = service.users().labels().create(userId="me", body=body).execute()
        except HttpError as exc:
            LABEL_INSTALLS_COUNTER.labels(label=name, result="error").inc()
            raise LabelBootstrapError(f"users.labels.create({name!r}) failed: {exc}") from exc

        LABEL_INSTALLS_COUNTER.labels(label=name, result="created").inc()
        result_map[name] = created["id"]
        log.info("created Gmail label %s (id=%s)", name, created["id"])

    return result_map
