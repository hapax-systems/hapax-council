"""Tests for the world-surface audio adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents.world_surface.audio_adapter import (
    AudioWorldSurfaceRow,
    project_route_to_world_surface_row,
)
from shared.voice_output_router import RouteResult


def _route(
    role: str = "broadcast",
    sink_name: str | None = "hapax-livestream",
    provenance: str = "config_role",
) -> RouteResult:
    return RouteResult(
        role=role,  # type: ignore[arg-type]
        sink_name=sink_name,
        provenance=provenance,  # type: ignore[arg-type]
        live_at=datetime.now(tz=UTC).isoformat(),
        description=None,
    )


def _write_health_state(
    tmp_path: Path,
    *,
    status: str = "safe",
    safe: bool = True,
    checked_at_offset_s: float = 0.0,
    now: float = 1_700_000_000.0,
) -> Path:
    """Write a minimal valid BroadcastAudioHealth state JSON to a temp path."""

    checked_at_iso = datetime.fromtimestamp(now - checked_at_offset_s, tz=UTC).isoformat()
    payload = {
        "audio_safe_for_broadcast": {
            "safe": safe,
            "status": status,
            "checked_at": checked_at_iso,
            "freshness_s": checked_at_offset_s,
            "blocking_reasons": [],
            "warnings": [],
            "evidence": {},
            "owners": {},
        }
    }
    path = tmp_path / "broadcast-audio-health.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── Route × audibility matrix ───────────────────────────────────────────


class TestRouteAvailableAndAudible:
    def test_safe_health_yields_audible_row(self, tmp_path: Path) -> None:
        health_path = _write_health_state(tmp_path, status="safe", safe=True)
        route = _route()
        row = project_route_to_world_surface_row(
            route, audio_health_path=health_path, now=1_700_000_000.0
        )
        assert isinstance(row, AudioWorldSurfaceRow)
        assert row.role == "broadcast"
        assert row.sink_name == "hapax-livestream"
        assert row.provenance == "config_role"
        assert row.audibility_status == "audible"
        assert row.audibility_reason is None


class TestRouteAvailableAudibilityUncertain:
    def test_degraded_health_yields_unknown_row(self, tmp_path: Path) -> None:
        health_path = _write_health_state(tmp_path, status="degraded", safe=False)
        route = _route()
        row = project_route_to_world_surface_row(
            route, audio_health_path=health_path, now=1_700_000_000.0
        )
        assert row.audibility_status == "unknown"
        assert row.audibility_reason == "degraded"
        assert row.sink_name == "hapax-livestream"

    def test_unsafe_health_yields_unknown_row(self, tmp_path: Path) -> None:
        health_path = _write_health_state(tmp_path, status="unsafe", safe=False)
        route = _route()
        row = project_route_to_world_surface_row(
            route, audio_health_path=health_path, now=1_700_000_000.0
        )
        assert row.audibility_status == "unknown"
        assert row.audibility_reason == "unsafe"

    def test_missing_health_file_yields_unknown_row(self, tmp_path: Path) -> None:
        """No file at audio_health_path: fail-closed reader returns UNKNOWN."""

        nonexistent = tmp_path / "no-such-file.json"
        route = _route()
        row = project_route_to_world_surface_row(
            route, audio_health_path=nonexistent, now=1_700_000_000.0
        )
        assert row.audibility_status == "unknown"
        # The fail-closed reader sets status to UNKNOWN; reason carries it.
        assert row.audibility_reason == "unknown"


class TestRouteUnavailable:
    def test_unavailable_provenance_yields_route_missing_row(self, tmp_path: Path) -> None:
        """Unavailable route short-circuits: never reads audibility state."""

        # Write a stale/missing health file but the adapter shouldn't read it.
        health_path = tmp_path / "should-not-be-read.json"
        # Don't even create it.

        route = _route(sink_name=None, provenance="unavailable")
        row = project_route_to_world_surface_row(
            route, audio_health_path=health_path, now=1_700_000_000.0
        )
        assert row.audibility_status == "route_missing"
        assert row.sink_name is None
        assert row.provenance == "unavailable"
        assert row.audibility_reason == "role unavailable per VoiceOutputRouter"
        assert row.freshness_seconds == 0.0


# ── Roles preserved through projection ────────────────────────────────


class TestRolePreservation:
    @pytest.mark.parametrize("role", ["assistant", "broadcast", "private_monitor", "notification"])
    def test_role_passes_through(self, role: str, tmp_path: Path) -> None:
        health_path = _write_health_state(tmp_path)
        route = _route(role=role)
        row = project_route_to_world_surface_row(
            route, audio_health_path=health_path, now=1_700_000_000.0
        )
        assert row.role == role


# ── Frozen-row immutability ────────────────────────────────────────────


class TestImmutability:
    def test_row_is_frozen(self, tmp_path: Path) -> None:
        health_path = _write_health_state(tmp_path)
        row = project_route_to_world_surface_row(
            _route(), audio_health_path=health_path, now=1_700_000_000.0
        )
        with pytest.raises((AttributeError, TypeError)):
            row.role = "tampered"  # type: ignore[misc]
