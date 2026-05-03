"""Audit-3 fix #1 regression: PresenceEngine emits impingement on transitions.

Verifies the wiring added in `agents/hapax_daimonion/presence_engine.py` so
that a hysteresis state change broadcasts a richly-narrated impingement to
the cognitive substrate.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.hapax_daimonion import presence_engine as pe_mod
from agents.hapax_daimonion.presence_engine import PresenceEngine
from agents.hapax_daimonion.primitives import Behavior


def _present(**kwargs: object) -> dict[str, Behavior]:
    base = {
        "operator_visible": True,
        "real_keyboard_active": True,
        "input_active": True,
        "midi_clock_active": True,
        "watch_connected": True,
        "heart_rate_bpm": 72,
        "watch_hr_stale_seconds": 5,
    }
    base.update(kwargs)
    return {k: Behavior(v) for k, v in base.items()}


class TestPresenceEngineEmitsImpingementOnTransition:
    def test_uncertain_to_present_publishes_impingement(self, tmp_path: Path) -> None:
        bus = tmp_path / "impingements.jsonl"
        eng = PresenceEngine(prior=0.5, enter_ticks=2)
        b = _present()

        with patch.object(pe_mod, "emit_state_transition_impingement") as mock_emit:
            mock_emit.side_effect = lambda **kwargs: _capture_to_bus(bus, **kwargs)
            eng.contribute(b)
            eng.contribute(b)
        assert mock_emit.called
        assert bus.exists()
        line = bus.read_text().strip().splitlines()[-1]
        payload = json.loads(line)
        assert payload["source"] == "presence_engine"
        assert payload["claim_name"] == "operator-presence"
        assert payload["from_state"] == "UNCERTAIN"
        assert payload["to_state"] == "PRESENT"

    def test_no_emit_when_state_holds(self, tmp_path: Path) -> None:
        eng = PresenceEngine(prior=0.5, enter_ticks=2)
        with patch.object(pe_mod, "emit_state_transition_impingement") as mock_emit:
            empty: dict[str, Behavior] = {}
            for _ in range(5):
                eng.contribute(empty)
        assert mock_emit.call_count == 0

    def test_emit_called_with_posterior_and_signals(self, tmp_path: Path) -> None:
        eng = PresenceEngine(prior=0.5, enter_ticks=2)
        with patch.object(pe_mod, "emit_state_transition_impingement") as mock_emit:
            b = _present()
            eng.contribute(b)
            eng.contribute(b)
        assert mock_emit.called
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["source"] == "presence_engine"
        assert kwargs["claim_name"] == "operator-presence"
        assert kwargs["from_state"] == "UNCERTAIN"
        assert kwargs["to_state"] == "PRESENT"
        assert kwargs["posterior"] > 0.7
        assert isinstance(kwargs["active_signals"], dict)
        assert len(kwargs["active_signals"]) > 0

    def test_emit_failure_does_not_break_tick(self, tmp_path: Path) -> None:
        """A bus write failure must NOT crash the engine's tick loop."""
        eng = PresenceEngine(prior=0.5, enter_ticks=2)
        with patch.object(pe_mod, "emit_state_transition_impingement") as mock_emit:
            mock_emit.side_effect = OSError("bus full")
            b = _present()
            eng.contribute(b)
            eng.contribute(b)
        assert eng.state == "PRESENT"


def _capture_to_bus(bus: Path, **kwargs: object) -> bool:
    bus.parent.mkdir(parents=True, exist_ok=True)
    with bus.open("a") as f:
        f.write(json.dumps(kwargs, default=str) + "\n")
    return True
