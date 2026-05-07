"""Tests for cc-task u5-semantic-verbs-consumer (Phase 0 substrate).

Pin the no-orphan-verbs invariant (the U5 acceptance criterion) plus
the Phase 0 vocabulary contract. Phase 1 adds the per-verb consumer
implementations + the Prometheus counter.
"""

from __future__ import annotations

import pytest

from shared.director_semantic_verbs import (
    SEMANTIC_VERB_ACTIONS,
    SEMANTIC_VERBS,
    VerbAction,
    consumer_for,
    no_orphan_verbs,
    registered_verbs,
)


class TestVocabularyFloor:
    def test_at_least_eleven_verbs_registered(self) -> None:
        """U5 acceptance asks for ≥6 verbs dispatched in a 10-min sample.
        Pin an 11-verb floor so the operator has margin: a director that
        only fires 6 distinct verbs in a window still has 5 unfired
        verbs in the catalog."""
        assert len(SEMANTIC_VERBS) >= 11, (
            f"SEMANTIC_VERBS must have ≥11 entries (got {len(SEMANTIC_VERBS)}); "
            f"the floor matches the U5 acceptance criterion of ≥6-dispatched-in-10-min "
            f"with safety margin"
        )

    def test_vocabulary_is_sorted_for_determinism(self) -> None:
        assert list(SEMANTIC_VERBS) == sorted(SEMANTIC_VERBS), (
            "SEMANTIC_VERBS must be sorted so iteration order is "
            "deterministic across runs (Phase 1 telemetry depends on stable order)"
        )


class TestNoOrphanVerbs:
    """The U5 acceptance criterion: 'no orphan verbs' (every declared
    verb has a registered consumer)."""

    def test_no_orphan_verbs_invariant(self) -> None:
        orphans = no_orphan_verbs()
        assert orphans == (), (
            f"Verbs in SEMANTIC_VERBS without an entry in "
            f"SEMANTIC_VERB_ACTIONS: {orphans}. Either register the verb's "
            f"VerbAction or remove it from the vocabulary."
        )

    @pytest.mark.parametrize("verb", SEMANTIC_VERBS)
    def test_every_verb_has_consumer(self, verb: str) -> None:
        action = consumer_for(verb)
        assert action is not None, f"verb {verb!r} has no registered consumer"
        assert isinstance(action, VerbAction)
        assert action.verb == verb


class TestVerbActionShape:
    """Pin the per-action descriptor contract — the shape downstream
    consumers will rely on at Phase 1 wire-up time."""

    @pytest.mark.parametrize("verb", SEMANTIC_VERBS)
    def test_action_has_required_fields(self, verb: str) -> None:
        action = consumer_for(verb)
        assert action is not None
        assert action.verb
        assert action.axis in {
            "temporal",
            "spatial",
            "phenomenological",
            "chromatic",
            "structural",
        }
        assert action.description, f"verb {verb!r} action has empty description"
        # hint may be empty for a simple verb; what matters is it's a dict.
        assert isinstance(action.hint, dict)

    def test_actions_cover_every_axis(self) -> None:
        """The 5 semantic axes are the cc-task body's organising principle —
        a vocabulary that drops an axis is a regression."""
        axes_seen = {a.axis for a in SEMANTIC_VERB_ACTIONS.values()}
        for axis in (
            "temporal",
            "spatial",
            "phenomenological",
            "chromatic",
            "structural",
        ):
            assert axis in axes_seen, f"vocabulary missing semantic axis {axis!r}"


class TestKnownVerbsPresent:
    """Pin the example verbs the cc-task body cited verbatim — a refactor
    that drops one is a vocabulary regression."""

    @pytest.mark.parametrize("verb", ["ascend", "linger", "rupture"])
    def test_cc_task_example_verb_present(self, verb: str) -> None:
        assert verb in SEMANTIC_VERBS, (
            f"verb {verb!r} cited in cc-task u5 body but absent from registry; "
            f"if intentionally renamed, update the cc-task closure note"
        )


class TestRegisteredVerbsAccessor:
    def test_returns_sorted_tuple(self) -> None:
        verbs = registered_verbs()
        assert isinstance(verbs, tuple)
        assert list(verbs) == sorted(verbs)

    def test_consumer_for_unknown_returns_none(self) -> None:
        assert consumer_for("not-a-verb") is None
