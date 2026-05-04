"""Tests for M6 topology drift and M8 channel-position consistency daemons."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.audio_health.m6_topology_drift_daemon import (
    DriftState,
    M6DaemonConfig,
    ModuleInfo,
    compute_module_signature,
)
from agents.audio_health.m6_topology_drift_daemon import (
    _emit_snapshot as m6_emit_snapshot,
)
from agents.audio_health.m8_channel_position_daemon import (
    DOWNMIX_EXEMPT_NODES,
    M8DaemonConfig,
    NodeCheck,
    check_all_channels,
)
from agents.audio_health.m8_channel_position_daemon import (
    _emit_snapshot as m8_emit_snapshot,
)

# ── M6 Tests ────────────────────────────────────────────────────────────


class TestModuleSignature:
    """Module signature computation."""

    def test_empty_modules(self) -> None:
        sig = compute_module_signature([])
        assert sig == ""

    def test_single_module(self) -> None:
        m = ModuleInfo(index=1, name="module-null-sink", args="sink_name=test")
        sig = compute_module_signature([m])
        assert sig == "module-null-sink:sink_name=test"

    def test_order_independent(self) -> None:
        """Signature should be the same regardless of module order."""
        m1 = ModuleInfo(index=1, name="module-null-sink", args="sink_name=a")
        m2 = ModuleInfo(index=2, name="module-loopback", args="source=b")
        sig_12 = compute_module_signature([m1, m2])
        sig_21 = compute_module_signature([m2, m1])
        assert sig_12 == sig_21

    def test_different_args_different_sig(self) -> None:
        m1 = ModuleInfo(index=1, name="module-null-sink", args="sink_name=a")
        m2 = ModuleInfo(index=1, name="module-null-sink", args="sink_name=b")
        sig1 = compute_module_signature([m1])
        sig2 = compute_module_signature([m2])
        assert sig1 != sig2


class TestM6Config:
    """M6DaemonConfig construction."""

    def test_defaults(self) -> None:
        cfg = M6DaemonConfig()
        assert cfg.probe_interval_s == 300.0
        assert cfg.restart_suppress_s == 30.0

    def test_from_env_override(self) -> None:
        with patch.dict(
            "os.environ",
            {"HAPAX_AUDIO_HEALTH_TOPOLOGY_DRIFT_PROBE_INTERVAL_S": "600"},
        ):
            cfg = M6DaemonConfig.from_env()
            assert cfg.probe_interval_s == 600.0

    def test_expected_module_count_from_env(self) -> None:
        with patch.dict(
            "os.environ",
            {"HAPAX_AUDIO_HEALTH_TOPOLOGY_DRIFT_EXPECTED_MODULES": "37"},
        ):
            cfg = M6DaemonConfig.from_env()
            assert cfg.expected_module_count == 37


class TestM6DriftDetection:
    """Topology drift detection logic."""

    def test_baseline_established(self) -> None:
        state = DriftState()
        modules = [
            ModuleInfo(index=1, name="module-null-sink", args="sink_name=test"),
        ]
        state.baseline_signature = compute_module_signature(modules)
        state.baseline_count = len(modules)
        assert state.baseline_count == 1
        assert state.baseline_signature == "module-null-sink:sink_name=test"

    def test_drift_detected_new_module(self) -> None:
        """Adding a module changes the signature."""
        m1 = ModuleInfo(index=1, name="module-null-sink", args="sink_name=a")
        baseline = [m1]
        baseline_sig = compute_module_signature(baseline)

        m2 = ModuleInfo(index=2, name="module-loopback", args="source=b")
        current = [m1, m2]
        current_sig = compute_module_signature(current)

        assert baseline_sig != current_sig

    def test_drift_detected_removed_module(self) -> None:
        """Removing a module changes the signature."""
        m1 = ModuleInfo(index=1, name="module-null-sink", args="sink_name=a")
        m2 = ModuleInfo(index=2, name="module-loopback", args="source=b")
        baseline = [m1, m2]
        baseline_sig = compute_module_signature(baseline)

        current = [m1]
        current_sig = compute_module_signature(current)

        assert baseline_sig != current_sig

    def test_no_drift_same_modules(self) -> None:
        m1 = ModuleInfo(index=1, name="module-null-sink", args="sink_name=a")
        sig1 = compute_module_signature([m1])
        sig2 = compute_module_signature([m1])
        assert sig1 == sig2


class TestM6Emission:
    """M6 Prometheus textfile and SHM snapshot emission."""

    def test_emit_snapshot_writes_json(self, tmp_path: Path) -> None:
        snapshot_path = tmp_path / "topology-drift.json"
        state = DriftState(baseline_count=5, drift_events_appeared=1)
        modules = [
            ModuleInfo(index=1, name="module-null-sink", args="test"),
        ]
        m6_emit_snapshot(state, modules, now=1000.0, path=snapshot_path)
        assert snapshot_path.exists()
        data = json.loads(snapshot_path.read_text())
        assert data["monitor"] == "topology-drift"
        assert data["expected_count"] == 5
        assert data["observed_count"] == 1


# ── M8 Tests ────────────────────────────────────────────────────────────


class TestM8Config:
    """M8DaemonConfig construction."""

    def test_defaults(self) -> None:
        cfg = M8DaemonConfig()
        assert cfg.probe_interval_s == 60.0
        assert "hapax-broadcast-master" in cfg.expected_channels

    def test_downmix_exempt(self) -> None:
        assert "hapax-livestream-tap" in DOWNMIX_EXEMPT_NODES


class TestNodeCheck:
    """Node channel check logic."""

    def test_match(self) -> None:
        nc = NodeCheck(name="test", declared=2, observed=2, matched=True)
        assert nc.matched

    def test_mismatch(self) -> None:
        nc = NodeCheck(name="test", declared=2, observed=14, matched=False)
        assert not nc.matched

    def test_absent_is_not_mismatch(self) -> None:
        nc = NodeCheck(name="test", declared=2, observed=None, matched=True)
        assert nc.matched


class TestM8ChannelCheck:
    """Channel check with mocked pactl."""

    def test_check_all_channels_with_mock(self) -> None:
        """Mock get_sink_channel_count to test check logic."""
        cfg = M8DaemonConfig(
            expected_channels={"hapax-broadcast-master": 2, "hapax-livestream-tap": 2},
            downmix_exempt=frozenset({"hapax-livestream-tap"}),
        )

        with patch(
            "agents.audio_health.m8_channel_position_daemon.get_sink_channel_count"
        ) as mock_get:
            # broadcast-master returns 2 (match), livestream-tap returns 14 (exempt)
            mock_get.side_effect = lambda name: 2 if name == "hapax-broadcast-master" else 14
            checks = check_all_channels(cfg)

            assert len(checks) == 2
            master = next(c for c in checks if c.name == "hapax-broadcast-master")
            assert master.matched is True
            assert master.observed == 2

            tap = next(c for c in checks if c.name == "hapax-livestream-tap")
            assert tap.matched is True  # exempt
            assert tap.observed == 14

    def test_mismatch_not_exempt(self) -> None:
        """Non-exempt node with mismatch should be flagged."""
        cfg = M8DaemonConfig(
            expected_channels={"hapax-broadcast-master": 2},
            downmix_exempt=frozenset(),
        )
        with patch(
            "agents.audio_health.m8_channel_position_daemon.get_sink_channel_count"
        ) as mock_get:
            mock_get.return_value = 14
            checks = check_all_channels(cfg)
            assert len(checks) == 1
            assert checks[0].matched is False


class TestM8Emission:
    """M8 Prometheus textfile and SHM snapshot emission."""

    def test_emit_snapshot_writes_json(self, tmp_path: Path) -> None:
        snapshot_path = tmp_path / "channel-position.json"
        checks = [
            NodeCheck(name="hapax-broadcast-master", declared=2, observed=2, matched=True),
        ]
        m8_emit_snapshot(checks, now=1000.0, path=snapshot_path)
        assert snapshot_path.exists()
        data = json.loads(snapshot_path.read_text())
        assert data["monitor"] == "channel-position"
        assert data["nodes"]["hapax-broadcast-master"]["declared"] == 2
        assert data["nodes"]["hapax-broadcast-master"]["matched"] is True
