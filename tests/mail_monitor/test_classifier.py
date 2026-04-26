"""Tests for ``agents.mail_monitor.classifier``.

Covers spec §3 invariants — particularly the ``Hapax/Suppress``-pin
and the rule-priority ordering.
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from agents.mail_monitor import classifier
from agents.mail_monitor.classifier import Category, classify


def _counter(category: str, source: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_classifications_total",
        {"category": category, "source": source},
    )
    return val or 0.0


# ── label-driven cases ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Hapax/Verify", Category.B_VERIFY),
        ("Hapax/Suppress", Category.C_SUPPRESS),
        ("Hapax/Operational", Category.D_OPERATIONAL),
        ("Hapax/Discard", Category.F_ANTIPATTERN),
    ],
)
def test_label_drives_category(label: str, expected: Category) -> None:
    cat, source = classify({"label_names": [label]})
    assert cat is expected
    assert source == "rule_label"


def test_suppress_label_wins_over_other_signals() -> None:
    """Spec §3 invariant: Hapax/Suppress always classifies as C_SUPPRESS,
    no matter what other labels / body / reply state co-occur.

    This is the constitutional pin guarding against
    `mail-monitor-refused-spam-classifier-overreach`.
    """
    message = {
        "label_names": ["Hapax/Suppress", "Hapax/Discard"],
        "replies_to_hapax_thread": True,
        "body_text": "this could read as feedback or marketing",
    }
    cat, source = classify(message)
    assert cat is Category.C_SUPPRESS
    assert source == "rule_label"


# ── reply-driven cases ────────────────────────────────────────────────


def test_reply_to_hapax_thread_without_label_is_refusal_feedback() -> None:
    cat, source = classify(
        {
            "replies_to_hapax_thread": True,
            "body_text": "thanks for the email but please don't",
        }
    )
    assert cat is Category.E_REFUSAL_FEEDBACK
    assert source == "rule_reply"


def test_reply_with_suppress_body_is_suppress_even_without_label() -> None:
    """Belt-and-suspenders against the case where filter B failed to
    label an inbound SUPPRESS reply (e.g. early Mailhook payload)."""
    cat, source = classify(
        {
            "replies_to_hapax_thread": True,
            "body_text": "Thanks for reaching out, but:\n\nSUPPRESS\n",
        }
    )
    assert cat is Category.C_SUPPRESS
    assert source == "rule_reply"


def test_suppress_body_match_is_line_anchored() -> None:
    """`SUPPRESSED` in prose must NOT trigger; SUPPRESS as a single-word
    line must."""
    cat_a, _ = classify(
        {
            "replies_to_hapax_thread": True,
            "body_text": "I think the message was SUPPRESSED at the spam filter.",
        }
    )
    assert cat_a is Category.E_REFUSAL_FEEDBACK  # NOT C_SUPPRESS


def test_suppress_body_match_case_insensitive() -> None:
    cat, _ = classify({"replies_to_hapax_thread": True, "body_text": "\nsuppress\n"})
    assert cat is Category.C_SUPPRESS


# ── fallback ──────────────────────────────────────────────────────────


def test_no_label_no_reply_is_antipattern() -> None:
    cat, source = classify(
        {"label_names": [], "replies_to_hapax_thread": False, "body_text": "marketing"}
    )
    assert cat is Category.F_ANTIPATTERN
    assert source == "fallback"


# ── metric pre-registration ───────────────────────────────────────────


def test_module_pre_registers_all_outcome_pairs() -> None:
    for cat in classifier.Category:
        for source in ("rule_label", "rule_sender", "rule_reply", "fallback"):
            val = REGISTRY.get_sample_value(
                "hapax_mail_monitor_classifications_total",
                {"category": cat.value, "source": source},
            )
            assert val is not None, (cat, source)


def test_classification_increments_counter() -> None:
    before = _counter("B_VERIFY", "rule_label")
    classify({"label_names": ["Hapax/Verify"]})
    assert _counter("B_VERIFY", "rule_label") - before == 1.0
