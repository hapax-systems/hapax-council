"""Audio probe target-resolution tests."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import numpy as np

from agents.audio_health import probes
from agents.audio_health.probes import PersistentProbeSet, ProbeConfig, resolve_parecord_target


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


def test_pactl_short_names_caches_repeated_discovery() -> None:
    probes._PACTL_SHORT_CACHE.clear()
    cfg = ProbeConfig(pactl_path="pactl")
    completed = subprocess.CompletedProcess(
        ["pactl", "list", "sources", "short"],
        0,
        stdout="1\thapax-broadcast-master\tmodule\tformat\tRUNNING\n",
        stderr="",
    )

    with (
        patch("agents.audio_health.probes.shutil.which", return_value="/usr/bin/pactl"),
        patch("agents.audio_health.probes.subprocess.run", return_value=completed) as run,
    ):
        assert probes._pactl_short_names("sources", cfg) == {"hapax-broadcast-master"}
        assert probes._pactl_short_names("sources", cfg) == {"hapax-broadcast-master"}

    assert run.call_count == 1
    probes._PACTL_SHORT_CACHE.clear()


def test_probe_config_defaults_to_native_broadcast_rate() -> None:
    assert ProbeConfig().sample_rate == 48000


def test_persistent_probe_set_reuses_one_stream_per_target() -> None:
    class FakeStream:
        instances: list[FakeStream] = []

        def __init__(self, target: str, config: ProbeConfig) -> None:
            self.target = target
            self.config = config
            self.closed = False
            FakeStream.instances.append(self)

        def read_window(self, duration_s: float | None = None) -> bytes:
            stereo = np.array([1000, 1000, 2000, 2000], dtype=np.int16)
            return stereo.tobytes()

        def close(self) -> None:
            self.closed = True

    cfg = ProbeConfig(duration_s=0.01)
    with PersistentProbeSet(config=cfg, stream_factory=FakeStream) as probe_set:
        first = probe_set.capture("hapax-broadcast-master.monitor")
        second = probe_set.capture("hapax-broadcast-master.monitor")

    assert len(FakeStream.instances) == 1
    assert FakeStream.instances[0].target == "hapax-broadcast-master.monitor"
    assert FakeStream.instances[0].closed is True
    assert first.ok is True
    assert second.ok is True
    assert first.sample_rate == 48000
    assert first.samples_mono.tolist() == [1000, 2000]
