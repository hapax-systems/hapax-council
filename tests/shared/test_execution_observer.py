"""CapabilityExecutionInvariant observer and verdict tests."""

from __future__ import annotations

import json
from pathlib import Path

from shared.execution_observer import (
    EXPLICIT_SELF_ENFORCED,
    IMPLICIT_INHERITANCE,
    EndpointAttestation,
    FallbackEvent,
    ObservedExecution,
    SelfEnforcementGuard,
    capability_class_for_model,
    check_execution_invariant,
    observe_claude_transcript,
    observe_codex_rollout,
)


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_single_model_transcript_is_lane_observed_but_not_endpoint_attested(
    tmp_path: Path,
) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-opus-4-8"}},
            {"type": "assistant", "message": {"model": "claude-opus-4-8"}},
        ],
    )
    observed = observe_claude_transcript(transcript)
    assert observed.models == frozenset({"claude-opus-4-8"})
    assert observed.endpoint_attested is False
    assert observed.turn_count == 2
    assert observed.drifted is False

    verdict = check_execution_invariant(observed, frozenset({"claude-opus-4-8"}))
    assert verdict.status == "execution_observation_missing"
    assert verdict.admissible is False
    assert "endpoint_attestation_missing" in verdict.failure_reasons


def test_endpoint_attested_provenance_is_preferred_over_lane_model(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-fable-5"}},
            {
                "type": "endpoint_attestation",
                "source": "litellm_usage",
                "model": "claude-opus-4-8",
                "usage_row_id": "usage-1",
            },
        ],
    )
    observed = observe_claude_transcript(transcript)
    assert observed.models == frozenset({"claude-fable-5"})
    assert observed.endpoint_models == frozenset({"claude-opus-4-8"})
    assert observed.endpoint_attestations == (
        EndpointAttestation(
            model="claude-opus-4-8",
            source="litellm_usage",
            receipt_ref="usage-1",
        ),
    )

    verdict = check_execution_invariant(observed, frozenset({"claude-opus-4-8"}))
    assert verdict.status == "execution_invariant_satisfied"
    assert verdict.admissible is True
    assert verdict.observed_models == frozenset({"claude-opus-4-8"})


def test_lane_writable_endpoint_claim_is_ignored(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-opus-4-8"}},
            {
                "type": "endpoint_attestation",
                "source": "lane",
                "model": "claude-opus-4-8",
                "receipt_id": "self-attested",
            },
        ],
    )
    observed = observe_claude_transcript(transcript)
    assert observed.endpoint_attested is False

    verdict = check_execution_invariant(observed, frozenset({"claude-opus-4-8"}))
    assert verdict.status == "execution_observation_missing"
    assert verdict.admissible is False


def test_otel_gen_ai_response_model_is_endpoint_receipt(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-opus-4-8"}},
            {
                "type": "span",
                "attributes": {
                    "gen_ai.response.model": "claude-opus-4-8",
                    "trace_id": "trace-1",
                },
            },
        ],
    )
    observed = observe_claude_transcript(transcript)
    assert observed.endpoint_attested is True
    assert observed.endpoint_attestations[0].source == "otel_gen_ai"


def test_refusal_fallback_is_captured_as_drift(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {
                "type": "system",
                "subtype": "model_refusal_fallback",
                "originalModel": "claude-fable-5",
                "fallbackModel": "gpt-5.3-codex-spark",
                "trigger": "refusal",
                "requestId": "req-x",
            },
            {
                "type": "endpoint_attestation",
                "source": "litellm_usage",
                "model": "gpt-5.3-codex-spark",
                "usage_row_id": "usage-1",
            },
        ],
    )
    observed = observe_claude_transcript(transcript)
    assert observed.models == frozenset({"claude-fable-5", "gpt-5.3-codex-spark"})
    assert observed.fallback_events == (
        FallbackEvent(
            from_model="claude-fable-5",
            to_model="gpt-5.3-codex-spark",
            trigger="refusal",
            request_id="req-x",
        ),
    )

    verdict = check_execution_invariant(observed, frozenset({"claude-opus-4-8"}))
    assert verdict.status == "unsanctioned_fallback_observed"
    assert verdict.admissible is False
    assert verdict.unsanctioned_fallbacks[0].to_model == "gpt-5.3-codex-spark"


def test_implicit_inheritance_requires_endpoint_attested_close(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {
                "type": "system",
                "subtype": "model_refusal_fallback",
                "originalModel": "claude-fable-5",
                "fallbackModel": "claude-opus-4-8",
            },
            {"type": "assistant", "message": {"model": "claude-opus-4-8"}},
        ],
    )
    observed = observe_claude_transcript(transcript)
    verdict = check_execution_invariant(
        observed,
        frozenset({"claude-opus-4-8"}),
        gbai_case=IMPLICIT_INHERITANCE,
    )
    assert verdict.status == "execution_observation_missing"
    assert "endpoint_attestation_missing" in verdict.failure_reasons


def test_explicit_self_enforced_case_rejects_lane_rewritable_guard() -> None:
    observed = ObservedExecution(
        endpoint_models=frozenset({"claude-opus-4-8"}),
        endpoint_attestations=(EndpointAttestation("claude-opus-4-8", "litellm_usage", "usage-1"),),
        turn_count=1,
    )
    verdict = check_execution_invariant(
        observed,
        frozenset({"claude-opus-4-8"}),
        gbai_case=EXPLICIT_SELF_ENFORCED,
        self_enforcement_guard=SelfEnforcementGuard("guard", lane_rewritable=True),
    )
    assert verdict.status == "execution_drift_observed"
    assert "self_enforcement_guard_lane_rewritable" in verdict.failure_reasons


def test_explicit_self_enforced_case_accepts_non_lane_rewritable_guard() -> None:
    observed = ObservedExecution(
        endpoint_models=frozenset({"claude-opus-4-8"}),
        endpoint_attestations=(EndpointAttestation("claude-opus-4-8", "litellm_usage", "usage-1"),),
        turn_count=1,
    )
    verdict = check_execution_invariant(
        observed,
        frozenset({"claude-opus-4-8"}),
        gbai_case=EXPLICIT_SELF_ENFORCED,
        self_enforcement_guard=SelfEnforcementGuard(
            "guard", lane_rewritable=False, receipt_ref="guard-receipt-1"
        ),
    )
    assert verdict.status == "execution_invariant_satisfied"
    assert verdict.admissible is True


def test_capability_class_equality_accepts_same_class_model_change() -> None:
    observed = ObservedExecution(
        endpoint_models=frozenset({"claude-sonnet-4-6"}),
        endpoint_attestations=(
            EndpointAttestation("claude-sonnet-4-6", "litellm_usage", "usage-1"),
        ),
        turn_count=1,
    )
    verdict = check_execution_invariant(observed, frozenset({"claude-opus-4-8"}))
    assert capability_class_for_model("claude-sonnet-4-6") == "frontier_authoritative"
    assert verdict.status == "execution_invariant_satisfied"
    assert verdict.unsanctioned_models == frozenset()


def test_unknown_capability_class_fails_closed() -> None:
    observed = ObservedExecution(
        endpoint_models=frozenset({"mystery-model"}),
        endpoint_attestations=(EndpointAttestation("mystery-model", "litellm_usage", "usage-1"),),
        turn_count=1,
    )
    verdict = check_execution_invariant(observed, frozenset({"claude-opus-4-8"}))
    assert verdict.status == "execution_drift_observed"
    assert "unknown_observed_capability_class" in verdict.failure_reasons
    assert verdict.admissible is False


def test_synthetic_placeholder_model_is_not_counted(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-opus-4-8"}},
            {"type": "assistant", "message": {"model": "<synthetic>"}},
        ],
    )
    observed = observe_claude_transcript(transcript)
    assert observed.models == frozenset({"claude-opus-4-8"})
    assert observed.turn_count == 1


def test_malformed_lines_are_skipped_not_raised(tmp_path: Path) -> None:
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        '{"type":"assistant","message":{"model":"claude-opus-4-8"}}\n'
        "this is not json\n"
        "\n"
        '{"type":"assistant","message":{"model":"claude-opus-4-8"}}\n',
        encoding="utf-8",
    )
    observed = observe_claude_transcript(transcript)
    assert observed.models == frozenset({"claude-opus-4-8"})
    assert observed.turn_count == 2
    assert observed.malformed_lines == 1


def test_missing_file_yields_empty_observation(tmp_path: Path) -> None:
    observed = observe_claude_transcript(tmp_path / "nope.jsonl")
    assert observed.models == frozenset()
    assert observed.turn_count == 0
    assert observed.drifted is False
    assert observed.endpoint_attested is False


def test_codex_rollout_endpoint_attestation(tmp_path: Path) -> None:
    rollout = _write(
        tmp_path / "rollout.jsonl",
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.5"}},
            {
                "type": "span",
                "attributes": {
                    "gen_ai.response.model": "gpt-5.5",
                    "span_id": "span-1",
                },
            },
        ],
    )
    observed = observe_codex_rollout(rollout)
    assert observed.models == frozenset({"gpt-5.5"})
    assert observed.endpoint_models == frozenset({"gpt-5.5"})
    assert observed.endpoint_attested is True


def test_codex_rollout_model_change_is_drift(tmp_path: Path) -> None:
    rollout = _write(
        tmp_path / "rollout.jsonl",
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.5"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.3-codex-spark"}},
            {
                "type": "endpoint_attestation",
                "source": "litellm_usage",
                "model": "gpt-5.3-codex-spark",
                "usage_row_id": "usage-1",
            },
        ],
    )
    observed = observe_codex_rollout(rollout)
    verdict = check_execution_invariant(observed, frozenset({"gpt-5.5"}))
    assert verdict.status == "execution_drift_observed"
    assert verdict.unsanctioned_capability_classes == frozenset({"frontier_support"})
