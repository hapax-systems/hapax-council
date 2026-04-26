"""mail-monitor message dispatcher.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §3 / §5.4.

The runner is the post-classifier orchestrator. Given a fetched Gmail
message dict, it:

1. Classifies the message (rule-based; LLM fallback lands in a
   follow-up commit).
2. Looks up the per-category processor.
3. Invokes the processor.
4. Audits each step.

The full ``process_history`` Pub/Sub-driven loop lands with the webhook
receivers (mail-monitor-006). This module ships the dispatch primitive
so 008/009/010/011 can wire their processors into a known callsite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from prometheus_client import Counter

from agents.mail_monitor.audit import audit_call
from agents.mail_monitor.classifier import Category, classify
from agents.mail_monitor.processors.discard import process_discard
from agents.mail_monitor.processors.refusal_feedback import emit_refusal_feedback
from agents.mail_monitor.processors.suppress import process_suppress

log = logging.getLogger(__name__)

DISPATCH_COUNTER = Counter(
    "hapax_mail_monitor_dispatch_total",
    "Per-message dispatch attempts by category and outcome.",
    labelnames=("category", "result"),
)
for _category in Category:
    for _result in ("processed", "deferred", "error"):
        DISPATCH_COUNTER.labels(category=_category.value, result=_result)


# Categories whose processors land in later cc-tasks. ``deferred`` is a
# legitimate non-error outcome — the classifier did its job; downstream
# code is just not yet on main. Each gets a distinct counter result so
# the gap is visible in Grafana.
_DEFERRED_CATEGORIES: set[Category] = {
    Category.A_ACCEPT,  # mail-monitor-010 auto-clicker
    Category.B_VERIFY,  # mail-monitor-009 verify processor
    Category.D_OPERATIONAL,  # mail-monitor-011 operational awareness
}


def dispatch_message(service: Any, message: dict[str, Any]) -> Category:
    """Classify ``message`` and invoke the per-category processor.

    ``message`` is the dict returned by ``messages.get`` enriched with
    ``label_names``, ``replies_to_hapax_thread``, ``body_text`` (see
    classifier docstring). ``service`` is the authenticated Gmail
    discovery client.

    Returns the resolved :class:`Category`.
    """
    message_id = message.get("id") or message.get("messageId") or "<unknown>"
    category, source = classify(message)

    log.info(
        "mail dispatch: id=%s category=%s source=%s",
        message_id,
        category.value,
        source,
    )
    audit_call(
        "messages.get",
        message_id=message_id,
        label=_label_for_audit(message, category),
        result="ok",
    )

    if category is Category.F_ANTIPATTERN:
        ok = process_discard(service, message_id)
        DISPATCH_COUNTER.labels(
            category=category.value,
            result="processed" if ok else "error",
        ).inc()
        return category

    if category is Category.E_REFUSAL_FEEDBACK:
        emit_refusal_feedback(message, kind="feedback")
        DISPATCH_COUNTER.labels(category=category.value, result="processed").inc()
        return category

    if category is Category.C_SUPPRESS:
        ok = process_suppress(service, message)
        DISPATCH_COUNTER.labels(
            category=category.value,
            result="processed" if ok else "error",
        ).inc()
        return category

    # Categories A / B / C / D land in mail-monitor-008/009/010/011.
    # Until those are merged, the dispatch path here is a no-op that
    # records the deferred outcome — the classifier still ran and the
    # audit log captured the read.
    if category in _DEFERRED_CATEGORIES:
        DISPATCH_COUNTER.labels(category=category.value, result="deferred").inc()
        return category

    # Future-proofing: should never reach here while Category enum has
    # only six members, but a defensive `error` outcome keeps the
    # exhaustiveness explicit.
    DISPATCH_COUNTER.labels(category=category.value, result="error").inc()  # pragma: no cover
    return category


def _label_for_audit(message: dict[str, Any], category: Category) -> str:
    """Return the most specific label name to record in the audit log."""
    names = message.get("label_names") or []
    for name in names:
        if name.startswith("Hapax/"):
            return name
    return f"<no-hapax-label;cat={category.value}>"


def register_processor(
    category: Category,
    fn: Callable[[Any, dict[str, Any]], bool],  # noqa: ARG001 — future hook
) -> None:  # pragma: no cover
    """Hook for mail-monitor-008/009/010/011 to register their processors.

    Currently a no-op stub; the wired-in version lands when the
    deferred-category processors arrive. Documented here so the surface
    is reserved.
    """
    raise NotImplementedError(
        "register_processor is a placeholder; deferred-category processors "
        "land in mail-monitor-008/009/010/011."
    )
