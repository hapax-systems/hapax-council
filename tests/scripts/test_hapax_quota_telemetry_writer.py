"""Tests for the live quota/resource telemetry writer (routing Phase 0.4)."""

from __future__ import annotations

import json
import os
import runpy
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-quota-telemetry-writer"
CLAUDE_ADMISSION_SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-subscription-quota-admission"
FIXTURES = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"
NOW = "2026-06-10T00:00:00Z"
PAYG_NOW = "2026-07-06T14:05:00Z"


def _fake_nvidia_smi(tmp_path: Path, body: str) -> Path:
    stub = tmp_path / "fake-nvidia-smi"
    stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _run_writer(
    tmp_path: Path,
    *extra_args: str,
    nvidia_body: str = "echo '1000, 32000'",
    now: str = NOW,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir(exist_ok=True)
    platform_receipts.mkdir(exist_ok=True)
    stub = _fake_nvidia_smi(tmp_path, nvidia_body)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skip-receipts",
            "--now",
            now,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT),
            "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR": str(platform_receipts),
        },
    )
    return result, out


def test_capability_receipt_refresh_preserves_codex_exec_auth_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert capture_output is True
        assert text is True
        assert timeout == 36
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)

    assert namespace["refresh_capability_receipts"](timeout=12) is True
    assert calls == [
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"),
            "--all",
            "--codex-exec-auth-probe",
            "--timeout",
            "12",
        ]
    ]


def _wall_receipt(
    relay: Path,
    role: str,
    resets_at: str,
    *,
    failure_class: str = "quota_exhausted",
) -> None:
    (relay / f"{role}-quota-wall.yaml").write_text(
        f"""role: {role}
status: quota_blocked
detected_at: 2026-06-09T23:00:00Z
signal_kind: rate_limit_event
failure_class: {failure_class}
rate_limit_type: {failure_class}
resets_at: {resets_at}
is_overage: False
action: exit_clean_await_restart
""",
        encoding="utf-8",
    )


def _codex_platform_receipt(
    receipt_dir: Path,
    *,
    reason_code: str,
    observed_at: str = "2026-06-09T23:59:00Z",
) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "receipt_schema": 1,
        "receipt_id": "codex-auth-blocked-test",
        "platform": "codex",
        "routes": ["codex.headless.full"],
        "observed_at": observed_at,
        "stale_after": "15m",
        "cli": {"binary": "codex", "available": True, "version": "codex-test"},
        "wrapper": {
            "path": "scripts/hapax-codex-headless",
            "exists": True,
            "executable": True,
            "sha256": None,
        },
        "config_refs": [],
        "tool_state": [],
        "mcp_status": [],
        "capability": {
            "status": "blocked",
            "source": "live",
            "observed_at": observed_at,
            "stale_after": "15m",
            "evidence_refs": [],
            "reason_codes": ["codex_exec_auth_failed", reason_code],
        },
        "resource": {
            "status": "blocked",
            "source": "live",
            "observed_at": observed_at,
            "stale_after": "15m",
            "evidence_refs": [],
            "reason_codes": ["codex_exec_auth_failed", reason_code],
        },
        "quota": {
            "status": "observed",
            "source": "live",
            "observed_at": observed_at,
            "stale_after": "15m",
            "evidence_refs": ["test:quota:observed"],
            "reason_codes": [],
        },
        "provider_docs": {
            "refs": ["test:provider-docs"],
            "fetched_at": observed_at,
            "stale_after": "7d",
            "fetch_status": "observed",
        },
        "known_unknowns": [],
    }
    (receipt_dir / "codex.json").write_text(json.dumps(payload), encoding="utf-8")


def _glmcp_admission(
    relay: Path,
    *,
    observed_at: str,
    stale_after_seconds: int = 900,
    evidence_ref: str = "supported-tool-usage-witness",
    supported_tool: str = "hapax-glmcp-reviewer",
    endpoint: str = "https://api.z.ai/api/coding/paas/v4",
    model: str = "glm-5.2",
    name: str = "glmcp-quota-admission.yaml",
    timestamp_field: str = "observed_at",
    capacity_pool: str | None = None,
    billing_mode: str | None = None,
    payg_fallback: str | None = None,
    primary_error_class: str | None = None,
    quota_wall_evidence_ref: str | None = None,
) -> None:
    if capacity_pool is None:
        capacity_pool = (
            "api_paid_spend" if endpoint == "https://api.z.ai/api/paas/v4" else "subscription_quota"
        )
    if billing_mode is None:
        billing_mode = (
            "api_credit_payg"
            if endpoint == "https://api.z.ai/api/paas/v4"
            else "coding_plan_subscription"
        )
    if payg_fallback is None:
        payg_fallback = "true" if endpoint == "https://api.z.ai/api/paas/v4" else "false"
    extra_payg_fields = ""
    if endpoint == "https://api.z.ai/api/paas/v4":
        if primary_error_class is None:
            primary_error_class = "quota_exhausted"
        if quota_wall_evidence_ref is None:
            quota_wall_evidence_ref = "cx-glmcp-quota-wall.yaml"
        extra_payg_fields = (
            f"primary_error_class: {primary_error_class}\n"
            f"quota_wall_evidence_ref: {quota_wall_evidence_ref}\n"
        )
    (relay / name).write_text(
        f"""schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: {capacity_pool}
route_id: glmcp.review.direct
supported_tool: {supported_tool}
endpoint: {endpoint}
model: {model}
{timestamp_field}: {observed_at}
stale_after_seconds: {stale_after_seconds}
evidence_ref: {evidence_ref}
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: {billing_mode}
payg_fallback: {payg_fallback}
{extra_payg_fields}""",
        encoding="utf-8",
    )


def _agy_admission(
    relay: Path,
    *,
    observed_at: str,
    stale_after_seconds: int = 900,
    evidence_ref: str = "agy-gemini31pro-smoke-witness",
    model: str = "gemini-3.1-pro-preview",
    name: str = "agy-quota-admission.yaml",
    secret_value_persisted: str = "false",
) -> None:
    (relay / name).write_text(
        f"""schema: hapax.agy_quota_admission.v1
status: quota_available
provider: google-antigravity-cli-agy
capacity_pool: subscription_quota
route_id: agy.review.direct
supported_tool: hapax-agy-reviewer
model: {model}
observed_at: {observed_at}
stale_after_seconds: {stale_after_seconds}
evidence_ref: {evidence_ref}
secret_source: agy:operator-session
secret_value_persisted: {secret_value_persisted}
prompt_or_output_persisted: false
billing_mode: operator_session_subscription
smoke_command: scripts/hapax-agy-reviewer
smoke_returncode: 0
smoke_stdout_validated: true
positive_admission: true
""",
        encoding="utf-8",
    )


def _glmcp_payg_spend(
    relay: Path,
    *,
    name: str = "glmcp-payg-spend.yaml",
    spend_id: str = "spend-20260706T140430Z-glmcp-payg-review-test",
    task_id: str = "cc-task-glmcp-review-seat-glm52-model-contract-20260706",
    task_hash: str | None = None,
    created_at: str = "2026-07-06T14:04:30Z",
    reconcile_by: str = "2026-07-07T14:04:30Z",
    estimated_cost_usd: str = "0.05",
    extra_fields: str = "",
) -> None:
    task_hash_line = f"task_hash: {task_hash}\n" if task_hash is not None else ""
    (relay / name).write_text(
        f"""schema: hapax.glmcp_payg_spend.v1
status: spend_estimated
spend_id: {spend_id}
task_id: {task_id}
{task_hash_line}authority_case: CASE-CAPACITY-ROUTING-GLMCP-PAYG-20260706
route_id: glmcp.review.direct
capacity_pool: api_paid_spend
budget_id: tb-20260706-zai-glmcp-payg-review
provider: z_ai
model_or_engine: glm-5.2
model_id: z_ai-glm-5.2
effort: none
quantization: not_applicable
auth_surface: api_key
quality_floor: frontier_review_required
quality_preservation_reason: receipt-bounded GLMCP review fallback after Coding Plan quota wall
spend_reason: quota_exhaustion
estimated_cost_usd: {estimated_cost_usd}
created_at: {created_at}
reconcile_by: {reconcile_by}
reconciliation_state: pending
support_artifact_authority: none
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/paas/v4
billing_mode: api_credit_payg
payg_fallback: true
primary_error_class: quota_exhausted
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
{extra_fields}
""",
        encoding="utf-8",
    )


def test_glmcp_admission_recheck_command_uses_scanner_glob() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    receipt_glob = namespace["GLMCP_ADMISSION_RECEIPT_GLOB"]

    assert receipt_glob == "*glmcp-quota-admission*.yaml"
    assert f"-name '{receipt_glob}'" in namespace["GLMCP_ADMISSION_RECHECK_COMMAND"]
    assert "receipt_dir.glob(GLMCP_ADMISSION_RECEIPT_GLOB)" in SCRIPT.read_text(encoding="utf-8")


def test_claude_lane_presence_regex_is_consistent_across_receipt_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLAUDE_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import CLAUDE_ADMISSION_LANE_PRESENCE_RE

    assert (
        telemetry_namespace["CLAUDE_ADMISSION_LANE_PRESENCE_RE"].pattern
        == admission_namespace["LANE_PRESENCE_RE"].pattern
        == CLAUDE_ADMISSION_LANE_PRESENCE_RE.pattern
    )


def test_claude_billingish_regex_is_consistent_across_receipt_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLAUDE_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import CLAUDE_ADMISSION_BILLINGISH_RE

    assert (
        telemetry_namespace["CLAUDE_ADMISSION_BILLINGISH_RE"].pattern
        == admission_namespace["BILLINGISH_RE"].pattern
        == CLAUDE_ADMISSION_BILLINGISH_RE.pattern
    )


def test_claude_witness_allowlist_regex_is_consistent_across_receipt_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLAUDE_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE

    assert (
        telemetry_namespace["CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE"].pattern
        == admission_namespace["WITNESS_ALLOWLIST_RE"].pattern
        == CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE.pattern
    )


def test_claude_secretish_regex_is_consistent_across_receipt_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLAUDE_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import CLAUDE_ADMISSION_SECRETISH_RE

    assert (
        telemetry_namespace["CLAUDE_ADMISSION_SECRETISH_RE"].pattern
        == admission_namespace["SECRETISH_RE"].pattern
        == CLAUDE_ADMISSION_SECRETISH_RE.pattern
    )


def test_claude_account_live_quota_suffix_tokens_are_consistent_across_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.platform_capability_registry import _ref_tokens
    from shared.quota_spend_ledger import (
        CLAUDE_ADMISSION_ACCOUNT_LIVE_QUOTA_SUFFIX as LEDGER_SUFFIX,
    )

    suffix_tokens = ("account", "live", "quota", "observed")
    assert _ref_tokens(telemetry_namespace["CLAUDE_ADMISSION_ACCOUNT_LIVE_QUOTA_SUFFIX"]) == (
        suffix_tokens
    )
    assert _ref_tokens(LEDGER_SUFFIX) == suffix_tokens


def test_writes_valid_live_ledger_with_fresh_captured_at(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["captured_at"] == NOW
    assert payload["ledger_id"].startswith("quota-spend-ledger-live-")
    assert payload["local_resource_state"] in {"green", "yellow"}

    # The output revalidates through the fail-closed loader.
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import load_quota_spend_ledger

    ledger = load_quota_spend_ledger(out)
    states = {
        snapshot.route_id: snapshot.subscription_quota_state.value
        for snapshot in ledger.quota_snapshots
    }
    # claude.headless.full is now receipt-bounded (like agy): unknown without a fresh admission
    # receipt — account-live quota is never inferred from lane/session presence or wall-absence.
    assert states["claude.headless.full"] == "unknown"
    assert states["codex.headless.full"] == "fresh"
    assert states["agy.review.direct"] == "unknown"
    assert "gemini.headless.full" not in states
    assert states["glmcp.review.direct"] == "unknown"
    assert states["litellm.local.command-r-35b"] == "fresh"


def test_codex_snapshot_unknown_when_exec_auth_receipt_reports_refresh_token_invalidated(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        reason_code="codex_exec_auth_refresh_token_invalidated",
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_exec_auth_refresh_token_invalidated" in codex_snapshot["operator_visible_reason"]
    assert (
        "codex-auth-blocker:codex_exec_auth_refresh_token_invalidated"
        in codex_snapshot["evidence_refs"]
    )


def test_codex_snapshot_unknown_when_platform_receipt_is_invalid(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts-invalid"
    platform_receipts.mkdir()
    (platform_receipts / "codex.json").write_text("[not a mapping]", encoding="utf-8")

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_platform_capability_receipt_invalid" in codex_snapshot["operator_visible_reason"]
    assert (
        "codex-auth-blocker:codex_platform_capability_receipt_invalid"
        in codex_snapshot["evidence_refs"]
    )


def test_governance_records_carry_over_unchanged(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    live = json.loads(out.read_text(encoding="utf-8"))
    base = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for key in (
        "transition_budgets",
        "spend_receipts",
        "spend_gate_decisions",
        "provider_dependencies",
        "artifact_provenance",
        "renewal_records",
        "authority_source",
        "paid_api_budget_freshness_ttl_s",
    ):
        assert live[key] == base[key], f"{key} must not be rewritten by telemetry"


def test_unexpired_quota_wall_marks_platform_exhausted(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "theta", "2026-06-10T06:00:00Z")
    _wall_receipt(relay, "cx-amber", "2026-06-09T06:00:00Z")  # expired -> ignored

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["claude.headless.full"] == "exhausted"
    assert states["codex.headless.full"] == "fresh"
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 1}


def test_retired_gemini_quota_wall_receipts_warn_and_do_not_seed_routes(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "gemini-iota", "2026-06-10T06:00:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "WARNING ignoring retired Gemini quota-wall receipt" in result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    route_ids = {snapshot["route_id"] for snapshot in payload["quota_snapshots"]}
    assert all(not route_id.startswith("gemini.") for route_id in route_ids)
    summary = json.loads(result.stdout)
    assert "retired-gemini" not in summary["quota_walls"]


def test_glmcp_role_quota_wall_maps_to_glmcp_not_codex(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "cx-glmcp", "2026-06-10T06:00:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "exhausted"
    assert states["codex.headless.full"] == "fresh"
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"glmcp": 1}


def test_glmcp_quota_wall_beats_fresh_admission_receipt(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "cx-glmcp", "2026-06-10T06:00:00Z")
    _glmcp_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert "quota wall" in glmcp_snapshot["operator_visible_reason"]
    assert any("cx-glmcp-quota-wall.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert not any("glmcp-quota-admission.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"glmcp": 1}
    assert summary["glmcp_admissions"] == 1
    assert summary["glmcp_payg_spend_receipts"] == 0


def test_claude_quota_wall_beats_fresh_admission_receipt(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "theta", "2026-06-10T06:00:00Z")
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "exhausted"
    assert "quota wall" in snapshot["operator_visible_reason"]
    assert any("theta-quota-wall.yaml" in ref for ref in snapshot["evidence_refs"])
    assert not any(
        "claude-subscription-quota-admission.yaml" in ref for ref in snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 1}
    assert summary["claude_admissions"] == 1


def test_glmcp_payg_spend_receipt_counts_against_budget_gate(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(
        relay,
        name=spend_receipt_name,
        task_hash="sha256:" + ("a" * 64),
    )
    base = tmp_path / "quota-spend-ledger-fixtures.json"
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for budget in base_payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260706-zai-glmcp-payg-review":
            budget["daily_cap_usd"] = "0.05"
    base.write_text(json.dumps(base_payload), encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(base), now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    receipt = next(
        receipt
        for receipt in payload["spend_receipts"]
        if receipt["spend_id"] == "spend-20260706T140430Z-glmcp-payg-review-test"
    )
    assert receipt["task_hash"] == "sha256:" + ("a" * 64)
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert (
        "spend-gate:glmcp.review.direct:refused_exhausted_budget" in glmcp_snapshot["evidence_refs"]
    )
    assert "matching TransitionBudget cap exhausted" in glmcp_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["glmcp_payg_spend_receipts"] == 1


def test_glmcp_payg_spend_receipt_legacy_null_optionals_are_counted(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(
        relay,
        name=spend_receipt_name,
        extra_fields=("actual_cost_usd: None\nreconciled_at: None\nreconciliation_reason: None"),
    )
    base = tmp_path / "quota-spend-ledger-fixtures.json"
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for budget in base_payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260706-zai-glmcp-payg-review":
            budget["created_at"] = "2026-07-06T13:00:00Z"
            budget["expires_at"] = "2026-07-07T13:00:00Z"
            budget["subscription_path_checked_at"] = "2026-07-06T13:00:00Z"
    base.write_text(json.dumps(base_payload), encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(base), now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    receipt = next(
        receipt
        for receipt in payload["spend_receipts"]
        if receipt["spend_id"] == "spend-20260706T140430Z-glmcp-payg-review-test"
    )
    assert "task_hash" not in receipt
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert (
        "spend-gate:glmcp.review.direct:eligible_active_budget" in glmcp_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["glmcp_payg_spend_receipts"] == 1
    assert summary["glmcp_ignored_payg_spend_receipts"] == 0


def test_glmcp_payg_spend_receipt_strips_malformed_task_hash_but_counts_spend(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(relay, name=spend_receipt_name, task_hash="not-a-sha256-hash")

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    receipt = next(
        receipt
        for receipt in payload["spend_receipts"]
        if receipt["spend_id"] == "spend-20260706T140430Z-glmcp-payg-review-test"
    )
    assert "task_hash" not in receipt
    assert "stripped malformed optional task_hash" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_payg_spend_receipts"] == 1
    assert summary["glmcp_ignored_payg_spend_receipts"] == 0


def test_glmcp_payg_admission_rechecks_witness_task_cap(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(relay, name=spend_receipt_name)
    base = tmp_path / "quota-spend-ledger-fixtures.json"
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for budget in base_payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260706-zai-glmcp-payg-review":
            budget["per_task_cap_usd"] = "0.05"
    base.write_text(json.dumps(base_payload), encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(base), now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert (
        "spend-gate:glmcp.review.direct:refused_exhausted_budget" in glmcp_snapshot["evidence_refs"]
    )
    assert "matching TransitionBudget cap exhausted" in glmcp_snapshot["operator_visible_reason"]


def test_glmcp_payg_admission_supersedes_coding_plan_quota_wall(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(relay, name=spend_receipt_name)

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert any("cx-glmcp-quota-wall.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert any(
        "glmcp-quota-admission-payg.yaml" in ref
        and "endpoint:https://api.z.ai/api/paas/v4" in ref
        and "primary_error_class:quota_exhausted" in ref
        and "quota_wall_evidence_ref:cx-glmcp-quota-wall.yaml" in ref
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "PAYG" in glmcp_snapshot["operator_visible_reason"]
    assert any(
        ref == "spend-gate:glmcp.review.direct:eligible_active_budget"
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "spend-gate-budget:tb-20260706-zai-glmcp-payg-review" in glmcp_snapshot["evidence_refs"]
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"glmcp": 1}
    assert summary["glmcp_admissions"] == 1
    assert summary["glmcp_payg_spend_receipts"] == 1


def test_glmcp_payg_admission_does_not_supersede_without_validated_spend_receipt(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref="glmcp-payg-spend-missing.yaml",
    )

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert (
        "spend-gate-blocker:validated-payg-spend-receipt-absent" in glmcp_snapshot["evidence_refs"]
    )
    assert "validated PAYG spend receipt reservation" in glmcp_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 1
    assert summary["glmcp_payg_spend_receipts"] == 0


def test_glmcp_payg_admission_does_not_supersede_wrong_wall_class(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "cx-glmcp",
        "2026-07-06T16:00:00Z",
        failure_class="provider_high_traffic",
    )
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        primary_error_class="quota_exhausted",
    )

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert any(
        "failure_class:provider_high_traffic" in ref for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "matching active quota-wall witness" in glmcp_snapshot["operator_visible_reason"]


def test_glmcp_payg_admission_does_not_supersede_without_active_paid_budget(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260609t235500z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-06-10T06:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(
        relay,
        name=spend_receipt_name,
        spend_id="spend-20260609T235500Z-glmcp-payg-review-test",
        created_at="2026-06-09T23:55:00Z",
        reconcile_by="2026-06-10T23:55:00Z",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert any("cx-glmcp-quota-wall.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert any("glmcp-quota-admission-payg.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert (
        "spend-gate:glmcp.review.direct:refused_expired_budget" in glmcp_snapshot["evidence_refs"]
    )
    assert "spend-gate-budget:tb-20260706-zai-glmcp-payg-review" in glmcp_snapshot["evidence_refs"]
    assert "paid-spend gate" in glmcp_snapshot["operator_visible_reason"]


def test_glmcp_role_aliases_map_to_glmcp_not_codex(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    for role in ("codex-glmcp", "codex_glmcp", "cx_glmcp", "glmcp", "glm-review", "glmcp-seat"):
        _wall_receipt(relay, role, "2026-06-10T06:00:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "exhausted"
    assert states["codex.headless.full"] == "fresh"
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"glmcp": 6}


def test_fresh_glmcp_admission_receipt_marks_glmcp_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["provider"] == "z_ai-glm-coding-plan"
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert glmcp_snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    assert any("glmcp-quota-admission.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert any(
        "witness:supported-tool-usage-witness" in ref
        and "supported_tool:hapax-glmcp-reviewer" in ref
        and "endpoint:https://api.z.ai/api/coding/paas/v4" in ref
        and "model:glm-5.2" in ref
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "finite" in glmcp_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 1


def test_fresh_agy_admission_receipt_marks_agy_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _agy_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["provider"] == "google-antigravity-cli-agy"
    assert agy_snapshot["subscription_quota_state"] == "fresh"
    assert agy_snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    assert any("agy-quota-admission.yaml" in ref for ref in agy_snapshot["evidence_refs"])
    assert any(
        "witness:agy-gemini31pro-smoke-witness" in ref
        and "supported_tool:hapax-agy-reviewer" in ref
        and "model:gemini-3.1-pro-preview" in ref
        for ref in agy_snapshot["evidence_refs"]
    )
    assert "receipt-bounded" in agy_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 1


def _claude_admission(
    relay: Path,
    *,
    observed_at: str,
    stale_after_seconds: str = "900",
    evidence_ref: str = "claude-subscription-headroom-observed-20260609t2355z",
    observation: str = "subscription_quota_headroom_observed",
    secret_value_persisted: str = "false",
    lane_presence_used_as_quota_evidence: str = "false",
    name: str = "claude-subscription-quota-admission.yaml",
) -> None:
    (relay / name).write_text(
        "schema: hapax.claude_quota_admission.v1\n"
        "status: quota_available\n"
        "provider: anthropic-claude-subscription\n"
        "route_id: claude.headless.full\n"
        "capacity_pool: subscription_quota\n"
        "auth_surface: subscription\n"
        f"observation: {observation}\n"
        f"observed_at: {observed_at}\n"
        f"stale_after_seconds: {stale_after_seconds}\n"
        f"evidence_ref: {evidence_ref}\n"
        "secret_source: claude:operator-session-subscription\n"
        f"secret_value_persisted: {secret_value_persisted}\n"
        "prompt_or_output_persisted: false\n"
        "billing_mode: operator_session_subscription\n"
        "account_live_quota_observed: true\n"
        f"lane_presence_used_as_quota_evidence: {lane_presence_used_as_quota_evidence}\n"
        "positive_admission: true\n",
        encoding="utf-8",
    )


def _claude_snapshot(payload: dict) -> dict:
    return next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "claude.headless.full"
    )


def _assert_claude_admission_ignored(tmp_path: Path, expected_reason: str) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "unknown"
    assert any(f":ignored:{expected_reason}" in ref for ref in snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1
    assert "ignoring claude admission receipt: validation failed" in result.stderr


@pytest.mark.parametrize(
    ("name", "expected_reason"),
    [
        (
            "claude-subscription-quota-admission-cus_123.yaml",
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            "claude-subscription-quota-admission-lane2.yaml",
            "receipt-name-names-lane-session-presence",
        ),
        (
            "claude-subscription-quota-admission-token.yaml",
            "receipt-name-names-secretish-value",
        ),
    ],
)
def test_rejected_claude_receipt_name_is_hashed_in_ignored_evidence(
    tmp_path: Path,
    name: str,
    expected_reason: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z", name=name)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    evidence_refs = "\n".join(snapshot["evidence_refs"])
    assert snapshot["subscription_quota_state"] == "unknown"
    assert name not in evidence_refs
    assert f":ignored:{expected_reason}" in evidence_refs
    assert "relay-receipt:unsafe-receipt-name-sha256:" in evidence_refs


def test_fresh_claude_admission_receipt_marks_claude_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["provider"] == "anthropic-claude-subscription"
    assert snapshot["subscription_quota_state"] == "fresh"
    assert snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    ref = next(
        r for r in snapshot["evidence_refs"] if "claude-subscription-quota-admission.yaml" in r
    )
    assert ref.endswith(":account-live-quota:observed")
    assert "witness:claude-subscription-headroom-observed-20260609t2355z" in ref
    assert "observation:subscription_quota_headroom_observed" in ref
    assert "receipt-bounded" in snapshot["operator_visible_reason"]
    assert json.loads(result.stdout)["claude_admissions"] == 1


def test_claude_admission_writer_output_marks_claude_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    admission_result = subprocess.run(
        [
            sys.executable,
            str(CLAUDE_ADMISSION_SCRIPT),
            "--receipt-dir",
            str(relay),
            "--now",
            "2026-06-09T23:55:00Z",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260609t2355z",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert admission_result.returncode == 0, admission_result.stderr

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "fresh"
    assert snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    assert any(
        ref.endswith(":account-live-quota:observed")
        and "claude-subscription-headroom-observed-20260609t2355z" in ref
        for ref in snapshot["evidence_refs"]
    )
    assert json.loads(result.stdout)["claude_admissions"] == 1


def test_fresh_claude_admission_ref_passes_ledger_validator(tmp_path: Path) -> None:
    # Cross-layer contract: the composite ref the telemetry writer emits is exactly what the ledger
    # accepts as claude admission evidence, so the guarantor attests. Pins telemetry <-> ledger.
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    ref = next(
        r for r in snapshot["evidence_refs"] if "claude-subscription-quota-admission.yaml" in r
    )

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import _is_claude_admission_evidence_ref

    assert _is_claude_admission_evidence_ref(ref) is True


def test_fractional_second_claude_admission_ref_is_normalized_for_ledger(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00.123Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "fresh"
    assert snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    ref = next(
        r for r in snapshot["evidence_refs"] if "claude-subscription-quota-admission.yaml" in r
    )
    assert "observed_at:2026-06-09T23:55:00Z:" in ref
    assert "fresh_until:2026-06-10T00:10:00Z:" in ref

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import _is_claude_admission_evidence_ref

    assert _is_claude_admission_evidence_ref(ref) is True


def test_fractional_second_claude_admission_expires_at_normalized_boundary(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00.123Z")

    result, out = _run_writer(tmp_path, now="2026-06-10T00:10:00Z")

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "unknown"
    assert any(":ignored:receipt-expired" in ref for ref in snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1


def test_claude_admission_rejects_lane_presence_evidence_ref(tmp_path: Path) -> None:
    # Defense in depth: even a receipt naming lane/tmux presence is refused by the scanner.
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        evidence_ref="tmux-hapax-claude-eta-present-20260609",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "unknown"
    assert any(":ignored:" in ref for ref in snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1


def test_claude_admission_rejects_secret_persistence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z", secret_value_persisted="true")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "unknown"
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1
    # the receipt field name/value must never echo to stderr (generic warning only).
    assert "secret_value_persisted" not in result.stderr


@pytest.mark.parametrize(
    ("kwargs", "expected_reason"),
    [
        (
            {"observed_at": "2026-06-09T23:00:00Z", "stale_after_seconds": "60"},
            "receipt-expired",
        ),
        ({"observed_at": "2026-06-10T00:01:00Z"}, "observed-at-is-in-the-future"),
        ({"observed_at": "not-a-date"}, "missing-or-malformed-observed-at"),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "stale_after_seconds": "soon"},
            "malformed-stale-after-seconds",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "stale_after_seconds": "0"},
            "non-positive-stale-after-seconds",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "stale_after_seconds": "3601"},
            "stale-after-seconds-exceeds-maximum-3600",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "observation": "lane_presence_seen"},
            "observation-missing-or-unsupported",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "eta"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "cx-theta"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-session-observed-20260609t2355z",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-lane-observed-20260609t2355z",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "vbe-3-headroom"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "mu-headroom"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-sessions-observed-20260609t2355z",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "tmux2-headroom"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-session2-observed-20260609t2355z",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "eta2"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "eta+present"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-headroom-eta2-observed",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude+headroom+eta+observed",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billing-cus_123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billing:cus_123-headroom-20260609",
            },
            "evidence-ref-unsafe-expected-sanitized-account-live-observation-reference",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription-sub_123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription-id-123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription_id_123_headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription+id+123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billing+cus_123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billing-cus.123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-account-acct.123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription-sub.123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-cus123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-sub123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-acct123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billingcus123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-in_123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "sk-live-secret-token-000000000000000000000000",
            },
            "evidence-ref-unsafe-expected-sanitized-account-live-observation-reference",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-si-1abc-headroom",
            },
            "evidence-ref-unsupported-expected-claude-subscription-headroom-witness-reference",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "bad#claude-subscription-quota-admission.yaml",
            },
            "unsafe-receipt-name",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "eta-claude-subscription-quota-admission.yaml",
            },
            "receipt-name-names-lane-session-presence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-lane2.yaml",
            },
            "receipt-name-names-lane-session-presence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-eta2.yaml",
            },
            "receipt-name-names-lane-session-presence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-eta+present.yaml",
            },
            "receipt-name-names-lane-session-presence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-token.yaml",
            },
            "receipt-name-names-secretish-value",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-cus_123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-subscription-id-123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-subscription_id_123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-subscription+id+123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-billing+cus_123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-cus.123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-acct.123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-sub.123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-cus123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-sub123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-acct123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-billingcus123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
    ],
)
def test_claude_admission_fail_closed_validation_cases(
    tmp_path: Path,
    kwargs: dict[str, str],
    expected_reason: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, **kwargs)

    _assert_claude_admission_ignored(tmp_path, expected_reason)


def test_claude_admission_rejects_unreadable_receipt(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "claude-subscription-quota-admission-invalid-utf8.yaml").write_bytes(b"\xff\xfe\xfa")

    _assert_claude_admission_ignored(tmp_path, "unreadable-receipt-unicodedecodeerror")


def test_claude_admission_rejects_strict_parse_failure(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")
    with (relay / "claude-subscription-quota-admission.yaml").open(
        "a",
        encoding="utf-8",
    ) as receipt:
        receipt.write("status: quota_available\n")

    _assert_claude_admission_ignored(tmp_path, "duplicate-key-on-line-18")


def test_agy_admission_rejects_secret_persistence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _agy_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        secret_value_persisted="true",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:secret-value-persisted" in ref for ref in agy_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 0
    assert summary["agy_ignored_admissions"] == 1
    assert "ignoring agy admission receipt: validation failed" in result.stderr
    assert "false-negative recovery" in result.stderr
    assert "secret_value_persisted" not in result.stderr


def test_ignored_agy_admission_warning_omits_secretish_receipt_dir(tmp_path: Path) -> None:
    secretish_dir = tmp_path / "sk-secret-token-relay-receipts-000000000000000000000000"
    secretish_dir.mkdir()
    (secretish_dir / "agy-quota-admission-invalid-utf8.yaml").write_bytes(b"\xff\xfe\xfa")

    result, out = _run_writer(tmp_path, "--relay-receipt-dir", str(secretish_dir))

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "unknown"
    assert "ignoring agy admission receipt: validation failed" in result.stderr
    assert secretish_dir.name not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 0
    assert summary["agy_ignored_admissions"] == 1


def test_agy_admission_rejects_missing_smoke_validation(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "agy-quota-admission.yaml").write_text(
        """schema: hapax.agy_quota_admission.v1
status: quota_available
provider: google-antigravity-cli-agy
capacity_pool: subscription_quota
route_id: agy.review.direct
supported_tool: hapax-agy-reviewer
model: gemini-3.1-pro-preview
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: agy-gemini31pro-smoke-witness
secret_source: agy:operator-session
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: operator_session_subscription
positive_admission: true
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:smoke-command-missing" in ref for ref in agy_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 0
    assert summary["agy_ignored_admissions"] == 1


def test_fresh_glmcp_payg_admission_without_active_wall_stays_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
    )

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["provider"] == "z_ai-glm-coding-plan"
    assert glmcp_snapshot["capacity_pool"] == "subscription_quota"
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "glmcp-quota-admission-payg.yaml" in ref
        and "endpoint:https://api.z.ai/api/paas/v4" in ref
        and "model:glm-5.2" in ref
        and "primary_error_class:quota_exhausted" in ref
        and "quota_wall_evidence_ref:cx-glmcp-quota-wall.yaml" in ref
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert not any(ref.startswith("spend-gate:") for ref in glmcp_snapshot["evidence_refs"])
    assert (
        "without an active Coding Plan quota-wall witness"
        in glmcp_snapshot["operator_visible_reason"]
    )
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 1


def test_glmcp_admission_scans_documented_recheck_glob(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        name="manual_glmcp-quota-admission.yaml",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert any(
        "manual_glmcp-quota-admission.yaml" in ref for ref in glmcp_snapshot["evidence_refs"]
    )


def test_glmcp_admission_hashes_unsafe_receipt_name_in_evidence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    unsafe_name = "sk-secret-token-glmcp-quota-admission.yaml"
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        name=unsafe_name,
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert any("unsafe-receipt-name-sha256:" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert unsafe_name not in payload_text


@pytest.mark.parametrize("timestamp_field", ["captured_at", "detected_at"])
def test_glmcp_admission_rejects_timestamp_fallback_fields(
    tmp_path: Path,
    timestamp_field: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        name=f"glmcp-quota-admission-{timestamp_field}.yaml",
        timestamp_field=timestamp_field,
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert "unsupported timestamp field; expected observed_at only" in result.stderr
    assert json.loads(result.stdout)["glmcp_admissions"] == 0


def test_glmcp_admission_rejects_claude_code_anthropic_evidence_for_review_route(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        supported_tool="claude_code",
        endpoint="https://api.z.ai/api/anthropic",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert "supported_tool missing or unsupported" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_rejects_unsupported_tool_or_endpoint(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-claude-code-coding-endpoint.yaml").write_text(
        """schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: claude_code
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-reviewer-anthropic-endpoint.yaml").write_text(
        """schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-reviewer-trailing-slash-endpoint.yaml").write_text(
        """schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4/
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert "endpoint missing or unsupported" in result.stderr
    assert "supported_tool missing or unsupported" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_requires_provider_and_route(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-missing-provider.yaml").write_text(
        """status: quota_available
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-missing-route.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert "present but rejected" in glmcp_snapshot["operator_visible_reason"]
    assert not any("quota-admission:absent" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert any(
        ":ignored:provider-missing-or-unsupported" in ref for ref in glmcp_snapshot["evidence_refs"]
    )
    assert any(
        ":ignored:route-id-missing-or-unsupported" in ref for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "provider missing or unsupported" in result.stderr
    assert "route_id missing or unsupported" in result.stderr
    assert "find ~/.cache/hapax/relay/receipts" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0
    assert summary["glmcp_ignored_admissions"] == 2


def test_glmcp_admission_receipt_warns_on_unsupported_status(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-unsupported-status.yaml").write_text(
        """status: ok
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "status missing or unsupported; expected quota_available" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_duplicate_keys(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-duplicate-provider.yaml").write_text(
        """status: quota_available
provider: not-glmcp
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "duplicate key on line" in result.stderr
    assert "duplicate key 'provider'" not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_secretish_unknown_keys_without_echo(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    secretish_key = "sk-live-secret-token-000000000000000000000000"
    (relay / "glmcp-quota-admission-unknown-key.yaml").write_text(
        f"""status: quota_available
{secretish_key}: first
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "unsupported key on line" in result.stderr
    assert secretish_key not in result.stderr
    assert secretish_key not in payload_text
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_non_flat_yaml(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-nested.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
endpoint:
  endpoint: https://api.z.ai/api/coding/paas/v4
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "non-flat line" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_ambiguous_provider_alias(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-ambiguous-provider.yaml").write_text(
        """status: quota_available
provider: z_ai
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "provider ambiguous alias" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_requires_subscription_capacity_pool(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-missing-capacity.yaml").write_text(
        """schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "capacity_pool missing or unsupported for endpoint" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


@pytest.mark.parametrize(
    ("field_name", "expected_reason"),
    [
        ("provider", "provider missing or unsupported"),
        ("capacity_pool", "capacity_pool missing or unsupported for endpoint"),
        ("route_id", "route_id missing or unsupported"),
        ("supported_tool", "supported_tool missing or unsupported"),
        ("endpoint", "endpoint missing or unsupported"),
        ("model", "model missing or unsupported"),
        ("observed_at", "missing or malformed observed_at"),
        ("stale_after_seconds", "malformed stale_after_seconds"),
        ("schema", "schema missing or unsupported"),
        ("secret_source", "secret_source missing or unsupported"),
        ("secret_value_persisted", "secret_value_persisted must be false"),
        ("prompt_or_output_persisted", "prompt_or_output_persisted must be false"),
        ("billing_mode", "billing_mode missing or unsupported for endpoint"),
        ("payg_fallback", "payg_fallback missing or unsupported for endpoint"),
    ],
)
def test_glmcp_admission_rejection_warnings_do_not_echo_untrusted_values(
    tmp_path: Path,
    field_name: str,
    expected_reason: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    secretish_value = "sk-live-secret-token-000000000000000000000000"
    fields = {
        "schema": "hapax.glmcp_quota_admission.v1",
        "status": "quota_available",
        "provider": "z_ai-glm-coding-plan",
        "capacity_pool": "subscription_quota",
        "route_id": "glmcp.review.direct",
        "supported_tool": "hapax-glmcp-reviewer",
        "endpoint": "https://api.z.ai/api/coding/paas/v4",
        "model": "glm-5.2",
        "observed_at": "2026-06-09T23:55:00Z",
        "stale_after_seconds": "900",
        "evidence_ref": "supported-tool-usage-witness",
        "secret_source": "pass:glmcp/api-key",
        "secret_value_persisted": "false",
        "prompt_or_output_persisted": "false",
        "billing_mode": "coding_plan_subscription",
        "payg_fallback": "false",
    }
    fields[field_name] = secretish_value
    receipt_body = "".join(f"{key}: {value}\n" for key, value in fields.items())
    (relay / f"glmcp-quota-admission-secretish-{field_name}.yaml").write_text(
        receipt_body,
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert expected_reason in result.stderr
    assert secretish_value not in result.stderr
    assert secretish_value not in payload_text
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


@pytest.mark.parametrize(
    ("field_name", "expected_reason"),
    [
        ("secret_value_persisted", "secret_value_persisted must be false"),
        ("prompt_or_output_persisted", "prompt_or_output_persisted must be false"),
        ("payg_fallback", "payg_fallback missing or unsupported for endpoint"),
    ],
)
def test_glmcp_admission_rejects_noncanonical_false_booleans(
    tmp_path: Path,
    field_name: str,
    expected_reason: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    fields = {
        "schema": "hapax.glmcp_quota_admission.v1",
        "status": "quota_available",
        "provider": "z_ai-glm-coding-plan",
        "capacity_pool": "subscription_quota",
        "route_id": "glmcp.review.direct",
        "supported_tool": "hapax-glmcp-reviewer",
        "endpoint": "https://api.z.ai/api/coding/paas/v4",
        "model": "glm-5.2",
        "observed_at": "2026-06-09T23:55:00Z",
        "stale_after_seconds": "900",
        "evidence_ref": "supported-tool-usage-witness",
        "secret_source": "pass:glmcp/api-key",
        "secret_value_persisted": "false",
        "prompt_or_output_persisted": "false",
        "billing_mode": "coding_plan_subscription",
        "payg_fallback": "false",
    }
    fields[field_name] = "False"
    receipt_body = "".join(f"{key}: {value}\n" for key, value in fields.items())
    (relay / f"glmcp-quota-admission-noncanonical-{field_name}.yaml").write_text(
        receipt_body,
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert expected_reason in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_requires_supported_tool_evidence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-missing-supported-tool.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-unsupported-endpoint.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/v1
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-unsupported-model.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-4.7
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-missing-evidence.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "supported_tool missing or unsupported" in result.stderr
    assert "unsupported-endpoint" in result.stderr
    assert "expected official Z.ai Coding Plan or PAYG endpoint" in result.stderr
    assert "model missing or unsupported" in result.stderr
    assert "evidence_ref missing" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_stale_glmcp_admission_receipt_keeps_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(relay, observed_at="2026-06-09T23:00:00Z", stale_after_seconds=60)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "receipt expired" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_overlong_glmcp_admission_ttl_keeps_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(relay, observed_at="2026-06-09T23:55:00Z", stale_after_seconds=3601)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "stale_after_seconds exceeds maximum 3600" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_future_glmcp_admission_receipt_keeps_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(relay, observed_at="2026-06-10T00:05:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "observed_at is in the future" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


@pytest.mark.parametrize(
    "legacy_timestamp_line",
    [
        "captured_at: 2026-06-10T00:05:00Z",
        "captured_at:",
        "detected_at:",
    ],
)
def test_ambiguous_glmcp_admission_timestamps_keep_glmcp_unknown(
    tmp_path: Path,
    legacy_timestamp_line: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-ambiguous-timestamp.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
{legacy_timestamp_line}
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        ":ignored:unsupported-timestamp-field" in ref for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "unsupported timestamp field; expected observed_at only" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0
    assert summary["glmcp_ignored_admissions"] == 1


def test_malformed_glmcp_admission_timestamps_are_operator_visible(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-bad-observed-at.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: definitely-not-a-date
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-blank-observed-at.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at:
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-bad-stale-after.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: soon
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-zero-stale-after.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 0
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "malformed observed_at" in result.stderr
    assert "malformed stale_after_seconds" in result.stderr
    assert "non-positive stale_after_seconds" in result.stderr
    assert "false-negative recovery" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_requires_explicit_stale_after_seconds(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-missing-stale-after.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "stale_after_seconds missing" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_ttl_rejection_does_not_echo_numeric_secret(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    numeric_secret = "12345678901234567890123456789012"
    (relay / "glmcp-quota-admission-secretish-ttl.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: {numeric_secret}
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "stale_after_seconds exceeds maximum 3600" in result.stderr
    assert numeric_secret not in result.stderr
    assert numeric_secret not in payload_text
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_secretish_evidence_ref(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    secretish_ref = "sk-live-secret-token-000000000000000000000000"
    colon_ref = "relay:receipt:ambiguous"
    email_ref = "seat@example.com"
    overlong_secretish_ref = ("a-" * 120) + "sk-live-secret-token-000000000000000000000000"
    (relay / "glmcp-quota-admission-secretish-evidence.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: {secretish_ref}
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-colon-evidence.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: {colon_ref}
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-email-evidence.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: {email_ref}
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-overlong-secretish-evidence.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: {overlong_secretish_ref}
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "evidence_ref unsafe" in result.stderr
    assert secretish_ref not in result.stderr
    assert overlong_secretish_ref not in result.stderr
    assert secretish_ref not in payload_text
    assert colon_ref not in payload_text
    assert email_ref not in payload_text
    assert overlong_secretish_ref not in payload_text
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_unreadable_glmcp_admission_receipt_keeps_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-invalid-utf8.yaml").write_bytes(b"\xff\xfe\xfa")
    unsafe_dir_name = "sk-secret-token-glmcp-quota-admission.yaml"
    (relay / unsafe_dir_name).mkdir()

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "unreadable receipt UnicodeDecodeError" in result.stderr
    assert "unreadable receipt IsADirectoryError" in result.stderr
    assert unsafe_dir_name not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_ignored_glmcp_admission_warning_omits_secretish_receipt_dir(tmp_path: Path) -> None:
    secretish_dir = tmp_path / "sk-secret-token-relay-receipts-000000000000000000000000"
    secretish_dir.mkdir()
    (secretish_dir / "glmcp-quota-admission-invalid-utf8.yaml").write_bytes(b"\xff\xfe\xfa")

    result, out = _run_writer(tmp_path, "--relay-receipt-dir", str(secretish_dir))

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "unreadable receipt UnicodeDecodeError" in result.stderr
    assert secretish_dir.name not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0
    assert summary["glmcp_ignored_admissions"] == 1


def test_resource_probe_failure_fails_closed_to_unknown(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path, nvidia_body="exit 9")

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["local_resource_state"] == "unknown"
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["litellm.local.command-r-35b"] == "unknown"


def test_vram_pressure_degrades_resource_state(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path, nvidia_body="echo '31000, 32000'")

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["local_resource_state"] in {"yellow", "red"}


def test_unusable_base_ledger_fails_without_writing(tmp_path: Path) -> None:
    bad_base = tmp_path / "bad-base.json"
    bad_base.write_text("{not json", encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(bad_base))

    assert result.returncode == 1
    assert "base ledger unusable" in result.stderr
    assert not out.exists()


def test_output_is_private_and_atomic(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600
    leftovers = [p for p in out.parent.iterdir() if p.name not in {out.name, f"{out.name}.lock"}]
    assert leftovers == []


def test_no_secret_material_in_output(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    for token in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "LITELLM_API_KEY",
        "pass show",
        "hapax-secrets.env",
    ):
        assert token not in text
