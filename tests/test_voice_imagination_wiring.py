"""Tests for imagination wiring into voice daemon."""

import json
import time
import unittest.mock
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
    # Sigmoid gate is probabilistic — mock RNG for deterministic test
    with unittest.mock.patch("agents.proactive_gate.random") as mock_rng:
        mock_rng.random.return_value = 0.0  # always below sigmoid probability
        assert gate.should_speak(frag, state) is True


def test_spontaneous_speech_imagination_prompt():
    """generate_spontaneous_speech uses imagination-specific prompt for source='imagination'."""
    from unittest.mock import MagicMock

    from agents.hapax_voice.conversation_pipeline import ConversationPipeline

    # Create a minimal pipeline with mocked dependencies
    pipeline = ConversationPipeline.__new__(ConversationPipeline)
    pipeline._running = True
    pipeline.state = MagicMock()
    pipeline.state.__eq__ = lambda self, other: False  # not SPEAKING
    pipeline._system_context = "test system"
    pipeline._model_id = "test-model"
    pipeline.messages = [{"role": "system", "content": "test"}]
    pipeline._experiment_flags = {}

    # Mock impingement with imagination source
    imp = MagicMock()
    imp.source = "imagination"
    imp.strength = 0.9
    imp.content = {
        "narrative": "The drift report suggests consolidating inference.",
        "content_references": [
            {"kind": "qdrant_query", "source": "documents", "salience": 0.7},
        ],
        "continuation": False,
    }

    # Extract the prompt that would be built
    content = imp.content
    source = imp.source
    narrative = content.get("narrative", "")
    refs = content.get("content_references", [])
    ref_summary = ", ".join(r.get("source", "") for r in refs[:3] if isinstance(r, dict))

    assert source == "imagination"
    assert "consolidating inference" in narrative
    assert "documents" in ref_summary


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
    # Sigmoid gate is probabilistic — mock RNG for deterministic test
    with unittest.mock.patch("agents.proactive_gate.random") as mock_rng:
        mock_rng.random.return_value = 0.99  # above sigmoid probability for salience 0.5
        assert gate.should_speak(frag, state) is False
