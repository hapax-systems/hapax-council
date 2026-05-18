"""Hypothesis property tests for VetoChain algebraic laws."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agentgov.primitives import Veto, VetoChain

from .strategies import st_veto, st_veto_chain


class TestVetoChainMonotonicityProperty:
    """Adding constraints can only restrict — never permit more."""

    @given(chain=st_veto_chain(), extra=st_veto())
    @settings(max_examples=200)
    def test_adding_veto_never_permits_more(self, chain: VetoChain, extra: Veto):
        before = chain.evaluate("ctx")
        chain.add(extra)
        after = chain.evaluate("ctx")
        if not before.allowed:
            assert not after.allowed, "Adding a veto must not permit a previously-denied context"


class TestVetoChainCompositionProperty:
    """VetoChain | operator is associative and identity-preserving."""

    @given(a=st_veto_chain(), b=st_veto_chain(), c=st_veto_chain())
    @settings(max_examples=200)
    def test_associativity(self, a: VetoChain, b: VetoChain, c: VetoChain):
        lhs = (a | b) | c
        rhs = a | (b | c)
        assert lhs.evaluate("ctx").allowed == rhs.evaluate("ctx").allowed
        assert lhs.evaluate("ctx").denied_by == rhs.evaluate("ctx").denied_by

    @given(chain=st_veto_chain())
    @settings(max_examples=200)
    def test_empty_chain_is_identity(self, chain: VetoChain):
        empty = VetoChain([])
        left = empty | chain
        right = chain | empty
        ctx = "test"
        assert left.evaluate(ctx).allowed == chain.evaluate(ctx).allowed
        assert right.evaluate(ctx).allowed == chain.evaluate(ctx).allowed

    @given(a=st_veto_chain(), b=st_veto_chain())
    @settings(max_examples=200)
    def test_composition_deny_wins(self, a: VetoChain, b: VetoChain):
        combined = a | b
        result = combined.evaluate("ctx")
        a_result = a.evaluate("ctx")
        b_result = b.evaluate("ctx")
        if not a_result.allowed or not b_result.allowed:
            assert not result.allowed


class TestVetoChainDeterminism:
    """Same chain + same context = same result."""

    @given(chain=st_veto_chain(), ctx=st.text(min_size=1, max_size=10))
    @settings(max_examples=200)
    def test_evaluation_is_deterministic(self, chain: VetoChain, ctx: str):
        r1 = chain.evaluate(ctx)
        r2 = chain.evaluate(ctx)
        assert r1.allowed == r2.allowed
        assert r1.denied_by == r2.denied_by
        assert r1.axiom_ids == r2.axiom_ids


class TestVetoChainDenyWinsInvariant:
    """If any veto denies, the chain denies."""

    @given(
        allowing=st.lists(st_veto(allow_prob=1.0), min_size=0, max_size=3),
        denying_name=st.text(min_size=1, max_size=10, alphabet="abcdefgh"),
    )
    @settings(max_examples=200)
    def test_single_deny_overrides_all_allows(self, allowing, denying_name):
        vetoes = allowing + [Veto(name=denying_name, predicate=lambda _: False)]
        chain = VetoChain(vetoes)
        result = chain.evaluate("ctx")
        assert not result.allowed
        assert denying_name in result.denied_by
