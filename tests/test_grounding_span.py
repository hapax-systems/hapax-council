"""Tests for grounding span emission from GroundingLedger."""

from __future__ import annotations

import time
from pathlib import Path

from shared.chronicle import query


def test_emit_grounding_span_converged(tmp_path: Path):
    from agents.hapax_daimonion.grounding_ledger import GroundingLedger

    ledger = GroundingLedger()
    chronicle_path = tmp_path / "events.jsonl"

    span_id = ledger.emit_grounding_span(
        checks=["T1", "T2"],
        converged=True,
        confidence=0.8,
        chronicle_path=chronicle_path,
    )
    assert isinstance(span_id, str)

    now = time.time()
    results = query(since=now - 5, event_type="semantics.grounding_converged", path=chronicle_path)
    assert len(results) == 1
    assert results[0].payload["grounding"]["converged"] is True
    assert results[0].payload["grounding"]["confidence_bound"] == 0.8
    assert results[0].evidence_class == "semantic_interpretation"


def test_emit_grounding_span_diverged(tmp_path: Path):
    from agents.hapax_daimonion.grounding_ledger import GroundingLedger

    ledger = GroundingLedger()
    chronicle_path = tmp_path / "events.jsonl"

    ledger.emit_grounding_span(
        checks=["T1"],
        converged=False,
        confidence=0.2,
        chronicle_path=chronicle_path,
    )

    now = time.time()
    results = query(since=now - 5, event_type="semantics.grounding_diverged", path=chronicle_path)
    assert len(results) == 1
    assert results[0].payload["grounding"]["converged"] is False
