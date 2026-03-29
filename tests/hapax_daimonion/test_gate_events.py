"""Tests for ContextGate event emission."""

from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.context_gate import ContextGate
from agents.hapax_daimonion.session import SessionManager


def test_gate_emits_decision_event():
    sm = SessionManager(silence_timeout_s=10)
    gate = ContextGate(session=sm, volume_threshold=0.7)
    mock_log = MagicMock()
    gate.set_event_log(mock_log)

    with (
        patch.object(gate, "_get_sink_volume", return_value=0.3),
        patch.object(gate, "_check_studio", return_value=(True, "")),
        patch.object(gate, "_check_ambient", return_value=(True, "")),
    ):
        result = gate.check()

    assert result.eligible is True
    mock_log.emit.assert_called_once()
    call_args = mock_log.emit.call_args
    assert call_args[0][0] == "gate_decision"
    assert call_args[1]["eligible"] is True


def test_gate_emits_blocked_decision():
    sm = SessionManager(silence_timeout_s=10)
    sm.open(trigger="test")
    gate = ContextGate(session=sm, volume_threshold=0.7)
    mock_log = MagicMock()
    gate.set_event_log(mock_log)

    result = gate.check()

    assert result.eligible is False
    mock_log.emit.assert_called_once()
    call_args = mock_log.emit.call_args
    assert call_args[1]["reason"] == "Session active"


def test_gate_emits_subprocess_failed_on_wpctl_error():
    sm = SessionManager(silence_timeout_s=10)
    gate = ContextGate(session=sm, volume_threshold=0.7)
    mock_log = MagicMock()
    gate.set_event_log(mock_log)

    with patch("subprocess.run", side_effect=FileNotFoundError("wpctl not found")):
        gate._get_sink_volume()

    calls = [c for c in mock_log.emit.call_args_list if c[0][0] == "subprocess_failed"]
    assert len(calls) == 1
    assert calls[0][1]["command"] == "wpctl"
