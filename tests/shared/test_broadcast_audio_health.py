"""Tests for the broadcast audio safety producer."""

from __future__ import annotations

import json
import os
import textwrap
from collections.abc import Sequence
from pathlib import Path

from shared.broadcast_audio_health import (
    BroadcastAudioHealthPaths,
    CommandResult,
    ServiceStatus,
    read_broadcast_audio_health_state,
    resolve_broadcast_audio_health,
    write_broadcast_audio_health_state,
)

NOW = 1_800_000_000.0


def _write_json(path: Path, payload: dict, *, now: float = NOW, age_s: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    mtime = now - age_s
    os.utime(path, (mtime, mtime))


def _paths(tmp_path: Path) -> BroadcastAudioHealthPaths:
    return BroadcastAudioHealthPaths(
        state_path=tmp_path / "audio-safe-for-broadcast.json",
        topology_descriptor=Path("config/audio-topology.yaml"),
        audio_safety_state=tmp_path / "audio-safety-state.json",
        audio_ducker_state=tmp_path / "audio-ducker-state.json",
        voice_output_witness=tmp_path / "voice-output-witness.json",
        egress_loopback_witness=tmp_path / "egress-loopback.json",
    )


def _live_loopback_witness(**overrides: object) -> dict:
    payload = {
        "checked_at": "2026-05-02T14:00:00Z",
        "rms_dbfs": -18.0,
        "peak_dbfs": -3.0,
        "silence_ratio": 0.05,
        "window_seconds": 5.0,
        "target_sink": "hapax-livestream",
        "error": None,
    }
    payload.update(overrides)
    return payload


def _audio_ducker_state(**overrides: object) -> dict:
    payload = {
        "trigger_cause": "none",
        "fail_open": False,
        "blockers": [],
        "commanded_music_duck_gain": 1.0,
        "actual_music_duck_gain": 1.0,
        "commanded_tts_duck_gain": 1.0,
        "actual_tts_duck_gain": 1.0,
        "music_duck": {
            "commanded_gain": 1.0,
            "actual_gain": 1.0,
            "last_readback_error": None,
            "last_write_error": None,
        },
        "tts_duck": {
            "commanded_gain": 1.0,
            "actual_gain": 1.0,
            "last_readback_error": None,
            "last_write_error": None,
        },
        "rode": {"fresh": True, "sample_age_ms": 20.0, "last_error": None},
        "tts": {"fresh": True, "sample_age_ms": 20.0, "last_error": None},
    }
    payload.update(overrides)
    return payload


def _write_clear_runtime_states(paths: BroadcastAudioHealthPaths) -> None:
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})
    _write_json(paths.audio_ducker_state, _audio_ducker_state())
    _write_json(paths.egress_loopback_witness, _live_loopback_witness())


def _healthy_obs_egress_links() -> str:
    return textwrap.dedent(
        """
        hapax-broadcast-normalized:capture_FL
          |-> hapax-obs-broadcast-remap-capture:input_FL
        hapax-broadcast-normalized:capture_FR
          |-> hapax-obs-broadcast-remap-capture:input_FR
        hapax-obs-broadcast-remap:capture_FL
          |-> OBS:input_FL
        hapax-obs-broadcast-remap:capture_FR
          |-> OBS:input_FR
        """
    )


def _remap_without_obs_links() -> str:
    return textwrap.dedent(
        """
        hapax-broadcast-normalized:capture_FL
          |-> hapax-obs-broadcast-remap-capture:input_FL
        hapax-broadcast-normalized:capture_FR
          |-> hapax-obs-broadcast-remap-capture:input_FR
        hapax-obs-broadcast-remap:capture_FL
        hapax-obs-broadcast-remap:capture_FR
        """
    )


def _runner(
    overrides: dict[str, CommandResult] | None = None,
):
    by_prefix = {
        "scripts/hapax-audio-topology verify": CommandResult(
            0, "live graph matches descriptor (no unclassified drift)\n"
        ),
        "scripts/audio-leak-guard.sh": CommandResult(0, "No leak risk detected\n"),
        "scripts/hapax-audio-topology l12-forward-check": CommandResult(
            0, "L-12 forward invariant: OK\n"
        ),
        "scripts/hapax-audio-topology tts-broadcast-check": CommandResult(
            0, "TTS broadcast path: OK\n"
        ),
        "scripts/audio-measure.sh": CommandResult(
            0,
            """
            Hapax broadcast loudness measurement
              I:         -14.0 LUFS
              Peak:       -1.0 dBFS
            """,
        ),
        "pw-link -l": CommandResult(0, _healthy_obs_egress_links()),
    }
    by_prefix.update(overrides or {})

    def run(command: Sequence[str], _timeout_s: float) -> CommandResult:
        joined = " ".join(command)
        for prefix, result in by_prefix.items():
            if joined.startswith(prefix):
                return result
        return CommandResult(99, stderr=f"unexpected command: {joined}")

    return run


def _service_probe(overrides: dict[str, ServiceStatus | None] | None = None):
    override_map = overrides or {}

    def probe(unit: str) -> ServiceStatus | None:
        if unit in override_map:
            return override_map[unit]
        return ServiceStatus(unit=unit, active_state="active", sub_state="running", n_restarts=0)

    return probe


def _safe_fixture(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )
    return paths, health


def _codes(health) -> set[str]:
    return {reason.code for reason in health.blocking_reasons}


def test_safe_state_contains_contract_shape(tmp_path: Path) -> None:
    _paths_obj, health = _safe_fixture(tmp_path)

    assert health.safe is True
    assert health.status == "safe"
    assert health.freshness_s == 0.0
    assert health.evidence["topology"]["verification"] == "pass"
    assert health.evidence["private_routes"]["status"] == "pass"
    assert health.evidence["broadcast_forward"]["status"] == "pass"
    assert health.evidence["voice_output_witness"]["status"] == "missing"
    assert health.evidence["loudness"]["stage"] == "hapax-broadcast-normalized"
    assert health.evidence["loudness"]["target_lufs_i"] == -14.0
    assert health.evidence["loudness"]["target_min_lufs_i"] == -16.0
    assert health.evidence["loudness"]["target_max_lufs_i"] == -12.0
    assert health.evidence["loudness"]["target_true_peak_dbtp"] == -1.0
    assert health.evidence["egress_binding"]["bound"] is True
    assert health.evidence["egress_binding"]["expected_source"] == "hapax-obs-broadcast-remap"
    assert health.evidence["egress_binding"]["state"] == "obs_bound_unverified"
    assert health.evidence["audio_ducker"]["actual_music_duck_gain"] == 1.0
    assert "hapax-audio-ducker.service" in health.evidence["service_freshness"]["required_units"]
    assert health.owners["loudness_constants"] == "shared/audio_loudness.py"
    assert health.owners["egress_binding"] == "shared/obs_egress_predicate.py + pw-link -l"


def test_state_file_round_trips_named_envelope(tmp_path: Path) -> None:
    paths, health = _safe_fixture(tmp_path)

    write_broadcast_audio_health_state(health, paths.state_path)
    os.utime(paths.state_path, (NOW, NOW))
    payload = json.loads(paths.state_path.read_text(encoding="utf-8"))
    assert "audio_safe_for_broadcast" in payload

    read = read_broadcast_audio_health_state(paths.state_path, now=NOW, max_age_s=30.0)
    assert read.safe is True
    assert read.status == "safe"


def test_missing_state_file_fails_closed(tmp_path: Path) -> None:
    health = read_broadcast_audio_health_state(tmp_path / "missing.json", now=NOW)

    assert health.safe is False
    assert health.status == "unknown"
    assert _codes(health) == {"audio_safe_for_broadcast_missing"}


def test_malformed_state_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")

    health = read_broadcast_audio_health_state(path, now=NOW)

    assert health.safe is False
    assert "audio_safe_for_broadcast_malformed" in _codes(health)


def test_stale_state_file_fails_closed(tmp_path: Path) -> None:
    paths, health = _safe_fixture(tmp_path)
    write_broadcast_audio_health_state(health, paths.state_path)
    os.utime(paths.state_path, (NOW - 60.0, NOW - 60.0))

    stale = read_broadcast_audio_health_state(paths.state_path, now=NOW, max_age_s=30.0)

    assert stale.safe is False
    assert "audio_safe_for_broadcast_stale" in _codes(stale)


def test_missing_topology_descriptor_fails_closed(tmp_path: Path) -> None:
    paths = BroadcastAudioHealthPaths(
        state_path=tmp_path / "out.json",
        topology_descriptor=tmp_path / "missing-topology.yaml",
        audio_safety_state=tmp_path / "audio-safety-state.json",
        audio_ducker_state=tmp_path / "audio-ducker-state.json",
    )
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "topology_descriptor_missing" in _codes(health)


def test_private_leak_guard_failure_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {
                "scripts/audio-leak-guard.sh": CommandResult(
                    2, stderr="hapax-private reaches hapax-livestream"
                )
            }
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "private_route_leak_guard_failed" in _codes(health)


def test_tts_broadcast_path_failure_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {"scripts/hapax-audio-topology tts-broadcast-check": CommandResult(2)}
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "tts_broadcast_path_failed" in _codes(health)


def test_stale_voice_output_witness_blocks_public_voice_claim(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    _write_json(
        paths.voice_output_witness,
        {
            "version": 1,
            "updated_at": "2027-01-15T08:00:00Z",
            "freshness_s": 0.0,
            "status": "playback_completed",
            "last_playback": {"status": "completed", "completed": True},
        },
        age_s=300.0,
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "voice_output_witness_stale" in _codes(health)
    assert health.evidence["voice_output_witness"]["playback_present"] is False


def test_voice_output_silent_failure_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    _write_json(
        paths.voice_output_witness,
        {
            "version": 1,
            "updated_at": "2027-01-15T08:00:00Z",
            "freshness_s": 0.0,
            "status": "drop_recorded",
            "blocker_drop_reason": "pipeline_unavailable",
            "downstream_route_status": {
                "destination": "livestream",
                "target": "hapax-livestream",
                "media_role": "Broadcast",
                "route_present": True,
            },
            "last_drop": {
                "status": "dropped",
                "completed": False,
                "reason": "pipeline_unavailable",
                "pcm_duration_s": None,
            },
        },
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "voice_output_silent_failure" in _codes(health)
    witness = health.evidence["voice_output_witness"]
    assert witness["route_present"] is True
    assert witness["playback_present"] is False
    assert witness["silent_failure"] is True
    assert witness["last_drop"]["reason"] == "pipeline_unavailable"


def test_voice_output_preserves_playback_evidence_after_drop_record(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    _write_json(
        paths.voice_output_witness,
        {
            "version": 1,
            "updated_at": "2027-01-15T08:00:00Z",
            "freshness_s": 0.0,
            "status": "drive_seen",
            "downstream_route_status": {
                "destination": "livestream",
                "target": "hapax-livestream",
                "media_role": "Broadcast",
                "route_present": True,
            },
            "last_playback": {
                "status": "completed",
                "completed": True,
                "pcm_duration_s": 1.5,
            },
            "last_successful_playback": {
                "status": "completed",
                "completed": True,
                "pcm_duration_s": 1.5,
            },
            "last_drop": {
                "status": "dropped",
                "completed": False,
                "reason": "pipeline_unavailable",
            },
        },
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is True
    witness = health.evidence["voice_output_witness"]
    assert witness["route_present"] is True
    assert witness["playback_present"] is True
    assert witness["silent_failure"] is False
    assert witness["last_drop"]["reason"] == "pipeline_unavailable"
    assert witness["last_successful_playback"]["completed"] is True


def test_loudness_under_target_warns(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {
                "scripts/audio-measure.sh": CommandResult(
                    0,
                    """
                      I:         -20.0 LUFS
                      Peak:       -1.0 dBFS
                    """,
                )
            }
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is True
    assert "loudness_under_target" in {w.code for w in health.warnings}


def test_loudness_over_target_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {
                "scripts/audio-measure.sh": CommandResult(
                    0,
                    """
                      I:          -9.1 LUFS
                      Peak:       -1.0 dBFS
                    """,
                )
            }
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "loudness_out_of_band" in _codes(health)


def test_true_peak_failure_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {
                "scripts/audio-measure.sh": CommandResult(
                    0,
                    """
                      I:         -14.0 LUFS
                      Peak:        0.0 dBFS
                    """,
                )
            }
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "true_peak_over_ceiling" in _codes(health)


def test_missing_egress_binding_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner({"pw-link -l": CommandResult(0, "OBS Studio only\n")}),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_binding_missing" in _codes(health)
    assert health.evidence["egress_binding"]["state"] == "remap_missing"


def test_normalized_source_attached_directly_to_obs_still_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {
                "pw-link -l": CommandResult(
                    0,
                    textwrap.dedent(
                        """
                        hapax-broadcast-normalized:capture_FL
                          |-> hapax-obs-broadcast-remap-capture:input_FL
                          |-> OBS:input_FL
                        hapax-broadcast-normalized:capture_FR
                          |-> hapax-obs-broadcast-remap-capture:input_FR
                          |-> OBS:input_FR
                        hapax-obs-broadcast-remap:capture_FL
                        hapax-obs-broadcast-remap:capture_FR
                        """
                    ),
                )
            }
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_binding_missing" in _codes(health)
    assert health.evidence["egress_binding"]["state"] == "obs_wrong_source"
    assert health.evidence["egress_binding"]["observed_source"] == "hapax-broadcast-normalized"


def test_obs_absent_is_distinguished_from_detached_binding(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner({"pw-link -l": CommandResult(0, _remap_without_obs_links())}),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_binding_missing" in _codes(health)
    assert health.evidence["egress_binding"]["state"] == "obs_absent"
    assert health.evidence["egress_binding"]["obs_present"] is False


def test_obs_detached_is_distinguished_when_obs_ports_exist(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {
                "pw-link -l": CommandResult(
                    0,
                    _remap_without_obs_links()
                    + textwrap.dedent(
                        """
                        OBS:input_FL
                        OBS:input_FR
                        """
                    ),
                )
            }
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_binding_missing" in _codes(health)
    assert health.evidence["egress_binding"]["state"] == "obs_detached"
    assert health.evidence["egress_binding"]["obs_present"] is True


def test_egress_binding_unknown_distinguishes_inspection_failure(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner({"pw-link -l": CommandResult(2, stderr="pw-link failed")}),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_binding_unknown" in _codes(health)
    assert health.evidence["egress_binding"]["state"] == "unknown"


def test_runtime_safety_state_stale_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_ducker_state, _audio_ducker_state())
    _write_json(
        paths.audio_safety_state,
        {"status": "clear", "breach_active": False},
        age_s=60.0,
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "runtime_safety_state_stale" in _codes(health)


def test_runtime_safety_breach_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_ducker_state, _audio_ducker_state())
    _write_json(paths.audio_safety_state, {"status": "breach", "breach_active": True})

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "runtime_safety_failed" in _codes(health)


def test_runtime_safety_source_missing_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_ducker_state, _audio_ducker_state())
    _write_json(paths.audio_safety_state, {"status": "source_missing", "breach_active": False})

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "runtime_safety_failed" in _codes(health)


def test_audio_ducker_state_missing_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "audio_ducker_state_missing" in _codes(health)


def test_audio_ducker_fail_open_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})
    _write_json(
        paths.audio_ducker_state,
        _audio_ducker_state(
            fail_open=True,
            trigger_cause="fail_open",
            blockers=["rode_capture_stale:820ms"],
        ),
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "audio_ducker_fail_open" in _codes(health)
    assert health.evidence["audio_ducker"]["blockers"] == ["rode_capture_stale:820ms"]


def test_audio_ducker_idle_retired_readback_is_non_blocking(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    readback_error = "duck_l/r Gain 1 not present in PipeWire Props"
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})
    _write_json(paths.egress_loopback_witness, _live_loopback_witness())
    _write_json(
        paths.audio_ducker_state,
        _audio_ducker_state(
            fail_open=True,
            trigger_cause="none",
            blockers=[
                f"music_readback_error:{readback_error}",
                f"tts_readback_error:{readback_error}",
            ],
            actual_music_duck_gain=None,
            actual_tts_duck_gain=None,
            music_duck={
                "commanded_gain": 1.0,
                "actual_gain": None,
                "last_readback_error": readback_error,
                "last_write_error": None,
            },
            tts_duck={
                "commanded_gain": 1.0,
                "actual_gain": None,
                "last_readback_error": readback_error,
                "last_write_error": None,
            },
        ),
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is True
    assert "audio_ducker_fail_open" not in _codes(health)
    assert "audio_ducker_music_readback_missing" not in _codes(health)
    assert "audio_ducker_tts_readback_missing" not in _codes(health)
    assert health.evidence["audio_ducker"]["raw_fail_open"] is True
    assert health.evidence["audio_ducker"]["fail_open"] is False
    assert set(health.evidence["audio_ducker"]["readback_non_blocking"]) == {
        "music",
        "tts",
    }


def test_audio_ducker_idle_retired_readback_does_not_mask_real_blockers(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    readback_error = "duck_l/r Gain 1 not present in PipeWire Props"
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})
    _write_json(paths.egress_loopback_witness, _live_loopback_witness())
    _write_json(
        paths.audio_ducker_state,
        _audio_ducker_state(
            fail_open=True,
            trigger_cause="none",
            blockers=[
                f"music_readback_error:{readback_error}",
                f"tts_readback_error:{readback_error}",
                "rode_capture_stale:820ms",
            ],
            actual_music_duck_gain=None,
            actual_tts_duck_gain=None,
            music_duck={
                "commanded_gain": 1.0,
                "actual_gain": None,
                "last_readback_error": readback_error,
                "last_write_error": None,
            },
            tts_duck={
                "commanded_gain": 1.0,
                "actual_gain": None,
                "last_readback_error": readback_error,
                "last_write_error": None,
            },
        ),
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "audio_ducker_fail_open" in _codes(health)
    assert health.evidence["audio_ducker"]["fail_open"] is True
    assert health.evidence["audio_ducker"]["non_blocking_readback_blockers"] == [
        f"music_readback_error:{readback_error}",
        f"tts_readback_error:{readback_error}",
    ]


def test_audio_ducker_readback_mismatch_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})
    _write_json(
        paths.audio_ducker_state,
        _audio_ducker_state(
            commanded_music_duck_gain=0.5,
            actual_music_duck_gain=1.0,
        ),
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "audio_ducker_music_readback_mismatch" in _codes(health)


def test_failed_service_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(
            {
                "wireplumber.service": ServiceStatus(
                    unit="wireplumber.service",
                    active_state="failed",
                    sub_state="failed",
                    n_restarts=3,
                )
            }
        ),
    )

    assert health.safe is False
    assert "service_failed" in _codes(health)
    assert (
        health.evidence["service_freshness"]["services"]["wireplumber.service"]["active_state"]
        == "failed"
    )


def test_loudness_command_failure_blocks_as_missing_measurement(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {"scripts/audio-measure.sh": CommandResult(1, stderr="capture is empty")}
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "loudness_measurement_failed" in _codes(health)


# ── Egress loopback witness gate ─────────────────────────────────────


def test_egress_loopback_witness_missing_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    paths.egress_loopback_witness.unlink()

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_loopback_missing" in _codes(health)


def test_egress_loopback_witness_malformed_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    paths.egress_loopback_witness.write_text("not valid json", encoding="utf-8")
    os.utime(paths.egress_loopback_witness, (NOW, NOW))

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_loopback_malformed" in _codes(health)


def test_egress_loopback_witness_stale_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    _write_json(paths.egress_loopback_witness, _live_loopback_witness(), age_s=120.0)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_loopback_stale" in _codes(health)


def test_egress_loopback_witness_schema_invalid_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    _write_json(
        paths.egress_loopback_witness,
        {"checked_at": "2026-05-02T14:00:00Z", "missing": "rms"},
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_loopback_schema_invalid" in _codes(health)


def test_egress_loopback_witness_silent_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    _write_json(
        paths.egress_loopback_witness,
        _live_loopback_witness(silence_ratio=0.95, rms_dbfs=-70.0),
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_loopback_silent" in _codes(health)


def test_egress_loopback_witness_producer_error_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    _write_json(
        paths.egress_loopback_witness,
        _live_loopback_witness(error="pw-cat capture failed"),
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_loopback_producer_failed" in _codes(health)
    assert health.evidence["egress_loopback"]["obs_egress_state"] == "analyzer_internal_failure"


def test_contradictory_loudness_and_loopback_evidence_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {
                "scripts/audio-measure.sh": CommandResult(
                    0,
                    """
                    Hapax broadcast loudness measurement
                      I:         -60.0 LUFS
                      Peak:       -6.0 dBFS
                    """,
                )
            }
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "health_predicate_drift" in _codes(health)
    drift = health.evidence["health_predicate_drift"]
    assert drift["state"] == "health_predicate_drift"
    assert drift["loudness_integrated_lufs_i"] == -60.0
    assert drift["egress_loopback_checked_at"] == "2026-05-02T14:00:00Z"


def test_egress_loopback_witness_low_signal_warns_not_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)
    _write_json(
        paths.egress_loopback_witness,
        _live_loopback_witness(rms_dbfs=-60.0, silence_ratio=0.3),
    )

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert "egress_loopback_low_signal" in {w.code for w in health.warnings}
    assert "egress_loopback_low_signal" not in _codes(health)
    assert health.evidence["egress_loopback"]["status"] == "live"


def test_egress_loopback_witness_happy_path_populates_evidence(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_clear_runtime_states(paths)

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    record = health.evidence["egress_loopback"]
    assert record["status"] == "live"
    assert record["rms_dbfs"] == -18.0
    assert record["target_sink"] == "hapax-livestream"
    assert record["silence_ratio"] == 0.05
    # No loopback-related contributions to blocking/warnings.
    assert not any(c.startswith("egress_loopback") for c in _codes(health))
    assert not any(w.code.startswith("egress_loopback") for w in health.warnings)
