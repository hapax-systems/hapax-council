"""Tests for the L-12 BROADCAST wet-return detector (audit A#6).

Synthetic AUX8/9-cold-during-music input → assert event fires within
``min_silence_s``. Covers:

  * pure DSP RMS-in-dBFS calculation on interleaved int16 PCM
  * silence-window state machine (accumulate, fire-once, re-arm,
    music-not-running clears)
  * pactl music-sink-RUNNING parser
  * end-to-end ``probe_l12_broadcast_scene`` with fake pw-cat + pactl
    runners, fake notifier, all paths under tmp_path
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from agents.broadcast_audio_health.l12_broadcast_scene_probe import (
    EVENT_NAME,
    RUNBOOK_ANCHOR,
    L12SceneProbeConfig,
    L12SceneProbeState,
    _parse_sink_running,
    channel_rms_dbfs,
    evaluate_tick,
    fire_ntfy_alert,
    is_music_sink_running,
    load_scene_check_rotation_state,
    load_state,
    probe_l12_broadcast_scene,
    run_l12_scene_check_rotation,
    save_state,
    write_impingement,
)
from shared.audio_topology import TopologyDescriptor
from shared.audio_topology_inspector import SceneAssertion

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_YAML = REPO_ROOT / "config" / "audio-topology.yaml"

# ── DSP layer ────────────────────────────────────────────────────────────────


class TestChannelRmsDbfs:
    def test_silence_returns_minus_infinity(self) -> None:
        # 14-channel int16, 100 samples, all zero
        pcm = np.zeros(14 * 100, dtype=np.int16).tobytes()
        dbfs = channel_rms_dbfs(pcm, channels=14, channel_index=4)
        assert dbfs == float("-inf")

    def test_full_scale_sine_returns_around_minus_3_dbfs(self) -> None:
        # Construct a 14-channel buffer where AUX8 carries a
        # near-full-scale 1 kHz sine; other channels are silent.
        sample_count = 4800
        t = np.arange(sample_count) / 48000.0
        sine = (np.sin(2 * np.pi * 1000.0 * t) * 30000).astype(np.int16)
        buffer = np.zeros((sample_count, 14), dtype=np.int16)
        buffer[:, 8] = sine
        pcm = buffer.tobytes()
        dbfs = channel_rms_dbfs(pcm, channels=14, channel_index=8)
        # RMS of full-scale sine ≈ 0.707 → 20*log10(0.707 * 30000/32768) ≈ -3.3 dBFS
        assert -4.0 < dbfs < -2.5

    def test_aux8_index_isolation(self) -> None:
        """A loud signal on channel 0 must not bleed into AUX8 reading."""
        sample_count = 4800
        buffer = np.zeros((sample_count, 14), dtype=np.int16)
        buffer[:, 0] = 30000  # loud DC on channel 0
        pcm = buffer.tobytes()
        dbfs = channel_rms_dbfs(pcm, channels=14, channel_index=8)
        assert dbfs == float("-inf")

    def test_short_buffer_truncates_to_whole_frames(self) -> None:
        # 14 channels × 1 sample short → still works, doesn't crash
        pcm = struct.pack("<14h", *([0] * 14))
        dbfs = channel_rms_dbfs(pcm, channels=14, channel_index=4)
        assert dbfs == float("-inf")

    def test_empty_buffer_returns_minus_infinity(self) -> None:
        assert channel_rms_dbfs(b"", channels=14, channel_index=4) == float("-inf")


# ── State machine ────────────────────────────────────────────────────────────


class TestEvaluateTick:
    def _config(self) -> L12SceneProbeConfig:
        return L12SceneProbeConfig(
            silence_threshold_dbfs=-60.0,
            min_silence_s=300.0,
        )

    def test_signal_present_resets_window(self) -> None:
        cfg = self._config()
        state = L12SceneProbeState(silent_since=100.0, alert_active=True)
        outcome = evaluate_tick(
            aux5_dbfs=-12.0,
            music_running=True,
            now=200.0,
            state=state,
            config=cfg,
        )
        assert outcome.fired is False
        assert outcome.silent_for_s == 0.0
        assert state.silent_since is None
        assert state.alert_active is False
        assert outcome.state_changed is True

    def test_music_not_running_clears_window(self) -> None:
        cfg = self._config()
        state = L12SceneProbeState(silent_since=100.0)
        outcome = evaluate_tick(
            aux5_dbfs=-90.0,  # silent
            music_running=False,
            now=500.0,
            state=state,
            config=cfg,
        )
        assert outcome.fired is False
        assert state.silent_since is None
        assert outcome.silent_for_s == 0.0

    def test_first_silent_tick_stamps_silence_since(self) -> None:
        cfg = self._config()
        state = L12SceneProbeState()
        outcome = evaluate_tick(
            aux5_dbfs=-90.0,
            music_running=True,
            now=1000.0,
            state=state,
            config=cfg,
        )
        assert outcome.fired is False
        assert state.silent_since == 1000.0
        assert outcome.silent_for_s == 0.0

    def test_silence_below_threshold_does_not_fire(self) -> None:
        cfg = self._config()
        state = L12SceneProbeState(silent_since=1000.0)
        outcome = evaluate_tick(
            aux5_dbfs=-90.0,
            music_running=True,
            now=1100.0,  # only 100s elapsed, threshold 300s
            state=state,
            config=cfg,
        )
        assert outcome.fired is False
        assert outcome.silent_for_s == 100.0

    def test_silence_above_threshold_fires_once(self) -> None:
        cfg = self._config()
        state = L12SceneProbeState(silent_since=1000.0)
        # 5+ minutes (>= 300s) of silence
        outcome = evaluate_tick(
            aux5_dbfs=-90.0,
            music_running=True,
            now=1305.0,
            state=state,
            config=cfg,
        )
        assert outcome.fired is True
        assert state.alert_active is True
        assert state.last_alert_at == 1305.0

        # Next tick must NOT fire again (alert already active)
        outcome2 = evaluate_tick(
            aux5_dbfs=-90.0,
            music_running=True,
            now=1310.0,
            state=state,
            config=cfg,
        )
        assert outcome2.fired is False

    def test_re_arms_after_signal_returns_then_silence_repeats(self) -> None:
        cfg = self._config()
        state = L12SceneProbeState(silent_since=1000.0, alert_active=True, last_alert_at=1305.0)
        # Signal returns
        evaluate_tick(
            aux5_dbfs=-12.0,
            music_running=True,
            now=1500.0,
            state=state,
            config=cfg,
        )
        assert state.alert_active is False
        # Silence resumes; needs another full window
        evaluate_tick(
            aux5_dbfs=-90.0,
            music_running=True,
            now=1600.0,
            state=state,
            config=cfg,
        )
        assert state.silent_since == 1600.0
        # 5+ minutes later, fires again
        outcome = evaluate_tick(
            aux5_dbfs=-90.0,
            music_running=True,
            now=1905.0,
            state=state,
            config=cfg,
        )
        assert outcome.fired is True


# ── pactl parser ─────────────────────────────────────────────────────────────


class TestParseSinkRunning:
    def test_running_sink_returns_true(self) -> None:
        text = """\
Sink #50
        State: RUNNING
        Name: hapax-music-loudnorm
        Description: Music loudnorm chain
"""
        assert _parse_sink_running(text, "hapax-music-loudnorm") is True

    def test_idle_sink_returns_false(self) -> None:
        text = """\
Sink #50
        State: IDLE
        Name: hapax-music-loudnorm
"""
        assert _parse_sink_running(text, "hapax-music-loudnorm") is False

    def test_suspended_sink_returns_false(self) -> None:
        text = """\
Sink #50
        State: SUSPENDED
        Name: hapax-music-loudnorm
"""
        assert _parse_sink_running(text, "hapax-music-loudnorm") is False

    def test_other_sink_running_does_not_count(self) -> None:
        text = """\
Sink #50
        State: RUNNING
        Name: alsa_output.something_else
Sink #51
        State: IDLE
        Name: hapax-music-loudnorm
"""
        assert _parse_sink_running(text, "hapax-music-loudnorm") is False

    def test_absent_sink_returns_false(self) -> None:
        text = "Sink #50\n        State: RUNNING\n        Name: foo\n"
        assert _parse_sink_running(text, "hapax-music-loudnorm") is False

    def test_pactl_runner_failure_returns_false(self) -> None:
        def failing_runner() -> str:
            raise RuntimeError("pactl missing")

        assert is_music_sink_running("hapax-music-loudnorm", pactl_runner=failing_runner) is False


# ── State persistence ───────────────────────────────────────────────────────


class TestStatePersistence:
    def test_load_missing_state_returns_empty(self, tmp_path: Path) -> None:
        s = load_state(tmp_path / "absent.json")
        assert s.silent_since is None
        assert s.alert_active is False

    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        original = L12SceneProbeState(
            silent_since=1000.0,
            alert_active=True,
            last_alert_at=1305.0,
            last_content_return_dbfs=-90.0,
            last_music_running=True,
            last_checked_at=1310.0,
        )
        save_state(path, original)
        reloaded = load_state(path)
        assert reloaded.silent_since == 1000.0
        assert reloaded.alert_active is True
        assert reloaded.last_alert_at == 1305.0

    def test_corrupt_state_returns_fresh(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.json"
        path.write_text("{not valid json", encoding="utf-8")
        s = load_state(path)
        assert s.silent_since is None
        assert s.alert_active is False


# ── Side effects ────────────────────────────────────────────────────────────


class TestSideEffects:
    def test_write_impingement_appends_event_record(self, tmp_path: Path) -> None:
        path = tmp_path / "impingements.jsonl"
        cfg = L12SceneProbeConfig(impingements_file=path)
        write_impingement(path, content_return_dbfs=-90.0, silent_for_s=305.0, config=cfg)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["content"]["alert"] == EVENT_NAME
        assert record["content"]["content_return_dbfs"] == -90.0
        assert record["content"]["silent_for_s"] == 305.0

    def test_fire_ntfy_alert_dispatches_with_high_priority(self) -> None:
        captured: dict = {}

        def fake_notifier(title: str, message: str, **kwargs) -> None:
            captured["title"] = title
            captured["message"] = message
            captured.update(kwargs)

        cfg = L12SceneProbeConfig()
        fire_ntfy_alert(
            content_return_dbfs=-90.0,
            silent_for_s=305.0,
            config=cfg,
            notifier=fake_notifier,
        )
        assert "L-12 BROADCAST scene wet return silent" in captured["title"]
        assert "operator-only fix" in captured["message"]
        assert "BROADCAST-V2" in captured["message"]
        assert RUNBOOK_ANCHOR in captured["message"]
        assert captured.get("priority") == "high"

    def test_fire_ntfy_alert_swallows_notifier_exceptions(self) -> None:
        def raising_notifier(*args, **kwargs):
            raise RuntimeError("ntfy down")

        cfg = L12SceneProbeConfig()
        # Must not raise
        fire_ntfy_alert(
            content_return_dbfs=-90.0,
            silent_for_s=305.0,
            config=cfg,
            notifier=raising_notifier,
        )


class TestL12SceneCheckRotation:
    def test_rotation_alerts_only_on_transition_to_not_ok(self, tmp_path: Path) -> None:
        captured: list[tuple[str, str]] = []
        state_path = tmp_path / "scene-check-state.json"

        def fake_notifier(title: str, message: str, **kwargs) -> None:
            captured.append((title, message))

        def fail_checker(
            _descriptor: TopologyDescriptor,
            _duration_s: float,
        ) -> SceneAssertion:
            return SceneAssertion(
                ok=False,
                evidence={"content_return_peak_dbfs": "-inf"},
                violations=("AUX8 content return L peak -inf dBFS below -10.0 dBFS threshold",),
            )

        outcome1 = run_l12_scene_check_rotation(
            descriptor_path=CANONICAL_YAML,
            state_path=state_path,
            interval_s=0.0,
            duration_s=30.0,
            now=1000.0,
            music_running=True,
            checker=fail_checker,
            notifier=fake_notifier,
        )
        assert outcome1.ran is True
        assert outcome1.status == "not-ok"
        assert outcome1.alerted is True
        assert len(captured) == 1
        assert RUNBOOK_ANCHOR in captured[0][1]

        outcome2 = run_l12_scene_check_rotation(
            descriptor_path=CANONICAL_YAML,
            state_path=state_path,
            interval_s=0.0,
            duration_s=30.0,
            now=1300.0,
            music_running=True,
            checker=fail_checker,
            notifier=fake_notifier,
        )
        assert outcome2.ran is True
        assert outcome2.alerted is False
        assert len(captured) == 1

        def ok_checker(
            _descriptor: TopologyDescriptor,
            _duration_s: float,
        ) -> SceneAssertion:
            return SceneAssertion(ok=True, evidence={})

        run_l12_scene_check_rotation(
            descriptor_path=CANONICAL_YAML,
            state_path=state_path,
            interval_s=0.0,
            duration_s=30.0,
            now=1600.0,
            music_running=True,
            checker=ok_checker,
            notifier=fake_notifier,
        )
        outcome4 = run_l12_scene_check_rotation(
            descriptor_path=CANONICAL_YAML,
            state_path=state_path,
            interval_s=0.0,
            duration_s=30.0,
            now=1900.0,
            music_running=True,
            checker=fail_checker,
            notifier=fake_notifier,
        )
        assert outcome4.alerted is True
        assert len(captured) == 2

    def test_rotation_skips_when_music_is_not_running(self, tmp_path: Path) -> None:
        calls = 0

        def checker(
            _descriptor: TopologyDescriptor,
            _duration_s: float,
        ) -> SceneAssertion:
            nonlocal calls
            calls += 1
            return SceneAssertion(ok=False, evidence={})

        state_path = tmp_path / "scene-check-state.json"
        outcome = run_l12_scene_check_rotation(
            descriptor_path=CANONICAL_YAML,
            state_path=state_path,
            interval_s=0.0,
            duration_s=30.0,
            now=1000.0,
            music_running=False,
            checker=checker,
        )

        assert outcome.ran is False
        assert outcome.status == "skipped_music_not_running"
        assert calls == 0
        state = load_scene_check_rotation_state(state_path)
        assert state.last_status == "skipped_music_not_running"


# ── End-to-end probe ────────────────────────────────────────────────────────


def _make_silent_pcm(channels: int = 14, samples: int = 4800) -> bytes:
    return np.zeros(channels * samples, dtype=np.int16).tobytes()


def _make_loud_content_return_pcm(channels: int = 14, samples: int = 4800) -> bytes:
    buffer = np.zeros((samples, channels), dtype=np.int16)
    t = np.arange(samples) / 48000.0
    sine = (np.sin(2 * np.pi * 1000.0 * t) * 25000).astype(np.int16)
    buffer[:, 8] = sine
    buffer[:, 9] = sine
    return buffer.tobytes()


class TestProbeL12BroadcastScene:
    """End-to-end synthetic flow: content return silent + music RUNNING → fires."""

    def _config(self, tmp_path: Path) -> L12SceneProbeConfig:
        return L12SceneProbeConfig(
            min_silence_s=300.0,  # 5 minutes
            sample_window_s=0.001,  # tests do not actually sleep
            state_path=tmp_path / "state.json",
            impingements_file=tmp_path / "impingements.jsonl",
        )

    def test_signal_returns_no_fire(self, tmp_path: Path) -> None:
        cfg = self._config(tmp_path)
        captured = []

        def runner(_cfg):
            return _make_loud_content_return_pcm()

        outcome = probe_l12_broadcast_scene(
            config=cfg,
            now=1000.0,
            pw_cat_runner=runner,
            pactl_runner=lambda: (
                "Sink #1\n        State: RUNNING\n        Name: hapax-music-loudnorm\n"
            ),
            notifier=lambda *args, **kwargs: captured.append((args, kwargs)),
        )
        assert outcome.fired is False
        assert outcome.content_return_dbfs > -10.0
        assert outcome.music_running is True
        assert captured == []

    def test_silent_content_return_during_music_fires_within_min_silence(
        self, tmp_path: Path
    ) -> None:
        cfg = self._config(tmp_path)
        captured = []

        def silent_runner(_cfg):
            return _make_silent_pcm()

        running_pactl = "Sink #1\n        State: RUNNING\n        Name: hapax-music-loudnorm\n"

        # Tick 1 at t=1000: starts the silence window
        outcome1 = probe_l12_broadcast_scene(
            config=cfg,
            now=1000.0,
            pw_cat_runner=silent_runner,
            pactl_runner=lambda: running_pactl,
            notifier=lambda *args, **kwargs: captured.append((args, kwargs)),
        )
        assert outcome1.fired is False
        assert outcome1.silent_for_s == 0.0
        assert captured == []

        # Tick 2 at t=1100: 100s silence — still under 5min threshold
        outcome2 = probe_l12_broadcast_scene(
            config=cfg,
            now=1100.0,
            pw_cat_runner=silent_runner,
            pactl_runner=lambda: running_pactl,
            notifier=lambda *args, **kwargs: captured.append((args, kwargs)),
        )
        assert outcome2.fired is False
        assert outcome2.silent_for_s == pytest.approx(100.0)

        # Tick 3 at t=1305: 305s silence — fires
        outcome3 = probe_l12_broadcast_scene(
            config=cfg,
            now=1305.0,
            pw_cat_runner=silent_runner,
            pactl_runner=lambda: running_pactl,
            notifier=lambda *args, **kwargs: captured.append((args, kwargs)),
        )
        assert outcome3.fired is True, (
            f"silent_for_s={outcome3.silent_for_s} should have triggered alert"
        )
        assert outcome3.silent_for_s == pytest.approx(305.0)
        assert len(captured) == 1
        title = captured[0][0][0]
        assert "BROADCAST scene wet return silent" in title

        # Impingement was written
        impingements = (tmp_path / "impingements.jsonl").read_text(encoding="utf-8")
        assert EVENT_NAME in impingements

        # State is persisted with alert_active
        state_payload = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert state_payload["alert_active"] is True
        assert state_payload["last_alert_at"] == 1305.0

    def test_music_not_running_does_not_fire_even_with_silent_content_return(
        self, tmp_path: Path
    ) -> None:
        cfg = self._config(tmp_path)
        captured = []
        outcome = probe_l12_broadcast_scene(
            config=cfg,
            now=1305.0,
            pw_cat_runner=lambda _cfg: _make_silent_pcm(),
            pactl_runner=lambda: (
                "Sink #1\n        State: IDLE\n        Name: hapax-music-loudnorm\n"
            ),
            notifier=lambda *args, **kwargs: captured.append((args, kwargs)),
        )
        assert outcome.fired is False
        assert outcome.music_running is False
        assert captured == []

    def test_pw_cat_failure_treated_as_silent(self, tmp_path: Path) -> None:
        """Audit-A#6: an absent L-12 source IS the unloaded condition.

        If pw-cat fails, the operator effectively can't be on BROADCAST,
        so the probe treats the failure as silence (operationally
        identical). This prevents false-OK readings from a failed
        capture path.
        """
        cfg = self._config(tmp_path)

        def failing_runner(_cfg):
            raise RuntimeError("pw-cat missing")

        outcome = probe_l12_broadcast_scene(
            config=cfg,
            now=1000.0,
            pw_cat_runner=failing_runner,
            pactl_runner=lambda: (
                "Sink #1\n        State: RUNNING\n        Name: hapax-music-loudnorm\n"
            ),
        )
        assert outcome.content_return_dbfs == float("-inf")
        # First tick — accumulates but doesn't fire yet
        assert outcome.fired is False

    def test_state_persists_between_probe_calls(self, tmp_path: Path) -> None:
        """Multiple probe calls accumulate silence via persisted state."""
        cfg = self._config(tmp_path)
        running_pactl = "Sink #1\n        State: RUNNING\n        Name: hapax-music-loudnorm\n"

        # Tick 1: stamp silence_since
        probe_l12_broadcast_scene(
            config=cfg,
            now=2000.0,
            pw_cat_runner=lambda _c: _make_silent_pcm(),
            pactl_runner=lambda: running_pactl,
        )
        state_after_1 = load_state(cfg.state_path)
        assert state_after_1.silent_since == 2000.0

        # Tick 2: state is loaded, elapsed is computed
        outcome = probe_l12_broadcast_scene(
            config=cfg,
            now=2150.0,
            pw_cat_runner=lambda _c: _make_silent_pcm(),
            pactl_runner=lambda: running_pactl,
        )
        assert outcome.silent_for_s == pytest.approx(150.0)
        assert outcome.fired is False
