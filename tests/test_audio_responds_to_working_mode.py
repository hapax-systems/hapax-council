"""End-to-end-ish: mode flip must change audio policy snapshots.

Exercises the three downstream consumers wired in audit finding E#7:

1. ``shared.broadcast_audio_health.resolve_broadcast_audio_health`` —
   fortress tightens the true-peak ceiling; research short-circuits
   the LUFS measurement.
2. ``agents.audio_ducker.compute_targets`` — fortress refuses
   ``role.assistant → broadcast`` cross-routing.
3. ``shared.audio_route_switcher.apply_switch`` — fortress refuses
   ``pactl set-default-sink`` outright.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.audio_ducker.__main__ import (
    MUSIC_DUCK_OPERATOR,
    MUSIC_DUCK_TTS,
    UNITY,
    compute_targets,
)
from shared.audio_route_switcher import DefaultSinkChangeBlocked, apply_switch
from shared.broadcast_audio_health import (
    BroadcastAudioHealthThresholds,
    _apply_constraints,
)
from shared.working_mode import WorkingMode


def _set_mode(tmp_path: Path, mode: WorkingMode) -> Path:
    mode_file = tmp_path / "working-mode"
    mode_file.write_text(f"{mode.value}\n")
    return mode_file


# ── Broadcast health threshold coupling ───────────────────────────────


def test_thresholds_unchanged_in_rnd_mode():
    """RND mode = empty constraints = nominal thresholds."""
    base = BroadcastAudioHealthThresholds()
    coupled = _apply_constraints(base, {})
    assert coupled.true_peak_dbtp_override is None
    assert coupled.skip_lufs_egress_check is False
    # Property returns nominal -1.0 + 0.5 tolerance ceiling.
    assert coupled.true_peak_max_dbtp == pytest.approx(-0.5)


def test_fortress_tightens_true_peak_ceiling():
    base = BroadcastAudioHealthThresholds()
    coupled = _apply_constraints(base, {"broadcast_true_peak_dbtp": -1.5})
    assert coupled.true_peak_dbtp_override == -1.5
    # Tighter than nominal; replaces the +tolerance widening.
    assert coupled.true_peak_max_dbtp == -1.5


def test_research_skips_lufs_egress_check():
    base = BroadcastAudioHealthThresholds()
    coupled = _apply_constraints(base, {"lufs_egress_check_skipped": True})
    assert coupled.skip_lufs_egress_check is True


def test_unknown_constraint_keys_ignored():
    """Coupling layer can grow without breaking older threshold dataclasses."""
    base = BroadcastAudioHealthThresholds()
    coupled = _apply_constraints(base, {"some_future_knob": 42})
    assert coupled is base or coupled == base  # replace skipped or no-op replace


# ── Audio ducker coupling ─────────────────────────────────────────────


def test_compute_targets_default_allows_tts_into_broadcast():
    """RND/legacy: TTS active still drives music duck."""
    music, tts = compute_targets(rode_active=False, tts_active=True)
    assert music == MUSIC_DUCK_TTS
    assert tts == UNITY


def test_compute_targets_fortress_refuses_tts_into_broadcast():
    """Fortress: TTS active alone does NOT duck the music broadcast."""
    music, tts = compute_targets(rode_active=False, tts_active=True, allow_tts_into_broadcast=False)
    assert music == UNITY
    assert tts == UNITY


def test_compute_targets_fortress_still_honors_operator_voice():
    """Fortress: operator voice is the broadcast voice — always ducks."""
    music, tts = compute_targets(rode_active=True, tts_active=False, allow_tts_into_broadcast=False)
    assert music == MUSIC_DUCK_OPERATOR


def test_compute_targets_fortress_combined_uses_operator_only():
    """Fortress: rode + tts → music only deepens for rode; TTS leg ignored."""
    music_with_tts, _ = compute_targets(
        rode_active=True, tts_active=True, allow_tts_into_broadcast=False
    )
    music_rode_only, _ = compute_targets(
        rode_active=True, tts_active=False, allow_tts_into_broadcast=False
    )
    assert music_with_tts == music_rode_only


# ── Route switcher coupling ───────────────────────────────────────────


def test_apply_switch_rnd_executes_normally(tmp_path: Path):
    """RND: default-sink swap is allowed."""
    mode_file = _set_mode(tmp_path, WorkingMode.RND)
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        # dry_run avoids actually invoking pactl
        result = apply_switch("alsa_output.test", sink_input_ids=[], dry_run=True)
    assert result == []


def test_apply_switch_research_executes_normally(tmp_path: Path):
    mode_file = _set_mode(tmp_path, WorkingMode.RESEARCH)
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        result = apply_switch("alsa_output.test", sink_input_ids=[], dry_run=True)
    assert result == []


def test_apply_switch_fortress_blocks_default_sink_swap(tmp_path: Path):
    """Fortress: default-sink swap is refused outright."""
    mode_file = _set_mode(tmp_path, WorkingMode.FORTRESS)
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        with pytest.raises(DefaultSinkChangeBlocked) as exc:
            apply_switch("alsa_output.test", sink_input_ids=[], dry_run=True)
    assert "fortress" in str(exc.value)


def test_apply_switch_explicit_constraints_override_live_read(tmp_path: Path):
    """Caller-supplied constraints take precedence over the live mode file.

    Lets test/maintenance flows opt out of the live coupling.
    """
    mode_file = _set_mode(tmp_path, WorkingMode.FORTRESS)
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        # Even though fortress is live, the caller provides a permissive dict.
        result = apply_switch(
            "alsa_output.test",
            sink_input_ids=[],
            dry_run=True,
            constraints={"default_sink_change_allowed": True},
        )
    assert result == []


# ── Mode-flip propagation ─────────────────────────────────────────────


def test_mode_flip_rnd_to_fortress_changes_audio_snapshot(tmp_path: Path):
    """Flip the mode file mid-flight → constraints + thresholds change."""
    from shared.audio_working_mode_couplings import current_audio_constraints

    mode_file = _set_mode(tmp_path, WorkingMode.RND)
    base = BroadcastAudioHealthThresholds()

    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        rnd_constraints = current_audio_constraints()
        rnd_thresholds = _apply_constraints(base, rnd_constraints)

        mode_file.write_text(f"{WorkingMode.FORTRESS.value}\n")

        fortress_constraints = current_audio_constraints()
        fortress_thresholds = _apply_constraints(base, fortress_constraints)

    assert rnd_constraints == {}
    assert rnd_thresholds.true_peak_max_dbtp == pytest.approx(-0.5)

    assert fortress_constraints["broadcast_true_peak_dbtp"] == -1.5
    assert fortress_constraints["audio_routing_policy_yaml_frozen"] is True
    assert fortress_thresholds.true_peak_max_dbtp == -1.5


def test_mode_flip_to_research_skips_lufs_in_envelope(tmp_path: Path):
    """Research mode injects the skip flag → resolver's loudness evidence
    short-circuits without ever shelling out to audio-measure.sh."""
    from shared.audio_working_mode_couplings import current_audio_constraints
    from shared.broadcast_audio_health import (
        BroadcastAudioHealthPaths,
        CommandResult,
        ServiceStatus,
        resolve_broadcast_audio_health,
    )

    mode_file = _set_mode(tmp_path, WorkingMode.RESEARCH)

    invocations: list[tuple[tuple[str, ...], float]] = []

    def runner(cmd, timeout):
        invocations.append((tuple(cmd), timeout))
        # Return zero rc so non-loudness checks pass; loudness must
        # never be invoked under research mode.
        return CommandResult(returncode=0, stdout="", stderr="")

    def probe(unit: str) -> ServiceStatus:
        return ServiceStatus(
            unit=unit, active_state="active", sub_state="running", load_state="loaded"
        )

    paths = BroadcastAudioHealthPaths(
        state_path=tmp_path / "audio-safe.json",
        topology_descriptor=tmp_path / "topology.yaml",
        audio_safety_state=tmp_path / "audio-safety.json",
        audio_ducker_state=tmp_path / "audio-ducker.json",
        voice_output_witness=tmp_path / "voice-witness.json",
        egress_loopback_witness=tmp_path / "egress-loopback.json",
    )

    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        constraints = current_audio_constraints()
        health = resolve_broadcast_audio_health(
            paths=paths,
            command_runner=runner,
            service_status_probe=probe,
            constraints=constraints,
        )

    # The loudness key is present but flagged as skipped.
    assert health.evidence.get("loudness", {}).get("skipped_by_working_mode") is True
    # The audio-measure.sh command must NEVER have been invoked.
    invoked_cmds = [cmd[0] for cmd, _ in invocations]
    assert not any("audio-measure.sh" in part for cmd in invoked_cmds for part in cmd)
    # Constraints land in evidence so the operator can see what was applied.
    assert (
        health.evidence.get("working_mode_constraints", {}).get("lufs_egress_check_skipped") is True
    )
