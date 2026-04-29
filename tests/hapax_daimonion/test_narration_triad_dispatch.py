from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _daemon() -> MagicMock:
    daemon = MagicMock()
    daemon._affordance_pipeline = MagicMock()
    return daemon


def _imp() -> SimpleNamespace:
    return SimpleNamespace(
        id="impulse-1",
        source="endogenous.narrative_drive",
        strength=0.5,
        content={
            "drive": "narration",
            "narrative": "compose public narration",
            "action_tendency": "speak",
            "wcs_snapshot_ref": "wcs:audio.broadcast_voice:voice-output-witness",
            "route_evidence_ref": "route:audio.broadcast_voice:health_witness_required",
            "public_claim_evidence_ref": "claim_posture:bounded_nonassertive_narration",
        },
    )


def _candidate() -> SimpleNamespace:
    return SimpleNamespace(
        capability_name="narration.autonomous_first_system",
        combined=0.5,
        payload={"impulse_id": "impulse-1"},
    )


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        programme=SimpleNamespace(programme_id="prog-1", role="experiment"),
        stimmung_tone="ambient",
        director_activity="observe",
        chronicle_events=(
            {
                "source": "world.surface.health",
                "payload": {"narrative": "voice witness fresh"},
                "salience": 0.8,
            },
        ),
        triad_continuity={},
    )


def test_dispatch_writes_triad_before_learning_success(tmp_path, monkeypatch) -> None:
    from agents.hapax_daimonion.autonomous_narrative.emit import EmitResult
    from agents.hapax_daimonion.run_loops_aux import _dispatch_autonomous_narration
    from shared import narration_triad

    monkeypatch.setattr(narration_triad, "TRIAD_LEDGER_PATH", tmp_path / "triads.jsonl")
    monkeypatch.setattr(narration_triad, "TRIAD_STATE_PATH", tmp_path / "triad-state.json")

    with (
        patch(
            "agents.hapax_daimonion.autonomous_narrative.state_readers.assemble_context",
            return_value=_context(),
        ),
        patch(
            "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
            return_value="Hapax is monitoring the fresh witness and will re-evaluate pressure.",
        ),
        patch(
            "agents.hapax_daimonion.autonomous_narrative.emit.emit_narrative",
            return_value=EmitResult(True, True, True, "speech-1"),
        ) as emit_mock,
        patch("agents.hapax_daimonion.autonomous_narrative.emit.record_metric"),
    ):
        _dispatch_autonomous_narration(_daemon(), _imp(), _candidate())

    records = [
        json.loads(line)
        for line in (tmp_path / "triads.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    triad = records[0]
    assert triad["programme_id"] == "prog-1"
    assert triad["programme_role"] == "experiment"
    assert triad["status"] == "open"
    assert {item["outcome_kind"] for item in triad["intended_outcome_items"]} == {
        "monitor",
        "re_evaluate",
    }
    assert emit_mock.call_args.kwargs["speech_event_id"] == triad["speech_event_id"]
    assert emit_mock.call_args.kwargs["triad_ids"] == (triad["triad_id"],)


def test_dispatch_marks_triad_failed_when_emit_write_fails(tmp_path, monkeypatch) -> None:
    from agents.hapax_daimonion.run_loops_aux import _dispatch_autonomous_narration
    from shared import narration_triad

    daemon = _daemon()
    monkeypatch.setattr(narration_triad, "TRIAD_LEDGER_PATH", tmp_path / "triads.jsonl")
    monkeypatch.setattr(narration_triad, "TRIAD_STATE_PATH", tmp_path / "triad-state.json")

    with (
        patch(
            "agents.hapax_daimonion.autonomous_narrative.state_readers.assemble_context",
            return_value=_context(),
        ),
        patch(
            "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
            return_value="Hapax is monitoring the fresh witness.",
        ),
        patch(
            "agents.hapax_daimonion.autonomous_narrative.emit.emit_narrative",
            return_value=False,
        ),
        patch("agents.hapax_daimonion.autonomous_narrative.emit.record_metric"),
    ):
        _dispatch_autonomous_narration(daemon, _imp(), _candidate())

    records = [
        json.loads(line)
        for line in (tmp_path / "triads.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["status"] for record in records] == ["open", "failed"]
    assert daemon._affordance_pipeline.record_outcome.call_args.kwargs["success"] is False
    assert daemon._affordance_pipeline.record_outcome.call_args.kwargs["context"]["triad_id"]
