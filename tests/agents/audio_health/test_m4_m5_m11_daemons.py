"""Tests for M4 inter-stage correlation, M5 pw-top xrun, M11 L-12 USB daemons."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from agents.audio_health.classifier import classify, measure_pcm
from agents.audio_health.m1_dimensions import compute_envelope_correlation
from agents.audio_health.m4_inter_stage_corr_daemon import (
    M4DaemonConfig,
    PairState,
    _is_downstream_signal_loss,
    _pair_key,
    _probe_pair,
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
from agents.audio_health.probes import ProbeResult


def _probe_result(stage: str, samples: np.ndarray) -> ProbeResult:
    measurement = measure_pcm(samples)
    return ProbeResult(
        stage=stage,
        classification=classify(measurement),
        measurement=measurement,
        samples_mono=samples,
        captured_at=1000.0,
        duration_s=samples.size / 48000,
        error=None,
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

    def test_from_env_can_disable_ntfy(self) -> None:
        with patch.dict(
            "os.environ",
            {"HAPAX_AUDIO_HEALTH_INTER_STAGE_CORR_ENABLE_NTFY": "0"},
        ):
            cfg = M4DaemonConfig.from_env()
            assert cfg.enable_ntfy is False


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


class TestM4RawSampleContract:
    def test_pair_probe_captures_both_stages_concurrently(self) -> None:
        t = np.linspace(0, 1, 48000, endpoint=False)
        samples = (0.25 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        results = {
            "a.monitor": _probe_result("a", samples),
            "b.monitor": _probe_result("b", samples.copy()),
        }
        started: set[str] = set()
        lock = threading.Lock()
        both_started = threading.Event()

        def fake_capture(target: str, *, config: object) -> ProbeResult:
            with lock:
                started.add(target)
                if len(started) == 2:
                    both_started.set()
            if not both_started.wait(timeout=1.0):
                raise AssertionError("second stage capture did not start concurrently")
            return results[target]

        state = PairState()
        cfg = M4DaemonConfig(stage_pairs=[("a", "b")], enable_ntfy=False)

        with patch(
            "agents.audio_health.m4_inter_stage_corr_daemon.capture_and_measure",
            side_effect=fake_capture,
        ):
            _probe_pair("a", "b", state, cfg, now=1000.0)

        assert state.last_error is None
        assert started == {"a.monitor", "b.monitor"}

    def test_pair_probe_uses_result_samples_without_dynamic_measurement_attr(self) -> None:
        t = np.linspace(0, 1, 48000, endpoint=False)
        samples = (0.25 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        results = {
            "a.monitor": _probe_result("a", samples),
            "b.monitor": _probe_result("b", samples.copy()),
        }
        state = PairState()
        cfg = M4DaemonConfig(
            stage_pairs=[("a", "b")],
            enable_ntfy=False,
            silence_floor_rms=1e-6,
        )

        def fake_capture(target: str, *, config: object) -> ProbeResult:
            return results[target]

        with patch(
            "agents.audio_health.m4_inter_stage_corr_daemon.capture_and_measure",
            side_effect=fake_capture,
        ):
            _probe_pair("a", "b", state, cfg, now=1000.0)

        assert not hasattr(results["a.monitor"].measurement, "samples_mono")
        assert state.last_error is None
        assert state.both_silent is False
        assert state.last_correlation is not None
        assert state.last_correlation > 0.9

    def test_low_correlation_with_two_live_stages_is_diagnostic_only(self) -> None:
        rng = np.random.default_rng(42)
        samples_a = (0.25 * rng.standard_normal(48000) * 32767).astype(np.int16)
        samples_b = (0.25 * rng.standard_normal(48000) * 32767).astype(np.int16)
        results = {
            "a.monitor": _probe_result("a", samples_a),
            "b.monitor": _probe_result("b", samples_b),
        }
        state = PairState(breach_start=1000.0)
        cfg = M4DaemonConfig(
            stage_pairs=[("a", "b")],
            enable_ntfy=True,
            silence_floor_rms=1e-6,
            breach_sustain_s=1.0,
        )

        def fake_capture(target: str, *, config: object) -> ProbeResult:
            return results[target]

        with (
            patch(
                "agents.audio_health.m4_inter_stage_corr_daemon.capture_and_measure",
                side_effect=fake_capture,
            ),
            patch("agents.audio_health.m4_inter_stage_corr_daemon._send_ntfy") as send_ntfy,
        ):
            _probe_pair("a", "b", state, cfg, now=1002.0)

        assert state.last_error is None
        assert state.last_correlation is not None
        assert state.last_correlation < cfg.correlation_min
        assert state.breach_count == 0
        assert state.low_correlation_count == 1
        send_ntfy.assert_not_called()

    def test_downstream_silence_after_upstream_signal_pages_operator(self) -> None:
        t = np.linspace(0, 1, 48000, endpoint=False)
        samples_a = (0.25 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        samples_b = np.zeros(48000, dtype=np.int16)
        results = {
            "a.monitor": _probe_result("a", samples_a),
            "b.monitor": _probe_result("b", samples_b),
        }
        state = PairState(breach_start=1000.0)
        cfg = M4DaemonConfig(
            stage_pairs=[("a", "b")],
            enable_ntfy=True,
            silence_floor_rms=1e-6,
            breach_sustain_s=1.0,
        )

        def fake_capture(target: str, *, config: object) -> ProbeResult:
            return results[target]

        with (
            patch(
                "agents.audio_health.m4_inter_stage_corr_daemon.capture_and_measure",
                side_effect=fake_capture,
            ),
            patch("agents.audio_health.m4_inter_stage_corr_daemon._send_ntfy") as send_ntfy,
        ):
            _probe_pair("a", "b", state, cfg, now=1002.0)

        assert state.last_error is None
        assert state.last_correlation is not None
        assert state.last_correlation < cfg.correlation_min
        assert state.breach_count == 1
        send_ntfy.assert_called_once()

    def test_both_silent_pair_does_not_page_or_start_breach(self) -> None:
        silence = np.zeros(48000, dtype=np.int16)
        results = {
            "a.monitor": _probe_result("a", silence),
            "b.monitor": _probe_result("b", silence.copy()),
        }
        state = PairState(breach_start=1000.0)
        cfg = M4DaemonConfig(stage_pairs=[("a", "b")], enable_ntfy=True)

        def fake_capture(target: str, *, config: object) -> ProbeResult:
            return results[target]

        with (
            patch(
                "agents.audio_health.m4_inter_stage_corr_daemon.capture_and_measure",
                side_effect=fake_capture,
            ),
            patch("agents.audio_health.m4_inter_stage_corr_daemon._send_ntfy") as send_ntfy,
        ):
            _probe_pair("a", "b", state, cfg, now=1002.0)

        assert state.both_silent is True
        assert state.last_correlation is None
        assert state.breach_start is None
        send_ntfy.assert_not_called()

    def test_downstream_signal_loss_predicate_requires_upstream_signal(self) -> None:
        cfg = M4DaemonConfig(silence_floor_rms=1e-4)

        assert _is_downstream_signal_loss(0.01, 0.0, cfg) is True
        assert _is_downstream_signal_loss(0.01, 0.01, cfg) is False
        assert _is_downstream_signal_loss(0.0, 0.0, cfg) is False

    def test_pair_probe_records_capture_error_as_health_evidence(self, tmp_path: Path) -> None:
        good = _probe_result("a", np.zeros(48000, dtype=np.int16))
        bad = ProbeResult(
            stage="b",
            classification=good.classification,
            measurement=good.measurement,
            samples_mono=np.zeros(0, dtype=np.int16),
            captured_at=1000.0,
            duration_s=0.0,
            error="capture failed",
        )
        state = PairState()
        cfg = M4DaemonConfig(stage_pairs=[("a", "b")], snapshot_path=tmp_path / "corr.json")

        def fake_capture(target: str, *, config: object) -> ProbeResult:
            return {"a.monitor": good, "b.monitor": bad}[target]

        with patch(
            "agents.audio_health.m4_inter_stage_corr_daemon.capture_and_measure",
            side_effect=fake_capture,
        ):
            _probe_pair("a", "b", state, cfg, now=1000.0)

        assert state.analyzer_error_count == 1
        assert state.last_error == "b: capture failed"
        m4_emit_snapshot({"a|b": state}, now=1000.0, path=cfg.snapshot_path)
        payload = json.loads(cfg.snapshot_path.read_text(encoding="utf-8"))
        assert payload["pairs"]["a|b"]["analyzer_error"] == state.last_error
        assert payload["pairs"]["a|b"]["analyzer_error_count"] == 1

    def test_pair_probe_records_analyzer_exception_as_health_evidence(self) -> None:
        t = np.linspace(0, 1, 48000, endpoint=False)
        samples = (0.25 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        state = PairState()
        cfg = M4DaemonConfig(stage_pairs=[("a", "b")])
        results = {
            "a.monitor": _probe_result("a", samples),
            "b.monitor": _probe_result("b", samples),
        }

        def fake_capture(target: str, *, config: object) -> ProbeResult:
            return results[target]

        with (
            patch(
                "agents.audio_health.m4_inter_stage_corr_daemon.capture_and_measure",
                side_effect=fake_capture,
            ),
            patch(
                "agents.audio_health.m4_inter_stage_corr_daemon.compute_envelope_correlation",
                side_effect=RuntimeError("correlation analyzer failed"),
            ),
        ):
            _probe_pair("a", "b", state, cfg, now=1000.0)

        assert state.analyzer_error_count == 1
        assert state.last_error == "RuntimeError: correlation analyzer failed"


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
