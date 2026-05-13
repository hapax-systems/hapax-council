"""Tests for semantic voice output routing."""

from __future__ import annotations

import json
import os
from pathlib import Path

from shared.voice_output_router import (
    PROHIBITED_PRIVATE_FALLBACK_REFS,
    VoiceOutputDestination,
    VoiceRouteState,
    VoiceRouteWitnessRequirement,
    resolve_voice_output_route,
)


def _write_private_status(
    path: Path,
    *,
    state: str = "ready",
    reason_code: str = "mpc_private_monitor_bound",
) -> None:
    payload = {
        "bridge": {
            "installed": True,
            "matches_repo": True,
            "repaired": False,
            "requires_pipewire_reload": False,
        },
        "bridge_nodes_present": state == "ready",
        "checked_at": "2026-04-30T00:00:00Z",
        "exact_target_present": state == "ready",
        "fallback_policy": "no_default_fallback",
        "operator_visible_reason": (
            "MPC Live III private monitor target and fail-closed bridge are present."
            if state == "ready"
            else "MPC Live III private monitor target is absent; private monitor route remains silent."
        ),
        "reason_code": reason_code,
        "route_id": "route:private.mpc_live_iii_monitor",
        "sanitized": True,
        "state": state,
        "surface_id": "audio.mpc_private_monitor",
        "target_ref": "audio.mpc_private_monitor",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_public_broadcast_route_binds_to_policy_target() -> None:
    result = resolve_voice_output_route(VoiceOutputDestination.PUBLIC_BROADCAST)

    assert result.state is VoiceRouteState.ACCEPTED
    assert result.accepted is True
    assert result.reason_code == "public_broadcast_route_bound"
    assert result.witness_requirement is VoiceRouteWitnessRequirement.PUBLIC_AUDIO_HEALTH
    assert result.target_binding is not None
    assert result.target_binding.source_id == "broadcast-tts"
    assert result.target_binding.target == "hapax-voice-fx-capture"
    assert result.target_binding.media_role == "Broadcast"
    assert result.target_binding.raw_high_level_target_assumption is False
    assert "system-default" in result.target_binding.prohibited_fallback_refs


def test_private_assistant_route_requires_fresh_exact_monitor_evidence(tmp_path: Path) -> None:
    status_path = tmp_path / "private-monitor-target.json"
    _write_private_status(status_path)

    result = resolve_voice_output_route(
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        private_monitor_status_path=status_path,
    )

    assert result.state is VoiceRouteState.ACCEPTED
    assert result.reason_code == "private_assistant_monitor_bound"
    assert result.witness_requirement is VoiceRouteWitnessRequirement.PRIVATE_MONITOR_STATUS
    assert result.target_binding is not None
    assert result.target_binding.source_id == "assistant-private"
    assert result.target_binding.target == "hapax-private"
    assert result.target_binding.target_ref == "audio.mpc_private_monitor"
    assert result.target_binding.media_role == "Assistant"
    assert result.target_binding.fallback_policy == "no_default_fallback"
    assert "hapax-voice-fx-capture" in result.target_binding.prohibited_fallback_refs
    assert "system-default" in result.target_binding.prohibited_fallback_refs


def test_private_notification_route_uses_notification_policy_target(tmp_path: Path) -> None:
    status_path = tmp_path / "private-monitor-target.json"
    _write_private_status(status_path)

    result = resolve_voice_output_route(
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR,
        private_monitor_status_path=status_path,
    )

    assert result.state is VoiceRouteState.ACCEPTED
    assert result.reason_code == "private_notification_monitor_bound"
    assert result.target_binding is not None
    assert result.target_binding.source_id == "notification-private"
    assert result.target_binding.target == "hapax-notification-private"
    assert result.target_binding.media_role == "Notification"


def test_private_missing_status_blocks_without_target_or_fallback(tmp_path: Path) -> None:
    result = resolve_voice_output_route(
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        private_monitor_status_path=tmp_path / "missing.json",
    )

    assert result.state is VoiceRouteState.BLOCKED
    assert result.accepted is False
    assert result.reason_code == "private_monitor_status_missing"
    assert result.target_binding is not None
    assert result.target_binding.target is None
    assert result.target_binding.prohibited_fallback_refs == PROHIBITED_PRIVATE_FALLBACK_REFS
    assert "hapax-livestream" in result.target_binding.prohibited_fallback_refs
    assert "input.loopback.sink.role.multimedia" in result.target_binding.prohibited_fallback_refs


def test_private_blocked_absent_status_carries_mpc_reason(tmp_path: Path) -> None:
    status_path = tmp_path / "private-monitor-target.json"
    _write_private_status(
        status_path,
        state="blocked_absent",
        reason_code="mpc_private_monitor_target_absent",
    )

    result = resolve_voice_output_route(
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        private_monitor_status_path=status_path,
    )

    assert result.state is VoiceRouteState.BLOCKED
    assert result.reason_code == "mpc_private_monitor_target_absent"
    assert result.target_binding is not None
    assert result.target_binding.target is None


def test_private_stale_status_blocks_without_default_fallback(tmp_path: Path) -> None:
    status_path = tmp_path / "private-monitor-target.json"
    _write_private_status(status_path)
    os.utime(status_path, (0.0, 0.0))

    result = resolve_voice_output_route(
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        private_monitor_status_path=status_path,
        private_monitor_max_age_s=60.0,
        now=120.0,
    )

    assert result.state is VoiceRouteState.BLOCKED
    assert result.reason_code == "private_monitor_status_stale"
    assert result.target_binding is not None
    assert result.target_binding.target is None
    assert "system-default" in result.target_binding.prohibited_fallback_refs


def test_raw_high_level_target_strings_are_refused() -> None:
    result = resolve_voice_output_route("private")

    assert result.state is VoiceRouteState.BLOCKED
    assert result.accepted is False
    assert result.reason_code == "raw_high_level_target_refused"
    assert result.semantic_destination is None
    assert result.target_binding is None


def test_dry_run_probe_never_binds_playback_target() -> None:
    result = resolve_voice_output_route(VoiceOutputDestination.DRY_RUN_PROBE)

    assert result.state is VoiceRouteState.ACCEPTED
    assert result.reason_code == "dry_run_probe_no_playback"
    assert result.target_binding is not None
    assert result.target_binding.target is None
    assert result.target_binding.media_role is None
    assert result.witness_requirement is VoiceRouteWitnessRequirement.ROUTE_INTENT_ONLY
