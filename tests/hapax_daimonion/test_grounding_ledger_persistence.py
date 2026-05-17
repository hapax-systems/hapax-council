"""Tests for GQI session persistence."""

from __future__ import annotations

import json
from pathlib import Path


def test_session_summary_fields() -> None:
    """Session summary must contain gqi, total_dus, acceptance counts."""
    from agents.hapax_daimonion.grounding_ledger import GroundingLedger

    ledger = GroundingLedger()
    ledger.add_du(1, "test utterance")
    ledger.update_from_acceptance("ACCEPT")
    ledger.add_du(2, "second utterance")
    ledger.update_from_acceptance("CLARIFY")

    summary = ledger.session_summary()
    assert "final_gqi" in summary
    assert "total_dus" in summary
    assert summary["total_dus"] == 2
    assert 0.0 <= summary["final_gqi"] <= 1.0


def test_persist_session_summary(tmp_path: Path) -> None:
    """Session summary writes to JSONL file."""
    from agents.hapax_daimonion.grounding_ledger import GroundingLedger

    ledger = GroundingLedger()
    ledger.add_du(1, "test")
    ledger.update_from_acceptance("ACCEPT")

    output = tmp_path / "gqi-sessions.jsonl"
    ledger.persist_session_summary(path=output)
    assert output.exists()
    data = json.loads(output.read_text().strip())
    assert data["final_gqi"] > 0
    assert data["total_dus"] == 1
