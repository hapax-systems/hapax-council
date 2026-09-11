"""CEI SLICE 4 — Claude transcript execution observer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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


def test_effort_is_observed_and_a_mid_session_change_is_drift(tmp_path: Path) -> None:
    """Effort became adjustable MID-CONVERSATION in Fable 5.1, and nothing read the field.

    Claude Code 2.1.257 records a top-level `effort` on every assistant record — verified
    2026-09-01 across 153 assistant records in four live transcripts, none missing it. Under this
    estate's definition, configuration is constitutive of capability identity, so a session whose
    effort changed partway is two capabilities wearing one label: the same drift class as two
    models, one field over.
    """
    steady = _write(
        tmp_path / "steady.jsonl",
        [
            {"type": "assistant", "effort": "high", "message": {"model": "claude-fable-5-1"}},
            {"type": "assistant", "effort": "high", "message": {"model": "claude-fable-5-1"}},
        ],
    )
    obs = observe_claude_transcript(steady)
    assert obs.efforts == frozenset({"high"})
    assert obs.effort_drifted is False

    changed = _write(
        tmp_path / "changed.jsonl",
        [
            {"type": "assistant", "effort": "high", "message": {"model": "claude-fable-5-1"}},
            {"type": "assistant", "effort": "low", "message": {"model": "claude-fable-5-1"}},
        ],
    )
    obs = observe_claude_transcript(changed)
    assert obs.efforts == frozenset({"high", "low"})
    assert obs.effort_drifted is True, "one model, two efforts, is still two capabilities"
    assert obs.drifted is False, (
        "model drift and effort drift are separate verdicts: an older transcript carries no "
        "`effort` field at all, so folding it into `drifted` would make every legacy transcript "
        "read as clean on a question nobody asked it"
    )


def test_a_transcript_without_the_effort_field_reports_no_effort_not_stable_effort(
    tmp_path: Path,
) -> None:
    """Silence is not evidence of stability — the distinction this estate keeps having to relearn."""
    legacy = _write(
        tmp_path / "legacy.jsonl",
        [{"type": "assistant", "message": {"model": "claude-opus-4-8"}}],
    )
    obs = observe_claude_transcript(legacy)
    assert obs.efforts == frozenset(), "absent field must not synthesise a level"
    assert obs.effort_drifted is False, "and must not be reported as drift either"


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


def test_fallback_only_unsanctioned_source_is_not_satisfied(tmp_path: Path) -> None:
    """The fail-open the review caught: a model_refusal_fallback from an UNSANCTIONED source
    to a SANCTIONED target, with NO assistant turn for the source, must still register the
    source as observed and NOT return execution_invariant_satisfied. The source ran — it
    produced the refusal that triggered the remap."""
    t = _write(
        tmp_path / "t.jsonl",
        [
            # No assistant turn for the source model; only the fallback system record.
            {
                "type": "system",
                "subtype": "model_refusal_fallback",
                "originalModel": "claude-fable-5",
                "fallbackModel": "claude-opus-4-8",
                "trigger": "refusal",
            },
            {"type": "assistant", "message": {"model": "claude-opus-4-8", "content": "served"}},
        ],
    )
    obs = observe_claude_transcript(t)
    # from_model is in the observed set even though it has no assistant turn of its own.
    assert obs.models == frozenset({"claude-fable-5", "claude-opus-4-8"})

    # sanctioned = only the fallback TARGET. The unsanctioned source must be caught.
    verdict = check_execution_invariant(obs, frozenset({"claude-opus-4-8"}))
    assert verdict.status == "unsanctioned_fallback_observed"
    assert verdict.admissible is False
    assert "claude-fable-5" in verdict.unsanctioned_models
    assert verdict.unsanctioned_fallbacks[0].from_model == "claude-fable-5"


def test_assistant_turn_missing_model_key_is_not_counted(tmp_path: Path) -> None:
    """An assistant record whose message lacks a model key registers no model and no turn."""
    t = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"content": "no model key"}},
            {"type": "assistant", "message": {"model": None, "content": "null model"}},
            {"type": "assistant", "message": {"model": "claude-opus-4-8", "content": "real"}},
        ],
    )
    obs = observe_claude_transcript(t)
    assert obs.models == frozenset({"claude-opus-4-8"})
    assert obs.turn_count == 1


def test_non_dict_toplevel_json_record_is_skipped(tmp_path: Path) -> None:
    """A valid-JSON but non-object line (array/string) is skipped, not raised or counted."""
    t = tmp_path / "t.jsonl"
    t.write_text(
        '["not", "an", "object"]\n'
        '"a bare string"\n'
        '{"type":"assistant","message":{"model":"claude-opus-4-8"}}\n',
        encoding="utf-8",
    )
    obs = observe_claude_transcript(t)
    assert obs.models == frozenset({"claude-opus-4-8"})
    assert obs.turn_count == 1
    assert obs.malformed_lines == 0


def test_codex_rollout_missing_file_and_malformed(tmp_path: Path) -> None:
    """The Codex observer honors the same fail-safe contract as the Claude observer."""
    empty = observe_codex_rollout(tmp_path / "nope.jsonl")
    assert empty.models == frozenset()
    assert empty.turn_count == 0

    t = tmp_path / "rollout.jsonl"
    t.write_text(
        '{"type":"turn_context","payload":{"model":"gpt-5.5"}}\n'
        "not json at all\n"
        '{"type":"turn_context","payload":{"model":"gpt-5.5"}}\n',
        encoding="utf-8",
    )
    obs = observe_codex_rollout(t)
    assert obs.models == frozenset({"gpt-5.5"})
    assert obs.turn_count == 2
    assert obs.malformed_lines == 1


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


def test_claude_transcript_io_error_yields_empty_observation(tmp_path: Path) -> None:
    t = tmp_path / "t.jsonl"
    t.write_text('{"type":"assistant","message":{"model":"claude-opus-4-8"}}\n', encoding="utf-8")

    with patch.object(Path, "open", side_effect=OSError("permission denied")):
        obs = observe_claude_transcript(t)

    assert obs.models == frozenset()
    assert obs.turn_count == 0
    assert obs.source_path == str(t)
    assert obs.drifted is False


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


def test_codex_rollout_io_error_yields_empty_observation(tmp_path: Path) -> None:
    t = tmp_path / "rollout.jsonl"
    t.write_text('{"type":"turn_context","payload":{"model":"gpt-5.5"}}\n', encoding="utf-8")

    with patch.object(Path, "open", side_effect=OSError("permission denied")):
        obs = observe_codex_rollout(t)

    assert obs.models == frozenset()
    assert obs.turn_count == 0
    assert obs.source_path == str(t)
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


def test_invariant_verdict_rejects_effort_drift_without_changing_model_status() -> None:
    """R7: the verdict refuses a one-effort label for a two-effort run.

    The status stays model-based (the five CEI terminal states are about models); the effort
    facts ride alongside and make the otherwise-satisfied verdict inadmissible, so a consumer
    cannot label the mixture as one capability.
    """
    two_efforts = ObservedExecution(
        models=frozenset({"claude-fable-5-1"}),
        turn_count=2,
        efforts=frozenset({"high", "low"}),
    )
    v = check_execution_invariant(two_efforts, frozenset({"claude-fable-5-1"}))
    assert v.status == "execution_invariant_satisfied"
    assert v.admissible is False, "mixed-effort execution must fail closed"
    assert v.observed_efforts == frozenset({"high", "low"})
    assert v.effort_drifted is True

    one_effort = ObservedExecution(
        models=frozenset({"claude-fable-5-1"}), turn_count=2, efforts=frozenset({"high"})
    )
    one_effort_verdict = check_execution_invariant(one_effort, frozenset({"claude-fable-5-1"}))
    assert one_effort_verdict.effort_drifted is False
    assert one_effort_verdict.admissible is True
