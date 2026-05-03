"""Daemon-level tests: tick orchestration, snapshot, metrics, gating.

These tests stub out parecord (no real audio capture) and
notification side-effects, then exercise the daemon's pure logic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.audio_signal_assertion import daemon
from agents.audio_signal_assertion.classifier import (
    Classification,
    ClassifierConfig,
    ProbeMeasurement,
)
from agents.audio_signal_assertion.probes import ProbeConfig, ProbeResult
from agents.audio_signal_assertion.transitions import TransitionDetector


def _silent_probe(stage: str, ts: float) -> ProbeResult:
    return ProbeResult(
        stage=stage,
        classification=Classification.SILENT,
        measurement=ProbeMeasurement(
            rms_dbfs=-90.0,
            peak_dbfs=-90.0,
            crest_factor=0.0,
            zero_crossing_rate=0.0,
            sample_count=96000,
        ),
        captured_at=ts,
        duration_s=2.0,
        error=None,
    )


def _music_probe(stage: str, ts: float) -> ProbeResult:
    return ProbeResult(
        stage=stage,
        classification=Classification.MUSIC_VOICE,
        measurement=ProbeMeasurement(
            rms_dbfs=-18.0,
            peak_dbfs=-3.0,
            crest_factor=8.0,
            zero_crossing_rate=0.08,
            sample_count=96000,
        ),
        captured_at=ts,
        duration_s=2.0,
        error=None,
    )


def _clipping_probe(stage: str, ts: float) -> ProbeResult:
    return ProbeResult(
        stage=stage,
        classification=Classification.CLIPPING,
        measurement=ProbeMeasurement(
            rms_dbfs=-2.0,
            peak_dbfs=0.0,
            crest_factor=2.5,
            zero_crossing_rate=0.30,
            sample_count=96000,
        ),
        captured_at=ts,
        duration_s=2.0,
        error=None,
    )


def test_run_tick_writes_snapshot_with_per_stage_probes(tmp_path: Path):
    snapshot_path = tmp_path / "signal-flow.json"
    config = daemon.DaemonConfig(
        stages=("hapax-broadcast-master", "hapax-obs-broadcast-remap"),
        snapshot_path=snapshot_path,
        livestream_flag_path=tmp_path / "no-such-flag",
        enable_ntfy=False,
        discover_stages=False,
    )
    detector = TransitionDetector(stage_names=config.stages)
    state = daemon.DaemonState()
    seq = iter(
        [
            _music_probe("hapax-broadcast-master", 100.0),
            _music_probe("hapax-obs-broadcast-remap", 100.0),
        ]
    )

    def _fake_capture(stage, **_kwargs):
        return next(seq)

    with patch.object(daemon, "capture_and_measure", side_effect=_fake_capture):
        with patch.object(daemon, "emit_metrics") as emit:
            fired = daemon.run_tick(
                config=config,
                detector=detector,
                state=state,
                probe_config=ProbeConfig(),
                classifier_config=ClassifierConfig(),
                now=100.0,
            )

    assert fired == []
    assert snapshot_path.exists()
    payload = json.loads(snapshot_path.read_text())
    assert payload["tick_count"] == 1
    assert {s["stage"] for s in payload["stages"]} == set(config.stages)
    for s in payload["stages"]:
        assert s["classification"] == "music_voice"
    emit.assert_called_once()


def test_run_tick_no_ntfy_when_disabled(tmp_path: Path):
    snapshot_path = tmp_path / "signal-flow.json"
    flag = tmp_path / "livestream-active"
    flag.write_text("on")  # Mark livestream as active.
    config = daemon.DaemonConfig(
        stages=("hapax-obs-broadcast-remap",),
        snapshot_path=snapshot_path,
        livestream_flag_path=flag,
        enable_ntfy=False,
        discover_stages=False,
        clipping_sustain_s=0.0,
        noise_sustain_s=0.0,
        silence_sustain_s=0.0,
    )
    detector = TransitionDetector(
        stage_names=config.stages,
        clipping_sustain_s=0.0,
        noise_sustain_s=0.0,
        silence_sustain_s=0.0,
    )
    state = daemon.DaemonState()
    seq = iter([_clipping_probe("hapax-obs-broadcast-remap", 50.0)])

    def _fake_capture(stage, **_kwargs):
        return next(seq)

    with patch.object(daemon, "capture_and_measure", side_effect=_fake_capture):
        with patch.object(daemon, "emit_metrics"):
            with patch.object(daemon, "_ntfy_event") as ntfy:
                fired = daemon.run_tick(
                    config=config,
                    detector=detector,
                    state=state,
                    probe_config=ProbeConfig(),
                    classifier_config=ClassifierConfig(),
                    now=50.0,
                )

    assert len(fired) == 1
    ntfy.assert_not_called()


def test_run_tick_ntfy_only_for_obs_bound_stage(tmp_path: Path):
    snapshot_path = tmp_path / "signal-flow.json"
    flag = tmp_path / "livestream-active"
    flag.write_text("on")
    config = daemon.DaemonConfig(
        stages=("hapax-broadcast-master", "hapax-obs-broadcast-remap"),
        snapshot_path=snapshot_path,
        livestream_flag_path=flag,
        enable_ntfy=True,
        discover_stages=False,
        clipping_sustain_s=0.0,
        noise_sustain_s=0.0,
        silence_sustain_s=0.0,
    )
    detector = TransitionDetector(
        stage_names=config.stages,
        clipping_sustain_s=0.0,
        noise_sustain_s=0.0,
        silence_sustain_s=0.0,
    )
    state = daemon.DaemonState()
    seq = iter(
        [
            _clipping_probe("hapax-broadcast-master", 1.0),
            _music_probe("hapax-obs-broadcast-remap", 1.0),
        ]
    )

    def _fake_capture(stage, **_kwargs):
        return next(seq)

    with patch.object(daemon, "capture_and_measure", side_effect=_fake_capture):
        with patch.object(daemon, "emit_metrics"):
            with patch.object(daemon, "_ntfy_event") as ntfy:
                daemon.run_tick(
                    config=config,
                    detector=detector,
                    state=state,
                    probe_config=ProbeConfig(),
                    classifier_config=ClassifierConfig(),
                    now=1.0,
                )

    # Master stage clipped, but ntfy must NOT fire — non-OBS stages
    # are upstream context only.
    ntfy.assert_not_called()


def test_run_tick_ntfy_fires_for_obs_clipping(tmp_path: Path):
    snapshot_path = tmp_path / "signal-flow.json"
    flag = tmp_path / "livestream-active"
    flag.write_text("on")
    config = daemon.DaemonConfig(
        stages=("hapax-broadcast-master", "hapax-obs-broadcast-remap"),
        snapshot_path=snapshot_path,
        livestream_flag_path=flag,
        enable_ntfy=True,
        discover_stages=False,
        clipping_sustain_s=0.0,
        noise_sustain_s=0.0,
        silence_sustain_s=0.0,
    )
    detector = TransitionDetector(
        stage_names=config.stages,
        clipping_sustain_s=0.0,
        noise_sustain_s=0.0,
        silence_sustain_s=0.0,
    )
    state = daemon.DaemonState()
    seq = iter(
        [
            _music_probe("hapax-broadcast-master", 1.0),
            _clipping_probe("hapax-obs-broadcast-remap", 1.0),
        ]
    )

    def _fake_capture(stage, **_kwargs):
        return next(seq)

    with patch.object(daemon, "capture_and_measure", side_effect=_fake_capture):
        with patch.object(daemon, "emit_metrics"):
            with patch.object(daemon, "_ntfy_event") as ntfy:
                daemon.run_tick(
                    config=config,
                    detector=detector,
                    state=state,
                    probe_config=ProbeConfig(),
                    classifier_config=ClassifierConfig(),
                    now=1.0,
                )

    ntfy.assert_called_once()
    # Body must include upstream context for the operator runbook.
    event_arg = ntfy.call_args.args[0]
    assert event_arg.stage == "hapax-obs-broadcast-remap"
    upstream = dict(event_arg.upstream_context)
    assert upstream["hapax-broadcast-master"] == Classification.MUSIC_VOICE


def test_is_livestream_active_off_when_flag_missing(tmp_path: Path):
    assert daemon.is_livestream_active(tmp_path / "missing", now=100.0) is False


def test_is_livestream_active_on_when_flag_fresh(tmp_path: Path):
    flag = tmp_path / "live"
    flag.write_text("")
    mtime = 100.0
    os.utime(flag, (mtime, mtime))
    assert daemon.is_livestream_active(flag, max_age_s=60.0, now=110.0) is True


def test_is_livestream_active_off_when_flag_stale(tmp_path: Path):
    flag = tmp_path / "live"
    flag.write_text("")
    mtime = 100.0
    os.utime(flag, (mtime, mtime))
    assert daemon.is_livestream_active(flag, max_age_s=10.0, now=200.0) is False


def test_emit_metrics_writes_textfile_gauges(tmp_path: Path):
    config = daemon.DaemonConfig(
        stages=("hapax-broadcast-master",),
        snapshot_path=tmp_path / "snap.json",
        livestream_flag_path=tmp_path / "no-flag",
        discover_stages=False,
    )
    state = daemon.DaemonState(
        last_probes={"hapax-broadcast-master": _music_probe("hapax-broadcast-master", 0.0)}
    )

    captured: list[dict[str, object]] = []

    def _fake_write_gauge(**kwargs):
        captured.append(kwargs)

    with patch("shared.recovery_counter_textfile.write_gauge", side_effect=_fake_write_gauge):
        daemon.emit_metrics(
            config=config,
            state=state,
            livestream_active=True,
        )

    metric_names = {kw["metric_name"] for kw in captured}
    assert "hapax_audio_signal_health" in metric_names
    assert "hapax_audio_signal_rms_dbfs" in metric_names
    assert "hapax_audio_signal_peak_dbfs" in metric_names
    assert "hapax_audio_signal_crest_factor" in metric_names
    assert "hapax_audio_signal_zero_crossing_rate" in metric_names
    assert "hapax_audio_signal_livestream_active" in metric_names

    # The active classification gauge for music_voice should be 1.0.
    health_writes = [
        kw
        for kw in captured
        if kw["metric_name"] == "hapax_audio_signal_health"
        and kw["labels"]["stage"] == "hapax-broadcast-master"
    ]
    music_voice = next(
        kw for kw in health_writes if kw["labels"]["classification"] == "music_voice"
    )
    silent = next(kw for kw in health_writes if kw["labels"]["classification"] == "silent")
    assert music_voice["value"] == 1.0
    assert silent["value"] == 0.0


def test_daemon_config_from_env(monkeypatch):
    monkeypatch.setenv("HAPAX_AUDIO_SIGNAL_PROBE_INTERVAL_S", "60.0")
    monkeypatch.setenv("HAPAX_AUDIO_SIGNAL_STAGES", "stage-a, stage-b")
    monkeypatch.setenv("HAPAX_AUDIO_SIGNAL_ENABLE_NTFY", "false")
    monkeypatch.setenv("HAPAX_AUDIO_SIGNAL_DISCOVER_STAGES", "0")
    config = daemon.DaemonConfig.from_env()
    assert config.probe_interval_s == 60.0
    assert config.stages == ("stage-a", "stage-b")
    assert config.enable_ntfy is False
    assert config.discover_stages is False


def test_format_event_message_includes_runbook_anchor():
    from agents.audio_signal_assertion.transitions import TransitionEvent

    event = TransitionEvent(
        stage="hapax-obs-broadcast-remap",
        new_state=Classification.CLIPPING,
        previous_state=Classification.MUSIC_VOICE,
        detected_at=10.0,
        sustained_for_s=2.0,
        upstream_context=(
            ("hapax-broadcast-master", Classification.MUSIC_VOICE),
            ("hapax-broadcast-normalized", Classification.NOISE),
        ),
    )
    body = daemon._format_event_message(event, anchor="docs/runbooks/audio-signal-assertion.md")
    assert "Runbook: docs/runbooks/audio-signal-assertion.md" in body
    assert "Upstream:" in body
    assert "hapax-broadcast-master=music_voice" in body
    assert "hapax-broadcast-normalized=noise" in body


def test_run_tick_handles_probe_errors(tmp_path: Path):
    snapshot_path = tmp_path / "signal-flow.json"
    config = daemon.DaemonConfig(
        stages=("hapax-broadcast-master",),
        snapshot_path=snapshot_path,
        livestream_flag_path=tmp_path / "no-flag",
        enable_ntfy=False,
        discover_stages=False,
    )
    detector = TransitionDetector(stage_names=config.stages)
    state = daemon.DaemonState()
    err = ProbeResult(
        stage="hapax-broadcast-master",
        classification=Classification.MUSIC_VOICE,  # placeholder
        measurement=ProbeMeasurement(-120, -120, 0.0, 0.0, 0),
        captured_at=10.0,
        duration_s=0.0,
        error="parecord captured 0 bytes",
    )

    def _fake_capture(stage, **_kwargs):
        return err

    with patch.object(daemon, "capture_and_measure", side_effect=_fake_capture):
        with patch.object(daemon, "emit_metrics"):
            fired = daemon.run_tick(
                config=config,
                detector=detector,
                state=state,
                probe_config=ProbeConfig(),
                classifier_config=ClassifierConfig(),
                now=10.0,
            )

    # Error did not crash; no transition event emitted.
    assert fired == []
    payload = json.loads(snapshot_path.read_text())
    stage = payload["stages"][0]
    assert stage["error"] == "parecord captured 0 bytes"
    assert stage["ok"] is False


@pytest.mark.parametrize(
    "duration",
    [0.0, 1.0, 5.0],
)
def test_format_event_message_handles_various_durations(duration):
    from agents.audio_signal_assertion.transitions import TransitionEvent

    event = TransitionEvent(
        stage="hapax-obs-broadcast-remap",
        new_state=Classification.NOISE,
        previous_state=Classification.MUSIC_VOICE,
        detected_at=0.0,
        sustained_for_s=duration,
    )
    body = daemon._format_event_message(event, anchor="anchor")
    assert "noise" in body
    assert f"{duration:.1f}" in body
