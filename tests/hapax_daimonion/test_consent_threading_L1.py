"""Consent threading tests for L1 (Behavior) — DD-22.

7-dimension matrix coverage for consent label threading on Behavior[T].
Tests label construction, join-only floating, None/bottom distinction,
and composition contracts to L2.
"""

from __future__ import annotations

import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_daimonion.primitives import Behavior, Stamped
from shared.governance.consent_label import ConsentLabel
from tests.consent_strategies import st_consent_label

# ── Dimension A: Construction ────────────────────────────────────────


class TestConsentL1Construction(unittest.TestCase):
    """Behavior construction with consent labels."""

    def test_default_consent_label_is_none(self):
        """Default: consent untracked."""
        b = Behavior(0, watermark=1.0)
        assert b.consent_label is None

    def test_explicit_consent_label(self):
        """Consent label set at construction."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(0, watermark=1.0, consent_label=label)
        assert b.consent_label == label

    def test_bottom_consent_label(self):
        """Bottom = explicitly public, distinct from None = untracked."""
        b = Behavior(0, watermark=1.0, consent_label=ConsentLabel.bottom())
        assert b.consent_label == ConsentLabel.bottom()
        assert b.consent_label is not None


# ── Dimension B: Invariants ──────────────────────────────────────────


class TestConsentL1Invariants(unittest.TestCase):
    """Consent label invariants: join-only float, monotonicity."""

    def test_label_floats_upward_on_update(self):
        """Update with label joins with existing (more restrictive)."""
        label_a = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        label_b = ConsentLabel(frozenset({("carol", frozenset({"dave"}))}))
        b = Behavior(0, watermark=1.0, consent_label=label_a)
        b.update(1, 2.0, consent_label=label_b)
        assert b.consent_label == label_a.join(label_b)

    def test_label_join_idempotent(self):
        """Updating with same label twice does not change it."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(0, watermark=1.0, consent_label=label)
        b.update(1, 2.0, consent_label=label)
        assert b.consent_label == label

    def test_none_update_preserves_label(self):
        """Update without label preserves existing label."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(0, watermark=1.0, consent_label=label)
        b.update(1, 2.0)
        assert b.consent_label == label

    def test_none_update_preserves_none(self):
        """Update without label on untracked behavior stays untracked."""
        b = Behavior(0, watermark=1.0)
        b.update(1, 2.0)
        assert b.consent_label is None


# ── Dimension C: Operations ──────────────────────────────────────────


class TestConsentL1Operations(unittest.TestCase):
    """Consent label operations during Behavior lifecycle."""

    def test_sample_returns_stamped_unchanged(self):
        """sample() returns Stamped — consent stays on Behavior, not snapshot."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(42, watermark=1.0, consent_label=label)
        s = b.sample()
        assert isinstance(s, Stamped)
        assert s.value == 42
        assert not hasattr(s, "consent_label")

    def test_update_advances_watermark_and_label_simultaneously(self):
        """Both watermark and label update atomically."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(0, watermark=1.0)
        b.update(1, 2.0, consent_label=label)
        assert b.watermark == 2.0
        assert b.consent_label == label

    def test_multiple_labeled_updates_accumulate(self):
        """Sequential labeled updates join all labels."""
        l1 = ConsentLabel(frozenset({("a", frozenset({"x"}))}))
        l2 = ConsentLabel(frozenset({("b", frozenset({"y"}))}))
        l3 = ConsentLabel(frozenset({("c", frozenset({"z"}))}))
        b = Behavior(0, watermark=1.0)
        b.update(1, 2.0, consent_label=l1)
        b.update(2, 3.0, consent_label=l2)
        b.update(3, 4.0, consent_label=l3)
        assert b.consent_label == l1.join(l2).join(l3)


# ── Dimension D: Boundaries ─────────────────────────────────────────


class TestConsentL1Boundaries(unittest.TestCase):
    """Boundary conditions for consent label threading."""

    def test_bottom_then_nonbottom_becomes_nonbottom(self):
        """Bottom + non-bottom = non-bottom (join is union)."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(0, watermark=1.0, consent_label=ConsentLabel.bottom())
        b.update(1, 2.0, consent_label=label)
        assert b.consent_label == label

    def test_none_then_label_transitions_to_tracked(self):
        """First labeled update transitions from untracked to tracked."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(0, watermark=1.0)
        assert b.consent_label is None
        b.update(1, 2.0, consent_label=label)
        assert b.consent_label == label

    def test_none_then_bottom_transitions_to_tracked(self):
        """Bottom is a real label, not None — transitions to tracked."""
        b = Behavior(0, watermark=1.0)
        b.update(1, 2.0, consent_label=ConsentLabel.bottom())
        assert b.consent_label is not None
        assert b.consent_label == ConsentLabel.bottom()


# ── Dimension E: Error paths ─────────────────────────────────────────


class TestConsentL1ErrorPaths(unittest.TestCase):
    """Error behavior with consent labels."""

    def test_watermark_regression_rejected_with_label(self):
        """Watermark regression still rejected even when providing a consent label."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(0, watermark=5.0)
        with self.assertRaises(ValueError, msg="Watermark regression"):
            b.update(1, 3.0, consent_label=label)
        # Label should not have changed
        assert b.consent_label is None

    def test_watermark_regression_preserves_existing_label(self):
        """On regression error, existing consent label is preserved."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(0, watermark=5.0, consent_label=label)
        with self.assertRaises(ValueError):
            b.update(1, 3.0, consent_label=ConsentLabel.bottom())
        assert b.consent_label == label


# ── Dimension F: Dog Star proofs ─────────────────────────────────────


class TestConsentL1DogStar(unittest.TestCase):
    """Consent label cannot be lowered via update (join is monotone)."""

    def test_cannot_lower_label_via_update(self):
        """Updating with a less-restrictive label does not reduce restrictions."""
        less = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        more = ConsentLabel(
            frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))})
        )
        b = Behavior(0, watermark=1.0, consent_label=more)
        b.update(1, 2.0, consent_label=less)
        # Label should be join(more, less) = more (less ⊆ more)
        assert b.consent_label == more


# ── Dimension G: Composition contracts ───────────────────────────────


class TestConsentL1Composition(unittest.TestCase):
    """Composition contracts: L1 output valid as L2 input."""

    def test_sample_still_produces_valid_stamped(self):
        """Consent-labeled Behavior still produces valid Stamped for FusedContext."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = Behavior(42, watermark=1.0, consent_label=label)
        s = b.sample()
        assert isinstance(s, Stamped)
        assert s.value == 42
        assert s.watermark == 1.0

    def test_two_behaviors_labels_joinable_for_fusion(self):
        """Two Behaviors' consent labels can be joined for FusedContext construction."""
        l1 = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        l2 = ConsentLabel(frozenset({("carol", frozenset({"dave"}))}))
        b1 = Behavior(1, watermark=1.0, consent_label=l1)
        b2 = Behavior(2, watermark=1.0, consent_label=l2)
        fused_label = b1.consent_label.join(b2.consent_label)  # type: ignore[union-attr]
        assert l1.can_flow_to(fused_label)
        assert l2.can_flow_to(fused_label)


# ── Hypothesis property tests ────────────────────────────────────────


class TestConsentL1Hypothesis(unittest.TestCase):
    """Property-based tests for consent label threading invariants."""

    @given(label_a=st_consent_label(), label_b=st_consent_label())
    def test_update_join_is_commutative(self, label_a: ConsentLabel, label_b: ConsentLabel):
        """Order of labeled updates does not affect final label."""
        b1 = Behavior(0, watermark=1.0, consent_label=label_a)
        b1.update(1, 2.0, consent_label=label_b)

        b2 = Behavior(0, watermark=1.0, consent_label=label_b)
        b2.update(1, 2.0, consent_label=label_a)

        assert b1.consent_label == b2.consent_label

    @given(label=st_consent_label())
    def test_update_join_is_idempotent(self, label: ConsentLabel):
        """Updating with same label twice produces same result."""
        b = Behavior(0, watermark=1.0, consent_label=label)
        b.update(1, 2.0, consent_label=label)
        assert b.consent_label == label

    @given(
        labels=st.lists(st_consent_label(), min_size=1, max_size=5),
        timestamps=st.lists(
            st.floats(min_value=2.0, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=5,
            max_size=5,
        ),
    )
    @settings(max_examples=50)
    def test_label_monotonicity(self, labels: list[ConsentLabel], timestamps: list[float]):
        """After any sequence of labeled updates, final label is join of all."""
        b = Behavior(0, watermark=1.0)
        expected = ConsentLabel.bottom()
        ts = sorted(timestamps)
        for i, label in enumerate(labels):
            b.update(i, ts[i], consent_label=label)
            expected = expected.join(label)
        assert b.consent_label == expected

    @given(label=st_consent_label())
    def test_none_update_is_identity(self, label: ConsentLabel):
        """Update without label does not change consent state."""
        b = Behavior(0, watermark=1.0, consent_label=label)
        b.update(1, 2.0)  # no consent_label
        assert b.consent_label == label


if __name__ == "__main__":
    unittest.main()
