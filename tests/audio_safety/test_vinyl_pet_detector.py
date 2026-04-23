"""Unit tests for vinyl-into-Evil-Pet detector.

Pure functions + the process_frame state-machine step. No live PipeWire
or subprocess; mock the notifier and use synthetic int16 PCM frames.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import numpy as np
import pytest

from agents.audio_safety.vinyl_pet_detector import (
    DetectorConfig,
    DetectorState,
    channel_rms,
    fire_alert,
    is_simultaneous_activity,
    process_frame,
    should_fire,
)


def _interleaved_frame(
    channel_signals: dict[int, float], n_samples: int = 4800, channels: int = 14
) -> bytes:
    """Build an interleaved int16 PCM frame.

    `channel_signals` maps channel index → constant amplitude in [0, 1].
    All other channels are silent.
    """
    arr = np.zeros((n_samples, channels), dtype=np.float32)
    for ch, amp in channel_signals.items():
        # Constant DC signal at the requested amplitude is sufficient for RMS testing
        arr[:, ch] = amp
    int16 = (arr * 32767.0).astype(np.int16)
    return int16.tobytes()


# ── channel_rms ─────────────────────────────────────────────────────────────


def test_channel_rms_silence_is_zero() -> None:
    frame = _interleaved_frame({}, n_samples=480, channels=14)
    assert channel_rms(frame, 14, 5) == 0.0


def test_channel_rms_extracts_correct_channel() -> None:
    # AUX5 hot, AUX8 silent
    frame = _interleaved_frame({5: 0.5}, n_samples=480, channels=14)
    assert channel_rms(frame, 14, 5) == pytest.approx(0.5, abs=1e-3)
    assert channel_rms(frame, 14, 8) == 0.0


def test_channel_rms_handles_empty_frame() -> None:
    assert channel_rms(b"", 14, 5) == 0.0


def test_channel_rms_handles_incomplete_frame() -> None:
    # 13 int16 samples — not divisible by 14 channels
    bad = (np.zeros(13, dtype=np.int16)).tobytes()
    assert channel_rms(bad, 14, 5) == 0.0


def test_channel_rms_out_of_range_channel_returns_zero() -> None:
    frame = _interleaved_frame({5: 0.5}, n_samples=480, channels=14)
    assert channel_rms(frame, 14, 99) == 0.0


# ── is_simultaneous_activity ────────────────────────────────────────────────


def test_simultaneous_activity_both_above_threshold() -> None:
    assert is_simultaneous_activity(0.05, 0.10, threshold=0.02) is True


def test_simultaneous_activity_one_below_threshold() -> None:
    assert is_simultaneous_activity(0.01, 0.10, threshold=0.02) is False
    assert is_simultaneous_activity(0.10, 0.01, threshold=0.02) is False


def test_simultaneous_activity_both_below_threshold() -> None:
    assert is_simultaneous_activity(0.001, 0.001, threshold=0.02) is False


# ── should_fire ─────────────────────────────────────────────────────────────


def test_should_fire_window_not_full() -> None:
    win: deque[bool] = deque([True, True], maxlen=20)
    assert should_fire(win, dwell_frames=20) is False


def test_should_fire_window_full_all_true() -> None:
    win: deque[bool] = deque([True] * 20, maxlen=20)
    assert should_fire(win, dwell_frames=20) is True


def test_should_fire_window_full_with_one_false() -> None:
    win: deque[bool] = deque([True] * 19 + [False], maxlen=20)
    assert should_fire(win, dwell_frames=20) is False


# ── DetectorConfig ───────────────────────────────────────────────────────────


def test_detector_config_dwell_frames_rounds_correctly() -> None:
    cfg = DetectorConfig(dwell_s=2.0, frame_ms=100)
    assert cfg.dwell_frames == 20  # 2.0s / 100ms = 20 frames


def test_detector_config_frame_bytes_int16_14ch() -> None:
    cfg = DetectorConfig(rate=48000, channels=14, frame_ms=100)
    # 100ms at 48kHz = 4800 samples; 14ch × 2 bytes = 28 → 4800 × 28 = 134400
    assert cfg.frame_bytes == 134_400


def test_detector_config_dwell_frames_minimum_one() -> None:
    cfg = DetectorConfig(dwell_s=0.0, frame_ms=100)
    assert cfg.dwell_frames == 1


# ── process_frame ────────────────────────────────────────────────────────────


def _config_for_test(impingements_path: Path) -> DetectorConfig:
    return DetectorConfig(
        rate=48000,
        channels=14,
        frame_ms=100,
        rms_threshold=0.05,
        dwell_s=0.3,  # 3 frames at 100ms each
        cooldown_s=10.0,
        aux_evilpet=5,
        aux_vinyl_l=8,
        aux_vinyl_r=9,
        impingements_file=impingements_path,
    )


def test_process_frame_silent_does_not_fire(tmp_path: Path) -> None:
    cfg = _config_for_test(tmp_path / "imp.jsonl")
    state = DetectorState.fresh(cfg.dwell_frames)
    frame = _interleaved_frame({}, n_samples=4800)
    fired, vl, vr, ep = process_frame(frame=frame, config=cfg, state=state, now=0.0)
    assert fired is False
    assert vl == 0.0 and vr == 0.0 and ep == 0.0


def test_process_frame_only_vinyl_does_not_fire(tmp_path: Path) -> None:
    cfg = _config_for_test(tmp_path / "imp.jsonl")
    state = DetectorState.fresh(cfg.dwell_frames)
    frame = _interleaved_frame({8: 0.3, 9: 0.3}, n_samples=4800)
    for tick in range(10):
        fired, _, _, _ = process_frame(frame=frame, config=cfg, state=state, now=float(tick))
        assert fired is False


def test_process_frame_only_evilpet_does_not_fire(tmp_path: Path) -> None:
    cfg = _config_for_test(tmp_path / "imp.jsonl")
    state = DetectorState.fresh(cfg.dwell_frames)
    frame = _interleaved_frame({5: 0.3}, n_samples=4800)
    for tick in range(10):
        fired, _, _, _ = process_frame(frame=frame, config=cfg, state=state, now=float(tick))
        assert fired is False


def test_process_frame_simultaneous_after_dwell_fires(tmp_path: Path) -> None:
    cfg = _config_for_test(tmp_path / "imp.jsonl")
    state = DetectorState.fresh(cfg.dwell_frames)
    frame = _interleaved_frame({5: 0.3, 8: 0.3, 9: 0.3}, n_samples=4800)
    fires = []
    for tick in range(5):
        fired, *_ = process_frame(frame=frame, config=cfg, state=state, now=float(tick))
        fires.append(fired)
    # First fire happens once the window is full (3 frames of dwell).
    # Frames 0,1: window not full → no fire
    # Frame 2: window full + all True → fire
    assert fires[:3] == [False, False, True]


def test_process_frame_cooldown_suppresses_repeat(tmp_path: Path) -> None:
    cfg = _config_for_test(tmp_path / "imp.jsonl")
    state = DetectorState.fresh(cfg.dwell_frames)
    frame = _interleaved_frame({5: 0.3, 8: 0.3, 9: 0.3}, n_samples=4800)
    # First firing
    for tick in range(3):
        process_frame(frame=frame, config=cfg, state=state, now=float(tick))
    # Continue feeding hot frames; should NOT fire again within cooldown.
    # First fire happened at tick=2; cooldown is 10s, so ticks 3..11 are
    # within the cooldown window (max elapsed = 9s < 10s).
    for tick in range(3, 12):
        fired, *_ = process_frame(frame=frame, config=cfg, state=state, now=float(tick))
        assert fired is False, f"unexpected fire at tick {tick} (within cooldown)"


# ── fire_alert ──────────────────────────────────────────────────────────────


def test_fire_alert_writes_impingement_and_calls_notifier(tmp_path: Path) -> None:
    impingements = tmp_path / "imp.jsonl"
    cfg = _config_for_test(impingements)
    calls = []

    def fake_notifier(title, message, **kwargs):
        calls.append((title, message, kwargs))
        return True

    fire_alert(
        config=cfg,
        vinyl_l_rms=0.3,
        vinyl_r_rms=0.31,
        evilpet_rms=0.4,
        notifier=fake_notifier,
    )
    assert len(calls) == 1
    title, message, kwargs = calls[0]
    assert "vinyl" in title.lower()
    assert "0.300" in message
    assert kwargs["priority"] == "high"

    payload = json.loads(impingements.read_text(encoding="utf-8").strip())
    assert payload["source"] == "audio.safety.vinyl_pet"
    assert payload["content"]["vinyl_l_rms"] == 0.3
    assert payload["content"]["evilpet_rms"] == 0.4


def test_fire_alert_notifier_failure_does_not_break_impingement_write(tmp_path: Path) -> None:
    impingements = tmp_path / "imp.jsonl"
    cfg = _config_for_test(impingements)

    def boom(*args, **kwargs):
        raise RuntimeError("ntfy down")

    # Must not raise
    fire_alert(
        config=cfg,
        vinyl_l_rms=0.3,
        vinyl_r_rms=0.31,
        evilpet_rms=0.4,
        notifier=boom,
    )
    # Impingement still landed
    assert impingements.exists()
    payload = json.loads(impingements.read_text(encoding="utf-8").strip())
    assert payload["source"] == "audio.safety.vinyl_pet"
