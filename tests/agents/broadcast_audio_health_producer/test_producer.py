"""Tests for the broadcast audio health producer.

The producer drives delta's :mod:`shared.audio_marker_probe_fft`
through PipeWire shells (pw-cat / parec). Tests inject stubs for
those shells so the FFT detector runs against synthetic PCM and the
suite never touches the real audio system.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from agents.broadcast_audio_health_producer.producer import (
    BroadcastAudioHealthProducer,
    ProbeOutcome,
    RouteSpec,
    load_routes_from_env,
)
from shared.audio_marker_probe_fft import (
    DEFAULT_MARKER_FREQ_HZ,
    DEFAULT_SAMPLE_RATE_HZ,
    generate_marker_tone,
)


def _route(name: str = "broadcast-l12") -> RouteSpec:
    return RouteSpec(
        name=name,
        sink_name=f"hapax-{name}",
        monitor_source=f"hapax-{name}.monitor",
    )


def _silent_capture(_: str, duration_s: float, sample_rate: int) -> np.ndarray:
    n = int(round(sample_rate * duration_s))
    return np.zeros(n, dtype=np.int16)


def _passthrough_capture(_: str, duration_s: float, sample_rate: int) -> np.ndarray:
    return generate_marker_tone(
        DEFAULT_MARKER_FREQ_HZ,
        duration_s=duration_s,
        sample_rate=sample_rate,
    )


# ── Construction guards ────────────────────────────────────────────


class TestConstruction:
    def test_empty_routes_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            BroadcastAudioHealthProducer(routes=[], state_dir=tmp_path)


# ── Probe outcomes ─────────────────────────────────────────────────


class TestProbeOutcomes:
    def test_detected_when_capture_carries_marker(self, tmp_path: Path) -> None:
        injected: list[tuple[str, int]] = []

        def _inject(sink: str, samples: np.ndarray, sr: int) -> None:
            injected.append((sink, sr))

        producer = BroadcastAudioHealthProducer(
            routes=[_route()],
            state_dir=tmp_path,
            inject=_inject,
            capture=_passthrough_capture,
        )
        results = producer.run_once()
        assert len(results) == 1
        assert results[0].outcome == ProbeOutcome.DETECTED
        assert results[0].detection is not None
        assert results[0].detection.detected
        assert injected == [("hapax-broadcast-l12", DEFAULT_SAMPLE_RATE_HZ)]

    def test_not_detected_when_capture_silent(self, tmp_path: Path) -> None:
        producer = BroadcastAudioHealthProducer(
            routes=[_route()],
            state_dir=tmp_path,
            inject=lambda *a, **kw: None,
            capture=_silent_capture,
        )
        results = producer.run_once()
        assert results[0].outcome == ProbeOutcome.NOT_DETECTED
        assert results[0].detection is not None
        assert not results[0].detection.detected
        assert results[0].detection.failure_reason == "all-zero-capture"

    def test_error_outcome_on_inject_failure(self, tmp_path: Path) -> None:
        def _bad_inject(*_a: object, **_kw: object) -> None:
            raise RuntimeError("pw-cat unavailable")

        producer = BroadcastAudioHealthProducer(
            routes=[_route()],
            state_dir=tmp_path,
            inject=_bad_inject,
            capture=_passthrough_capture,
        )
        results = producer.run_once()
        assert results[0].outcome == ProbeOutcome.ERROR
        assert results[0].detection is None
        assert results[0].error is not None
        assert "pw-cat unavailable" in results[0].error

    def test_error_outcome_on_capture_failure(self, tmp_path: Path) -> None:
        def _bad_capture(*_a: object, **_kw: object) -> np.ndarray:
            raise RuntimeError("parec missing")

        producer = BroadcastAudioHealthProducer(
            routes=[_route()],
            state_dir=tmp_path,
            inject=lambda *a, **kw: None,
            capture=_bad_capture,
        )
        results = producer.run_once()
        assert results[0].outcome == ProbeOutcome.ERROR
        assert results[0].error is not None
        assert "parec missing" in results[0].error


# ── JSONL evidence ─────────────────────────────────────────────────


class TestJsonlOutput:
    def test_writes_one_row_per_route_per_call(self, tmp_path: Path) -> None:
        producer = BroadcastAudioHealthProducer(
            routes=[_route("broadcast"), _route("private")],
            state_dir=tmp_path,
            inject=lambda *a, **kw: None,
            capture=_passthrough_capture,
        )
        producer.run_once()
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        rows = [json.loads(line) for line in files[0].read_text().splitlines()]
        assert len(rows) == 2
        assert {r["route"] for r in rows} == {"broadcast", "private"}
        for row in rows:
            assert row["outcome"] == "detected"
            assert row["snr_db"] > 0
            assert "ts" in row

    def test_appends_across_calls(self, tmp_path: Path) -> None:
        producer = BroadcastAudioHealthProducer(
            routes=[_route()],
            state_dir=tmp_path,
            inject=lambda *a, **kw: None,
            capture=_passthrough_capture,
        )
        producer.run_once()
        producer.run_once()
        files = list(tmp_path.glob("*.jsonl"))
        rows = [json.loads(line) for line in files[0].read_text().splitlines()]
        assert len(rows) == 2

    def test_error_row_carries_error_field(self, tmp_path: Path) -> None:
        producer = BroadcastAudioHealthProducer(
            routes=[_route()],
            state_dir=tmp_path,
            inject=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
            capture=_passthrough_capture,
        )
        producer.run_once()
        rows = [
            json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()
        ]
        assert rows[0]["outcome"] == "error"
        assert "boom" in rows[0]["error"]


# ── Retention ──────────────────────────────────────────────────────


class TestRetention:
    def test_prunes_files_older_than_retention(self, tmp_path: Path) -> None:
        producer = BroadcastAudioHealthProducer(
            routes=[_route()],
            state_dir=tmp_path,
            inject=lambda *a, **kw: None,
            capture=_passthrough_capture,
        )
        # Seed an old + a recent file.
        old_date = (datetime.now(UTC) - timedelta(days=14)).strftime("%Y-%m-%d")
        recent_date = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / f"{old_date}.jsonl").write_text("old\n")
        (tmp_path / f"{recent_date}.jsonl").write_text("recent\n")
        removed = producer.prune_old_files()
        assert removed == 1
        assert not (tmp_path / f"{old_date}.jsonl").exists()
        assert (tmp_path / f"{recent_date}.jsonl").exists()

    def test_prune_skips_non_iso_filenames(self, tmp_path: Path) -> None:
        producer = BroadcastAudioHealthProducer(
            routes=[_route()],
            state_dir=tmp_path,
            inject=lambda *a, **kw: None,
            capture=_passthrough_capture,
        )
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "not-a-date.jsonl").write_text("x\n")
        removed = producer.prune_old_files()
        assert removed == 0
        assert (tmp_path / "not-a-date.jsonl").exists()


# ── Env-var route loader ───────────────────────────────────────────


class TestRouteLoader:
    def test_empty_env_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BROADCAST_AUDIO_HEALTH_ROUTES", raising=False)
        assert load_routes_from_env() == []

    def test_loads_triples(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "BROADCAST_AUDIO_HEALTH_ROUTES",
            "broadcast:hapax-broadcast:hapax-broadcast.monitor,"
            "private:hapax-private:hapax-private.monitor",
        )
        routes = load_routes_from_env()
        assert len(routes) == 2
        assert routes[0].name == "broadcast"
        assert routes[1].monitor_source == "hapax-private.monitor"

    def test_invalid_format_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROADCAST_AUDIO_HEALTH_ROUTES", "only-one-field")
        with pytest.raises(ValueError, match="invalid route entry"):
            load_routes_from_env()
