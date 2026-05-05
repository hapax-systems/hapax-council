"""Tests for the H5 Phase 2 A/B recorder."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import numpy as np
import pytest

from agents.audio_ab_recorder import (
    CaptureResult,
    DriftDetector,
    RecorderConfig,
    build_pair_record,
    measure_samples,
    run_once,
)
from agents.audio_ab_recorder import (
    recorder as recorder_mod,
)
from agents.audio_ab_recorder.recorder import AudioMetrics


def _metrics(lufs: float) -> AudioMetrics:
    return AudioMetrics(
        lufs_i=lufs,
        rms_dbfs=lufs - 3.0,
        peak_dbfs=lufs + 6.0,
        crest_factor=6.0,
        zero_crossing_rate=0.1,
        sample_count=4800,
    )


def _result(path: str, device: str, lufs: float) -> CaptureResult:
    return CaptureResult(
        path=path,
        device=device,
        captured_at=1_800_000_000.0,
        duration_s=0.2,
        metrics=_metrics(lufs),
    )


def test_measure_samples_reports_lufs_rms_and_crest() -> None:
    sample_rate = 48_000
    t = np.arange(int(sample_rate * 0.2)) / sample_rate
    stereo = np.column_stack(
        [
            0.2 * np.sin(2 * np.pi * 440 * t),
            0.2 * np.sin(2 * np.pi * 660 * t),
        ]
    )

    metrics = measure_samples(stereo, sample_rate=sample_rate)

    assert -60.0 < metrics.lufs_i < 0.0
    assert -60.0 < metrics.rms_dbfs < 0.0
    assert metrics.peak_dbfs < 0.0
    assert metrics.crest_factor > 1.0
    assert metrics.sample_count == stereo.shape[0]


def test_measure_samples_handles_silence() -> None:
    metrics = measure_samples(np.zeros((0, 2), dtype=np.float64))

    assert metrics.lufs_i == -120.0
    assert metrics.rms_dbfs == -120.0
    assert metrics.crest_factor == 0.0
    assert metrics.sample_count == 0


def test_build_pair_record_computes_software_minus_l12_delta() -> None:
    record = build_pair_record(
        _result("software", "hapax-broadcast-normalized.monitor", -14.0),
        _result("l12-mainmix", "hapax-obs-broadcast-mainmix-tap.monitor", -15.25),
        now=1_800_000_010.0,
    )

    assert record["delta_lufs_i"] == pytest.approx(1.25)
    assert record["abs_delta_lufs_i"] == pytest.approx(1.25)
    assert record["rtmp_egress_unchanged"] is True
    assert record["software"]["device"] == "hapax-broadcast-normalized.monitor"
    assert record["l12_mainmix"]["device"] == "hapax-obs-broadcast-mainmix-tap.monitor"


def test_drift_detector_requires_sustained_delta() -> None:
    detector = DriftDetector(threshold_db=1.0, sustain_s=30.0, cooldown_s=300.0)

    assert detector.observe(1.2, now=100.0) is False
    assert detector.observe(1.2, now=129.9) is False
    assert detector.observe(1.2, now=130.1) is True
    assert detector.observe(1.2, now=131.0) is False
    assert detector.observe(0.2, now=132.0) is False
    assert detector.observe(1.2, now=170.0) is False


def test_run_once_writes_jsonl_and_textfile_metrics(tmp_path: Path) -> None:
    config = RecorderConfig(
        state_root=tmp_path / "state",
        software_device="software.monitor",
        l12_device="l12.monitor",
        textfile_collector_dir=tmp_path / "collector",
        enable_ntfy=False,
    )

    def fake_capture(path: str, device: str, _config: RecorderConfig) -> CaptureResult:
        return _result(path, device, -14.0 if path == "software" else -14.4)

    record = run_once(config, capture_fn=fake_capture)

    jsonl = config.today_jsonl_path
    assert jsonl.exists()
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["delta_lufs_i"] == pytest.approx(record["delta_lufs_i"])

    prom = tmp_path / "collector" / "hapax_audio_ab.prom"
    text = prom.read_text(encoding="utf-8")
    assert 'hapax_audio_ab_lufs_i{path="software",source="software.monitor"} -14' in text
    assert 'hapax_audio_ab_lufs_i{path="l12-mainmix",source="l12.monitor"} -14.4' in text
    assert 'hapax_audio_ab_delta_lufs{pair="software_minus_l12"}' in text


def test_sd_notify_writes_to_notify_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    notify_path = tmp_path / "notify.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.bind(str(notify_path))
        sock.settimeout(1.0)
        monkeypatch.setenv("NOTIFY_SOCKET", str(notify_path))

        recorder_mod._sd_notify("READY=1")

        payload = sock.recv(128)
    finally:
        sock.close()

    assert payload == b"READY=1"
