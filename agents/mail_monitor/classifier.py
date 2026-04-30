"""Rule-based message classifier for the six-purpose mail flow.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §3.

The classifier is deterministic on the primary signal — the
server-side label installed by filter A/B/C/D — and falls back to
header / body inspection when the label is missing or ambiguous.

The classifier remains deterministic: live mail processing is driven by
server-side Hapax labels and explicit runner-provided correlation flags,
not by an LLM fallback.

A Hapax-Suppress-labelled message must never classify as anything but
``C_SUPPRESS`` — failing that invariant is a constitutional violation
(see ``mail-monitor-refused-spam-classifier-overreach``). A pin test in
``tests/mail_monitor/test_classifier.py`` covers it.
"""

from __future__ import annotations

import logging
import re
from enum import StrEnum
from typing import Any

from prometheus_client import Counter

log = logging.getLogger(__name__)


class Category(StrEnum):
    """One of the six per-purpose categories from spec §3.

    Ordering follows spec §3.A → §3.F. Pydantic and pydantic-ai treat
    this enum as a structured-output target.
    """

    A_ACCEPT = "A_ACCEPT"
    B_VERIFY = "B_VERIFY"
    C_SUPPRESS = "C_SUPPRESS"
    D_OPERATIONAL = "D_OPERATIONAL"
    E_REFUSAL_FEEDBACK = "E_REFUSAL_FEEDBACK"
    F_ANTIPATTERN = "F_ANTIPATTERN"


CLASSIFICATIONS_COUNTER = Counter(
    "hapax_mail_monitor_classifications_total",
    "Mail classifications by category and signal source.",
    labelnames=("category", "source"),
)
for _category in Category:
    for _source in ("rule_label", "rule_sender", "rule_reply", "fallback"):
        CLASSIFICATIONS_COUNTER.labels(category=_category.value, source=_source)


# Spec §2 — the four Hapax labels installed by mail-monitor-004.
LABEL_TO_CATEGORY: dict[str, Category] = {
    "Hapax/Verify": Category.B_VERIFY,
    "Hapax/Suppress": Category.C_SUPPRESS,
    "Hapax/Operational": Category.D_OPERATIONAL,
    "Hapax/Discard": Category.F_ANTIPATTERN,
}


# Spec §3.C — `^SUPPRESS$` line-anchored, case-insensitive. Single-word
# safety against false-positives in conversational mail.
_SUPPRESS_BODY_RE = re.compile(r"(?im)^\s*SUPPRESS\s*$")


def _label_names_from_message(message: dict[str, Any]) -> set[str]:
    """Extract human-readable label names from a Gmail message dict.

    Gmail returns `labelIds` as a list of ids; the caller is expected to
    have resolved those to names before passing the message in (so the
    classifier doesn't itself need a Gmail API client). Convention: pass
    a ``label_names`` field alongside the raw `labelIds`.
    """
    return set(message.get("label_names", []))


def _is_reply_to_hapax_thread(message: dict[str, Any]) -> bool:
    """Return True if the message is a reply to a Hapax-sent thread.

    The runner is responsible for populating
    ``message["replies_to_hapax_thread"]`` from the seen-set / chronicle
    correlation; the classifier just consults the flag. This keeps the
    classifier itself pure (no IO).
    """
    return bool(message.get("replies_to_hapax_thread"))


def _has_suppress_marker(message: dict[str, Any]) -> bool:
    """Return True if the message body contains a line-anchored
    ``SUPPRESS`` token."""
    body = message.get("body_text") or ""
    return bool(_SUPPRESS_BODY_RE.search(body))


def classify(message: dict[str, Any]) -> tuple[Category, str]:
    """Decide the per-purpose category for a single message.

    Returns ``(category, source)`` where ``source`` is the rule that
    fired:

    - ``"rule_label"`` — primary path; one of the four Hapax labels was
      present.
    - ``"rule_reply"`` — message is a reply to a Hapax-sent thread but
      carries no Hapax label. Triggers Category E (refusal-feedback) or
      Category C (suppress) depending on body.
    - ``"rule_sender"`` — sender / header rules disambiguated.
    - ``"fallback"`` — none matched; default to F_ANTIPATTERN.

    Spec §3 invariant — a ``Hapax/Suppress``-labelled message MUST
    classify as ``C_SUPPRESS``. The pin test in test_classifier.py
    enforces this.
    """
    labels = _label_names_from_message(message)

    if "Hapax/Suppress" in labels:
        CLASSIFICATIONS_COUNTER.labels(
            category=Category.C_SUPPRESS.value, source="rule_label"
        ).inc()
        return Category.C_SUPPRESS, "rule_label"

    if message.get("auto_accept_candidate") or message.get("outbound_correlation_hit"):
        CLASSIFICATIONS_COUNTER.labels(category=Category.A_ACCEPT.value, source="rule_sender").inc()
        return Category.A_ACCEPT, "rule_sender"

    for label_name, category in LABEL_TO_CATEGORY.items():
        if label_name in labels:
            CLASSIFICATIONS_COUNTER.labels(category=category.value, source="rule_label").inc()
            return category, "rule_label"

    if _is_reply_to_hapax_thread(message):
        # Reply with SUPPRESS body even when the omg.lol bridge missed
        # the server-side label install (e.g. early Mailhook payloads
        # before the bridge fully attached labels).
        if _has_suppress_marker(message):
            CLASSIFICATIONS_COUNTER.labels(
                category=Category.C_SUPPRESS.value, source="rule_reply"
            ).inc()
            return Category.C_SUPPRESS, "rule_reply"
        CLASSIFICATIONS_COUNTER.labels(
            category=Category.E_REFUSAL_FEEDBACK.value, source="rule_reply"
        ).inc()
        return Category.E_REFUSAL_FEEDBACK, "rule_reply"

    # Spec §3.F default — unmatched mail is Anti-pattern. The
    # server-side filter D should have already routed; the fallback
    # here covers messages that reached the daemon by some other path
    # (Mailhook bypass, etc.).
    CLASSIFICATIONS_COUNTER.labels(category=Category.F_ANTIPATTERN.value, source="fallback").inc()
    return Category.F_ANTIPATTERN, "fallback"
