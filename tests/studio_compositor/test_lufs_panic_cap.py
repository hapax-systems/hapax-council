"""Tests for LUFS-S panic-cap."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.studio_compositor.lufs_panic_cap import (
    DEFAULT_BREACH_WINDOW_MS,
    LufsPanicCap,
    _db_to_linear,
    _resolve_wpctl_node_id,
    _sine_ease,
)


class TestSineEase:
    """Sine-ease envelope helper — must be smooth (never binary)."""

    def test_endpoints(self) -> None:
        assert _sine_ease(0.0) == 0.0
        assert _sine_ease(1.0) == pytest.approx(1.0, abs=1e-9)

    def test_midpoint_is_half(self) -> None:
        assert _sine_ease(0.5) == pytest.approx(0.5, abs=1e-9)

    def test_monotonic(self) -> None:
        prev = -1.0
        for t in (i / 100.0 for i in range(101)):
            v = _sine_ease(t)
            assert v >= prev
            prev = v

    def test_no_binary_jump(self) -> None:
        """No two adjacent micro-steps should jump > 0.1 (no square-wave shape)."""
        steps = [_sine_ease(i / 64.0) for i in range(65)]
        diffs = [b - a for a, b in zip(steps[:-1], steps[1:], strict=True)]
        assert max(diffs) < 0.1, f"sine-ease has a binary jump: max diff = {max(diffs)}"


class TestDbToLinear:
    def test_zero_db_is_unity(self) -> None:
        assert _db_to_linear(0.0) == pytest.approx(1.0)

    def test_minus_six_db_is_half_voltage(self) -> None:
        assert _db_to_linear(-6.0) == pytest.approx(0.5012, abs=1e-3)

    def test_minus_forty_db(self) -> None:
        # 10**(-40/20) = 0.01
        assert _db_to_linear(-40.0) == pytest.approx(0.01, abs=1e-6)


class TestWpctlNodeResolution:
    @patch("subprocess.run")
    def test_numeric_target_is_used_directly(self, mock_run: MagicMock) -> None:
        assert _resolve_wpctl_node_id("80") == "80"
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_resolves_pipewire_node_name_from_pw_dump(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": 80,
                        "type": "PipeWire:Interface:Node",
                        "info": {"props": {"node.name": "hapax-broadcast-master"}},
                    }
                ]
            ),
            stderr="",
        )

        assert _resolve_wpctl_node_id("hapax-broadcast-master") == "80"

    @patch("subprocess.run")
    def test_returns_none_when_node_name_missing(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": 80,
                        "type": "PipeWire:Interface:Node",
                        "info": {"props": {"node.name": "other-node"}},
                    }
                ]
            ),
            stderr="",
        )

        assert _resolve_wpctl_node_id("hapax-broadcast-master") is None

    @pytest.mark.parametrize(
        "exc",
        (
            FileNotFoundError("missing pw-dump"),
            subprocess.TimeoutExpired(["pw-dump"], 5.0),
            OSError("pipewire unavailable"),
        ),
    )
    @patch("subprocess.run")
    def test_returns_none_when_pw_dump_raises_with_next_action(
        self,
        mock_run: MagicMock,
        caplog: pytest.LogCaptureFixture,
        exc: Exception,
    ) -> None:
        mock_run.side_effect = exc

        with caplog.at_level("WARNING", logger="agents.studio_compositor.lufs_panic_cap"):
            assert _resolve_wpctl_node_id("hapax-broadcast-master") is None

        assert "Next action:" in caplog.text
        assert "wpctl status" in caplog.text
        assert "hapax-broadcast-master" in caplog.text

    @patch("subprocess.run")
    def test_returns_none_when_pw_dump_returns_nonzero_with_next_action(
        self,
        mock_run: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="pw server down")

        with caplog.at_level("WARNING", logger="agents.studio_compositor.lufs_panic_cap"):
            assert _resolve_wpctl_node_id("hapax-broadcast-master") is None

        assert "pw server down" in caplog.text
        assert "Next action:" in caplog.text
        assert "pw-dump" in caplog.text

    @patch("subprocess.run")
    def test_returns_none_when_pw_dump_emits_invalid_json_with_next_action(
        self,
        mock_run: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="{", stderr="")

        with caplog.at_level("WARNING", logger="agents.studio_compositor.lufs_panic_cap"):
            assert _resolve_wpctl_node_id("hapax-broadcast-master") is None

        assert "invalid JSON" in caplog.text
        assert "Next action:" in caplog.text

    @patch("subprocess.run")
    def test_ignores_node_id_with_unusable_type(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": {"nested": 80},
                        "type": "PipeWire:Interface:Node",
                        "info": {"props": {"node.name": "hapax-broadcast-master"}},
                    }
                ]
            ),
            stderr="",
        )

        assert _resolve_wpctl_node_id("hapax-broadcast-master") is None


class TestBreachAccumulator:
    """``evaluate_window`` exercises breach detection in isolation."""

    def test_single_loud_window_does_not_trigger(self) -> None:
        cap = LufsPanicCap()
        # Threshold default -6.0; one window above is not enough.
        assert cap.evaluate_window(-3.0) is False

    def test_three_consecutive_loud_windows_trigger(self) -> None:
        cap = LufsPanicCap()
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is True
        # Default breach window is 300 ms = 3 × 100 ms.

    def test_brief_peak_below_breach_window_does_not_trigger(self) -> None:
        """Two loud windows (200 ms) — under the 300 ms sustain — don't fire."""
        cap = LufsPanicCap()
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is False
        # Drop below threshold; history must reset.
        assert cap.evaluate_window(-20.0) is False
        # Now require three NEW consecutive loud windows.
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is True

    def test_normal_program_material_never_triggers(self) -> None:
        """-16 LUFS-I (typical broadcast target) is well below cap."""
        cap = LufsPanicCap()
        for _ in range(100):
            assert cap.evaluate_window(-16.0) is False

    def test_threshold_boundary_strict_above(self) -> None:
        """Equal-to-threshold doesn't fire — only strictly above."""
        cap = LufsPanicCap(threshold_lufs_s=-6.0)
        for _ in range(10):
            assert cap.evaluate_window(-6.0) is False

    def test_inf_input_is_skipped(self) -> None:
        cap = LufsPanicCap()
        assert cap.evaluate_window(float("-inf")) is False
        assert cap.evaluate_window(float("nan")) is False
        # History wasn't polluted; need 3 fresh loud windows.
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is True


class TestBreachWindowConfig:
    """Custom breach window translates to the right number of measurements."""

    def test_500ms_window_requires_five_loud_measurements(self) -> None:
        cap = LufsPanicCap(breach_window_ms=500)
        for _ in range(4):
            assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is True

    def test_100ms_window_requires_one_loud_measurement(self) -> None:
        cap = LufsPanicCap(breach_window_ms=100)
        assert cap.evaluate_window(-3.0) is True


class TestStateMachineDuringCooldown:
    """Once triggered, breach history is suppressed until cooldown ends."""

    def test_cooldown_state_blocks_re_evaluation(self) -> None:
        cap = LufsPanicCap()
        # Manually drive into cooldown.
        with cap._state_lock:
            cap._state = "cooldown"
        # Even sustained loud windows should not return True.
        for _ in range(20):
            assert cap.evaluate_window(-1.0) is False

    def test_idle_state_evaluates_normally(self) -> None:
        cap = LufsPanicCap()
        assert cap.state == "idle"
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is False
        assert cap.evaluate_window(-3.0) is True


class TestMetricsCallback:
    """LUFS-S gauge fires on every evaluation; trigger counter on duck."""

    def test_gauge_fires_per_window(self) -> None:
        emitted: list[tuple[str, float]] = []
        cap = LufsPanicCap(metrics_callback=lambda k, v: emitted.append((k, v)))
        cap.evaluate_window(-15.0)
        cap.evaluate_window(-12.0)
        names = [name for name, _ in emitted]
        assert names == [
            "hapax_broadcast_master_lufs_short_term",
            "hapax_broadcast_master_lufs_short_term",
        ]
        values = [v for _, v in emitted]
        assert values == [-15.0, -12.0]

    def test_metrics_callback_failure_does_not_kill_evaluation(self) -> None:
        def bad(k: str, v: float) -> None:
            raise RuntimeError("metrics down")

        cap = LufsPanicCap(metrics_callback=bad)
        # evaluate_window must not raise even if the metrics callback explodes.
        assert cap.evaluate_window(-15.0) is False


class TestPublishAwareness:
    """Awareness state surface — graceful-skip when path absent."""

    def test_skips_when_parent_dir_missing(self, tmp_path: Path) -> None:
        cap = LufsPanicCap()
        # Point AWARENESS_STATE_PATH at a non-existent dir.
        with patch(
            "agents.studio_compositor.lufs_panic_cap.AWARENESS_STATE_PATH",
            tmp_path / "nonexistent" / "state.json",
        ):
            # Must not raise.
            cap._publish_awareness(active=True, peak_lufs_s=-3.0)

    def test_writes_state_when_parent_exists(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        cap = LufsPanicCap()
        with patch(
            "agents.studio_compositor.lufs_panic_cap.AWARENESS_STATE_PATH",
            state_path,
        ):
            cap._publish_awareness(active=True, peak_lufs_s=-3.5)

        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert "lufs_panic_cap" in data
        assert data["lufs_panic_cap"]["active"] is True
        assert data["lufs_panic_cap"]["peak_lufs_s"] == -3.5
        assert data["lufs_panic_cap"]["triggered_at"] is not None
        # Total envelope = attack + hold + release.
        assert data["lufs_panic_cap"]["duck_envelope_seconds"] == 4.2

    def test_preserves_existing_state_keys(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"some_other_key": "preserved"}))

        cap = LufsPanicCap()
        with patch(
            "agents.studio_compositor.lufs_panic_cap.AWARENESS_STATE_PATH",
            state_path,
        ):
            cap._publish_awareness(active=False, peak_lufs_s=-2.0)

        data = json.loads(state_path.read_text())
        assert data["some_other_key"] == "preserved"
        assert data["lufs_panic_cap"]["active"] is False
        # When inactive, triggered_at is None.
        assert data["lufs_panic_cap"]["triggered_at"] is None


class TestPublishRefusalLog:
    def test_skips_when_parent_dir_missing(self, tmp_path: Path) -> None:
        cap = LufsPanicCap()
        with patch(
            "agents.studio_compositor.lufs_panic_cap.REFUSAL_LOG_PATH",
            tmp_path / "missing" / "log.jsonl",
        ):
            cap._publish_refusal_log(peak_lufs_s=-3.0)

    def test_appends_jsonl_entry(self, tmp_path: Path) -> None:
        log_path = tmp_path / "log.jsonl"
        cap = LufsPanicCap()
        with patch(
            "agents.studio_compositor.lufs_panic_cap.REFUSAL_LOG_PATH",
            log_path,
        ):
            cap._publish_refusal_log(peak_lufs_s=-3.2)
            cap._publish_refusal_log(peak_lufs_s=-2.8)
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["axiom"] == "broadcast_no_loopback"
        assert first["surface"] == "studio-compositor:lufs-panic-cap"
        assert "-3.20 LUFS-S" in first["reason"]


class TestRampVolume:
    """Smooth-envelope sine ramp must emit monotonic intermediate volumes."""

    def test_ramp_emits_smooth_values(self) -> None:
        cap = LufsPanicCap()
        emitted: list[float] = []
        with patch.object(cap, "_set_sink_volume", side_effect=emitted.append):
            cap._ramp_volume(
                start_linear=1.0,
                end_linear=0.01,
                duration_ms=10,  # short, but >0 so we get steps
                steps=8,
            )
        # First emission should still be near start (sine-ease starts slow).
        # Final emission should be exactly end.
        assert emitted[-1] == pytest.approx(0.01)
        # Monotonic decrease (start > end).
        for a, b in zip(emitted[:-1], emitted[1:], strict=True):
            assert b <= a

    def test_zero_duration_jumps_to_end(self) -> None:
        cap = LufsPanicCap()
        emitted: list[float] = []
        with patch.object(cap, "_set_sink_volume", side_effect=emitted.append):
            cap._ramp_volume(
                start_linear=1.0,
                end_linear=0.5,
                duration_ms=0,
                steps=8,
            )
        assert emitted == [0.5]


class TestWpctlVolumeControl:
    @patch("subprocess.run")
    def test_read_volume_resolves_node_name_before_wpctl(self, mock_run: MagicMock) -> None:
        pw_dump = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": 80,
                        "type": "PipeWire:Interface:Node",
                        "info": {"props": {"node.name": "hapax-broadcast-master"}},
                    }
                ]
            ),
            stderr="",
        )
        get_volume = MagicMock(returncode=0, stdout="Volume: 0.82\n", stderr="")
        mock_run.side_effect = [pw_dump, get_volume]

        cap = LufsPanicCap(sink_name="hapax-broadcast-master")

        assert cap._read_sink_volume() == pytest.approx(0.82)
        assert mock_run.call_args_list[1].args[0] == ["wpctl", "get-volume", "80"]

    @patch("subprocess.run")
    def test_set_volume_resolves_node_name_before_wpctl(self, mock_run: MagicMock) -> None:
        pw_dump = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": 80,
                        "type": "PipeWire:Interface:Node",
                        "info": {"props": {"node.name": "hapax-broadcast-master"}},
                    }
                ]
            ),
            stderr="",
        )
        set_volume = MagicMock(returncode=0, stdout="", stderr="")
        mock_run.side_effect = [pw_dump, set_volume]

        cap = LufsPanicCap(sink_name="hapax-broadcast-master")
        cap._set_sink_volume(0.5)

        assert mock_run.call_args_list[1].args[0] == ["wpctl", "set-volume", "80", "0.5000"]

    @patch("subprocess.run")
    def test_set_volume_refreshes_stale_cached_node_id(self, mock_run: MagicMock) -> None:
        stale_failure = MagicMock(returncode=1, stdout="", stderr="not found")
        pw_dump = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": 81,
                        "type": "PipeWire:Interface:Node",
                        "info": {"props": {"node.name": "hapax-broadcast-master"}},
                    }
                ]
            ),
            stderr="",
        )
        retry_success = MagicMock(returncode=0, stdout="", stderr="")
        mock_run.side_effect = [stale_failure, pw_dump, retry_success]

        cap = LufsPanicCap(sink_name="hapax-broadcast-master")
        cap._wpctl_target_id = "80"
        cap._set_sink_volume(0.25)

        assert mock_run.call_args_list[0].args[0] == ["wpctl", "set-volume", "80", "0.2500"]
        assert mock_run.call_args_list[2].args[0] == ["wpctl", "set-volume", "81", "0.2500"]

    @patch("agents.studio_compositor.lufs_panic_cap._resolve_wpctl_node_id")
    @patch("subprocess.run")
    def test_read_volume_returns_fallback_when_target_cannot_resolve(
        self,
        mock_run: MagicMock,
        mock_resolve: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_resolve.return_value = None
        cap = LufsPanicCap(sink_name="hapax-broadcast-master")

        with caplog.at_level("WARNING", logger="agents.studio_compositor.lufs_panic_cap"):
            assert cap._read_sink_volume() == pytest.approx(1.0)

        mock_run.assert_not_called()
        assert "Could not resolve PipeWire node" in caplog.text
        assert "Next action:" in caplog.text

    @patch("agents.studio_compositor.lufs_panic_cap._resolve_wpctl_node_id")
    @patch("subprocess.run")
    def test_read_volume_refreshes_stale_cached_node_id(
        self,
        mock_run: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        stale_failure = MagicMock(returncode=1, stdout="", stderr="not found")
        retry_success = MagicMock(returncode=0, stdout="Volume: 0.75\n", stderr="")
        mock_run.side_effect = [stale_failure, retry_success]
        mock_resolve.return_value = "81"

        cap = LufsPanicCap(sink_name="hapax-broadcast-master")
        cap._wpctl_target_id = "80"

        assert cap._read_sink_volume() == pytest.approx(0.75)
        assert mock_run.call_args_list[0].args[0] == ["wpctl", "get-volume", "80"]
        assert mock_run.call_args_list[1].args[0] == ["wpctl", "get-volume", "81"]

    @patch("subprocess.run")
    def test_wpctl_exception_logs_next_action(
        self,
        mock_run: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_run.side_effect = OSError("wpctl unavailable")
        cap = LufsPanicCap(sink_name="hapax-broadcast-master")
        cap._wpctl_target_id = "80"

        with caplog.at_level("WARNING", logger="agents.studio_compositor.lufs_panic_cap"):
            cap._set_sink_volume(0.25)

        assert "wpctl set-volume failed" in caplog.text
        assert "Next action:" in caplog.text
        assert "wpctl get-volume <node-id>" in caplog.text

    @patch("agents.studio_compositor.lufs_panic_cap._resolve_wpctl_node_id")
    @patch("subprocess.run")
    def test_set_volume_warns_when_retry_exhausted(
        self,
        mock_run: MagicMock,
        mock_resolve: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        stale_failure = MagicMock(returncode=1, stdout="", stderr="old id missing")
        retry_failure = MagicMock(returncode=1, stdout="", stderr="new id missing")
        mock_run.side_effect = [stale_failure, retry_failure]
        mock_resolve.return_value = "81"

        cap = LufsPanicCap(sink_name="hapax-broadcast-master")
        cap._wpctl_target_id = "80"

        with caplog.at_level("WARNING", logger="agents.studio_compositor.lufs_panic_cap"):
            cap._set_sink_volume(0.25)

        assert mock_run.call_args_list[0].args[0] == ["wpctl", "set-volume", "80", "0.2500"]
        assert mock_run.call_args_list[1].args[0] == ["wpctl", "set-volume", "81", "0.2500"]
        assert "wpctl set-volume failed" in caplog.text
        assert "target_id=81" in caplog.text
        assert "Next action:" in caplog.text


class TestNotifyCallback:
    def test_notify_fires_on_trigger(self) -> None:
        notifier = MagicMock()
        cap = LufsPanicCap(notify_callback=notifier)
        # Bypass duck-thread spawn (don't actually run the envelope).
        with patch.object(cap, "_run_duck_envelope"):
            cap._trigger_duck(peak_lufs_s=-3.0)
        # Wait briefly for the spawned thread (which is now no-op).
        time.sleep(0.01)
        notifier.assert_called_once()
        priority, message = notifier.call_args.args
        assert priority == "high"
        assert "LUFS panic-cap" in message
        assert "-3.0" in message

    def test_notify_failure_does_not_block_trigger(self) -> None:
        notifier = MagicMock(side_effect=RuntimeError("ntfy down"))
        cap = LufsPanicCap(notify_callback=notifier)
        with patch.object(cap, "_run_duck_envelope"):
            cap._trigger_duck(peak_lufs_s=-3.0)
        # Trigger count still incremented despite notify failure.
        assert cap.triggers_total == 1


class TestStateAccessors:
    def test_initial_state_is_idle(self) -> None:
        cap = LufsPanicCap()
        assert cap.state == "idle"
        assert cap.triggers_total == 0
        assert cap.last_peak_lufs_s == float("-inf")

    def test_default_breach_window_is_300ms(self) -> None:
        cap = LufsPanicCap()
        assert cap._breach_window_ms == DEFAULT_BREACH_WINDOW_MS
        assert cap._breach_count_required == 3
