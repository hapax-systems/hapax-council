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
        "pw-link -l": CommandResult(
            0,
            """
            OBS Studio:input_FL
              |<- hapax-broadcast-normalized:monitor_FL
            """,
        ),
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
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})
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
    assert health.evidence["loudness"]["target_lufs_i"] == -14.0
    assert health.evidence["loudness"]["target_true_peak_dbtp"] == -1.0
    assert health.evidence["egress_binding"]["bound"] is True
    assert health.owners["loudness_constants"] == "shared/audio_loudness.py"


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
    )
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

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
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

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
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

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


def test_loudness_failure_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

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

    assert health.safe is False
    assert "loudness_out_of_band" in _codes(health)


def test_true_peak_failure_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

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
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner({"pw-link -l": CommandResult(0, "OBS Studio only\n")}),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_binding_missing" in _codes(health)


def test_obs_bound_to_pre_normalized_master_still_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(
            {
                "pw-link -l": CommandResult(
                    0,
                    textwrap.dedent(
                        """
                    OBS:input_FL
                      |<- hapax-broadcast-master:capture_FL
                    hapax-broadcast-normalized:monitor_FL
                      |-> pw-cat:input_FL
                    """
                    ),
                )
            }
        ),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "egress_binding_missing" in _codes(health)
    assert health.evidence["egress_binding"]["observed_source"] is None


def test_runtime_safety_state_stale_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
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
    _write_json(paths.audio_safety_state, {"status": "source_missing", "breach_active": False})

    health = resolve_broadcast_audio_health(
        paths=paths,
        now=NOW,
        command_runner=_runner(),
        service_status_probe=_service_probe(),
    )

    assert health.safe is False
    assert "runtime_safety_failed" in _codes(health)


def test_failed_service_blocks(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

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
    _write_json(paths.audio_safety_state, {"status": "clear", "breach_active": False})

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
