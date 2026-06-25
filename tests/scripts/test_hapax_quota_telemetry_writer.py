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
FIXTURES = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"
NOW = "2026-06-10T00:00:00Z"


def _fake_nvidia_smi(tmp_path: Path, body: str) -> Path:
    stub = tmp_path / "fake-nvidia-smi"
    stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _run_writer(
    tmp_path: Path,
    *extra_args: str,
    nvidia_body: str = "echo '1000, 32000'",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    relay = tmp_path / "relay-receipts"
    relay.mkdir(exist_ok=True)
    stub = _fake_nvidia_smi(tmp_path, nvidia_body)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skip-receipts",
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--nvidia-smi",
            str(stub),
            "--json",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    return result, out


def _wall_receipt(relay: Path, role: str, resets_at: str) -> None:
    (relay / f"{role}-quota-wall.yaml").write_text(
        f"""role: {role}
status: quota_blocked
detected_at: 2026-06-09T23:00:00Z
signal_kind: rate_limit_event
rate_limit_type: seven_day
resets_at: {resets_at}
is_overage: False
action: exit_clean_await_restart
""",
        encoding="utf-8",
    )


def _glmcp_admission(
    relay: Path,
    *,
    observed_at: str,
    stale_after_seconds: int = 900,
    supported_tool: str = "claude_code",
    endpoint: str = "https://api.z.ai/api/anthropic",
    model: str = "glm-5.2[1m]",
    name: str = "glmcp-quota-admission.yaml",
    timestamp_field: str = "observed_at",
) -> None:
    (relay / name).write_text(
        f"""schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: {supported_tool}
endpoint: {endpoint}
model: {model}
{timestamp_field}: {observed_at}
stale_after_seconds: {stale_after_seconds}
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )


def test_glmcp_admission_recheck_command_uses_scanner_glob() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    receipt_glob = namespace["GLMCP_ADMISSION_RECEIPT_GLOB"]

    assert receipt_glob == "*glmcp-quota-admission*.yaml"
    assert f"-name '{receipt_glob}'" in namespace["GLMCP_ADMISSION_RECHECK_COMMAND"]
    assert "receipt_dir.glob(GLMCP_ADMISSION_RECEIPT_GLOB)" in SCRIPT.read_text(encoding="utf-8")


def test_writes_valid_live_ledger_with_fresh_captured_at(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["captured_at"] == NOW
    assert payload["ledger_id"].startswith("quota-spend-ledger-live-")
    assert payload["local_resource_state"] == "green"

    # The output revalidates through the fail-closed loader.
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import load_quota_spend_ledger

    ledger = load_quota_spend_ledger(out)
    states = {
        snapshot.route_id: snapshot.subscription_quota_state.value
        for snapshot in ledger.quota_snapshots
    }
    assert states["claude.headless.full"] == "fresh"
    assert states["codex.headless.full"] == "fresh"
    assert "gemini.headless.full" not in states
    assert states["glmcp.review.direct"] == "unknown"
    assert states["litellm.local.command-r-35b"] == "fresh"


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
        and "supported_tool:claude_code" in ref
        and "endpoint:https://api.z.ai/api/anthropic" in ref
        and "model:glm-5.2[1m]" in ref
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "finite" in glmcp_snapshot["operator_visible_reason"]
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


def test_glmcp_admission_accepts_claude_code_with_anthropic_endpoint(tmp_path: Path) -> None:
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
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 1


def test_glmcp_admission_rejects_supported_tool_endpoint_mismatches(tmp_path: Path) -> None:
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
model: glm-5.2[1m]
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
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
  endpoint: https://api.z.ai/api/anthropic
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
        """status: quota_available
provider: z_ai-glm-coding-plan
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
    assert "capacity_pool missing or unsupported" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


@pytest.mark.parametrize(
    ("field_name", "expected_reason"),
    [
        ("provider", "provider missing or unsupported"),
        ("capacity_pool", "capacity_pool missing or unsupported"),
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
        ("billing_mode", "billing_mode missing or unsupported"),
        ("payg_fallback", "payg_fallback must be false"),
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
        "supported_tool": "claude_code",
        "endpoint": "https://api.z.ai/api/anthropic",
        "model": "glm-5.2[1m]",
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
supported_tool: claude_code
endpoint: https://api.z.ai/v1
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
    assert "expected official Z.ai Coding Plan endpoint" in result.stderr
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


def test_ambiguous_glmcp_admission_timestamps_keep_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-ambiguous-timestamp.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
observed_at: 2026-06-09T23:55:00Z
captured_at: 2026-06-10T00:05:00Z
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
observed_at: definitely-not-a-date
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-bad-stale-after.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
supported_tool: claude_code
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2[1m]
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
    leftovers = [p for p in out.parent.iterdir() if p.name != out.name]
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
