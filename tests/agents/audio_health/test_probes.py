"""Audio probe target-resolution tests."""

from __future__ import annotations

from unittest.mock import patch

from agents.audio_health.probes import ProbeConfig, resolve_parecord_target


def _names_for(sources: set[str], sinks: set[str]):
    def fake(kind: str, config: ProbeConfig) -> set[str]:
        if kind == "sources":
            return sources
        if kind == "sinks":
            return sinks
        return set()

    return fake


def test_resolve_parecord_target_uses_exact_source_without_monitor_suffix() -> None:
    cfg = ProbeConfig()
    with patch(
        "agents.audio_health.probes._pactl_short_names",
        side_effect=_names_for({"hapax-broadcast-normalized"}, set()),
    ):
        assert resolve_parecord_target("hapax-broadcast-normalized", cfg) == (
            "hapax-broadcast-normalized"
        )


def test_resolve_parecord_target_strips_monitor_when_stage_is_source() -> None:
    cfg = ProbeConfig()
    with patch(
        "agents.audio_health.probes._pactl_short_names",
        side_effect=_names_for({"hapax-broadcast-normalized"}, set()),
    ):
        assert resolve_parecord_target("hapax-broadcast-normalized.monitor", cfg) == (
            "hapax-broadcast-normalized"
        )


def test_resolve_parecord_target_keeps_sink_monitor_contract() -> None:
    cfg = ProbeConfig()
    with patch(
        "agents.audio_health.probes._pactl_short_names",
        side_effect=_names_for(set(), {"hapax-broadcast-master"}),
    ):
        assert resolve_parecord_target("hapax-broadcast-master", cfg) == (
            "hapax-broadcast-master.monitor"
        )


def test_resolve_parecord_target_preserves_legacy_fallback_without_discovery() -> None:
    cfg = ProbeConfig()
    with patch(
        "agents.audio_health.probes._pactl_short_names",
        side_effect=_names_for(set(), set()),
    ):
        assert resolve_parecord_target("hapax-broadcast-master", cfg) == (
            "hapax-broadcast-master.monitor"
        )
