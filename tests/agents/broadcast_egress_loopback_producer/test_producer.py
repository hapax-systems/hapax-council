"""Tests for the broadcast egress loopback witness producer.

The producer reads PCM via parec and writes
:class:`~shared.broadcast_audio_health.EgressLoopbackWitness` JSON to
``/dev/shm/hapax-broadcast/egress-loopback.json``. Tests inject stub
capture functions so the suite never touches real PipeWire and runs
against synthetic int16 PCM bytes.
"""

from __future__ import annotations

import array
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents.broadcast_egress_loopback_producer.producer import (
    DEFAULT_BROADCAST_SOURCE,
    DEFAULT_TICK_SECONDS,
    DEFAULT_WINDOW_SECONDS,
    EgressLoopbackProducer,
    compute_loopback_metrics,
    load_config_from_env,
    write_witness_atomic,
)
from shared.broadcast_audio_health import EgressLoopbackWitness

# ── PCM helpers ────────────────────────────────────────────────────


def _silence_bytes(n_samples: int) -> bytes:
    return array.array("h", [0] * n_samples).tobytes()


def _sine_bytes(
    n_samples: int,
    freq_hz: float = 1000.0,
    sample_rate: int = 48000,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a sine wave at the given amplitude (fraction of full scale)."""
    full_scale = 32767
    samples = array.array("h")
    for i in range(n_samples):
        t = i / sample_rate
        s = amplitude * full_scale * math.sin(2.0 * math.pi * freq_hz * t)
        samples.append(int(round(s)))
    return samples.tobytes()


def _half_silent_bytes(n_samples: int, sample_rate: int = 48000) -> bytes:
    """Half silence + half sine at -6 dBFS — silence_ratio should be ~0.5."""
    silent = _silence_bytes(n_samples // 2)
    audible = _sine_bytes(n_samples - (n_samples // 2), sample_rate=sample_rate)
    return silent + audible


# ── compute_loopback_metrics ────────────────────────────────────────


class TestComputeLoopbackMetrics:
    def test_silence_returns_floor_metrics(self) -> None:
        sample = compute_loopback_metrics(_silence_bytes(48000))
        assert sample.rms_dbfs == -120.0
        assert sample.peak_dbfs == -120.0
        assert sample.silence_ratio == 1.0

    def test_empty_input_returns_floor_metrics(self) -> None:
        sample = compute_loopback_metrics(b"")
        assert sample.rms_dbfs == -120.0
        assert sample.silence_ratio == 1.0

    def test_full_scale_sine_rms_near_minus_three_db(self) -> None:
        # Sine wave at amplitude 1.0 → RMS = 1/sqrt(2) → ~-3.01 dBFS
        sample = compute_loopback_metrics(_sine_bytes(48000, amplitude=1.0))
        assert sample.rms_dbfs == pytest.approx(-3.01, abs=0.1)
        # Peak should be at or just below 0 dBFS (full scale int16 is 32767).
        assert sample.peak_dbfs == pytest.approx(0.0, abs=0.1)
        # Sine never sits below the silence floor for long → ratio ≈ small.
        assert sample.silence_ratio < 0.1

    def test_half_silent_input_yields_half_silence_ratio(self) -> None:
        sample = compute_loopback_metrics(_half_silent_bytes(48000))
        # Half the samples are exact zero → silence_ratio ≈ 0.5
        # Exact value drifts a hair because the boundary sample of the
        # sine half sits just above 0; widen tolerance to suit.
        assert sample.silence_ratio == pytest.approx(0.5, abs=0.05)

    def test_odd_byte_count_does_not_crash(self) -> None:
        # parec could in principle return a partial last sample; the
        # producer truncates rather than crashing.
        odd = _silence_bytes(100) + b"\x00"
        sample = compute_loopback_metrics(odd)
        assert sample.silence_ratio == 1.0


# ── write_witness_atomic ────────────────────────────────────────────


class TestWriteWitnessAtomic:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "subdir" / "egress-loopback.json"
        witness = EgressLoopbackWitness(
            checked_at="2026-05-02T00:00:00+00:00",
            rms_dbfs=-12.0,
            peak_dbfs=-3.0,
            silence_ratio=0.05,
            window_seconds=5.0,
            target_sink="hapax-broadcast-normalized",
        )
        write_witness_atomic(witness, path)
        assert path.is_file()
        loaded = json.loads(path.read_text())
        assert loaded["target_sink"] == "hapax-broadcast-normalized"
        assert loaded["rms_dbfs"] == -12.0
        # Must round-trip into the evaluator's pydantic model unchanged.
        round_trip = EgressLoopbackWitness.model_validate(loaded)
        assert round_trip == witness

    def test_atomic_via_tmp_then_rename(self, tmp_path: Path) -> None:
        # The tmp file must not linger after a successful write.
        path = tmp_path / "egress-loopback.json"
        witness = EgressLoopbackWitness(
            checked_at="2026-05-02T00:00:00+00:00",
            rms_dbfs=-12.0,
            peak_dbfs=-3.0,
            silence_ratio=0.0,
            window_seconds=5.0,
            target_sink="hapax-broadcast-normalized",
        )
        write_witness_atomic(witness, path)
        siblings = list(path.parent.iterdir())
        assert path in siblings
        assert all(not p.name.endswith(".tmp") for p in siblings)

    def test_overwrites_existing_witness(self, tmp_path: Path) -> None:
        path = tmp_path / "egress-loopback.json"
        path.write_text('{ "stale": true }')
        witness = EgressLoopbackWitness(
            checked_at="2026-05-02T00:00:00+00:00",
            rms_dbfs=-12.0,
            peak_dbfs=-3.0,
            silence_ratio=0.0,
            window_seconds=5.0,
            target_sink="hapax-broadcast-normalized",
        )
        write_witness_atomic(witness, path)
        loaded = json.loads(path.read_text())
        assert "stale" not in loaded
        assert loaded["rms_dbfs"] == -12.0


# ── EgressLoopbackProducer.tick_once ────────────────────────────────


class TestProducerTickOnce:
    def test_writes_witness_for_silent_capture(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"

        def cap(_source: str, duration_s: float, sample_rate: int) -> bytes:
            return _silence_bytes(int(duration_s * sample_rate))

        producer = EgressLoopbackProducer(
            source="hapax-broadcast-normalized",
            window_seconds=1.0,
            tick_seconds=1.0,
            witness_path=out,
            capture=cap,
        )
        witness = producer.tick_once()
        assert out.is_file()
        assert witness.error is None
        assert witness.target_sink == "hapax-broadcast-normalized"
        assert witness.window_seconds == 1.0
        assert witness.silence_ratio == 1.0
        assert witness.rms_dbfs == -120.0
        # Re-load to confirm shape consumable by evaluator.
        EgressLoopbackWitness.model_validate(json.loads(out.read_text()))

    def test_writes_witness_for_live_capture(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"

        def cap(_source: str, duration_s: float, sample_rate: int) -> bytes:
            return _sine_bytes(int(duration_s * sample_rate), amplitude=0.5)

        producer = EgressLoopbackProducer(
            source="hapax-broadcast-normalized",
            window_seconds=1.0,
            tick_seconds=1.0,
            witness_path=out,
            capture=cap,
        )
        witness = producer.tick_once()
        assert witness.error is None
        # 0.5 amp sine RMS ≈ -9 dBFS (half full scale → -6 dB; rms half-power → -9)
        assert witness.rms_dbfs == pytest.approx(-9.03, abs=0.2)
        assert witness.silence_ratio < 0.1

    def test_capture_subprocess_failure_writes_error_witness(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"

        def cap(_source: str, _duration_s: float, _sample_rate: int) -> bytes:
            raise subprocess.CalledProcessError(returncode=2, cmd=["parec"])

        producer = EgressLoopbackProducer(
            source="hapax-broadcast-normalized",
            window_seconds=1.0,
            tick_seconds=1.0,
            witness_path=out,
            capture=cap,
        )
        witness = producer.tick_once()
        assert witness.error is not None
        assert "parec_failed" in witness.error
        assert "exit_2" in witness.error
        # Even on failure the file is written so the evaluator surfaces
        # producer_error rather than missing-witness.
        loaded = json.loads(out.read_text())
        assert loaded["error"] == witness.error

    def test_parec_missing_writes_error_witness(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"

        def cap(_source: str, _duration_s: float, _sample_rate: int) -> bytes:
            raise FileNotFoundError("parec")

        producer = EgressLoopbackProducer(
            source="hapax-broadcast-normalized",
            window_seconds=1.0,
            tick_seconds=1.0,
            witness_path=out,
            capture=cap,
        )
        witness = producer.tick_once()
        assert witness.error is not None
        assert "parec_missing" in witness.error
        assert out.is_file()

    def test_unexpected_exception_writes_error_witness(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"

        def cap(_source: str, _duration_s: float, _sample_rate: int) -> bytes:
            raise RuntimeError("sink graph unstable")

        producer = EgressLoopbackProducer(
            source="hapax-broadcast-normalized",
            window_seconds=1.0,
            tick_seconds=1.0,
            witness_path=out,
            capture=cap,
        )
        witness = producer.tick_once()
        assert witness.error is not None
        assert "capture_failed" in witness.error
        assert "RuntimeError" in witness.error
        assert "sink graph unstable" in witness.error

    def test_target_sink_and_window_in_witness(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"

        def cap(_source: str, duration_s: float, sample_rate: int) -> bytes:
            return _silence_bytes(int(duration_s * sample_rate))

        producer = EgressLoopbackProducer(
            source="hapax-obs-broadcast-remap",
            window_seconds=3.5,
            tick_seconds=1.0,
            witness_path=out,
            capture=cap,
        )
        witness = producer.tick_once()
        assert witness.target_sink == "hapax-obs-broadcast-remap"
        assert witness.window_seconds == 3.5

    def test_clock_injection_controls_checked_at(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"
        fixed = datetime(2026, 5, 2, 17, 0, 0, tzinfo=UTC)

        def cap(_source: str, duration_s: float, sample_rate: int) -> bytes:
            return _silence_bytes(int(duration_s * sample_rate))

        producer = EgressLoopbackProducer(
            source="hapax-broadcast-normalized",
            window_seconds=1.0,
            tick_seconds=1.0,
            witness_path=out,
            capture=cap,
            clock=lambda: fixed,
        )
        witness = producer.tick_once()
        assert witness.checked_at == fixed.isoformat()


# ── EgressLoopbackProducer construction ─────────────────────────────


class TestProducerConstruction:
    def test_invalid_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="window_seconds"):
            EgressLoopbackProducer(window_seconds=0.0)

    def test_invalid_tick_rejected(self) -> None:
        with pytest.raises(ValueError, match="tick_seconds"):
            EgressLoopbackProducer(tick_seconds=-1.0)

    def test_empty_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="source"):
            EgressLoopbackProducer(source="")

    def test_defaults_match_evaluator_expectations(self) -> None:
        p = EgressLoopbackProducer()
        assert p.source == DEFAULT_BROADCAST_SOURCE
        # Evaluator's freshness threshold is 60s by default; tick must
        # be well below that so witness staleness never trips on
        # benign scheduling jitter.
        assert p.tick_seconds == DEFAULT_TICK_SECONDS
        assert p.window_seconds == DEFAULT_WINDOW_SECONDS
        assert p.tick_seconds * 12.0 <= 60.0


# ── run_forever cadence ─────────────────────────────────────────────


class TestProducerRunForever:
    def test_run_forever_ticks_at_configured_cadence(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"
        tick_count = 0
        max_ticks = 3

        def cap(_source: str, duration_s: float, sample_rate: int) -> bytes:
            nonlocal tick_count
            tick_count += 1
            if tick_count >= max_ticks:
                # Stop the loop on the third tick by raising
                # KeyboardInterrupt — same path the systemd unit uses
                # on SIGINT shutdown.
                raise KeyboardInterrupt()
            return _silence_bytes(int(duration_s * sample_rate))

        sleep_calls: list[float] = []

        producer = EgressLoopbackProducer(
            source="hapax-broadcast-normalized",
            window_seconds=0.5,
            tick_seconds=2.0,
            witness_path=out,
            capture=cap,
            sleeper=sleep_calls.append,
        )
        with pytest.raises(KeyboardInterrupt):
            producer.run_forever()
        # Two successful ticks before KeyboardInterrupt → at least one
        # sleep call between them (and at most as many as ticks).
        assert len(sleep_calls) >= 1
        # Every sleep duration must be > 0 (residual after capture)
        # and ≤ tick_seconds (cadence cap).
        for s in sleep_calls:
            assert 0 < s <= 2.0


# ── load_config_from_env ────────────────────────────────────────────


class TestLoadConfigFromEnv:
    def test_defaults_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "HAPAX_LOOPBACK_SOURCE",
            "HAPAX_LOOPBACK_WINDOW_S",
            "HAPAX_LOOPBACK_TICK_S",
            "HAPAX_LOOPBACK_WITNESS_PATH",
        ):
            monkeypatch.delenv(var, raising=False)
        cfg = load_config_from_env()
        assert cfg["source"] == DEFAULT_BROADCAST_SOURCE
        assert cfg["window_seconds"] == DEFAULT_WINDOW_SECONDS
        assert cfg["tick_seconds"] == DEFAULT_TICK_SECONDS

    def test_env_overrides_apply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_LOOPBACK_SOURCE", "hapax-obs-broadcast-remap")
        monkeypatch.setenv("HAPAX_LOOPBACK_WINDOW_S", "10.0")
        monkeypatch.setenv("HAPAX_LOOPBACK_TICK_S", "2.5")
        monkeypatch.setenv("HAPAX_LOOPBACK_WITNESS_PATH", "/tmp/test-egress-loopback.json")
        cfg = load_config_from_env()
        assert cfg["source"] == "hapax-obs-broadcast-remap"
        assert cfg["window_seconds"] == 10.0
        assert cfg["tick_seconds"] == 2.5
        assert str(cfg["witness_path"]) == "/tmp/test-egress-loopback.json"


# ── Cross-module integration with the evaluator ────────────────────
#
# Pin the JSON shape end-to-end: the producer's output must be
# directly consumable by the evaluator's pydantic validation.


class TestEvaluatorIntegration:
    def test_witness_passes_evaluator_pydantic_validation(self, tmp_path: Path) -> None:
        out = tmp_path / "egress-loopback.json"

        def cap(_source: str, duration_s: float, sample_rate: int) -> bytes:
            return _sine_bytes(int(duration_s * sample_rate), amplitude=0.5)

        producer = EgressLoopbackProducer(
            source="hapax-broadcast-normalized",
            window_seconds=1.0,
            tick_seconds=1.0,
            witness_path=out,
            capture=cap,
        )
        producer.tick_once()
        # Reads exactly like the evaluator's _read_json_file +
        # EgressLoopbackWitness.model_validate path.
        data = json.loads(out.read_text())
        witness = EgressLoopbackWitness.model_validate(data)
        # Evaluator default threshold (silence_ratio_max=0.85) must
        # NOT block on a healthy live signal — sanity-pin the producer's
        # output shape against the evaluator's expectations.
        assert witness.silence_ratio < 0.85
