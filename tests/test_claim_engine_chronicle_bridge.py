"""Tests for ClaimEngine chronicle bridge (UBCC Phase 5b)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from shared.chronicle import ChronicleEvent, query
from shared.claim import ClaimEngine, LRDerivation, TemporalProfile


def _make_engine(name: str = "test-claim") -> ClaimEngine[bool]:
    return ClaimEngine(
        name=name,
        prior=0.5,
        temporal_profile=TemporalProfile(
            enter_threshold=0.7,
            exit_threshold=0.3,
            k_enter=1,
            k_exit=1,
            k_uncertain=1,
        ),
        signal_weights={
            "signal_a": LRDerivation(
                signal_name="signal_a",
                claim_name=name,
                source_category="calibration_study",
                p_true_given_h1=0.95,
                p_true_given_h0=0.05,
                positive_only=False,
                estimation_reference="test",
            ),
        },
    )


class _redirect_record:
    """Context manager: patch record in both chronicle and semantic_trace modules."""

    def __init__(self, chronicle_path: Path) -> None:
        self._path = chronicle_path
        from shared.chronicle import record as original_record

        self._original = original_record

        def _patched(event: ChronicleEvent, *, path: Path = chronicle_path) -> None:
            self._original(event, path=chronicle_path)

        self._p1 = patch("shared.chronicle.record", new=_patched)
        self._p2 = patch("shared.semantic_trace.record", new=_patched)

    def __enter__(self) -> None:
        self._p1.__enter__()
        self._p2.__enter__()

    def __exit__(self, *args: object) -> None:
        self._p2.__exit__(*args)
        self._p1.__exit__(*args)


def test_state_transition_emits_to_chronicle(tmp_path: Path):
    chronicle_path = tmp_path / "events.jsonl"
    now = time.time()

    engine = _make_engine("operator-presence")

    with _redirect_record(chronicle_path):
        for _ in range(5):
            engine.update("signal_a", True)

    results = query(since=now - 5, path=chronicle_path)
    converged = [r for r in results if r.event_type == "semantics.grounding_converged"]
    assert len(converged) >= 1
    ev = converged[0]
    assert ev.source == "claim_engine:operator-presence"
    assert ev.payload["grounding"]["converged"] is True
    assert ev.payload["grounding"]["confidence_bound"] > 0.5


def test_retraction_emits_grounding_diverged(tmp_path: Path):
    chronicle_path = tmp_path / "events.jsonl"
    now = time.time()

    engine = _make_engine("music-playing")

    with _redirect_record(chronicle_path):
        for _ in range(5):
            engine.update("signal_a", True)
        for _ in range(5):
            engine.update("signal_a", False)

    results = query(since=now - 5, path=chronicle_path)
    diverged = [r for r in results if r.event_type == "semantics.grounding_diverged"]
    assert len(diverged) >= 1
    assert diverged[0].source == "claim_engine:music-playing"
    assert diverged[0].payload["grounding"]["converged"] is False


def test_no_emission_without_state_transition(tmp_path: Path):
    chronicle_path = tmp_path / "events.jsonl"

    engine = _make_engine()

    with _redirect_record(chronicle_path):
        engine.update("signal_a", True)

    if not chronicle_path.exists():
        return
    lines = chronicle_path.read_text().strip().splitlines()
    assert len(lines) == 0 or engine.state != "UNCERTAIN"
