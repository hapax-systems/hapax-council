"""Tests for the role-keyed semantic voice output router."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shared.voice_output_router import (
    VOICE_ROLES,
    RouteResult,
    VoiceOutputRouter,
    VoiceRoleRouterError,
)


def _write_routes(tmp: Path, mapping: dict[str, dict[str, str]]) -> Path:
    body = {"schema_version": 1, "roles": mapping}
    path = tmp / "voice-output-routes.yaml"
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return path


# ── Role enum ──────────────────────────────────────────────────────────


class TestVoiceRoles:
    def test_four_roles(self) -> None:
        assert VOICE_ROLES == ("assistant", "broadcast", "private_monitor", "notification")
        assert len(VOICE_ROLES) == 4


# ── Known role + sink present ──────────────────────────────────────────


class TestKnownRoleSinkPresent:
    def test_returns_sink_name_with_config_role_provenance(self, tmp_path: Path) -> None:
        routes = _write_routes(
            tmp_path,
            {
                "assistant": {"sink_name": "hapax-voice-fx-capture"},
                "broadcast": {"sink_name": "hapax-livestream"},
            },
        )
        router = VoiceOutputRouter(routes_path=routes)
        result = router.route("broadcast")

        assert isinstance(result, RouteResult)
        assert result.role == "broadcast"
        assert result.sink_name == "hapax-livestream"
        assert result.provenance == "config_role"
        assert result.live_at  # ISO timestamp populated

    def test_returns_description_when_present(self, tmp_path: Path) -> None:
        routes = _write_routes(
            tmp_path,
            {
                "assistant": {
                    "sink_name": "hapax-voice-fx-capture",
                    "description": "operator-private TTS path",
                },
            },
        )
        router = VoiceOutputRouter(routes_path=routes)
        result = router.route("assistant")
        assert result.description == "operator-private TTS path"


# ── Sink-present predicate downgrades to unavailable ───────────────────


class TestSinkPresentPredicate:
    def test_predicate_returns_true_keeps_config_role(self, tmp_path: Path) -> None:
        routes = _write_routes(
            tmp_path,
            {"broadcast": {"sink_name": "hapax-livestream"}},
        )
        router = VoiceOutputRouter(
            routes_path=routes,
            sink_present=lambda sink: sink == "hapax-livestream",
        )
        result = router.route("broadcast")
        assert result.provenance == "config_role"
        assert result.sink_name == "hapax-livestream"

    def test_predicate_returns_false_downgrades_to_unavailable(self, tmp_path: Path) -> None:
        routes = _write_routes(
            tmp_path,
            {"broadcast": {"sink_name": "hapax-livestream"}},
        )
        router = VoiceOutputRouter(
            routes_path=routes,
            sink_present=lambda sink: False,
        )
        result = router.route("broadcast")
        assert result.provenance == "unavailable"
        assert result.sink_name is None


# ── Missing role → unavailable ──────────────────────────────────────────


class TestMissingRoleInConfig:
    def test_role_not_in_yaml_returns_unavailable(self, tmp_path: Path) -> None:
        routes = _write_routes(
            tmp_path,
            {"broadcast": {"sink_name": "hapax-livestream"}},
        )
        router = VoiceOutputRouter(routes_path=routes)
        result = router.route("notification")
        assert result.role == "notification"
        assert result.sink_name is None
        assert result.provenance == "unavailable"

    def test_empty_yaml_returns_unavailable_for_all_roles(self, tmp_path: Path) -> None:
        routes = _write_routes(tmp_path, {})
        router = VoiceOutputRouter(routes_path=routes)
        for role in VOICE_ROLES:
            assert router.route(role).provenance == "unavailable"


# ── Unknown role string → raises ───────────────────────────────────────


class TestUnknownRole:
    def test_unknown_role_raises(self, tmp_path: Path) -> None:
        routes = _write_routes(tmp_path, {})
        router = VoiceOutputRouter(routes_path=routes)
        with pytest.raises(VoiceRoleRouterError, match="unknown voice role"):
            router.route("not_a_real_role")  # type: ignore[arg-type]

    def test_typo_role_raises(self, tmp_path: Path) -> None:
        routes = _write_routes(tmp_path, {})
        router = VoiceOutputRouter(routes_path=routes)
        with pytest.raises(VoiceRoleRouterError):
            router.route("braodcast")  # type: ignore[arg-type]


# ── YAML hot-reload on mtime advance ───────────────────────────────────


class TestHotReload:
    def test_mtime_change_picks_up_new_mapping(self, tmp_path: Path) -> None:
        routes = _write_routes(
            tmp_path,
            {"broadcast": {"sink_name": "old-livestream"}},
        )
        router = VoiceOutputRouter(routes_path=routes)
        first = router.route("broadcast")
        assert first.sink_name == "old-livestream"

        # Advance mtime + change content
        import os
        import time

        time.sleep(0.01)
        _write_routes(
            tmp_path,
            {"broadcast": {"sink_name": "new-livestream"}},
        )
        # Force mtime advance even on filesystems with second-resolution.
        os.utime(routes, (routes.stat().st_atime + 1, routes.stat().st_mtime + 1))

        second = router.route("broadcast")
        assert second.sink_name == "new-livestream"

    def test_missing_file_treated_as_empty(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nope.yaml"
        router = VoiceOutputRouter(routes_path=nonexistent)
        result = router.route("broadcast")
        assert result.provenance == "unavailable"

    def test_malformed_yaml_treated_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "malformed.yaml"
        path.write_text("::: not yaml :::\n", encoding="utf-8")
        router = VoiceOutputRouter(routes_path=path)
        result = router.route("broadcast")
        assert result.provenance == "unavailable"


# ── known_roles helper ──────────────────────────────────────────────────


class TestKnownRolesHelper:
    def test_returns_only_configured_roles(self, tmp_path: Path) -> None:
        routes = _write_routes(
            tmp_path,
            {
                "broadcast": {"sink_name": "hapax-livestream"},
                "assistant": {"sink_name": "hapax-voice-fx-capture"},
            },
        )
        router = VoiceOutputRouter(routes_path=routes)
        assert router.known_roles() == ("assistant", "broadcast")

    def test_ignores_invalid_role_names_in_yaml(self, tmp_path: Path) -> None:
        routes = _write_routes(
            tmp_path,
            {
                "broadcast": {"sink_name": "hapax-livestream"},
                "imaginary_role": {"sink_name": "x"},  # not in VOICE_ROLES
            },
        )
        router = VoiceOutputRouter(routes_path=routes)
        assert router.known_roles() == ("broadcast",)


# ── Default config file present ────────────────────────────────────────


class TestDefaultConfigShipped:
    def test_default_yaml_loads_and_has_four_roles(self) -> None:
        """The shipped config/voice-output-routes.yaml must define all four roles."""

        router = VoiceOutputRouter()
        for role in VOICE_ROLES:
            result = router.route(role)
            assert result.provenance == "config_role", (
                f"role {role!r} must be configured in default routes"
            )
            assert result.sink_name, f"role {role!r} must have non-empty sink_name"
