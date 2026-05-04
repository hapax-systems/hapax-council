"""Redaction-zone math + mode resolution."""

from __future__ import annotations

import pytest

from agents.hapax_steamdeck_bridge.redaction import (
    DEFAULT_REDACTION_MODE,
    REDACT_ENV,
    RedactionMode,
    RedactionZone,
    friends_list_mask,
    mode_from_env,
    redaction_zones_for_mode,
    steam_notification_mask,
)


def test_default_mode_is_full() -> None:
    assert DEFAULT_REDACTION_MODE is RedactionMode.FULL


def test_steam_notification_mask_is_top_right() -> None:
    z = steam_notification_mask()
    assert z.x == 1700
    assert z.y == 0
    assert z.w == 220
    assert z.h == 80
    assert z.right == 1920
    assert z.bottom == 80


def test_friends_list_mask_anchors_right_edge() -> None:
    z = friends_list_mask()
    # The friends drawer must reach the right edge so a popup can't
    # leak past the redaction.
    assert z.right == 1920


def test_redaction_zones_full_mode() -> None:
    zones = redaction_zones_for_mode(RedactionMode.FULL)
    names = [z.name for z in zones]
    assert "steam_notification" in names
    assert "steam_friends" in names


def test_redaction_zones_partial_mode_drops_friends() -> None:
    zones = redaction_zones_for_mode(RedactionMode.PARTIAL)
    names = [z.name for z in zones]
    assert names == ["steam_notification"]


def test_redaction_zones_off_mode_returns_empty() -> None:
    assert redaction_zones_for_mode(RedactionMode.OFF) == ()


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("full", RedactionMode.FULL),
        ("partial", RedactionMode.PARTIAL),
        ("off", RedactionMode.OFF),
        ("FULL", RedactionMode.FULL),
        ("  off  ", RedactionMode.OFF),
    ],
)
def test_mode_from_env_resolves_known_values(
    monkeypatch, env_value: str, expected: RedactionMode
) -> None:
    monkeypatch.setenv(REDACT_ENV, env_value)
    assert mode_from_env() is expected


def test_mode_from_env_falls_back_on_unknown(monkeypatch) -> None:
    monkeypatch.setenv(REDACT_ENV, "nonsense")
    # Default is FULL — never silently OFF.
    assert mode_from_env() is RedactionMode.FULL


def test_mode_from_env_fall_through_default_is_full(monkeypatch) -> None:
    monkeypatch.delenv(REDACT_ENV, raising=False)
    assert mode_from_env() is RedactionMode.FULL


def test_redaction_zone_geometry_helpers() -> None:
    zone = RedactionZone(name="x", x=10, y=20, w=30, h=40)
    assert zone.right == 40
    assert zone.bottom == 60
