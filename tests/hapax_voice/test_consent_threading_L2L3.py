"""Consent threading tests for L2 (FusedContext, consent_veto) and L3 (with_latest_from).

DD-5: FusedContext carries consent_label (join of inputs).
DD-6: VetoChain consent veto checks labels at enforcement boundaries.
DD-22 L3: with_latest_from computes label join automatically.
"""

from __future__ import annotations

import unittest

from hypothesis import given

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.governance import (
    FusedContext,
    Veto,
    VetoChain,
    consent_veto,
)
from agents.hapax_voice.primitives import Behavior, Event, Stamped
from shared.governance.consent_label import ConsentLabel
from tests.consent_strategies import st_consent_label

# ── L2: FusedContext consent_label ───────────────────────────────────


class TestFusedContextConsent(unittest.TestCase):
    """FusedContext consent_label construction and invariants."""

    def test_default_consent_label_is_none(self):
        """Existing code: no consent_label = None (gradual adoption)."""
        ctx = FusedContext(trigger_time=1.0, trigger_value=None)
        assert ctx.consent_label is None

    def test_explicit_consent_label(self):
        """FusedContext with explicit consent label."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        ctx = FusedContext(trigger_time=1.0, trigger_value=None, consent_label=label)
        assert ctx.consent_label == label

    def test_consent_label_is_frozen(self):
        """consent_label cannot be mutated on frozen FusedContext."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        ctx = FusedContext(trigger_time=1.0, trigger_value=None, consent_label=label)
        with self.assertRaises(AttributeError):
            ctx.consent_label = ConsentLabel.bottom()  # type: ignore[misc]

    def test_samples_still_immutable(self):
        """Adding consent_label doesn't break existing samples immutability."""
        s = Stamped(value=1, watermark=1.0)
        ctx = FusedContext(
            trigger_time=1.0,
            trigger_value=None,
            samples={"x": s},
            consent_label=ConsentLabel.bottom(),
        )
        with self.assertRaises(TypeError):
            ctx.samples["y"] = s  # type: ignore[index]


# ── L2: consent_veto (DD-6) ─────────────────────────────────────────


class TestConsentVeto(unittest.TestCase):
    """consent_veto factory and VetoChain integration."""

    def test_consent_veto_allows_matching_label(self):
        """Consent veto allows when context label can flow to required."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        veto = consent_veto(label)
        ctx = FusedContext(trigger_time=1.0, trigger_value=None, consent_label=label)
        assert veto.predicate(ctx)

    def test_consent_veto_allows_less_restricted_data(self):
        """Data with fewer policies (less restricted) can flow to more restricted context."""
        actual = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        required = ConsentLabel(
            frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))})
        )
        veto = consent_veto(required)
        ctx = FusedContext(trigger_time=1.0, trigger_value=None, consent_label=actual)
        assert veto.predicate(ctx)

    def test_consent_veto_denies_more_restricted_data(self):
        """Data with more policies cannot flow to less restrictive context."""
        actual = ConsentLabel(
            frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))})
        )
        required = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        veto = consent_veto(required)
        ctx = FusedContext(trigger_time=1.0, trigger_value=None, consent_label=actual)
        assert not veto.predicate(ctx)

    def test_consent_veto_denies_untracked(self):
        """DD-3: No consent = no access at enforcement boundaries."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        veto = consent_veto(label)
        ctx = FusedContext(trigger_time=1.0, trigger_value=None)  # consent_label=None
        assert not veto.predicate(ctx)

    def test_consent_veto_in_vetochain(self):
        """consent_veto integrates with VetoChain deny-wins."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        chain: VetoChain[FusedContext] = VetoChain([consent_veto(label)])
        ctx_ok = FusedContext(trigger_time=1.0, trigger_value=None, consent_label=label)
        ctx_bad = FusedContext(trigger_time=1.0, trigger_value=None)

        assert chain.evaluate(ctx_ok).allowed
        result_bad = chain.evaluate(ctx_bad)
        assert not result_bad.allowed
        assert "consent" in result_bad.denied_by
        assert "interpersonal_transparency" in result_bad.axiom_ids

    def test_consent_veto_composes_with_other_vetoes(self):
        """Consent veto + domain veto: deny-wins across both."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        domain_veto: Veto[FusedContext] = Veto(name="always_allow", predicate=lambda _: True)
        chain: VetoChain[FusedContext] = VetoChain([consent_veto(label), domain_veto])

        # Consent fails → whole chain denies despite domain allowing
        ctx = FusedContext(trigger_time=1.0, trigger_value=None)
        result = chain.evaluate(ctx)
        assert not result.allowed

    def test_consent_veto_axiom_customizable(self):
        """consent_veto axiom parameter is configurable."""
        veto = consent_veto(ConsentLabel.bottom(), axiom="custom_axiom")
        assert veto.axiom == "custom_axiom"


# ── L3: with_latest_from consent label computation ───────────────────


class TestWithLatestFromConsent(unittest.TestCase):
    """with_latest_from computes consent label join from Behaviors."""

    def test_all_untracked_produces_none(self):
        """All Behaviors untracked → FusedContext consent_label is None."""
        trigger = Event()
        behaviors = {"a": Behavior(1, watermark=1.0), "b": Behavior(2, watermark=1.0)}
        output = with_latest_from(trigger, behaviors)
        contexts: list[FusedContext] = []
        output.subscribe(lambda _, ctx: contexts.append(ctx))
        trigger.emit(2.0, None)
        assert contexts[0].consent_label is None

    def test_single_labeled_behavior(self):
        """One labeled Behavior → FusedContext gets that label."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        trigger = Event()
        behaviors = {"a": Behavior(1, watermark=1.0, consent_label=label)}
        output = with_latest_from(trigger, behaviors)
        contexts: list[FusedContext] = []
        output.subscribe(lambda _, ctx: contexts.append(ctx))
        trigger.emit(2.0, None)
        assert contexts[0].consent_label == label

    def test_multiple_labeled_behaviors_joined(self):
        """Multiple labeled Behaviors → FusedContext gets their join."""
        l1 = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        l2 = ConsentLabel(frozenset({("carol", frozenset({"dave"}))}))
        trigger = Event()
        behaviors = {
            "a": Behavior(1, watermark=1.0, consent_label=l1),
            "b": Behavior(2, watermark=1.0, consent_label=l2),
        }
        output = with_latest_from(trigger, behaviors)
        contexts: list[FusedContext] = []
        output.subscribe(lambda _, ctx: contexts.append(ctx))
        trigger.emit(2.0, None)
        assert contexts[0].consent_label == l1.join(l2)

    def test_mixed_tracked_untracked(self):
        """Mix of tracked and untracked → untracked treated as bottom for join."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        trigger = Event()
        behaviors = {
            "tracked": Behavior(1, watermark=1.0, consent_label=label),
            "untracked": Behavior(2, watermark=1.0),  # consent_label=None
        }
        output = with_latest_from(trigger, behaviors)
        contexts: list[FusedContext] = []
        output.subscribe(lambda _, ctx: contexts.append(ctx))
        trigger.emit(2.0, None)
        # Label should be join(label, bottom) = label
        assert contexts[0].consent_label == label

    def test_empty_behaviors_produces_none(self):
        """No Behaviors → consent_label is None."""
        trigger = Event()
        output = with_latest_from(trigger, {})
        contexts: list[FusedContext] = []
        output.subscribe(lambda _, ctx: contexts.append(ctx))
        trigger.emit(2.0, None)
        assert contexts[0].consent_label is None

    def test_label_updates_reflected_on_next_trigger(self):
        """Behavior label changes between triggers are picked up."""
        l1 = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        l2 = ConsentLabel(frozenset({("carol", frozenset({"dave"}))}))
        trigger = Event()
        b = Behavior(1, watermark=1.0, consent_label=l1)
        output = with_latest_from(trigger, {"a": b})
        contexts: list[FusedContext] = []
        output.subscribe(lambda _, ctx: contexts.append(ctx))

        trigger.emit(2.0, None)
        assert contexts[0].consent_label == l1

        b.update(2, 3.0, consent_label=l2)
        trigger.emit(4.0, None)
        assert contexts[1].consent_label == l1.join(l2)


# ── Hypothesis: L2/L3 consent properties ─────────────────────────────


class TestConsentL2L3Hypothesis(unittest.TestCase):
    """Property-based tests for L2/L3 consent threading."""

    @given(label=st_consent_label())
    def test_consent_veto_allows_self(self, label: ConsentLabel):
        """A label can always flow to itself → veto allows."""
        veto = consent_veto(label)
        ctx = FusedContext(trigger_time=1.0, trigger_value=None, consent_label=label)
        assert veto.predicate(ctx)

    @given(a=st_consent_label(), b=st_consent_label())
    def test_fused_context_label_join_is_lub(self, a: ConsentLabel, b: ConsentLabel):
        """Both input labels can flow to the joined FusedContext label."""
        trigger = Event()
        behaviors = {
            "x": Behavior(1, watermark=1.0, consent_label=a),
            "y": Behavior(2, watermark=1.0, consent_label=b),
        }
        output = with_latest_from(trigger, behaviors)
        contexts: list[FusedContext] = []
        output.subscribe(lambda _, ctx: contexts.append(ctx))
        trigger.emit(2.0, None)
        fused_label = contexts[0].consent_label
        assert fused_label is not None
        assert a.can_flow_to(fused_label)
        assert b.can_flow_to(fused_label)

    @given(a=st_consent_label(), b=st_consent_label())
    def test_consent_veto_flow_transitivity(self, a: ConsentLabel, b: ConsentLabel):
        """If a can flow to join(a,b), veto requiring join(a,b) allows data labeled a."""
        joined = a.join(b)
        veto = consent_veto(joined)
        ctx = FusedContext(trigger_time=1.0, trigger_value=None, consent_label=a)
        # a.policies ⊆ join(a,b).policies, so a can flow to joined
        assert veto.predicate(ctx)


if __name__ == "__main__":
    unittest.main()
