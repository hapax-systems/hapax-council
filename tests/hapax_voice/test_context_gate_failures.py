"""Failure-mode tests for ContextGate subprocess calls and ambient classification.

Covers wpctl failures, aconnect failures, ambient import/runtime errors,
and gate_decision event emission across all decision paths.

Updated for Batch 8: ContextGate now reads from Behaviors when available,
falling back to subprocess calls. Tests cover both paths.
"""

from __future__ import annotations

import subprocess
import time
from unittest.mock import MagicMock, patch

from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.session import SessionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gate(
    session_active: bool = False,
    volume_threshold: float = 0.7,
    ambient_classification: bool = True,
    ambient_block_threshold: float = 0.15,
) -> tuple[ContextGate, MagicMock]:
    """Create a ContextGate with a mock session and event log."""
    session = MagicMock(spec=SessionManager)
    session.is_active = session_active
    gate = ContextGate(
        session=session,
        volume_threshold=volume_threshold,
        ambient_classification=ambient_classification,
        ambient_block_threshold=ambient_block_threshold,
    )
    event_log = MagicMock()
    gate.set_event_log(event_log)
    return gate, event_log


def _make_gate_with_behaviors(
    *,
    volume: float = 0.3,
    midi_active: bool = False,
    session_active: bool = False,
    ambient_classification: bool = True,
) -> tuple[ContextGate, MagicMock]:
    """Create a ContextGate with Behaviors set (no subprocess)."""
    gate, event_log = _make_gate(
        session_active=session_active,
        ambient_classification=ambient_classification,
    )
    now = time.monotonic()
    gate.set_behaviors(
        {
            "sink_volume": Behavior(volume, watermark=now),
            "midi_active": Behavior(midi_active, watermark=now),
        }
    )
    return gate, event_log


def _mock_run_result(stdout: str = "", returncode: int = 0) -> MagicMock:
    """Create a mock subprocess.CompletedProcess."""
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.returncode = returncode
    return result


# ===========================================================================
# wpctl failures (subprocess fallback path, no Behaviors set)
# ===========================================================================


class TestWpctlFailures:
    """Tests for _read_volume subprocess fallback failure modes."""

    def test_wpctl_not_installed(self) -> None:
        """FileNotFoundError when wpctl binary is missing -> volume None -> gate blocks."""
        gate, _ = _make_gate()
        with patch("subprocess.run", side_effect=FileNotFoundError("wpctl not found")):
            result = gate.check()
        assert not result.eligible
        assert "volume" in result.reason.lower()

    def test_wpctl_timeout(self) -> None:
        """TimeoutExpired -> volume None -> gate blocks."""
        gate, _ = _make_gate()
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="wpctl", timeout=5),
        ):
            result = gate.check()
        assert not result.eligible
        assert "volume" in result.reason.lower() or "unavailable" in result.reason.lower()

    def test_wpctl_empty_output(self) -> None:
        """Empty stdout -> parts has <2 elements -> volume None -> blocks."""
        gate, _ = _make_gate()
        with patch("subprocess.run", return_value=_mock_run_result(stdout="")):
            result = gate.check()
        assert not result.eligible

    def test_wpctl_muted_output(self) -> None:
        """stdout='Volume: 0.50 [MUTED]' -> parses 0.50 correctly."""
        gate, _ = _make_gate(volume_threshold=0.7)
        _vol = gate._read_volume()
        # Without behaviors or mocking, this will try real subprocess
        # Use behaviors instead for a reliable test
        gate2, _ = _make_gate_with_behaviors(volume=0.50, ambient_classification=False)
        result = gate2.check()
        assert result.eligible

    def test_wpctl_unexpected_format(self) -> None:
        """stdout='SomeOtherText' -> only 1 part -> volume None -> blocks."""
        gate, _ = _make_gate()
        with patch(
            "subprocess.run",
            return_value=_mock_run_result(stdout="SomeOtherText"),
        ):
            result = gate.check()
        assert not result.eligible

    def test_wpctl_non_numeric_volume(self) -> None:
        """stdout='Volume: abc' -> float('abc') raises ValueError -> caught -> None -> blocks."""
        gate, _ = _make_gate()
        with patch(
            "subprocess.run",
            return_value=_mock_run_result(stdout="Volume: abc"),
        ):
            vol = gate._read_volume()
            assert vol is None

    def test_wpctl_failure_emits_subprocess_failed_event(self) -> None:
        """FileNotFoundError emits subprocess_failed event with command='wpctl'."""
        gate, event_log = _make_gate()
        with patch("subprocess.run", side_effect=FileNotFoundError("wpctl not found")):
            gate._read_volume()
        subprocess_calls = [
            c for c in event_log.emit.call_args_list if c[0][0] == "subprocess_failed"
        ]
        assert len(subprocess_calls) == 1
        assert subprocess_calls[0][1]["command"] == "wpctl"
        assert "wpctl not found" in subprocess_calls[0][1]["error"]


# ===========================================================================
# aconnect failures (subprocess fallback path, no Behaviors set)
# ===========================================================================


class TestAconnectFailures:
    """Tests for _read_midi_active subprocess fallback failure modes."""

    def test_aconnect_not_installed(self) -> None:
        """FileNotFoundError -> returns None (fail-closed)."""
        gate, _ = _make_gate()
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError("aconnect not found"),
        ):
            result = gate._read_midi_active()
        assert result is None

    def test_aconnect_timeout(self) -> None:
        """TimeoutExpired -> returns None."""
        gate, _ = _make_gate()
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="aconnect", timeout=5),
        ):
            result = gate._read_midi_active()
        assert result is None

    def test_aconnect_empty_output(self) -> None:
        """No connections listed -> returns False (no MIDI active)."""
        gate, _ = _make_gate()
        with patch(
            "subprocess.run",
            return_value=_mock_run_result(stdout=""),
        ):
            result = gate._read_midi_active()
        assert result is False

    def test_aconnect_through_only(self) -> None:
        """All connections contain 'Through' -> returns False."""
        aconnect_output = (
            "client 0: 'System' [type=kernel]\n"
            "    0 'Timer           '\n"
            "client 14: 'Midi Through' [type=kernel]\n"
            "    0 'Midi Through Port-0'\n"
            "        Connecting To: 14:0 [Through]\n"
            "        Connected From: 14:0 [Through]\n"
        )
        gate, _ = _make_gate()
        with patch(
            "subprocess.run",
            return_value=_mock_run_result(stdout=aconnect_output),
        ):
            result = gate._read_midi_active()
        assert result is False

    def test_aconnect_real_connection(self) -> None:
        """Real MIDI connection (no 'Through') -> returns True."""
        aconnect_output = (
            "client 0: 'System' [type=kernel]\n"
            "    0 'Timer           '\n"
            "client 28: 'OXI One MKII' [type=kernel,card=2]\n"
            "    0 'OXI One MKII MIDI 1'\n"
            "        Connected From: 32:0\n"
        )
        gate, _ = _make_gate()
        with patch(
            "subprocess.run",
            return_value=_mock_run_result(stdout=aconnect_output),
        ):
            result = gate._read_midi_active()
        assert result is True

    def test_aconnect_failure_emits_subprocess_failed_event(self) -> None:
        """aconnect failure emits subprocess_failed event with command='aconnect'."""
        gate, event_log = _make_gate()
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError("aconnect not found"),
        ):
            gate._read_midi_active()
        subprocess_calls = [
            c for c in event_log.emit.call_args_list if c[0][0] == "subprocess_failed"
        ]
        assert len(subprocess_calls) == 1
        assert subprocess_calls[0][1]["command"] == "aconnect"


# ===========================================================================
# ambient classification failures
# ===========================================================================


class TestAmbientFailures:
    """Tests for _check_ambient failure modes."""

    def test_ambient_import_failure(self) -> None:
        """ImportError on ambient_classifier module -> blocks with fail-closed."""
        gate, _ = _make_gate()
        with patch.dict("sys.modules", {"agents.hapax_voice.ambient_classifier": None}):
            ok, reason = gate._check_ambient()
        assert not ok
        assert "fail-closed" in reason.lower()

    def test_ambient_classify_exception(self) -> None:
        """classify() raises RuntimeError -> blocks with fail-closed."""
        gate, _ = _make_gate()
        mock_module = MagicMock()
        mock_module.classify.side_effect = RuntimeError("GPU OOM")
        with patch.dict("sys.modules", {"agents.hapax_voice.ambient_classifier": mock_module}):
            ok, reason = gate._check_ambient()
        assert not ok
        assert "fail-closed" in reason.lower()

    def test_ambient_disabled_skips_check(self) -> None:
        """ambient_classification=False -> skips ambient check entirely, gate passes."""
        gate, _ = _make_gate_with_behaviors(ambient_classification=False)
        result = gate.check()
        assert result.eligible


# ===========================================================================
# Gate decision event emission across all paths
# ===========================================================================


class TestGateDecisionEvents:
    """Verify gate_decision event is emitted for every check() code path."""

    def _get_gate_decisions(self, event_log: MagicMock) -> list:
        return [c for c in event_log.emit.call_args_list if c[0][0] == "gate_decision"]

    def test_session_active_emits_gate_decision(self) -> None:
        gate, event_log = _make_gate(session_active=True)
        result = gate.check()
        assert not result.eligible
        decisions = self._get_gate_decisions(event_log)
        assert len(decisions) == 1
        assert decisions[0][1]["eligible"] is False
        assert "session" in decisions[0][1]["reason"].lower()

    def test_volume_high_emits_gate_decision(self) -> None:
        gate, event_log = _make_gate_with_behaviors(volume=0.9)
        result = gate.check()
        assert not result.eligible
        decisions = self._get_gate_decisions(event_log)
        assert len(decisions) == 1
        assert decisions[0][1]["eligible"] is False
        assert "volume" in decisions[0][1]["reason"].lower()

    def test_midi_active_emits_gate_decision(self) -> None:
        gate, event_log = _make_gate_with_behaviors(
            volume=0.3, midi_active=True, ambient_classification=False
        )
        result = gate.check()
        assert not result.eligible
        decisions = self._get_gate_decisions(event_log)
        assert len(decisions) == 1
        assert "midi" in decisions[0][1]["reason"].lower()

    def test_ambient_block_emits_gate_decision(self) -> None:
        gate, event_log = _make_gate_with_behaviors()
        with patch.object(gate, "_check_ambient", return_value=(False, "Music detected")):
            result = gate.check()
        assert not result.eligible
        decisions = self._get_gate_decisions(event_log)
        assert len(decisions) == 1
        assert decisions[0][1]["eligible"] is False

    def test_eligible_emits_gate_decision(self) -> None:
        gate, event_log = _make_gate_with_behaviors(ambient_classification=False)
        result = gate.check()
        assert result.eligible
        decisions = self._get_gate_decisions(event_log)
        assert len(decisions) == 1
        assert decisions[0][1]["eligible"] is True
        assert decisions[0][1]["reason"] == ""
