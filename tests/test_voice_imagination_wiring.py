"""Tests for imagination wiring into voice daemon."""

import json
import time
from pathlib import Path

from agents.imagination import ContentReference, ImaginationFragment
from agents.imagination_context import format_imagination_context
from agents.proactive_gate import ProactiveGate


def test_context_injection_returns_string():
    result = format_imagination_context()
    assert isinstance(result, str)
    assert "Current Thoughts" in result


def test_context_injection_with_stream(tmp_path: Path):
    stream = tmp_path / "stream.jsonl"
    stream.write_text(
        json.dumps({"narrative": "thinking about code", "salience": 0.5, "continuation": False})
        + "\n"
    )
    result = format_imagination_context(stream)
    assert "thinking about code" in result
    assert "(active thought)" in result


def test_proactive_gate_checks_imagination_source():
    gate = ProactiveGate()
    frag = ImaginationFragment(
        content_references=[
            ContentReference(kind="text", source="insight", query=None, salience=0.8)
        ],
        dimensions={"intensity": 0.7},
        salience=0.9,
        continuation=False,
        narrative="Important realization.",
    )
    state = {
        "perception_activity": "active",
        "vad_active": False,
        "last_utterance_time": time.monotonic() - 60.0,
        "tpn_active": False,
    }
    assert gate.should_speak(frag, state) is True


def test_proactive_gate_rejects_low_salience():
    gate = ProactiveGate()
    frag = ImaginationFragment(
        content_references=[],
        dimensions={},
        salience=0.5,
        continuation=False,
        narrative="idle thought",
    )
    state = {
        "perception_activity": "active",
        "vad_active": False,
        "last_utterance_time": time.monotonic() - 60.0,
        "tpn_active": False,
    }
    assert gate.should_speak(frag, state) is False
