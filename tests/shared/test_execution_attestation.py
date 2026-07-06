"""CEI attestation helper tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.execution_attestation import (
    GATE2_LOCAL_INTERCEPTOR,
    assert_gate2_locality,
    attest_transcript,
    is_load_bearing_governance_surface,
    load_lbg_allowlist,
    sanctioned_capability_classes_for_route,
    sanctioned_models_for_route,
)
from shared.execution_observer import EXPLICIT_SELF_ENFORCED, SelfEnforcementGuard


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _stub_registry(route_id: str, model_id: str, variant_models: list[str] | None = None):
    variants = [
        SimpleNamespace(knobs_override={"model_id": model}) for model in variant_models or []
    ]
    route = SimpleNamespace(
        execution_descriptor=SimpleNamespace(model_id=model_id),
        descriptor_variants=variants,
    )
    return SimpleNamespace(route_map=lambda: {route_id: route})


def test_sanctioned_models_from_route_descriptor() -> None:
    registry = _stub_registry("claude.headless.opus", "claude-opus-4-8")
    assert sanctioned_models_for_route("claude.headless.opus", registry) == frozenset(
        {"claude-opus-4-8"}
    )


def test_sanctioned_models_include_variant_overrides() -> None:
    registry = _stub_registry(
        "local_tool.local.worker", "command-r-08-2024", variant_models=["qwen3.5-9b"]
    )
    assert sanctioned_models_for_route("local_tool.local.worker", registry) == frozenset(
        {"command-r-08-2024", "qwen3.5-9b"}
    )


def test_sanctioned_capability_classes_from_route() -> None:
    registry = _stub_registry(
        "claude.headless.opus", "claude-opus-4-8", variant_models=["claude-sonnet-4-6"]
    )
    assert sanctioned_capability_classes_for_route("claude/headless/opus", registry) == frozenset(
        {"frontier_authoritative"}
    )


def test_unknown_route_sanctions_nothing_fail_closed() -> None:
    registry = _stub_registry("claude.headless.opus", "claude-opus-4-8")
    assert sanctioned_models_for_route("no.such.route", registry) == frozenset()


def test_attest_transcript_requires_endpoint_receipt(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [{"type": "assistant", "message": {"model": "claude-opus-4-8"}}],
    )
    verdict = attest_transcript(transcript, frozenset({"claude-opus-4-8"}), carrier="claude")
    assert verdict.status == "execution_observation_missing"
    assert verdict.admissible is False


def test_attest_transcript_satisfied_with_endpoint_receipt(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-opus-4-8"}},
            {
                "type": "endpoint_attestation",
                "source": "litellm_usage",
                "model": "claude-opus-4-8",
                "usage_row_id": "usage-1",
            },
        ],
    )
    verdict = attest_transcript(transcript, frozenset({"claude-opus-4-8"}), carrier="claude")
    assert verdict.status == "execution_invariant_satisfied"
    assert verdict.admissible is True


def test_attest_codex_carrier(tmp_path: Path) -> None:
    rollout = _write(
        tmp_path / "rollout.jsonl",
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.5"}},
            {
                "type": "endpoint_attestation",
                "source": "litellm_usage",
                "model": "gpt-5.5",
                "usage_row_id": "usage-1",
            },
        ],
    )
    verdict = attest_transcript(rollout, frozenset({"gpt-5.5"}), carrier="codex")
    assert verdict.admissible is True


def test_attest_explicit_self_enforced_guard(tmp_path: Path) -> None:
    transcript = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-opus-4-8"}},
            {
                "type": "endpoint_attestation",
                "source": "litellm_usage",
                "model": "claude-opus-4-8",
                "usage_row_id": "usage-1",
            },
        ],
    )
    verdict = attest_transcript(
        transcript,
        frozenset({"claude-opus-4-8"}),
        carrier="claude",
        gbai_case=EXPLICIT_SELF_ENFORCED,
        self_enforcement_guard=SelfEnforcementGuard("guard", lane_rewritable=False),
    )
    assert verdict.admissible is True


def test_unsupported_carrier_fails_closed(tmp_path: Path) -> None:
    transcript = tmp_path / "x.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    verdict = attest_transcript(transcript, frozenset({"whatever"}), carrier="gemini")
    assert verdict.status == "unsupported_execution_observer"
    assert verdict.admissible is False
    assert verdict.failure_reasons == ("unsupported_carrier",)


def test_lbg_allowlist_is_versioned_and_curated() -> None:
    allowlist = load_lbg_allowlist()
    assert allowlist.version == 1
    assert is_load_bearing_governance_surface("shared/execution_observer.py")
    assert not is_load_bearing_governance_surface("shared/capability_availability_guarantor.py")
    with pytest.raises(ValueError, match="unsupported LBG allowlist version"):
        load_lbg_allowlist(999)


def test_gate2_locality_accepts_only_local_interceptor() -> None:
    assert assert_gate2_locality(GATE2_LOCAL_INTERCEPTOR) == GATE2_LOCAL_INTERCEPTOR
    with pytest.raises(ValueError, match="Gate 2 locality violation"):
        assert_gate2_locality("harness_round_trip")
    with pytest.raises(ValueError, match="Gate 2 locality violation"):
        assert_gate2_locality("remote service")
