"""Tests for agents.audio_ducker.pw_writer (cc-task audio-audit-C Phase 0).

Pin the ``MixerGainWriter`` Protocol contract, the SubprocessPWWriter
behaviour with a mocked subprocess.run, the NativePWWriter Phase 1
guard, and the latency-histogram observation contract.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agents.audio_ducker.pw_writer import (
    MIXER_WRITE_LATENCY_SECONDS,
    MixerGainWriter,
    MixerWriteOutcome,
    NativePWWriter,
    SubprocessPWWriter,
)


@pytest.fixture(autouse=True)
def _reset_histogram():
    """Histograms aren't trivially resettable; clear by recreating the
    underlying samples. We use ``_metrics`` access so the per-test counter
    asserts work without polluting other tests."""
    MIXER_WRITE_LATENCY_SECONDS.clear()
    yield
    MIXER_WRITE_LATENCY_SECONDS.clear()


def _observation_count(backend: str) -> int:
    """Sum of all bucket counts for the given backend label."""
    samples = MIXER_WRITE_LATENCY_SECONDS.labels(backend=backend).collect()
    if not samples:
        return 0
    for sample in samples[0].samples:
        if sample.name.endswith("_count"):
            return int(sample.value)
    return 0


class TestProtocolContract:
    def test_subprocess_writer_satisfies_protocol(self) -> None:
        writer = SubprocessPWWriter()
        assert isinstance(writer, MixerGainWriter)
        assert writer.backend_label == "subprocess"

    def test_native_writer_satisfies_protocol(self) -> None:
        writer = NativePWWriter()
        assert isinstance(writer, MixerGainWriter)
        assert writer.backend_label == "native"


class TestSubprocessPWWriter:
    def test_successful_write_returns_ok(self) -> None:
        writer = SubprocessPWWriter()
        with patch("agents.audio_ducker.pw_writer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr=b"")
            outcome = writer.write("hapax-music-duck", 0.25)
        assert outcome.ok is True
        assert outcome.error is None
        assert outcome.backend == "subprocess"
        assert outcome.succeeded is True

    def test_called_process_error_returns_not_ok_with_stderr(self) -> None:
        writer = SubprocessPWWriter()
        with patch("agents.audio_ducker.pw_writer.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["pw-cli"], stderr=b"node not found"
            )
            outcome = writer.write("missing-node", 0.5)
        assert outcome.ok is False
        assert outcome.error is not None
        assert "node not found" in outcome.error
        assert outcome.backend == "subprocess"
        assert outcome.succeeded is False

    def test_timeout_returns_not_ok(self) -> None:
        writer = SubprocessPWWriter(timeout_s=0.1)
        with patch("agents.audio_ducker.pw_writer.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="pw-cli", timeout=0.1)
            outcome = writer.write("slow-node", 0.5)
        assert outcome.ok is False
        assert outcome.error is not None
        assert "timed out" in outcome.error

    def test_pw_cli_missing_returns_not_ok(self) -> None:
        writer = SubprocessPWWriter()
        with patch("agents.audio_ducker.pw_writer.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("pw-cli")
            outcome = writer.write("any-node", 0.5)
        assert outcome.ok is False
        assert outcome.error is not None
        assert outcome.backend == "subprocess"

    def test_command_uses_correct_pw_cli_invocation(self) -> None:
        """Pin the exact pw-cli arg vector. Phase 1 will replace this with a
        binding call but the SubprocessPWWriter must remain the verified
        fallback — a regression here would make 'fall back to subprocess'
        silently wrong."""
        writer = SubprocessPWWriter()
        with patch("agents.audio_ducker.pw_writer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            writer.write("hapax-music-duck", 0.1234)
        args = mock_run.call_args[0][0]
        assert args[:2] == ["pw-cli", "set-param"]
        assert args[2] == "hapax-music-duck"
        assert args[3] == "Props"
        # Both channels must carry identical gain (atomic-ish stereo).
        params = args[4]
        assert "duck_l:Gain 1" in params
        assert "duck_r:Gain 1" in params
        assert "0.1234" in params


class TestNativePWWriterIsPhaseOnePlaceholder:
    def test_construction_succeeds(self) -> None:
        # Phase 1 will swap the constructor signature; pin that the placeholder
        # is constructible so the import-time wiring tests in Phase 1 don't
        # need to mock past a constructor failure.
        NativePWWriter()

    def test_write_raises_with_actionable_message(self) -> None:
        writer = NativePWWriter()
        with pytest.raises(NotImplementedError) as exc:
            writer.write("any-node", 0.5)
        # The error must name the cc-task and the fallback path so a future
        # operator hitting it has unambiguous next steps.
        msg = str(exc.value)
        assert "Phase 1" in msg
        assert "audio-audit-C" in msg
        assert "SubprocessPWWriter" in msg


class TestLatencyHistogramObservation:
    def test_subprocess_success_observes_one_sample(self) -> None:
        writer = SubprocessPWWriter()
        with patch("agents.audio_ducker.pw_writer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            writer.write("any-node", 0.5)
        assert _observation_count("subprocess") == 1

    def test_subprocess_failure_still_observes(self) -> None:
        """Latency observation must NOT short-circuit on error — operators
        need failure-path latency to detect timeout-class regressions."""
        writer = SubprocessPWWriter()
        with patch("agents.audio_ducker.pw_writer.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["pw-cli"], stderr=b""
            )
            writer.write("bad-node", 0.5)
        assert _observation_count("subprocess") == 1

    def test_repeated_writes_accumulate_observations(self) -> None:
        writer = SubprocessPWWriter()
        with patch("agents.audio_ducker.pw_writer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            for _ in range(7):
                writer.write("any-node", 0.5)
        assert _observation_count("subprocess") == 7

    def test_native_backend_label_is_distinct(self) -> None:
        """Phase 1 will populate this label; pin that subprocess and native
        are separate time series so the Grafana before/after panel can
        plot them as two lines."""
        # Force-create the labelled child so .collect() returns it.
        MIXER_WRITE_LATENCY_SECONDS.labels(backend="native").observe(0.001)
        MIXER_WRITE_LATENCY_SECONDS.labels(backend="subprocess").observe(0.001)
        assert _observation_count("native") == 1
        assert _observation_count("subprocess") == 1


class TestOutcomeShape:
    def test_succeeded_property_requires_ok_and_no_error(self) -> None:
        assert MixerWriteOutcome(ok=True).succeeded is True
        assert MixerWriteOutcome(ok=True, error="warning").succeeded is False
        assert MixerWriteOutcome(ok=False).succeeded is False
        assert MixerWriteOutcome(ok=False, error="boom").succeeded is False

    def test_outcome_is_frozen(self) -> None:
        """Frozen so a mid-flight FSM mutation can't corrupt telemetry state."""
        outcome = MixerWriteOutcome(ok=True)
        with pytest.raises((AttributeError, Exception)):
            outcome.ok = False  # type: ignore[misc]
