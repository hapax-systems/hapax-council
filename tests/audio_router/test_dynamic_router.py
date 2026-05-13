"""Tests for `agents.audio_router.dynamic_router` — the 5 Hz arbiter daemon.

Covers:

- State assembly from SHM files (tolerant of missing files).
- DynamicRouter.tick() composes policy + sticky tracker correctly.
- emit_intent_change is idempotent on stable state, fires on change.
- Hardware-absent posture (evilpet/s4 MIDI both None) does not raise.
- Sticky operator override flows through the file-watch lifecycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.audio_router.dynamic_router import (
    DynamicRouter,
    _intents_equivalent,
    assemble_state,
    emit_intent_change,
    probe_hardware,
    read_mode_d_active,
    read_stimmung_state,
    read_voice_active,
    read_voice_tier_override,
    write_router_state_snapshot,
)
from agents.audio_router.state import (
    AudioRouterState,
    ProgrammeState,
    RoutingIntent,
)

# ── Stimmung file reader ─────────────────────────────────────────────


def test_read_stimmung_state_returns_defaults_when_file_absent(tmp_path: Path) -> None:
    state = read_stimmung_state(tmp_path / "missing.json")
    assert state.stance == "NOMINAL"
    assert state.energy == 0.5


def test_read_stimmung_state_parses_full_payload(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "stance": "SEEKING",
                "energy": 0.8,
                "coherence": 0.4,
                "focus": 0.6,
                "intention_clarity": 0.7,
                "presence": 0.9,
                "exploration_deficit": 0.65,
                "timestamp": 1700000000.0,
            }
        )
    )
    state = read_stimmung_state(path)
    assert state.stance == "SEEKING"
    assert state.energy == 0.8
    assert state.exploration_deficit == 0.65


def test_read_stimmung_state_clamps_out_of_range_floats(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"stance": "NOMINAL", "energy": 1.5}))
    state = read_stimmung_state(path)
    assert state.energy == 1.0


def test_read_stimmung_state_falls_back_on_unknown_stance(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"stance": "BOGUS_STANCE"}))
    state = read_stimmung_state(path)
    assert state.stance == "NOMINAL"


def test_read_stimmung_state_handles_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{ not valid json")
    state = read_stimmung_state(path)
    assert state.stance == "NOMINAL"
    assert state.energy == 0.5


# ── Voice / Mode-D / override readers ────────────────────────────────


def test_read_voice_active_false_when_file_absent(tmp_path: Path) -> None:
    assert read_voice_active(tmp_path / "absent.json") is False


def test_read_voice_active_true_when_file_says_so(tmp_path: Path) -> None:
    path = tmp_path / "voice-state.json"
    path.write_text(json.dumps({"operator_speech_active": True}))
    assert read_voice_active(path) is True


def test_read_voice_active_false_when_field_missing(tmp_path: Path) -> None:
    path = tmp_path / "voice-state.json"
    path.write_text(json.dumps({}))
    assert read_voice_active(path) is False


def test_read_mode_d_active_false_when_file_absent(tmp_path: Path) -> None:
    assert read_mode_d_active(tmp_path / "absent.json") is False


def test_read_mode_d_active_respects_flag(tmp_path: Path) -> None:
    path = tmp_path / "evil-pet-state.json"
    path.write_text(json.dumps({"mode_d_active": True}))
    assert read_mode_d_active(path) is True


def test_read_voice_tier_override_returns_none_when_absent(tmp_path: Path) -> None:
    tier, sticky = read_voice_tier_override(tmp_path / "absent.json")
    assert tier is None
    assert sticky is False


def test_read_voice_tier_override_parses_full_payload(tmp_path: Path) -> None:
    path = tmp_path / "override.json"
    path.write_text(json.dumps({"tier": 4, "sticky": True}))
    tier, sticky = read_voice_tier_override(path)
    assert tier == 4
    assert sticky is True


def test_read_voice_tier_override_rejects_out_of_range(tmp_path: Path) -> None:
    path = tmp_path / "override.json"
    path.write_text(json.dumps({"tier": 99}))
    tier, _sticky = read_voice_tier_override(path)
    assert tier is None


# ── Hardware probe ──────────────────────────────────────────────────


def test_probe_hardware_evilpet_present_when_send_cc_provided() -> None:
    state = probe_hardware(evilpet_send_cc=MagicMock(), s4_reachable_fn=lambda: True)
    assert state.evilpet_midi_reachable is True
    assert state.s4_usb_enumerated is True


def test_probe_hardware_evilpet_absent_when_send_cc_none() -> None:
    state = probe_hardware(evilpet_send_cc=None, s4_reachable_fn=lambda: False)
    assert state.evilpet_midi_reachable is False
    assert state.s4_usb_enumerated is False


# ── State assembly ──────────────────────────────────────────────────


def test_assemble_state_uses_default_programme_when_omitted(tmp_path: Path) -> None:
    with (
        patch("agents.audio_router.dynamic_router.STIMMUNG_STATE_FILE", tmp_path / "missing"),
        patch("agents.audio_router.dynamic_router.VOICE_STATE_FILE", tmp_path / "missing"),
        patch("agents.audio_router.dynamic_router.EVIL_PET_STATE_FILE", tmp_path / "missing"),
    ):
        state = assemble_state(s4_reachable_fn=lambda: False)
    assert state.programme.role is None
    assert state.broadcaster.operator_voice_active is False


def test_assemble_state_passes_programme_through(tmp_path: Path) -> None:
    programme = ProgrammeState(role="memory_narrator")
    with (
        patch("agents.audio_router.dynamic_router.STIMMUNG_STATE_FILE", tmp_path / "missing"),
        patch("agents.audio_router.dynamic_router.VOICE_STATE_FILE", tmp_path / "missing"),
        patch("agents.audio_router.dynamic_router.EVIL_PET_STATE_FILE", tmp_path / "missing"),
    ):
        state = assemble_state(programme=programme, s4_reachable_fn=lambda: False)
    assert state.programme.role == "memory_narrator"


# ── Intent equivalence + idempotent emission ────────────────────────


def test_intents_equivalent_true_when_midi_fields_match() -> None:
    a = RoutingIntent(
        tier=2, evilpet_preset="hapax-broadcast-ghost", s4_vocal_scene="VOCAL-COMPANION"
    )
    b = a.model_copy(update={"clamp_reasons": ["test"]})
    assert _intents_equivalent(a, b) is True


def test_intents_equivalent_false_when_preset_differs() -> None:
    a = RoutingIntent(tier=2, evilpet_preset="hapax-broadcast-ghost")
    b = a.model_copy(update={"evilpet_preset": "hapax-radio"})
    assert _intents_equivalent(a, b) is False


def test_emit_intent_change_returns_false_when_no_change() -> None:
    intent = RoutingIntent(tier=2, evilpet_preset="hapax-broadcast-ghost")
    fired = emit_intent_change(
        intent,
        previous=intent,
        evilpet_midi=MagicMock(),
        s4_midi_port=None,
        s4_program_for_scene_fn=None,
    )
    assert fired is False


def test_emit_intent_change_calls_recall_preset_on_change() -> None:
    intent = RoutingIntent(tier=3, evilpet_preset="hapax-memory")
    evilpet = MagicMock()
    with patch("agents.audio_router.dynamic_router.recall_preset", return_value=4) as recall_mock:
        fired = emit_intent_change(
            intent,
            previous=None,
            evilpet_midi=evilpet,
            s4_midi_port=None,
            s4_program_for_scene_fn=None,
        )
    assert fired is True
    recall_mock.assert_called_once_with("hapax-memory", evilpet)


def test_emit_intent_change_swallows_recall_exceptions() -> None:
    intent = RoutingIntent(tier=3, evilpet_preset="hapax-memory")
    evilpet = MagicMock()
    with patch("agents.audio_router.dynamic_router.recall_preset", side_effect=RuntimeError):
        # Must not raise — failures are logged and swallowed in the hot path.
        fired = emit_intent_change(
            intent,
            previous=None,
            evilpet_midi=evilpet,
            s4_midi_port=None,
            s4_program_for_scene_fn=None,
        )
    # `fired` is False because no successful emit happened.
    assert fired is False


def test_emit_intent_change_emits_s4_program_when_scene_changes() -> None:
    intent = RoutingIntent(
        tier=2,
        evilpet_preset="hapax-broadcast-ghost",
        s4_vocal_scene="VOCAL-COMPANION",
    )
    s4_port = MagicMock()
    program_lookup = MagicMock(return_value=1)
    with (
        patch("agents.audio_router.dynamic_router.recall_preset", return_value=3),
        patch(
            "agents.audio_router.dynamic_router.s4_midi.emit_program_change", return_value=True
        ) as pc_mock,
    ):
        emit_intent_change(
            intent,
            previous=None,
            evilpet_midi=MagicMock(),
            s4_midi_port=s4_port,
            s4_program_for_scene_fn=program_lookup,
        )
    program_lookup.assert_called_once_with("VOCAL-COMPANION")
    pc_mock.assert_called_once_with(s4_port, program=1)


# ── DynamicRouter.tick integration ──────────────────────────────────


@pytest.fixture
def isolated_router_files(tmp_path: Path):
    """Patch all SHM file paths to a per-test tmp_path so tests don't
    cross-contaminate via the live /dev/shm surfaces."""
    with (
        patch("agents.audio_router.dynamic_router.STIMMUNG_STATE_FILE", tmp_path / "stimmung.json"),
        patch("agents.audio_router.dynamic_router.VOICE_STATE_FILE", tmp_path / "voice-state.json"),
        patch("agents.audio_router.dynamic_router.EVIL_PET_STATE_FILE", tmp_path / "evil-pet.json"),
        patch(
            "agents.audio_router.dynamic_router.VOICE_TIER_OVERRIDE_FILE",
            tmp_path / "override.json",
        ),
    ):
        yield tmp_path


def test_dynamic_router_tick_returns_routing_intent(isolated_router_files: Path) -> None:
    router = DynamicRouter(evilpet_midi=None, s4_midi_port=None)
    intent = router.tick(now=0.0)
    assert isinstance(intent, RoutingIntent)


def test_dynamic_router_tick_no_raise_when_hardware_absent(isolated_router_files: Path) -> None:
    """All probes return falsy; policy clamps to single-engine, no MIDI emitted."""
    router = DynamicRouter(evilpet_midi=None, s4_midi_port=None)
    # Should run cleanly even though everything's absent
    intent = router.tick(now=0.0)
    assert "evilpet_midi_unreachable" in intent.clamp_reasons
    # Plus s4_absent should also clamp
    assert intent.s4_vocal_scene is None  # downgrade-to-single-engine cleared it


def test_dynamic_router_tick_caches_intent_for_idempotence(
    isolated_router_files: Path,
) -> None:
    router = DynamicRouter(evilpet_midi=MagicMock(), s4_midi_port=None)
    with patch("agents.audio_router.dynamic_router.recall_preset", return_value=1) as recall_mock:
        router.tick(now=0.0)
        first_call_count = recall_mock.call_count
        # Same SHM state on second tick — no new emission.
        router.tick(now=0.2)
    assert recall_mock.call_count == first_call_count


def test_dynamic_router_throttles_s4_reachability_probe(
    isolated_router_files: Path,
) -> None:
    probe = MagicMock(return_value=False)
    router = DynamicRouter(
        evilpet_midi=None,
        s4_midi_port=None,
        s4_reachable_fn=probe,
        s4_reachable_probe_interval_s=30.0,
    )

    router.tick(now=0.0)
    router.tick(now=0.2)
    router.tick(now=0.4)

    probe.assert_called_once()


def test_dynamic_router_rechecks_s4_reachability_after_probe_interval(
    isolated_router_files: Path,
) -> None:
    probe = MagicMock(return_value=False)
    router = DynamicRouter(
        evilpet_midi=None,
        s4_midi_port=None,
        s4_reachable_fn=probe,
        s4_reachable_probe_interval_s=30.0,
    )

    router.tick(now=0.0)
    router.tick(now=29.9)
    router.tick(now=30.0)

    assert probe.call_count == 2


def test_dynamic_router_tick_re_emits_when_stimmung_changes(
    isolated_router_files: Path,
) -> None:
    router = DynamicRouter(evilpet_midi=MagicMock(), s4_midi_port=None)
    stimmung = isolated_router_files / "stimmung.json"
    stimmung.write_text(json.dumps({"stance": "NOMINAL"}))
    with patch("agents.audio_router.dynamic_router.recall_preset", return_value=1) as recall_mock:
        router.tick(now=0.0)
        # Switch to FORTRESS — policy clamps to T0 = different preset
        stimmung.write_text(json.dumps({"stance": "FORTRESS"}))
        router.tick(now=0.2)
    # Two distinct presets emitted (NOMINAL → broadcast-ghost vs FORTRESS → unadorned)
    presets_emitted = [c.args[0] for c in recall_mock.call_args_list]
    assert "hapax-broadcast-ghost" in presets_emitted
    assert "hapax-unadorned" in presets_emitted


def test_dynamic_router_tick_drives_sticky_on_voice_transitions(
    isolated_router_files: Path,
) -> None:
    """When VAD flips low→high, sticky tracker registers an emission."""
    router = DynamicRouter(evilpet_midi=None, s4_midi_port=None)
    voice = isolated_router_files / "voice-state.json"
    # Tick 1: silent
    voice.write_text(json.dumps({"operator_speech_active": False}))
    router.tick(now=0.0)
    # Tick 2: speaking
    voice.write_text(json.dumps({"operator_speech_active": True}))
    router.tick(now=0.2)
    # Internal sticky tracker should have an active tier captured
    assert router._sticky._active_tier is not None


# ── write_router_state_snapshot ─────────────────────────────────────


def test_write_router_state_snapshot_round_trip(tmp_path: Path) -> None:
    """Happy path: snapshot writes valid JSON with generated_at + state + intent."""
    target = tmp_path / "state.json"
    state = AudioRouterState()
    intent = RoutingIntent()
    write_router_state_snapshot(state=state, intent=intent, now=1700000000.0, path=target)
    assert target.exists()
    payload = json.loads(target.read_text())
    assert payload["generated_at"] == 1700000000.0
    assert payload["state"]["stimmung"]["stance"] == "NOMINAL"
    assert payload["intent"]["topology"] == "D2_SPLIT"


def test_write_router_state_snapshot_is_atomic(tmp_path: Path) -> None:
    """No .tmp sidecar should remain after a successful write."""
    target = tmp_path / "state.json"
    write_router_state_snapshot(
        state=AudioRouterState(),
        intent=RoutingIntent(),
        now=1.0,
        path=target,
    )
    assert target.exists()
    assert not target.with_suffix(target.suffix + ".tmp").exists()


def test_write_router_state_snapshot_swallows_errors(tmp_path: Path) -> None:
    """Write failures must not propagate — the router must keep ticking."""
    # Make parent path a file so mkdir fails
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    bad_path = blocker / "nested" / "state.json"
    # Should not raise
    write_router_state_snapshot(
        state=AudioRouterState(),
        intent=RoutingIntent(),
        now=1.0,
        path=bad_path,
    )
    assert not bad_path.exists()


def test_dynamic_router_tick_publishes_state_snapshot(
    isolated_router_files: Path, tmp_path: Path
) -> None:
    """After tick, the ROUTER_STATE_FILE must contain the current snapshot."""
    snapshot_path = tmp_path / "router-state.json"
    with patch("agents.audio_router.dynamic_router.ROUTER_STATE_FILE", snapshot_path):
        router = DynamicRouter(evilpet_midi=None, s4_midi_port=None)
        router.tick(now=0.0)
    assert snapshot_path.exists()
    payload = json.loads(snapshot_path.read_text())
    assert "generated_at" in payload
    assert "state" in payload
    assert "intent" in payload
    # Intent should include the full RoutingIntent schema
    assert "topology" in payload["intent"]
    assert "tier" in payload["intent"]
    assert "evilpet_preset" in payload["intent"]
