"""Tests for the HACL compressibility lattice (organ 2).

Exhaustive over the 4-element total order — every lattice law is checked
against all pairs/triples, the poison-upward batch property against every
label, and the ``compressibility_of`` mapping against every fail-closed rule
in the HACL spec (CASE-AUDIT-REMEDIATION-20260606).
"""

from __future__ import annotations

import itertools

from policyflow.consent_label import ConsentLabel
from policyflow.labeled import Labeled

from shared.governance.compressibility_label import (
    DEFAULT_OPERATOR_IDS,
    CompressibilityLabel,
    compressibility_of,
    join,
    supremum,
)

ALL = list(CompressibilityLabel)

SAFE = CompressibilityLabel.SAFE
GUARDED = CompressibilityLabel.GUARDED
PROTECTED = CompressibilityLabel.PROTECTED
UNKNOWN = CompressibilityLabel.UNKNOWN


def _policy(owner: str, *readers: str) -> tuple[str, frozenset[str]]:
    return (owner, frozenset((owner, *readers)))


def _label(*policies: tuple[str, frozenset[str]]) -> ConsentLabel:
    return ConsentLabel(frozenset(policies))


class TestTotalOrder:
    def test_exactly_four_elements(self):
        assert len(ALL) == 4

    def test_strict_chain(self):
        assert SAFE < GUARDED < PROTECTED < UNKNOWN

    def test_total_comparability(self):
        for a, b in itertools.product(ALL, repeat=2):
            assert a <= b or b <= a

    def test_antisymmetry(self):
        for a, b in itertools.product(ALL, repeat=2):
            if a <= b and b <= a:
                assert a is b

    def test_transitivity(self):
        for a, b, c in itertools.product(ALL, repeat=3):
            if a <= b and b <= c:
                assert a <= c


class TestJoin:
    def test_join_is_max(self):
        for a, b in itertools.product(ALL, repeat=2):
            assert join(a, b) is max(a, b)

    def test_commutative(self):
        for a, b in itertools.product(ALL, repeat=2):
            assert join(a, b) is join(b, a)

    def test_associative(self):
        for a, b, c in itertools.product(ALL, repeat=3):
            assert join(join(a, b), c) is join(a, join(b, c))

    def test_idempotent(self):
        for a in ALL:
            assert join(a, a) is a

    def test_safe_is_identity(self):
        for a in ALL:
            assert join(SAFE, a) is a

    def test_unknown_is_absorbing(self):
        for a in ALL:
            assert join(UNKNOWN, a) is UNKNOWN

    def test_join_is_least_upper_bound(self):
        for a, b in itertools.product(ALL, repeat=2):
            lub = join(a, b)
            assert a <= lub and b <= lub
            for upper in ALL:
                if a <= upper and b <= upper:
                    assert lub <= upper


class TestSupremum:
    def test_empty_batch_is_safe(self):
        assert supremum([]) is SAFE

    def test_singleton(self):
        for a in ALL:
            assert supremum([a]) is a

    def test_poison_upward(self):
        # One restrictive message poisons an otherwise-SAFE batch upward.
        for poison in (GUARDED, PROTECTED, UNKNOWN):
            batch = [SAFE, SAFE, poison, SAFE]
            assert supremum(batch) is poison

    def test_most_restrictive_wins(self):
        assert supremum([GUARDED, PROTECTED, SAFE]) is PROTECTED
        assert supremum([GUARDED, UNKNOWN, PROTECTED]) is UNKNOWN

    def test_accepts_generator(self):
        assert supremum(label for label in (SAFE, GUARDED)) is GUARDED


class TestCompressibilityOfLabels:
    def test_bottom_label_is_safe(self):
        assert compressibility_of(ConsentLabel.bottom(), "knowledge_search") is SAFE

    def test_non_bottom_label_is_at_least_guarded(self):
        label = _label(_policy("person-a", "operator"))
        assert compressibility_of(label, "knowledge_search") >= GUARDED

    def test_non_operator_policy_is_guarded_not_protected(self):
        label = _label(_policy("person-a", "operator"))
        assert compressibility_of(label, "knowledge_search") is GUARDED

    def test_operator_owned_policy_is_protected(self):
        label = _label(_policy("operator", "person-a"))
        assert compressibility_of(label, "knowledge_search") is PROTECTED

    def test_one_operator_policy_among_others_is_protected(self):
        label = _label(_policy("person-a"), _policy("operator"), _policy("person-b"))
        assert compressibility_of(label, "knowledge_search") is PROTECTED

    def test_default_operator_ids_cover_hapax(self):
        # Mirrors the qdrant_gate operator-id convention.
        assert "operator" in DEFAULT_OPERATOR_IDS
        label = _label(_policy("hapax"))
        assert compressibility_of(label, "knowledge_search") is PROTECTED

    def test_custom_operator_ids(self):
        label = _label(_policy("ryan"))
        assert compressibility_of(label, "x", operator_ids=frozenset({"ryan"})) is PROTECTED
        assert compressibility_of(label, "x", operator_ids=frozenset({"other"})) is GUARDED


class TestCompressibilityOfLabeled:
    def test_labeled_bottom_is_safe(self):
        wrapped = Labeled(value="hello", label=ConsentLabel.bottom())
        assert compressibility_of(wrapped, "knowledge_search") is SAFE

    def test_labeled_non_bottom_is_guarded(self):
        wrapped = Labeled(value="hello", label=_label(_policy("person-a")))
        assert compressibility_of(wrapped, "knowledge_search") is GUARDED

    def test_labeled_operator_owned_is_protected(self):
        wrapped = Labeled(value="hello", label=_label(_policy("operator")))
        assert compressibility_of(wrapped, "knowledge_search") is PROTECTED

    def test_label_dominates_empty_value(self):
        # The label classifies, not the payload size.
        wrapped = Labeled(value="", label=_label(_policy("person-a")))
        assert compressibility_of(wrapped, "knowledge_search") is GUARDED


class TestFailClosedDefault:
    def test_unlabeled_string_is_unknown(self):
        assert compressibility_of("raw transcript text", "knowledge_search") is UNKNOWN

    def test_unlabeled_dict_is_unknown(self):
        assert compressibility_of({"k": "v"}, "env_context") is UNKNOWN

    def test_unlabeled_object_is_unknown(self):
        assert compressibility_of(object(), "env_context") is UNKNOWN

    def test_none_is_safe(self):
        assert compressibility_of(None, "env_context") is SAFE

    def test_empty_string_is_safe(self):
        assert compressibility_of("", "env_context") is SAFE

    def test_empty_collections_are_safe(self):
        assert compressibility_of([], "env_context") is SAFE
        assert compressibility_of({}, "env_context") is SAFE
        assert compressibility_of(b"", "env_context") is SAFE

    def test_zero_is_unknown_not_safe(self):
        # Falsy but non-empty scalars still carry unclassified content.
        assert compressibility_of(0, "env_context") is UNKNOWN
        assert compressibility_of(False, "env_context") is UNKNOWN


class TestBatchPoisonEndToEnd:
    def test_one_operator_message_poisons_batch_to_protected(self):
        batch = [
            Labeled(value="m1", label=ConsentLabel.bottom()),
            Labeled(value="m2", label=_label(_policy("operator"))),
            Labeled(value="m3", label=ConsentLabel.bottom()),
        ]
        labels = [compressibility_of(item, "director_context") for item in batch]
        assert supremum(labels) is PROTECTED

    def test_one_unlabeled_message_poisons_batch_to_unknown(self):
        batch: list[object] = [
            Labeled(value="m1", label=ConsentLabel.bottom()),
            "raw unlabeled message",
        ]
        labels = [compressibility_of(item, "director_context") for item in batch]
        assert supremum(labels) is UNKNOWN

    def test_all_public_batch_is_safe(self):
        batch = [Labeled(value=f"m{i}", label=ConsentLabel.bottom()) for i in range(5)]
        labels = [compressibility_of(item, "director_context") for item in batch]
        assert supremum(labels) is SAFE
