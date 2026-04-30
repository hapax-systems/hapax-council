from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from agents.hapax_daimonion.voice_output_witness import (
    read_voice_output_witness,
    record_composed_autonomous_narrative,
    record_destination_decision,
    record_drop,
    record_narration_drive,
    record_playback_result,
    record_tts_synthesis,
)

NOW = 1_800_000_000.0


def test_records_typed_narration_drive_as_capability_contract(tmp_path: Path) -> None:
    path = tmp_path / "voice-output-witness.json"
    imp = SimpleNamespace(
        source="endogenous.narrative_drive",
        strength=0.44,
        content={"drive": "narration", "narrative": "compose public narration"},
    )

    witness = record_narration_drive(
        imp,
        fallback_dispatched=True,
        duplicate_prevented=False,
        path=path,
        now=NOW,
    )

    assert witness.status == "drive_seen"
    assert witness.last_narration_drive is not None
    assert witness.last_narration_drive["capability_contract"] == (
        "narration.autonomous_first_system"
    )
    assert witness.last_narration_drive["fallback_dispatched"] is True
    assert witness.last_narration_impulse is not None
    assert witness.last_narration_impulse["impulse_id"].startswith("narration-")
    assert witness.last_narration_impulse["action_tendency"] == "speak"
    assert witness.last_narration_impulse["speech_act_candidate"] == "autonomous_narrative"
    assert witness.last_narration_impulse["strength_posterior"] == 0.44
    assert witness.last_narration_impulse["evidence_refs"] == [
        "source:endogenous.narrative_drive",
        "drive:narration",
    ]


def test_playback_result_marks_playback_present_without_audible_claim(tmp_path: Path) -> None:
    path = tmp_path / "voice-output-witness.json"
    imp = SimpleNamespace(
        id="impulse-voice-1",
        source="endogenous.narrative_drive",
        strength=0.61,
        content={"drive": "narration", "narrative": "compose public narration"},
    )
    playback = SimpleNamespace(
        status="completed",
        completed=True,
        returncode=0,
        duration_s=2.0,
        timeout_s=7.0,
        error=None,
    )

    record_narration_drive(
        imp,
        fallback_dispatched=True,
        duplicate_prevented=False,
        path=path,
        now=NOW - 1,
    )
    record_tts_synthesis(
        status="completed",
        text="A complete public narration.",
        pcm=b"\x00" * (24000 * 2),
        impulse_id="impulse-voice-1",
        path=path,
        now=NOW,
    )
    witness = record_playback_result(
        text="A complete public narration.",
        playback_result=playback,
        destination="livestream",
        target="hapax-livestream",
        media_role="Broadcast",
        impulse_id="impulse-voice-1",
        path=path,
        now=NOW + 1,
    )

    assert witness.status == "playback_completed"
    assert witness.playback_present is True
    assert witness.planned_utterance == {"chars": 28, "words": 4}
    assert witness.last_playback is not None
    assert witness.last_playback["pcm_duration_s"] == 2.0
    assert witness.broadcast_egress_activity is not None
    assert witness.broadcast_egress_activity["egress_audible"] is None
    assert witness.last_narration_impulse is not None
    assert witness.last_narration_impulse["impulse_id"] == "impulse-voice-1"
    assert witness.last_narration_impulse["terminal_state"] == "completed"
    assert witness.last_narration_impulse["terminal_reason"] == "playback_completed"


def test_composed_narrative_witness_carries_triad_ids(tmp_path: Path) -> None:
    path = tmp_path / "voice-output-witness.json"
    imp = SimpleNamespace(source="endogenous.narrative_drive", content={})
    candidate = SimpleNamespace(capability_name="narration.autonomous_first_system", combined=0.7)

    witness = record_composed_autonomous_narrative(
        text="A composed narration.",
        impingement=imp,
        candidate=candidate,
        emit_status="emitted",
        impulse_id="impulse-1",
        triad_ids=("triad-1",),
        path=path,
        now=NOW,
    )

    assert witness.last_composed_autonomous_narrative is not None
    assert witness.last_composed_autonomous_narrative["triad_ids"] == ["triad-1"]


def test_drop_records_blocker_reason(tmp_path: Path) -> None:
    path = tmp_path / "voice-output-witness.json"

    witness = record_drop(
        reason="pipeline_unavailable",
        source="stimmung",
        destination="livestream",
        target="hapax-livestream",
        media_role="Broadcast",
        text="Surface this.",
        path=path,
        now=NOW,
    )

    assert witness.status == "drop_recorded"
    assert witness.blocker_drop_reason == "pipeline_unavailable"
    assert witness.last_playback is None
    assert witness.last_drop is not None
    assert witness.last_drop["completed"] is False
    assert witness.last_drop["reason"] == "pipeline_unavailable"


def test_destination_decision_is_recorded_before_playback(tmp_path: Path) -> None:
    path = tmp_path / "voice-output-witness.json"

    witness = record_destination_decision(
        source="operator.microphone.blue_yeti",
        destination="private",
        route_accepted=True,
        reason="private_assistant_monitor_bound",
        safety_gate={
            "context_default": "private_or_drop",
            "explicit_broadcast_intent": False,
        },
        target="hapax-private",
        media_role="Assistant",
        text="Private response.",
        impulse_id="impulse-private-1",
        path=path,
        now=NOW,
    )

    assert witness.status == "destination_decision_recorded"
    assert witness.last_destination_decision is not None
    assert witness.last_destination_decision["destination"] == "private"
    assert witness.last_destination_decision["route_accepted"] is True
    assert witness.last_destination_decision["safety_gate"]["context_default"] == (
        "private_or_drop"
    )
    assert witness.downstream_route_status is not None
    assert witness.downstream_route_status["target"] == "hapax-private"


def test_drop_does_not_overwrite_prior_completed_playback(tmp_path: Path) -> None:
    path = tmp_path / "voice-output-witness.json"
    playback = SimpleNamespace(
        status="completed",
        completed=True,
        returncode=0,
        duration_s=1.5,
        timeout_s=7.0,
        error=None,
    )

    record_playback_result(
        text="A completed narration.",
        playback_result=playback,
        destination="livestream",
        target="hapax-livestream",
        media_role="Broadcast",
        impulse_id="impulse-voice-2",
        path=path,
        now=NOW,
    )
    witness = record_drop(
        reason="pipeline_unavailable",
        source="exploration.affordance_pipeline",
        destination="livestream",
        target="hapax-livestream",
        media_role="Broadcast",
        text="Non-autonomous side channel.",
        path=path,
        now=NOW + 1,
    )

    assert witness.status == "drop_recorded"
    assert witness.last_playback is not None
    assert witness.last_playback["completed"] is True
    assert witness.last_successful_playback is not None
    assert witness.last_successful_playback["completed"] is True
    assert witness.last_drop is not None
    assert witness.last_drop["source"] == "exploration.affordance_pipeline"
    assert witness.last_drop["completed"] is False


def test_inhibited_impulse_terminal_state_is_witnessed(tmp_path: Path) -> None:
    path = tmp_path / "voice-output-witness.json"
    imp = SimpleNamespace(
        id="impulse-route-blocked",
        source="endogenous.narrative_drive",
        strength=0.55,
        content={"drive": "narration", "narrative": "route is not safe"},
    )
    record_narration_drive(
        imp,
        fallback_dispatched=False,
        duplicate_prevented=False,
        path=path,
        now=NOW,
    )

    witness = record_drop(
        reason="route_unsafe_for_public_voice",
        source="autonomous_narrative",
        destination="livestream",
        target=None,
        media_role="Broadcast",
        text="Composed text.",
        impulse_id="impulse-route-blocked",
        terminal_state="inhibited",
        path=path,
        now=NOW + 1,
    )

    assert witness.last_narration_impulse is not None
    assert witness.last_narration_impulse["terminal_state"] == "inhibited"
    assert witness.last_narration_impulse["terminal_reason"] == "route_unsafe_for_public_voice"


def test_stale_witness_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "voice-output-witness.json"
    record_drop(
        reason="pipeline_unavailable",
        source="stimmung",
        path=path,
        now=NOW,
    )
    os.utime(path, (NOW - 300.0, NOW - 300.0))

    witness = read_voice_output_witness(path, now=NOW, max_age_s=30.0)

    assert witness.status == "stale"
    assert witness.blocker_drop_reason == "voice_output_witness_stale"
