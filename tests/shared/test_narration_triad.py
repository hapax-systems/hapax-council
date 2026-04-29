from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from shared.narration_triad import (
    NarrationTriadEnvelope,
    NarrationTriadLedger,
    build_autonomous_narration_triad,
    build_director_speech_triad,
    obligation_outcome_kinds,
    read_triad_state,
    render_triad_prompt_context,
    speech_event_id_for_utterance,
    triad_resolution_refs_from_events,
)


def _context(*, programme_id: str | None = "prog-1", role: str | None = "experiment"):
    programme = None
    if programme_id is not None or role is not None:
        programme = SimpleNamespace(programme_id=programme_id, role=role)
    return SimpleNamespace(
        programme=programme,
        stimmung_tone="ambient",
        director_activity="observe",
        chronicle_events=(
            {
                "ts": 100.0,
                "source": "world.surface.health",
                "event_type": "surface.changed",
                "payload": {"narrative": "voice output witness is fresh"},
                "salience": 0.8,
            },
        ),
        triad_continuity={},
    )


def test_autonomous_triad_envelope_carries_required_refs() -> None:
    triad = build_autonomous_narration_triad(
        text="Hapax is monitoring a fresh voice witness and will re-evaluate the pressure.",
        context=_context(),
        impulse_id="impulse-1",
        speech_event_id="speech-1",
        now=100.0,
    )

    assert triad.schema_version
    assert triad.programme_id == "prog-1"
    assert triad.programme_role == "experiment"
    assert triad.wcs_snapshot_ref == "wcs:audio.broadcast_voice:voice-output-witness"
    assert triad.utterance_text_hash
    assert triad.observation_items
    assert triad.assessment_items
    assert {item.outcome_kind for item in triad.intended_outcome_items} == {
        "monitor",
        "re_evaluate",
    }
    assert triad.learning_update_allowed is False


def test_active_programme_role_without_programme_id_fails_validation() -> None:
    with pytest.raises(ValidationError, match="active programme role requires programme_id"):
        build_autonomous_narration_triad(
            text="Hapax is monitoring the current run.",
            context=_context(programme_id=None, role="experiment"),
            impulse_id="impulse-1",
            speech_event_id="speech-1",
            now=100.0,
        )


def test_obligation_language_opens_action_debt_not_truth_verdict() -> None:
    assert obligation_outcome_kinds("This is curious and warrants closer attention.") == (
        "probe",
        "route_attention",
    )
    triad = build_autonomous_narration_triad(
        text="This is curious and warrants closer attention.",
        context=_context(),
        impulse_id="impulse-2",
        speech_event_id="speech-2",
        now=100.0,
    )

    assert triad.status == "open"
    assert {item.status for item in triad.intended_outcome_items} == {"open"}
    assert triad.capability_outcome_refs == []
    assert triad.semantic_closure_refs() == []


def test_playback_completion_alone_cannot_satisfy_semantic_outcome(tmp_path: Path) -> None:
    ledger = NarrationTriadLedger(
        ledger_path=tmp_path / "triads.jsonl",
        state_path=tmp_path / "triad-state.json",
    )
    triad = build_autonomous_narration_triad(
        text="Hapax is monitoring the public voice witness.",
        context=_context(),
        impulse_id="impulse-3",
        speech_event_id="speech-3",
        now=100.0,
    )
    ledger.append(triad)

    updates = ledger.resolve_open_triads(
        now=120.0,
        observed_witness_refs={"wcs:audio.broadcast_voice:voice-output-witness"},
        semantic_closure_refs={"voice-output-witness:playback_completed"},
    )

    assert updates == []
    assert ledger.open_triads()[0].status == "open"


def test_status_update_rejects_playback_only_semantic_satisfaction(tmp_path: Path) -> None:
    ledger = NarrationTriadLedger(
        ledger_path=tmp_path / "triads.jsonl",
        state_path=tmp_path / "triad-state.json",
    )
    triad = build_autonomous_narration_triad(
        text="Hapax is monitoring the public voice witness.",
        context=_context(),
        impulse_id="impulse-3b",
        speech_event_id="speech-3b",
        now=100.0,
    )
    ledger.append(triad)

    with pytest.raises(ValidationError, match="semantic satisfaction requires"):
        ledger.append_status_update(
            triad,
            status="satisfied",
            closure_refs=["voice-output-witness:playback_completed"],
            now=120.0,
        )


def test_capability_outcome_ref_can_satisfy_semantic_outcome(tmp_path: Path) -> None:
    ledger = NarrationTriadLedger(
        ledger_path=tmp_path / "triads.jsonl",
        state_path=tmp_path / "triad-state.json",
    )
    triad = build_autonomous_narration_triad(
        text="Hapax is monitoring the public voice witness.",
        context=_context(),
        impulse_id="impulse-4",
        speech_event_id="speech-4",
        now=100.0,
    )
    ledger.append(triad)

    updates = ledger.resolve_open_triads(
        now=120.0,
        observed_witness_refs={
            "capability_outcome:narration.autonomous_first_system",
            "wcs:audio.broadcast_voice:voice-output-witness",
        },
        semantic_closure_refs={"capability_outcome:narration.autonomous_first_system"},
    )

    assert len(updates) == 1
    assert updates[0].status == "satisfied"
    assert updates[0].learning_update_allowed is True


def test_open_outcome_stales_after_ttl(tmp_path: Path) -> None:
    ledger = NarrationTriadLedger(
        ledger_path=tmp_path / "triads.jsonl",
        state_path=tmp_path / "triad-state.json",
    )
    triad = build_autonomous_narration_triad(
        text="Hapax is monitoring the public voice witness.",
        context=_context(),
        impulse_id="impulse-5",
        speech_event_id="speech-5",
        now=100.0,
    )
    ledger.append(triad)

    updates = ledger.resolve_open_triads(now=1000.0)

    assert len(updates) == 1
    assert updates[0].status == "stale"
    assert updates[0].learning_update_allowed is False


def test_resolution_refs_from_events_do_not_treat_playback_as_semantic() -> None:
    observed, semantic = triad_resolution_refs_from_events(
        (
            {
                "payload": {
                    "witness_refs": ["voice-output-witness:playback_completed"],
                    "capability_outcome_refs": [
                        "capability_outcome:narration.autonomous_first_system"
                    ],
                    "nested": {"director_move_ref": "director_move:attention-shift"},
                }
            },
        )
    )

    assert "voice-output-witness:playback_completed" in observed
    assert "voice-output-witness:playback_completed" not in semantic
    assert "capability_outcome:narration.autonomous_first_system" in semantic
    assert "director_move:attention-shift" in semantic


def test_ledger_writes_jsonl_and_current_summary(tmp_path: Path) -> None:
    ledger_path = tmp_path / "triads.jsonl"
    state_path = tmp_path / "triad-state.json"
    ledger = NarrationTriadLedger(ledger_path=ledger_path, state_path=state_path)
    triad = build_autonomous_narration_triad(
        text="Hapax will hold this state open.",
        context=_context(),
        impulse_id="impulse-6",
        speech_event_id="speech-6",
        now=100.0,
    )
    ledger.append(triad)

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["triad_id"] == triad.triad_id
    state = read_triad_state(state_path)
    assert state.open_triads[0]["triad_id"] == triad.triad_id
    prompt = render_triad_prompt_context(state)
    assert "Open narration continuity" in prompt


def test_director_speech_uses_same_envelope_shape() -> None:
    triad = build_director_speech_triad(
        text="The director marks a transition as pending witness.",
        programme_id="prog-1",
        programme_role="experiment",
        director_move_ref="director_move:transition-1",
        speech_event_id="speech-director-1",
        now=100.0,
    )

    assert isinstance(triad, NarrationTriadEnvelope)
    assert triad.source_path == "director.speech"
    assert triad.speech_act_type == "director_narrative"
    assert triad.director_move_refs == ["director_move:transition-1"]


def test_speech_event_id_is_stable_for_same_inputs() -> None:
    first = speech_event_id_for_utterance(impulse_id="impulse", text="hello", now=10.0)
    second = speech_event_id_for_utterance(impulse_id="impulse", text="hello", now=10.0)
    assert first == second
