"""Effect-purity tests for the Gate-0A ``cc-dispatch`` intake surface."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from shared.capability_dispatch import DEFAULT_REGISTRY_PATH, verify_dispatch_carrier
from shared.platform_capability_registry import (
    PlatformCapabilityRegistry,
    PlatformCapabilityRegistryError,
)

_CC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cc-dispatch"
FRESH_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def _load():
    loader = SourceFileLoader("cc_dispatch_cli", str(_CC_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _registry(*, available: bool) -> PlatformCapabilityRegistry:
    payload = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not available:
        return PlatformCapabilityRegistry.model_validate(payload)
    route = next(item for item in payload["routes"] if item["route_id"] == "codex.headless.full")
    observed = "2026-07-12T11:59:00Z"
    route["route_state"] = "active"
    route["blocked_reasons"] = []
    for surface in ("capability", "quota", "resource", "provider_docs"):
        route["freshness"][f"{surface}_checked_at"] = observed
        route["freshness"]["evidence"][surface] = {
            "evidence_refs": [f"test:codex:{surface}"],
            "blocked_reasons": [],
        }
    for score in route["capability_scores"].values():
        score["observed_at"] = observed
    for tool in route["tool_state"]:
        tool["observed_at"] = observed
    return PlatformCapabilityRegistry.model_validate(payload)


def _patch_registry(monkeypatch, module, *, available: bool = True) -> None:
    monkeypatch.setattr(module, "load_capability_registry", lambda: _registry(available=available))
    if available:
        original = module.resolve_capability
        monkeypatch.setattr(
            module,
            "resolve_capability",
            lambda name, *, registry: original(name, registry=registry, now=FRESH_NOW),
        )


def _carrier(stdout: str) -> dict:
    return json.loads(stdout.strip().splitlines()[-1])


def _support(carrier: dict, code: str) -> object:
    matches = [item for item in carrier["support"] if item["code"] == code]
    assert len(matches) == 1
    assert matches[0]["claim_ceiling"] == "support_non_authoritative"
    return matches[0]["value"]


def test_list_labels_catalogue_state_without_launchability_claim(monkeypatch, capsys) -> None:
    module = _load()
    _patch_registry(monkeypatch, module)
    assert module.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "codex" in output and "codex.headless.full" in output
    assert "[available]" in output
    assert "agy-review" in output and "[held]" in output
    assert "launchable" not in output.lower()


def test_validate_emits_only_an_exact_non_authorizing_carrier(monkeypatch, capsys) -> None:
    module = _load()
    _patch_registry(monkeypatch, module)
    assert module.main(["codex", "cc-task-x", "--lane", "cx-red"]) == 0
    captured = capsys.readouterr()
    carrier = _carrier(captured.out)
    assert captured.err == ""
    assert verify_dispatch_carrier(carrier)
    assert carrier["requested_operation"] == "validate"
    assert _support(carrier, "capability.name") == "codex"
    assert _support(carrier, "capability.state") == "available"
    assert _support(carrier, "task.validation_state") == "not_evaluated"
    assert carrier["effect_state"] == "held_not_admitted"
    assert carrier["materialization_state"] == "not_materialized"


def test_compatibility_launch_is_still_inert(monkeypatch, capsys) -> None:
    module = _load()
    _patch_registry(monkeypatch, module)
    assert module.main(["codex", "cc-task-x", "--lane", "cx-red", "--launch"]) == 0
    captured = capsys.readouterr()
    carrier = _carrier(captured.out)
    assert "compatibility-only" in captured.err
    assert carrier["requested_operation"] == "launch"
    assert carrier["effect_state"] == "held_not_admitted"
    assert carrier["materialization_state"] == "not_materialized"
    assert verify_dispatch_carrier(carrier)


def test_held_route_emits_a_held_intake_carrier_not_false_availability(monkeypatch, capsys) -> None:
    module = _load()
    _patch_registry(monkeypatch, module, available=False)
    assert module.main(["codex", "cc-task-x", "--lane", "cx-red"]) == 0
    captured = capsys.readouterr()
    carrier = _carrier(captured.out)
    assert "HOLD route_held" in captured.err
    assert _support(carrier, "capability.state") == "held"
    assert _support(carrier, "capability.blocker_reasons")
    assert verify_dispatch_carrier(carrier)


def test_correlation_values_never_imply_mq_or_persistence(monkeypatch, capsys) -> None:
    module = _load()
    _patch_registry(monkeypatch, module)
    argv = [
        "codex",
        "cc-task-x",
        "--lane",
        "cx-red",
        "--mq-message-id",
        "M1",
        "--idempotency-key",
        "K1",
    ]
    assert module.main(argv) == 0
    carrier = _carrier(capsys.readouterr().out)
    assert carrier["correlation"] == {
        "schema": "hapax.dispatch-correlation.v1",
        "idempotency_key": "K1",
        "mq_message_id": "M1",
    }


def test_unknown_and_unrouted_capabilities_hold_without_carrier(monkeypatch, capsys) -> None:
    module = _load()
    _patch_registry(monkeypatch, module)
    assert module.main(["bogus", "cc-task-x", "--lane", "cx-red"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "HOLD capability_unknown" in captured.err

    assert module.main(["fugu", "cc-task-x", "--lane", "cx-red"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "HOLD capability_held" in captured.err


def test_registry_failure_is_a_visible_hold(monkeypatch, capsys) -> None:
    module = _load()

    def fail():
        raise PlatformCapabilityRegistryError("typed fixture invalid")

    monkeypatch.setattr(module, "load_capability_registry", fail)
    assert module.main(["codex", "cc-task-x", "--lane", "cx-red"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "HOLD registry_unknown" in captured.err


def test_utilization_fails_visibly_unknown_without_reading_legacy_jsonl(capsys) -> None:
    module = _load()
    assert module.main(["--utilization"]) == 3
    output = capsys.readouterr().out
    assert "utilization: UNKNOWN" in output
    assert "support-only" in output
    assert "ACTIVE (" not in output and "LATENT (" not in output


def test_reserved_route_and_effect_flags_are_rejected(monkeypatch) -> None:
    module = _load()
    _patch_registry(monkeypatch, module)
    for bad in (
        ["--platform", "claude"],
        ["--no-receipt"],
        ["--task", "other"],
        ["--skip-worktree-check"],
    ):
        with pytest.raises(SystemExit):
            module.main(["codex", "cc-task-x", "--lane", "cx-red", *bad])


def test_missing_request_fields_fail_before_projection(monkeypatch) -> None:
    module = _load()
    _patch_registry(monkeypatch, module)
    with pytest.raises(SystemExit):
        module.main([])
    with pytest.raises(SystemExit):
        module.main(["codex", "cc-task-x"])


def test_script_has_no_actuator_writer_or_human_prose_authority_parser() -> None:
    source = _CC_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "subprocess" not in imported_roots
    assert "os" not in imported_roots
    for forbidden in (
        "hapax-methodology-dispatch",
        "--list-platform-paths",
        "read_dispatch_ledger",
        "ledger_health",
        "relay_mq",
        "write_text",
        "write_bytes",
        "mkdir(",
        "unlink(",
        "exec(",
        "Popen(",
        "subprocess.run",
    ):
        assert forbidden not in source


def test_real_script_leaves_home_and_requested_directory_untouched(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    proc = subprocess.run(
        [
            sys.executable,
            str(_CC_PATH),
            "codex",
            "cc-task-nonexistent-is-still-intake",
            "--lane",
            "cx-red",
            "--launch",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert proc.returncode == 0
    assert before == after
    carrier = _carrier(proc.stdout)
    assert _support(carrier, "task.validation_state") == "not_evaluated"
    assert carrier["effect_state"] == "held_not_admitted"
    assert carrier["materialization_state"] == "not_materialized"
    assert verify_dispatch_carrier(carrier)
