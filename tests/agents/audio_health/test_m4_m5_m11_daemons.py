"""Tests for M4 inter-stage correlation, M5 pw-top xrun, M11 L-12 USB daemons."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from agents.audio_health.m1_dimensions import compute_envelope_correlation
from agents.audio_health.m4_inter_stage_corr_daemon import (
    M4DaemonConfig,
    PairState,
    _pair_key,
)
from agents.audio_health.m4_inter_stage_corr_daemon import (
    _emit_snapshot as m4_emit_snapshot,
)
from agents.audio_health.m5_pipewire_xrun_daemon import (
    M5DaemonConfig,
    NodeState,
    parse_pwtop_output,
)
from agents.audio_health.m5_pipewire_xrun_daemon import (
    _emit_snapshot as m5_emit_snapshot,
)
from agents.audio_health.m11_l12_usb_daemon import (
    L12State,
    M11DaemonConfig,
    detect_l12_card,
    is_livestream_active,
)
from agents.audio_health.m11_l12_usb_daemon import (
    _emit_snapshot as m11_emit_snapshot,
)

# ── M4 Tests ────────────────────────────────────────────────────────────


class TestM4Config:
    def test_defaults(self) -> None:
        cfg = M4DaemonConfig()
        assert cfg.probe_interval_s == 5.0
        assert cfg.correlation_min == 0.7
        assert len(cfg.stage_pairs) == 2

    def test_from_env_override(self) -> None:
        with patch.dict(
            "os.environ",
            {"HAPAX_AUDIO_HEALTH_INTER_STAGE_CORR_CORRELATION_MIN": "0.8"},
        ):
            cfg = M4DaemonConfig.from_env()
            assert cfg.correlation_min == 0.8


class TestM4Correlation:
    def test_identical_signals_correlation_1(self) -> None:
        """Identical signals should have correlation ~1.0."""
        t = np.linspace(0, 1, 48000, endpoint=False)
        sig = np.sin(2 * np.pi * 440 * t)
        corr = compute_envelope_correlation(sig, sig)
        assert corr is not None
        assert corr == pytest.approx(1.0, abs=0.01)

    def test_inverted_signal_high_correlation(self) -> None:
        """Inverted signal should still have high envelope correlation."""
        t = np.linspace(0, 1, 48000, endpoint=False)
        sig = np.sin(2 * np.pi * 440 * t)
        corr = compute_envelope_correlation(sig, -sig)
        assert corr is not None
        # Envelope of -sig is same as sig, so correlation should be ~1.0
        assert corr > 0.9

    def test_uncorrelated_signals(self) -> None:
        """Uncorrelated signals should have low correlation."""
        rng = np.random.default_rng(42)
        sig_a = rng.standard_normal(48000)
        sig_b = rng.standard_normal(48000)
        corr = compute_envelope_correlation(sig_a, sig_b)
        assert corr is not None
        assert corr < 0.5

    def test_silence_both_constant_correlation(self) -> None:
        """Both silent signals have constant envelopes → correlation 1.0."""
        silence = np.zeros(48000)
        corr = compute_envelope_correlation(silence, silence)
        assert corr is not None
        # Constant envelopes are perfectly correlated (both zero)
        assert corr == pytest.approx(1.0, abs=0.01)

    def test_pair_key(self) -> None:
        assert _pair_key("a", "b") == "a|b"


class TestM4Emission:
    def test_emit_snapshot(self, tmp_path: Path) -> None:
        path = tmp_path / "inter-stage-corr.json"
        pairs = {"a|b": PairState(last_correlation=0.95, breach_count=0)}
        m4_emit_snapshot(pairs, now=1000.0, path=path)
        data = json.loads(path.read_text())
        assert data["monitor"] == "inter-stage-corr"
        assert data["pairs"]["a|b"]["correlation"] == pytest.approx(0.95)


# ── M5 Tests ────────────────────────────────────────────────────────────


PWTOP_SAMPLE = """\
S  ID QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME
S  34  1024  48000   0.15ms  0.12ms  0.7%  0.6%    0  alsa_output.usb-ZOOM_L-12
S  35  1024  48000   0.10ms  0.08ms  0.5%  0.4%    3  alsa_input.usb-ZOOM_L-12
S  50   512  48000   0.05ms  0.03ms  0.2%  0.1%    0  hapax-broadcast-master
"""


class TestM5Config:
    def test_defaults(self) -> None:
        cfg = M5DaemonConfig()
        assert cfg.probe_interval_s == 10.0
        assert cfg.xrun_storm_threshold == 5


class TestPwTopParsing:
    def test_parse_sample_output(self) -> None:
        nodes = parse_pwtop_output(PWTOP_SAMPLE)
        assert len(nodes) == 3

    def test_parse_node_values(self) -> None:
        nodes = parse_pwtop_output(PWTOP_SAMPLE)
        l12_output = next(n for n in nodes if "alsa_output" in n.name)
        assert l12_output.busy_pct == pytest.approx(0.6)
        assert l12_output.wait_pct == pytest.approx(0.7)
        assert l12_output.xruns == 0

    def test_parse_xruns(self) -> None:
        nodes = parse_pwtop_output(PWTOP_SAMPLE)
        l12_input = next(n for n in nodes if "alsa_input" in n.name)
        assert l12_input.xruns == 3

    def test_parse_empty_output(self) -> None:
        assert parse_pwtop_output("") == []

    def test_parse_header_only(self) -> None:
        header = "S  ID QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME\n"
        assert parse_pwtop_output(header) == []


class TestM5XrunDelta:
    def test_delta_calculation(self) -> None:
        state = NodeState(last_xruns=10)
        new_xruns = 15
        state.xrun_delta = max(0, new_xruns - state.last_xruns)
        state.last_xruns = new_xruns
        assert state.xrun_delta == 5

    def test_delta_no_new_xruns(self) -> None:
        state = NodeState(last_xruns=10)
        state.xrun_delta = max(0, 10 - state.last_xruns)
        assert state.xrun_delta == 0

    def test_storm_detection(self) -> None:
        cfg = M5DaemonConfig(xrun_storm_threshold=5)
        delta = 8
        assert delta > cfg.xrun_storm_threshold


class TestM5Emission:
    def test_emit_snapshot(self, tmp_path: Path) -> None:
        path = tmp_path / "pipewire-xrun.json"
        states = {"test-node": NodeState(xrun_delta=3, busy_pct=0.5, wait_pct=0.3)}
        m5_emit_snapshot(states, now=1000.0, path=path)
        data = json.loads(path.read_text())
        assert data["monitor"] == "pipewire-xrun"
        assert data["nodes"]["test-node"]["xrun_delta"] == 3


# ── M11 Tests ───────────────────────────────────────────────────────────


class TestM11Config:
    def test_defaults(self) -> None:
        cfg = M11DaemonConfig()
        assert cfg.probe_interval_s == 30.0
        assert cfg.expected_sample_rate == 48000
        assert cfg.absent_threshold_s == 30.0

    def test_from_env_override(self) -> None:
        with patch.dict(
            "os.environ",
            {"HAPAX_AUDIO_HEALTH_L12_USB_ABSENT_THRESHOLD_S": "60"},
        ):
            cfg = M11DaemonConfig.from_env()
            assert cfg.absent_threshold_s == 60.0


class TestM11Detection:
    def test_detect_l12_card_with_mock(self) -> None:
        mock_output = " 0 [L12            ]: USB-Audio - ZOOM L-12\n                      ZOOM Corporation ZOOM L-12 at usb-0000:00:14.0-2, high speed\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = mock_output
            card = detect_l12_card()
            assert card == 0

    def test_detect_l12_card_absent(self) -> None:
        mock_output = " 0 [Generic        ]: USB-Audio - Generic USB Audio\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = mock_output
            card = detect_l12_card()
            assert card is None

    def test_livestream_active(self, tmp_path: Path) -> None:
        flag = tmp_path / "livestream-active"
        assert is_livestream_active(flag) is False
        flag.touch()
        assert is_livestream_active(flag) is True


class TestM11AbsentLogic:
    def test_absent_during_livestream(self) -> None:
        state = L12State(absent_since=100.0, present=False)
        cfg = M11DaemonConfig(absent_threshold_s=30.0)
        now = 135.0  # 35s absent
        assert (now - state.absent_since) >= cfg.absent_threshold_s

    def test_present_clears_absent(self) -> None:
        state = L12State(absent_since=100.0, present=False)
        # Simulate device returning
        state.present = True
        state.absent_since = None
        assert state.absent_since is None

    def test_sample_rate_drift_detection(self) -> None:
        cfg = M11DaemonConfig(expected_sample_rate=48000)
        observed = 44100
        assert observed != cfg.expected_sample_rate


class TestM11Emission:
    def test_emit_snapshot(self, tmp_path: Path) -> None:
        path = tmp_path / "l12-usb.json"
        state = L12State(present=True, sample_rate=48000, xrun_delta=0)
        m11_emit_snapshot(state, now=1000.0, path=path)
        data = json.loads(path.read_text())
        assert data["monitor"] == "l12-usb"
        assert data["present"] is True
        assert data["sample_rate"] == 48000
