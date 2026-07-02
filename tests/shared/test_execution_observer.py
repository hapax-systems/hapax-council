"""CEI SLICE 4 — Claude transcript execution observer."""

from __future__ import annotations

import json
from pathlib import Path

from shared.execution_observer import FallbackEvent, observe_claude_transcript


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_single_model_transcript_has_no_drift(tmp_path: Path) -> None:
    t = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "user", "message": {"content": "hi"}},
            {"type": "assistant", "message": {"model": "claude-opus-4-8", "content": "hello"}},
            {"type": "assistant", "message": {"model": "claude-opus-4-8", "content": "again"}},
        ],
    )
    obs = observe_claude_transcript(t)
    assert obs.models == frozenset({"claude-opus-4-8"})
    assert obs.turn_count == 2
    assert obs.fallback_events == ()
    assert obs.drifted is False


def test_refusal_fallback_is_captured_as_drift(tmp_path: Path) -> None:
    t = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-fable-5", "content": "a"}},
            {
                "type": "system",
                "subtype": "model_refusal_fallback",
                "originalModel": "claude-fable-5",
                "fallbackModel": "claude-opus-4-8",
                "trigger": "refusal",
                "requestId": "req_x",
            },
        ],
    )
    obs = observe_claude_transcript(t)
    # Both the requested and the silently-served fallback model are in the observed set.
    assert obs.models == frozenset({"claude-fable-5", "claude-opus-4-8"})
    assert obs.fallback_events == (
        FallbackEvent(
            from_model="claude-fable-5",
            to_model="claude-opus-4-8",
            trigger="refusal",
            request_id="req_x",
        ),
    )
    assert obs.drifted is True


def test_malformed_lines_are_skipped_not_raised(tmp_path: Path) -> None:
    t = tmp_path / "t.jsonl"
    t.write_text(
        '{"type":"assistant","message":{"model":"claude-opus-4-8"}}\n'
        "this is not json\n"
        "\n"
        '{"type":"assistant","message":{"model":"claude-opus-4-8"}}\n',
        encoding="utf-8",
    )
    obs = observe_claude_transcript(t)
    assert obs.models == frozenset({"claude-opus-4-8"})
    assert obs.turn_count == 2
    assert obs.malformed_lines == 1


def test_missing_file_yields_empty_observation(tmp_path: Path) -> None:
    obs = observe_claude_transcript(tmp_path / "nope.jsonl")
    assert obs.models == frozenset()
    assert obs.turn_count == 0
    assert obs.drifted is False
    assert obs.endpoint_attested is False
