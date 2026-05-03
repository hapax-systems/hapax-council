"""Tests for agents.studio_compositor.semantic_verb_consumer (cc-task u5 Phase 1).

Pin:
- Every canonical verb in U5 substrate has a route entry (no-orphan)
- Per-route dispatch writes to the right file
- Counter increments per consume() with correct verb + outcome label
- Unknown verb → outcome=ignored, no file write
- Write failure → outcome=ignored
- 10 consumes cover all 10 verbs (live-verification proxy)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.studio_compositor.semantic_verb_consumer import (
    DEFAULT_ENVELOPE_PATH,
    DEFAULT_TRANSITION_BIAS_PATH,
    VERB_CONSUMER_ROUTES,
    SemanticVerbConsumer,
    all_verbs,
    hapax_semantic_verb_consumed_total,
    route_for,
    verbs_for_route,
)
from shared.director_semantic_verbs import SEMANTIC_VERBS


@pytest.fixture(autouse=True)
def _reset_counter():
    hapax_semantic_verb_consumed_total.clear()
    yield
    hapax_semantic_verb_consumed_total.clear()


def _counter(verb: str, outcome: str) -> float:
    return hapax_semantic_verb_consumed_total.labels(verb=verb, outcome=outcome)._value.get()


class TestRoutingTableNoOrphans:
    """The substrate guarantees no-orphan-verbs at the action layer; this
    consumer must guarantee no-orphan-verbs at the route layer too."""

    def test_every_substrate_verb_has_a_route(self) -> None:
        """Phase 1 acceptance: every verb in SEMANTIC_VERBS must map to
        a consumer route. A future vocabulary expansion that adds a
        verb to the substrate without a route entry must fail this
        assertion."""
        substrate_verbs = set(SEMANTIC_VERBS)
        route_verbs = set(VERB_CONSUMER_ROUTES.keys())
        missing = substrate_verbs - route_verbs
        assert not missing, f"verbs without consumer route: {missing}"

    def test_no_route_entry_for_unknown_verb(self) -> None:
        """Inverse: every route key must be in the substrate vocabulary.
        A leftover route entry from a deleted verb is dead config."""
        substrate_verbs = set(SEMANTIC_VERBS)
        route_verbs = set(VERB_CONSUMER_ROUTES.keys())
        extra = route_verbs - substrate_verbs
        assert not extra, f"route entries without substrate verb: {extra}"

    def test_all_routes_are_envelope_or_transition(self) -> None:
        """Pin the 2-route taxonomy. A new route would require a new
        output path + downstream consumer wiring."""
        valid = {"envelope", "transition"}
        for verb, route in VERB_CONSUMER_ROUTES.items():
            assert route in valid, f"verb {verb!r} has invalid route {route!r}"


class TestRouteHelpers:
    def test_route_for_known_verb(self) -> None:
        assert route_for("rupture") == "transition"
        assert route_for("ascend") == "envelope"

    def test_route_for_unknown_verb_is_none(self) -> None:
        assert route_for("not-a-verb") is None

    def test_verbs_for_envelope_route_is_sorted(self) -> None:
        result = verbs_for_route("envelope")
        assert list(result) == sorted(result)
        assert "ascend" in result
        assert "rupture" not in result

    def test_verbs_for_transition_route_is_sorted(self) -> None:
        result = verbs_for_route("transition")
        assert list(result) == sorted(result)
        assert "rupture" in result
        assert "ascend" not in result

    def test_all_verbs_matches_substrate(self) -> None:
        assert all_verbs() == SEMANTIC_VERBS


class TestConsumeKnownVerb:
    def test_envelope_verb_writes_to_envelope_path(self, tmp_path: Path) -> None:
        env_path = tmp_path / "envelope.jsonl"
        bias_path = tmp_path / "bias.jsonl"
        consumer = SemanticVerbConsumer(
            envelope_path=env_path,
            transition_bias_path=bias_path,
            clock=lambda: 1717000000.0,
        )
        outcome = consumer.consume("ascend")
        assert outcome == "dispatched"
        assert env_path.is_file()
        assert not bias_path.exists()
        record = json.loads(env_path.read_text().strip())
        assert record["verb"] == "ascend"
        assert record["route"] == "envelope"
        assert record["axis"] == "temporal"
        assert record["dispatched_at"] == 1717000000.0
        assert isinstance(record["hint"], dict)

    def test_transition_verb_writes_to_transition_path(self, tmp_path: Path) -> None:
        env_path = tmp_path / "envelope.jsonl"
        bias_path = tmp_path / "bias.jsonl"
        consumer = SemanticVerbConsumer(envelope_path=env_path, transition_bias_path=bias_path)
        outcome = consumer.consume("rupture")
        assert outcome == "dispatched"
        assert bias_path.is_file()
        assert not env_path.exists()
        record = json.loads(bias_path.read_text().strip())
        assert record["verb"] == "rupture"
        assert record["route"] == "transition"
        assert record["axis"] == "phenomenological"

    def test_consume_increments_dispatched_counter(self, tmp_path: Path) -> None:
        consumer = SemanticVerbConsumer(
            envelope_path=tmp_path / "e.jsonl",
            transition_bias_path=tmp_path / "t.jsonl",
        )
        consumer.consume("warm")
        assert _counter("warm", "dispatched") == 1
        assert _counter("warm", "ignored") == 0

    def test_repeated_consumes_append_to_jsonl(self, tmp_path: Path) -> None:
        env_path = tmp_path / "envelope.jsonl"
        consumer = SemanticVerbConsumer(
            envelope_path=env_path,
            transition_bias_path=tmp_path / "t.jsonl",
        )
        consumer.consume("ascend")
        consumer.consume("linger")
        consumer.consume("warm")
        lines = env_path.read_text().strip().splitlines()
        assert len(lines) == 3
        verbs = [json.loads(line)["verb"] for line in lines]
        assert verbs == ["ascend", "linger", "warm"]


class TestConsumeUnknownVerb:
    def test_unknown_verb_returns_ignored(self, tmp_path: Path) -> None:
        consumer = SemanticVerbConsumer(
            envelope_path=tmp_path / "e.jsonl",
            transition_bias_path=tmp_path / "t.jsonl",
        )
        outcome = consumer.consume("not-a-real-verb")
        assert outcome == "ignored"

    def test_unknown_verb_increments_ignored_counter(self, tmp_path: Path) -> None:
        consumer = SemanticVerbConsumer(
            envelope_path=tmp_path / "e.jsonl",
            transition_bias_path=tmp_path / "t.jsonl",
        )
        consumer.consume("nope")
        assert _counter("nope", "ignored") == 1
        assert _counter("nope", "dispatched") == 0

    def test_unknown_verb_does_not_write(self, tmp_path: Path) -> None:
        env_path = tmp_path / "envelope.jsonl"
        bias_path = tmp_path / "bias.jsonl"
        consumer = SemanticVerbConsumer(envelope_path=env_path, transition_bias_path=bias_path)
        consumer.consume("not-a-verb")
        assert not env_path.exists()
        assert not bias_path.exists()


class TestWriteFailureFallback:
    """If the JSONL write fails (disk full, /dev/shm not mounted), the
    consumer must NOT crash and MUST flag the failure as outcome=ignored."""

    def test_oserror_during_write_yields_ignored(self, tmp_path: Path) -> None:
        consumer = SemanticVerbConsumer(
            envelope_path=tmp_path / "e.jsonl",
            transition_bias_path=tmp_path / "t.jsonl",
        )
        with patch(
            "agents.studio_compositor.semantic_verb_consumer._atomic_append_jsonl"
        ) as mock_write:
            mock_write.side_effect = OSError("/dev/shm not mounted")
            outcome = consumer.consume("ascend")
        assert outcome == "ignored"
        assert _counter("ascend", "ignored") == 1
        # Did NOT increment dispatched.
        assert _counter("ascend", "dispatched") == 0


class TestTenVerbsCoverFullVocabulary:
    """Live-verification proxy: cc-task acceptance is ≥6 distinct verbs
    in 10 min. We pin stronger here — all 10 verbs dispatch cleanly."""

    def test_consume_each_verb_once(self, tmp_path: Path) -> None:
        consumer = SemanticVerbConsumer(
            envelope_path=tmp_path / "e.jsonl",
            transition_bias_path=tmp_path / "t.jsonl",
        )
        outcomes = [consumer.consume(v) for v in SEMANTIC_VERBS]
        assert all(o == "dispatched" for o in outcomes)
        for verb in SEMANTIC_VERBS:
            assert _counter(verb, "dispatched") == 1


class TestPathConstants:
    def test_default_envelope_path_under_devshm(self) -> None:
        assert str(DEFAULT_ENVELOPE_PATH).startswith("/dev/shm/")

    def test_default_transition_bias_path_under_devshm(self) -> None:
        assert str(DEFAULT_TRANSITION_BIAS_PATH).startswith("/dev/shm/")

    def test_envelope_and_bias_paths_are_distinct(self) -> None:
        assert DEFAULT_ENVELOPE_PATH != DEFAULT_TRANSITION_BIAS_PATH
