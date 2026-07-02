"""CEI SLICE 4 — Claude transcript execution observer."""

from __future__ import annotations

import json
from pathlib import Path

from shared.execution_observer import (
    FallbackEvent,
    ObservedExecution,
    check_execution_invariant,
    observe_claude_transcript,
    observe_codex_rollout,
)


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


def test_synthetic_placeholder_model_is_not_counted(tmp_path: Path) -> None:
    """Placeholder pseudo-models like "<synthetic>" (hook/tool-injected turns) are not a
    served identity and must not register as an extra model / false-positive drift."""
    t = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-opus-4-8", "content": "a"}},
            {"type": "assistant", "message": {"model": "<synthetic>", "content": "tool"}},
        ],
    )
    obs = observe_claude_transcript(t)
    assert obs.models == frozenset({"claude-opus-4-8"})
    assert obs.turn_count == 1


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


def test_codex_rollout_single_model_no_drift(tmp_path: Path) -> None:
    t = _write(
        tmp_path / "rollout.jsonl",
        [
            {"type": "session_meta", "payload": {"id": "x"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "xhigh"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "xhigh"}},
        ],
    )
    obs = observe_codex_rollout(t)
    assert obs.models == frozenset({"gpt-5.5"})
    assert obs.turn_count == 2
    assert obs.drifted is False


def test_codex_rollout_model_change_is_drift(tmp_path: Path) -> None:
    t = _write(
        tmp_path / "rollout.jsonl",
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.5"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.3-codex-spark"}},
        ],
    )
    obs = observe_codex_rollout(t)
    assert obs.models == frozenset({"gpt-5.5", "gpt-5.3-codex-spark"})
    assert obs.drifted is True
    v = check_execution_invariant(obs, frozenset({"gpt-5.5"}))
    assert v.status == "execution_drift_observed"
    assert v.admissible is False


def test_invariant_satisfied_when_observed_subset_of_sanctioned() -> None:
    obs = ObservedExecution(models=frozenset({"claude-opus-4-8"}), turn_count=3)
    v = check_execution_invariant(obs, frozenset({"claude-opus-4-8"}))
    assert v.status == "execution_invariant_satisfied"
    assert v.admissible is True
    assert v.unsanctioned_models == frozenset()


def test_invariant_drift_when_unsanctioned_model_ran() -> None:
    obs = ObservedExecution(models=frozenset({"claude-opus-4-8"}), turn_count=1)
    v = check_execution_invariant(obs, frozenset({"claude-fable-5"}))
    assert v.status == "execution_drift_observed"
    assert v.admissible is False
    assert v.unsanctioned_models == frozenset({"claude-opus-4-8"})


def test_invariant_unsanctioned_fallback_is_its_own_state() -> None:
    obs = ObservedExecution(
        models=frozenset({"claude-fable-5", "claude-opus-4-8"}),
        fallback_events=(FallbackEvent(from_model="claude-fable-5", to_model="claude-opus-4-8"),),
        turn_count=2,
    )
    v = check_execution_invariant(obs, frozenset({"claude-fable-5"}))
    assert v.status == "unsanctioned_fallback_observed"
    assert v.admissible is False
    assert v.unsanctioned_fallbacks[0].to_model == "claude-opus-4-8"


def test_invariant_missing_when_nothing_observed() -> None:
    v = check_execution_invariant(ObservedExecution(), frozenset({"claude-opus-4-8"}))
    assert v.status == "execution_observation_missing"
    assert v.admissible is False


def test_invariant_empty_sanctioned_set_fails_closed() -> None:
    obs = ObservedExecution(models=frozenset({"claude-opus-4-8"}), turn_count=1)
    v = check_execution_invariant(obs, frozenset())
    assert v.admissible is False
    assert v.unsanctioned_models == frozenset({"claude-opus-4-8"})
