"""Smoke tests for the L-12 feedback-loop daemon wrapper.

Production side-effects (wpctl auto-mute, awareness state writer,
refusal-log writer) are tested with file/path injection + subprocess
mocks rather than live PipeWire. The actual sd_notify wiring is not
exercised — the systemd integration test belongs to the post-merge
smoke step.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.studio_compositor import feedback_loop_daemon as fld_daemon
from agents.studio_compositor.feedback_loop_detector import TriggerEvent

# ── helpers ────────────────────────────────────────────────────────────────


def _example_event(channel_index: int = 4, hz: float = 1842.7) -> TriggerEvent:
    return TriggerEvent(
        channel_index=channel_index,
        timestamp=datetime(2026, 4, 26, 5, 0, 0, tzinfo=UTC),
        peak_amplitude=0.6,
        rms=0.42,
        baseline_rms=0.05,
        spectral_ratio_db=18.5,
        dominant_frequency_hz=hz,
    )


# ── awareness state writer ─────────────────────────────────────────────────


class TestMakeAwarenessWriter:
    def test_writes_feedback_risk_block_to_state_file(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        writer = fld_daemon.make_awareness_writer(state_path=state_path)
        writer(_example_event())
        assert state_path.exists()
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert "feedback_risk" in payload
        risk = payload["feedback_risk"]
        assert risk["active"] is True
        assert risk["channel_aux"] == 5  # 0-based ch=4 → 1-based 5
        assert risk["frequency_hz"] == 1842.7
        assert "triggered_at" in risk

    def test_preserves_existing_state_keys(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        # Pre-existing awareness state with sibling blocks.
        state_path.write_text(
            json.dumps({"existing_block": {"foo": "bar"}, "another": 42}),
            encoding="utf-8",
        )
        writer = fld_daemon.make_awareness_writer(state_path=state_path)
        writer(_example_event())
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert payload["existing_block"] == {"foo": "bar"}
        assert payload["another"] == 42
        assert "feedback_risk" in payload

    def test_skips_silently_when_parent_dir_missing(self, tmp_path: Path) -> None:
        # Path under a non-existent dir → graceful skip per cc-task spec.
        state_path = tmp_path / "missing" / "state.json"
        writer = fld_daemon.make_awareness_writer(state_path=state_path)
        # Must not raise.
        writer(_example_event())
        assert not state_path.exists()


# ── refusal logger ─────────────────────────────────────────────────────────


class TestMakeRefusalLogger:
    def test_appends_jsonl_entry(self, tmp_path: Path) -> None:
        log_path = tmp_path / "log.jsonl"
        # Pre-existing entry to verify append (not overwrite) semantics.
        log_path.write_text('{"prior": "entry"}\n', encoding="utf-8")
        logger = fld_daemon.make_refusal_logger(log_path=log_path)
        logger(_example_event())
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        new_entry = json.loads(lines[-1])
        assert new_entry["axiom"] == "broadcast_no_loopback"
        assert new_entry["surface"] == "studio-compositor:feedback-loop-detector"
        assert new_entry["public"] is False
        assert "L-12 channel 5" in new_entry["reason"]

    def test_skips_silently_when_parent_dir_missing(self, tmp_path: Path) -> None:
        log_path = tmp_path / "missing" / "log.jsonl"
        logger = fld_daemon.make_refusal_logger(log_path=log_path)
        logger(_example_event())
        assert not log_path.exists()


# ── wpctl auto-mute ────────────────────────────────────────────────────────


class TestMakeWpctlAutoMute:
    def test_invokes_wpctl_on_trigger(self) -> None:
        """The auto-mute callable should fan out wpctl set-volume calls."""
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs: Any) -> Any:
            calls.append(list(cmd))
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="Volume: 1.0\n", stderr=""
            )

        with patch.object(fld_daemon.subprocess, "run", side_effect=fake_run):
            with patch.object(fld_daemon.time, "sleep", lambda _s: None):  # don't actually wait
                auto_mute = fld_daemon.make_wpctl_auto_mute(
                    sink_name="test-sink",
                    duck_in_ms=10,
                    hold_ms=10,
                    duck_out_ms=10,
                    ramp_steps=2,
                )
                auto_mute(_example_event())
                # The thread spawned by auto_mute is daemon=True; give it a moment.
                import time as _t

                _t.sleep(0.05)

        # Should see at least one set-volume call (the get-volume baseline + ramp steps).
        assert any("set-volume" in c for c in calls), f"calls: {calls}"
        sink_used = {c[2] for c in calls if len(c) >= 3 and "set-volume" in c}
        assert "test-sink" in sink_used


# ── source discovery ───────────────────────────────────────────────────────


class TestDiscoverL12Source:
    _PACTL_OUTPUT = (
        "210\talsa_output.usb-Torso_Electronics_S-4_xxx-03.multichannel-output.monitor\t"
        "PipeWire\ts16le 10ch 48000Hz\tSUSPENDED\n"
        "211\talsa_input.usb-Torso_Electronics_S-4_xxx-03.multichannel-input\t"
        "PipeWire\ts16le 10ch 48000Hz\tSUSPENDED\n"
        "213\talsa_input.usb-ZOOM_Corporation_L-12_8253...-00.multichannel-input\t"
        "PipeWire\ts32le 14ch 48000Hz\tRUNNING\n"
    )

    def test_finds_l12_by_substring(self) -> None:
        with patch.object(fld_daemon.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["pactl"], returncode=0, stdout=self._PACTL_OUTPUT, stderr=""
            )
            source = fld_daemon.discover_l12_source()
        assert source == "alsa_input.usb-ZOOM_Corporation_L-12_8253...-00.multichannel-input"

    def test_returns_none_when_l12_absent(self) -> None:
        with patch.object(fld_daemon.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["pactl"],
                returncode=0,
                stdout="210\tsome-other-source\tPipeWire\ts16le\tSUSPENDED\n",
                stderr="",
            )
            source = fld_daemon.discover_l12_source()
        assert source is None

    def test_returns_none_when_pactl_fails(self) -> None:
        with patch.object(fld_daemon.subprocess, "run", side_effect=OSError("pactl missing")):
            assert fld_daemon.discover_l12_source() is None

    def test_pareccapture_resolves_via_discovery_when_source_none(self) -> None:
        capture = fld_daemon.ParecCapture(source=None)
        with patch.object(fld_daemon.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["pactl"], returncode=0, stdout=self._PACTL_OUTPUT, stderr=""
            )
            resolved = capture._resolve_source()
        assert "ZOOM_Corporation_L-12" in resolved
        assert "multichannel-input" in resolved

    def test_pareccapture_raises_oserror_when_l12_absent(self) -> None:
        capture = fld_daemon.ParecCapture(source=None)
        with patch.object(fld_daemon.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["pactl"], returncode=0, stdout="", stderr=""
            )
            with pytest.raises(OSError, match="L-12 multichannel-input source not found"):
                capture._resolve_source()


# ── prometheus counter (skip on absence) ───────────────────────────────────


class TestPrometheusCounter:
    def test_returns_callable_or_noop(self) -> None:
        """``make_prometheus_counter`` returns a callable in either case."""
        counter = fld_daemon.make_prometheus_counter()
        assert callable(counter)
        # Calling it should not raise (either real or no-op).
        counter(_example_event())


# ── daemon class smoke test (uses stub callables) ──────────────────────────


class TestFeedbackLoopDaemon:
    def test_killswitch_returns_zero_immediately(self, monkeypatch) -> None:
        """When killswitch env is set, run() returns 0 after a wait that we cancel."""
        monkeypatch.setenv(fld_daemon.KILLSWITCH_ENV, "1")
        sd_calls: list[str] = []
        daemon = fld_daemon.FeedbackLoopDaemon(
            capture=MagicMock(spec=fld_daemon.ParecCapture),
            auto_mute=MagicMock(),
            awareness_writer=MagicMock(),
            refusal_logger=MagicMock(),
            notifier=MagicMock(),
            counter_inc=MagicMock(),
            sd_notify=lambda msg: sd_calls.append(msg),
        )
        # Stop the daemon immediately so the wait() returns.
        daemon.stop()
        rc = daemon.run()
        assert rc == 0
        assert "READY=1" in sd_calls
        assert any("killswitch" in s for s in sd_calls)

    def test_emits_side_effects_on_trigger(self) -> None:
        """A simulated trigger from the detector should fan out to all callables."""
        capture = MagicMock(spec=fld_daemon.ParecCapture)
        import numpy as np

        sample_rate = 48_000
        window_samples = 12_000
        t = np.arange(window_samples, dtype=np.float32) / sample_rate
        sine = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        sine_buf = np.zeros((window_samples, 14), dtype=np.float32)
        sine_buf[:, 5] = sine
        silent_buf = np.zeros((window_samples, 14), dtype=np.float32)

        # Seed with silence (so baseline = floor 1e-6), then 2× sine to fire.
        capture.read_window.side_effect = [silent_buf, sine_buf, sine_buf, EOFError("done")]
        capture.start.return_value = None
        capture.stop.return_value = None

        auto_mute = MagicMock()
        awareness = MagicMock()
        refusal = MagicMock()
        notifier = MagicMock()
        counter = MagicMock()

        daemon = fld_daemon.FeedbackLoopDaemon(
            capture=capture,
            auto_mute=auto_mute,
            awareness_writer=awareness,
            refusal_logger=refusal,
            notifier=notifier,
            counter_inc=counter,
            sd_notify=lambda _msg: None,
        )

        # Stop the daemon shortly after the EOFError so we don't loop on restart.
        import threading

        def _stopper() -> None:
            import time as _t

            _t.sleep(0.5)
            daemon.stop()

        threading.Thread(target=_stopper, daemon=True).start()
        rc = daemon.run()
        assert rc == 0
        assert auto_mute.called, "auto_mute should fire on sustained sine"
        assert awareness.called, "awareness writer should fire on sustained sine"
        assert refusal.called, "refusal logger should fire on sustained sine"
        assert counter.called, "prometheus counter should fire on sustained sine"
