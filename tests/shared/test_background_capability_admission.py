"""Tests for background capability admission through the real dispatch policy."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from shared.dispatcher_policy import build_route_authority_receipt, write_route_authority_receipt
from shared.fix_capabilities.background_admission import admit_background_capability

NOW = datetime(2026, 6, 4, 16, 30, tzinfo=UTC)
NOW_ISO = NOW.isoformat().replace("+00:00", "Z")
REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORM_RECEIPT_SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"
QUOTA_FIXTURE = Path("config/quota-spend-ledger-fixtures.json")


def _provider_task_fields() -> dict[str, object]:
    return {
        "task_id": "task-background-model",
        "status": "claimed",
        "assigned_to": "background",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "spec.md",
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "provider_spend",
        "provider_spend_authorized": True,
        "mutation_scope_refs": ["background:model"],
        "risk_flags": {},
        "kind": "hardening",
    }


def _runtime_task_fields(
    *,
    task_id: str = "task-background-runtime",
    quality_floor: str = "deterministic_ok",
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "status": "claimed",
        "assigned_to": "background",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "spec.md",
        "quality_floor": quality_floor,
        "authority_level": "authoritative",
        "mutation_surface": "runtime",
        "runtime_mutation_authorized": True,
        "mutation_scope_refs": ["background:runtime"],
        "risk_flags": {},
        "kind": "hardening",
    }


def _source_only_task_fields() -> dict[str, object]:
    return {
        "task_id": "task-background-source",
        "status": "claimed",
        "assigned_to": "background",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "spec.md",
        "quality_floor": "frontier_review_required",
        "authority_level": "support_non_authoritative",
        "mutation_surface": "source",
        "source_mutation_authorized": True,
        "provider_spend_authorized": False,
        "runtime_mutation_authorized": False,
        "mutation_scope_refs": ["background:source"],
        "risk_flags": {},
        "kind": "hardening",
    }


def _write_provider_gateway_receipt(receipt_dir: Path) -> None:
    observed = NOW.isoformat().replace("+00:00", "Z")
    receipt = {
        "receipt_schema": 1,
        "receipt_id": "test-api-provider-gateway",
        "platform": "api",
        "routes": ["api.headless.provider_gateway"],
        "observed_at": observed,
        "stale_after": "1h",
        "cli": {"binary": "litellm", "available": True, "version": "test"},
        "wrapper": {
            "path": "scripts/hapax-methodology-dispatch",
            "exists": True,
            "executable": True,
        },
        "config_refs": [],
        "tool_state": [],
        "mcp_status": [],
        "capability": {
            "status": "observed",
            "source": "test",
            "observed_at": observed,
            "stale_after": "1h",
            "evidence_refs": ["test:capability"],
            "reason_codes": [],
        },
        "resource": {
            "status": "observed",
            "source": "test",
            "observed_at": observed,
            "stale_after": "1h",
            "evidence_refs": ["test:resource"],
            "reason_codes": [],
        },
        "quota": {
            "status": "unobservable",
            "source": "test",
            "observed_at": observed,
            "stale_after": "1h",
            "evidence_refs": [],
            "reason_codes": ["quota_telemetry_unknown"],
        },
        "provider_docs": {
            "refs": ["test:provider-docs"],
            "fetched_at": observed,
            "stale_after": "30d",
            "fetch_status": "observed",
        },
        "known_unknowns": [],
    }
    (receipt_dir / "api.json").write_text(json.dumps(receipt), encoding="utf-8")


def _write_runtime_actuation_receipt(
    receipt_dir: Path,
    *,
    route_id: str,
    task_id: str,
) -> None:
    receipt = build_route_authority_receipt(
        receipt_type="runtime_actuation",
        route_id=route_id,
        evidence_refs=[f"test:runtime-actuation:{route_id}:{task_id}"],
        receipt_id=f"runtime-{route_id.replace('.', '-')}",
        task_ids=[task_id],
        mutation_surfaces=["runtime"],
        issued_at=NOW,
        stale_after="24h",
    )
    write_route_authority_receipt(receipt, receipt_dir=receipt_dir)


def _write_codex_platform_receipt(receipt_dir: Path) -> None:
    bin_dir = receipt_dir / "bin"
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text("#!/bin/sh\nprintf '%s\\n' 'codex-cli 9.9.9'\n", encoding="utf-8")
    codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    result = subprocess.run(
        [
            sys.executable,
            str(PLATFORM_RECEIPT_SCRIPT),
            "--registry",
            str(REGISTRY),
            "--receipt-dir",
            str(receipt_dir),
            "--platform",
            "codex",
            "--now",
            NOW_ISO,
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def test_background_model_call_refuses_without_platform_receipt(tmp_path: Path) -> None:
    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-3.1-pro-preview",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome == "hold"
    assert "unsupported_route" not in admission.reason_codes
    assert "provider_gateway_evidence_absent" in admission.denial_summary()


def test_background_model_call_refuses_offered_unassigned_task(tmp_path: Path) -> None:
    fields = _provider_task_fields()
    fields["status"] = "offered"
    fields["assigned_to"] = "unassigned"

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        task_fields=fields,
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome is None
    assert admission.reason_codes == ("inactive_task_status",)
    assert "status=offered" in (admission.denied_reason or "")


def test_background_runtime_fix_refuses_inactive_task_assignee(tmp_path: Path) -> None:
    fields = _runtime_task_fields()
    fields["assigned_to"] = None

    admission = admit_background_capability(
        capability_name="health_monitor.legacy_remediation_shell",
        route_id="local_tool.local.worker",
        task_fields=fields,
        mutation_surface="runtime",
        quality_floor="deterministic_ok",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome is None
    assert admission.reason_codes == ("inactive_task_assignee",)
    assert "assigned_to=<absent>" in (admission.denied_reason or "")


def test_background_model_call_refuses_when_task_surface_does_not_authorize_provider_spend(
    tmp_path: Path,
) -> None:
    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-3.1-pro-preview",
        task_fields=_source_only_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome is None
    assert admission.reason_codes == ("task_mutation_surface_not_authorized",)
    assert admission.denial_summary() == "task_mutation_surface_not_authorized"


def test_background_model_call_cannot_elevate_task_authority(tmp_path: Path) -> None:
    fields = _provider_task_fields()
    fields["authority_level"] = "support_non_authoritative"

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        task_fields=fields,
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.reason_codes == ("task_authority_level_not_authorized",)
    assert "requested=authoritative" in (admission.denied_reason or "")


def test_background_model_call_cannot_raise_task_quality_floor(tmp_path: Path) -> None:
    fields = _provider_task_fields()
    fields["quality_floor"] = "deterministic_ok"

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        task_fields=fields,
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.reason_codes == ("task_quality_floor_not_authorized",)
    assert "declared=deterministic_ok" in (admission.denied_reason or "")


def test_background_model_call_admits_when_model_matches_route_descriptor(tmp_path: Path) -> None:
    _write_provider_gateway_receipt(tmp_path)

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-3.1-pro-preview",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is True
    assert admission.policy_outcome == "launch"
    assert admission.reason_codes == ("policy_launch",)
    assert admission.quota_evidence_refs == ("tb-20260510-anthropic-api-steady-state",)
    assert admission.model_descriptor["execution_descriptor"]["model_id"] == (
        "gemini-3.1-pro-preview"
    )


def test_provider_model_call_admits_declared_gateway_alias(
    tmp_path: Path,
) -> None:
    _write_provider_gateway_receipt(tmp_path)

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is True
    assert admission.policy_outcome == "launch"
    assert admission.route_id == "api.headless.provider_gateway"
    aliases = {
        alias["alias"]: alias for alias in admission.model_descriptor["provider_model_aliases"]
    }
    assert aliases["gemini-flash"]["model_id"] == "gemini-3.1-pro-preview"


def test_fix_evaluator_model_call_refuses_undeclared_provider_gateway_alias(
    tmp_path: Path,
) -> None:
    _write_provider_gateway_receipt(tmp_path)

    admission = admit_background_capability(
        capability_name="health_monitor.fix_evaluator.llm",
        route_id="api.headless.provider_gateway",
        model_alias="claude-sonnet",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome is None
    assert admission.reason_codes == ("provider_model_descriptor_mismatch",)
    assert "requested_model=claude-sonnet" in (admission.denied_reason or "")


def test_director_provider_model_call_refuses_undeclared_provider_gateway_model(
    tmp_path: Path,
) -> None:
    _write_provider_gateway_receipt(tmp_path)

    admission = admit_background_capability(
        capability_name="studio.director.llm",
        route_id="api.headless.provider_gateway",
        model_alias="unregistered-provider-model",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome is None
    assert admission.route_id == "api.headless.provider_gateway"
    assert admission.model_alias == "unregistered-provider-model"
    assert admission.reason_codes == ("provider_model_descriptor_mismatch",)


def test_local_worker_runtime_fix_refuses_through_real_policy(tmp_path: Path) -> None:
    task_id = "task-background-runtime"

    admission = admit_background_capability(
        capability_name="health_monitor.fix.mock.restart",
        route_id="local_tool.local.worker",
        task_fields=_runtime_task_fields(task_id=task_id),
        mutation_surface="runtime",
        quality_floor="deterministic_ok",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome == "refuse"
    assert admission.reason_codes == ("runtime_actuation_receipt_absent",)
    assert admission.model_descriptor["execution_descriptor"]["model_id"] == "command-r-08-2024"


def test_local_worker_model_call_refuses_mismatched_served_leaf(tmp_path: Path) -> None:
    admission = admit_background_capability(
        capability_name="dmn.local_sensory.llm",
        route_id="local_tool.local.worker",
        model_alias="Qwen3.5-9B-exl3-5.00bpw",
        task_fields=_runtime_task_fields(task_id="task-background-local-model"),
        mutation_surface="none",
        quality_floor="deterministic_ok",
        authority_level="support_only",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome is None
    assert admission.reason_codes == ("model_descriptor_mismatch",)
    assert "requested_model=Qwen3.5-9B-exl3-5.00bpw" in (admission.denied_reason or "")
    assert "command-r-08-2024" in (admission.denied_reason or "")


def test_local_worker_refuses_unbound_local_fast_alias(tmp_path: Path) -> None:
    admission = admit_background_capability(
        capability_name="studio.director.llm",
        route_id="local_tool.local.worker",
        model_alias="local-fast",
        task_fields=_runtime_task_fields(task_id="task-background-local-fast"),
        mutation_surface="none",
        quality_floor="deterministic_ok",
        authority_level="support_only",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome is None
    assert admission.reason_codes == ("model_descriptor_mismatch",)
    assert "requested_model=local-fast" in (admission.denied_reason or "")
    assert "command-r-08-2024" in (admission.denied_reason or "")


def test_background_admission_refuses_unregistered_route_with_model_alias(tmp_path: Path) -> None:
    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.missing",
        model_alias="gemini-flash",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome is None
    assert admission.reason_codes == ("model_route_unregistered",)
    assert admission.denied_reason == (
        "model_route_unregistered:route=api.headless.missing model=gemini-flash"
    )


def test_background_admission_refuses_invalid_route_id(tmp_path: Path) -> None:
    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="not-a-route",
        model_alias="gemini-flash",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.denied_reason == "invalid_route_id:not-a-route"


def test_background_admission_refuses_absent_task_note(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HAPAX_BACKGROUND_CAPABILITY_TASK_NOTE", raising=False)

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-3.1-pro-preview",
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.denied_reason is not None
    assert admission.denied_reason.startswith("task_note_absent:")


def test_background_admission_refuses_task_note_without_task_id(tmp_path: Path) -> None:
    fields = _provider_task_fields()
    fields.pop("task_id")

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        task_fields=fields,
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.denied_reason == "task_id_absent"


def test_background_admission_refuses_provider_spend_without_parent_spec(
    tmp_path: Path,
) -> None:
    fields = _provider_task_fields()
    fields.pop("parent_spec")

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-3.1-pro-preview",
        task_fields=fields,
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.denied_reason == "parent_spec_absent"
    assert admission.reason_codes == ("parent_spec_absent",)


def test_background_admission_refuses_unreadable_task_note(tmp_path: Path) -> None:
    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        task_note_path=tmp_path / "missing-task.md",
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.denied_reason is not None
    assert admission.denied_reason.startswith("task_note_unreadable:")


def test_background_admission_denies_when_route_decision_receipt_write_fails(
    tmp_path: Path,
) -> None:
    _write_provider_gateway_receipt(tmp_path)

    with patch(
        "shared.fix_capabilities.background_admission.write_route_decision_receipt",
        side_effect=OSError("readonly"),
    ):
        admission = admit_background_capability(
            capability_name="studio.scene_classifier.llm",
            route_id="api.headless.provider_gateway",
            model_alias="gemini-3.1-pro-preview",
            task_fields=_provider_task_fields(),
            mutation_surface="provider_spend",
            quality_floor="frontier_required",
            receipt_dir=tmp_path,
            quota_ledger_path=QUOTA_FIXTURE,
            now=NOW,
            write_receipt=True,
        )

    assert admission.admitted is False
    assert admission.reason_codes == ("route_decision_receipt_write_failed",)
    assert "readonly" in (admission.denied_reason or "")


def test_runtime_fix_route_admits_with_platform_and_runtime_receipts(tmp_path: Path) -> None:
    task_id = "task-background-runtime"
    _write_codex_platform_receipt(tmp_path)
    _write_runtime_actuation_receipt(
        tmp_path,
        route_id="codex.headless.full",
        task_id=task_id,
    )

    admission = admit_background_capability(
        capability_name="health_monitor.fix.mock.restart",
        route_id="codex.headless.full",
        task_fields=_runtime_task_fields(task_id=task_id, quality_floor="frontier_required"),
        mutation_surface="runtime",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is True
    assert admission.policy_outcome == "launch"
    assert any(
        reason.startswith("route-authority-receipt:runtime_actuation:codex.headless.full:")
        for reason in admission.reason_codes
    )
