"""CEI session attestation (close-gate core)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from shared.execution_attestation import attest_transcript, sanctioned_models_for_route


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _stub_registry(
    route_id: str,
    model_id: str,
    variant_models: list[str] | None = None,
    blocked_variant_models: list[str] | None = None,
    route_blocked_reasons: list[str] | None = None,
):
    variants = [
        SimpleNamespace(knobs_override={"model_id": vm}, blocked_reasons=[])
        for vm in (variant_models or [])
    ]
    variants.extend(
        SimpleNamespace(
            knobs_override={"model_id": vm},
            blocked_reasons=["quota_telemetry_unknown"],
        )
        for vm in (blocked_variant_models or [])
    )
    route = SimpleNamespace(
        execution_descriptor=SimpleNamespace(model_id=model_id),
        descriptor_variants=variants,
        blocked_reasons=route_blocked_reasons or [],
    )
    return SimpleNamespace(route_map=lambda: {route_id: route})


def test_sanctioned_models_from_route_descriptor() -> None:
    reg = _stub_registry("claude.headless.opus", "claude-opus-4-8")
    assert sanctioned_models_for_route("claude.headless.opus", reg) == frozenset(
        {"claude-opus-4-8"}
    )


def test_sanctioned_models_include_variant_overrides() -> None:
    reg = _stub_registry(
        "local_tool.local.worker", "command-r-08-2024", variant_models=["qwen3.5-9b"]
    )
    assert sanctioned_models_for_route("local_tool.local.worker", reg) == frozenset(
        {"command-r-08-2024", "qwen3.5-9b"}
    )


def test_sanctioned_models_exclude_blocked_variant_overrides() -> None:
    reg = _stub_registry(
        "local_tool.local.worker",
        "command-r-08-2024",
        variant_models=["qwen3.5-9b"],
        blocked_variant_models=["blocked-model"],
    )
    models = sanctioned_models_for_route("local_tool.local.worker", reg)
    assert models == frozenset({"command-r-08-2024", "qwen3.5-9b"})
    assert "blocked-model" not in models


def test_sanctioned_models_exclude_blocked_routes_fail_closed() -> None:
    reg = _stub_registry(
        "local_tool.local.worker",
        "command-r-08-2024",
        variant_models=["qwen3.5-9b"],
        route_blocked_reasons=["quota_telemetry_unknown"],
    )
    assert sanctioned_models_for_route("local_tool.local.worker", reg) == frozenset()


def test_unknown_route_sanctions_nothing_fail_closed() -> None:
    reg = _stub_registry("claude.headless.opus", "claude-opus-4-8")
    assert sanctioned_models_for_route("no.such.route", reg) == frozenset()


def test_attest_transcript_satisfied(tmp_path: Path) -> None:
    t = _write(
        tmp_path / "t.jsonl",
        [{"type": "assistant", "message": {"model": "claude-opus-4-8"}}],
    )
    v = attest_transcript(t, frozenset({"claude-opus-4-8"}), carrier="claude")
    assert v.status == "execution_invariant_satisfied"
    assert v.admissible is True


def test_attest_transcript_catches_fallback_drift(tmp_path: Path) -> None:
    t = _write(
        tmp_path / "t.jsonl",
        [
            {"type": "assistant", "message": {"model": "claude-fable-5"}},
            {
                "type": "system",
                "subtype": "model_refusal_fallback",
                "originalModel": "claude-fable-5",
                "fallbackModel": "claude-opus-4-8",
            },
        ],
    )
    v = attest_transcript(t, frozenset({"claude-fable-5"}), carrier="claude")
    assert v.status == "unsanctioned_fallback_observed"
    assert v.admissible is False


def test_attest_codex_carrier(tmp_path: Path) -> None:
    t = _write(
        tmp_path / "rollout.jsonl",
        [{"type": "turn_context", "payload": {"model": "gpt-5.5"}}],
    )
    v = attest_transcript(t, frozenset({"gpt-5.5"}), carrier="codex")
    assert v.admissible is True


def test_unsupported_carrier_fails_closed(tmp_path: Path) -> None:
    t = tmp_path / "x.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    v = attest_transcript(t, frozenset({"whatever"}), carrier="gemini")
    assert v.status == "unsupported_execution_observer"
    assert v.admissible is False
