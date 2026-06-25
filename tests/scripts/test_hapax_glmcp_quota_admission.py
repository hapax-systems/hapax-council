"""Tests for the passive GLMCP quota-admission receipt writer."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-glmcp-quota-admission"
NOW = "2026-06-10T00:00:00Z"
SUCCESS_METADATA_ARGS = (
    "--supported-tool",
    "hapax-glmcp-reviewer",
    "--endpoint",
    "https://api.z.ai/api/coding/paas/v4",
    "--model",
    "glm-5",
)


def _run(
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    receipt_dir = tmp_path / "receipts"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--receipt-dir",
            str(receipt_dir),
            "--now",
            NOW,
            "--json",
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, **(extra_env or {})},
    )
    return result, receipt_dir


def _read_flat_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition(":")
        fields[key] = value.strip()
    return fields


def test_observe_success_writes_private_exact_positive_receipt(tmp_path: Path) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-success",
        "--evidence-ref",
        "sanctioned-glmcp-usage-001",
        *SUCCESS_METADATA_ARGS,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    receipt = receipt_dir / "glmcp-quota-admission.yaml"
    assert summary["path"] == str(receipt)
    assert summary["receipt_kind"] == "admission"
    assert summary["status"] == "quota_available"
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert [path.name for path in receipt_dir.iterdir()] == ["glmcp-quota-admission.yaml"]

    fields = _read_flat_fields(receipt)
    assert fields == {
        "schema": "hapax.glmcp_quota_admission.v1",
        "status": "quota_available",
        "provider": "z_ai-glm-coding-plan",
        "route_id": "glmcp.review.direct",
        "capacity_pool": "subscription_quota",
        "supported_tool": "hapax-glmcp-reviewer",
        "endpoint": "https://api.z.ai/api/coding/paas/v4",
        "model": "glm-5",
        "observed_at": NOW,
        "stale_after_seconds": "900",
        "evidence_ref": "sanctioned-glmcp-usage-001",
        "secret_source": "pass:glmcp/api-key",
        "secret_value_persisted": "false",
        "prompt_or_output_persisted": "false",
        "billing_mode": "coding_plan_subscription",
        "payg_fallback": "false",
    }


def test_observe_success_does_not_persist_env_secret_or_prompt_content(tmp_path: Path) -> None:
    secret_value = "sk-live-secret-token-000000000000000000000000"
    prompt_content = "operator prompt content must not be stored"
    output_content = "provider response content must not be stored"

    result, receipt_dir = _run(
        tmp_path,
        "observe-success",
        "--evidence-ref",
        "sanctioned-glmcp-usage-001",
        *SUCCESS_METADATA_ARGS,
        extra_env={
            "ANTHROPIC_AUTH_TOKEN": secret_value,
            "HAPAX_TEST_PROMPT_CONTENT": prompt_content,
            "HAPAX_TEST_OUTPUT_CONTENT": output_content,
        },
    )

    assert result.returncode == 0, result.stderr
    text = (receipt_dir / "glmcp-quota-admission.yaml").read_text(encoding="utf-8")
    assert "pass show" not in text
    assert secret_value not in text
    assert prompt_content not in text
    assert output_content not in text


@pytest.mark.parametrize(
    "evidence_ref",
    [
        "sk-live-secret-token-000000000000000000000000",
        "relay:receipt:ambiguous",
        "seat@example.com",
    ],
)
def test_observe_success_rejects_unsafe_evidence_refs(
    tmp_path: Path,
    evidence_ref: str,
) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-success",
        "--evidence-ref",
        evidence_ref,
        *SUCCESS_METADATA_ARGS,
    )

    assert result.returncode == 2
    assert "unsafe evidence ref" in result.stderr
    assert evidence_ref not in result.stderr
    assert not receipt_dir.exists()


@pytest.mark.parametrize(
    ("metadata_args", "expected_message"),
    [
        (
            (
                "--supported-tool",
                "claude_code",
                "--endpoint",
                "https://api.z.ai/api/coding/paas/v4",
                "--model",
                "glm-5",
            ),
            "--supported-tool must be hapax-glmcp-reviewer",
        ),
        (
            (
                "--supported-tool",
                "hapax-glmcp-reviewer",
                "--endpoint",
                "https://api.z.ai/api/anthropic",
                "--model",
                "glm-5",
            ),
            "--endpoint must be https://api.z.ai/api/coding/paas/v4",
        ),
        (
            (
                "--supported-tool",
                "hapax-glmcp-reviewer",
                "--endpoint",
                "https://api.z.ai/api/coding/paas/v4",
                "--model",
                "glm-5.2[1m]",
            ),
            "--model must be glm-5",
        ),
    ],
)
def test_observe_success_requires_observed_supported_metadata(
    tmp_path: Path,
    metadata_args: tuple[str, ...],
    expected_message: str,
) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-success",
        "--evidence-ref",
        "sanctioned-glmcp-usage-001",
        *metadata_args,
    )

    assert result.returncode == 2
    assert expected_message in result.stderr
    assert "next action:" in result.stderr
    assert not receipt_dir.exists()


def test_observe_error_rejects_secret_shaped_numeric_provider_code(tmp_path: Path) -> None:
    numeric_secret = "12345678901234567890123456789012"

    result, receipt_dir = _run(
        tmp_path,
        "observe-error",
        "--provider-code",
        numeric_secret,
    )

    assert result.returncode == 2
    assert "provider code must be a four-digit Z.ai diagnostic code" in result.stderr
    assert "next action:" in result.stderr
    assert numeric_secret not in result.stderr
    assert not receipt_dir.exists()


def test_observe_error_1308_writes_quota_wall_until_reset_plus_jitter(tmp_path: Path) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-error",
        "--provider-code",
        "1308",
        "--reset-at",
        "2026-06-10T05:00:00Z",
        "--jitter-seconds",
        "60",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    receipt = receipt_dir / "cx-glmcp-quota-wall.yaml"
    assert summary["path"] == str(receipt)
    assert summary["receipt_kind"] == "quota_wall"
    assert summary["status"] == "quota_blocked"
    assert summary["release_at"] == "2026-06-10T05:01:00Z"
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600

    fields = _read_flat_fields(receipt)
    assert fields["status"] == "quota_blocked"
    assert fields["provider_code"] == "1308"
    assert fields["failure_class"] == "quota_exhausted"
    assert fields["failure_code"] == "quota_exhaustion"
    assert fields["action"] == "hold_until_reset"
    assert fields["resets_at"] == "2026-06-10T05:01:00Z"
    assert fields["positive_admission"] == "false"
    assert fields["payg_fallback"] == "false"


def test_observe_error_1310_writes_quota_wall_until_reset_plus_jitter(tmp_path: Path) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-error",
        "--provider-code",
        "1310",
        "--reset-at",
        "2026-06-10T05:00:00Z",
        "--jitter-seconds",
        "120",
    )

    assert result.returncode == 0, result.stderr
    fields = _read_flat_fields(receipt_dir / "cx-glmcp-quota-wall.yaml")
    assert fields["status"] == "quota_blocked"
    assert fields["provider_code"] == "1310"
    assert fields["failure_class"] == "quota_exhausted"
    assert fields["action"] == "hold_until_reset"
    assert fields["resets_at"] == "2026-06-10T05:02:00Z"


def test_observe_error_stale_reset_timestamp_writes_future_hold(tmp_path: Path) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-error",
        "--provider-code",
        "1308",
        "--reset-at",
        "2026-06-09T23:00:00Z",
        "--backoff-seconds",
        "1200",
    )

    assert result.returncode == 0, result.stderr
    fields = _read_flat_fields(receipt_dir / "cx-glmcp-quota-wall.yaml")
    assert fields["status"] == "quota_blocked"
    assert fields["provider_code"] == "1308"
    assert fields["action"] == "hold_until_reset"
    assert fields["resets_at"] == "2026-06-10T00:20:00Z"


@pytest.mark.parametrize(
    ("provider_code", "failure_class", "action"),
    [
        ("1302", "rate_limited_concurrency", "backoff_reduce_concurrency"),
        ("1303", "rate_limited_frequency", "backoff_reduce_frequency"),
        ("1305", "rate_limited", "backoff"),
        ("1312", "provider_high_traffic", "backoff_or_switch_model"),
    ],
)
def test_observe_error_backoff_codes_write_quota_wall_without_payg_fallback(
    tmp_path: Path,
    provider_code: str,
    failure_class: str,
    action: str,
) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-error",
        "--provider-code",
        provider_code,
        "--backoff-seconds",
        "1200",
    )

    assert result.returncode == 0, result.stderr
    fields = _read_flat_fields(receipt_dir / "cx-glmcp-quota-wall.yaml")
    assert fields["status"] == "quota_blocked"
    assert fields["provider_code"] == provider_code
    assert fields["failure_class"] == failure_class
    assert fields["action"] == action
    assert fields["backoff_until"] == "2026-06-10T00:20:00Z"
    assert fields["resets_at"] == "2026-06-10T00:20:00Z"
    assert fields["positive_admission"] == "false"
    assert fields["payg_fallback"] == "false"


def test_observe_error_stale_backoff_until_writes_future_hold(tmp_path: Path) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-error",
        "--provider-code",
        "1302",
        "--backoff-until",
        "2026-06-09T23:00:00Z",
        "--backoff-seconds",
        "600",
    )

    assert result.returncode == 0, result.stderr
    fields = _read_flat_fields(receipt_dir / "cx-glmcp-quota-wall.yaml")
    assert fields["status"] == "quota_blocked"
    assert fields["provider_code"] == "1302"
    assert fields["backoff_until"] == "2026-06-10T00:10:00Z"
    assert fields["resets_at"] == "2026-06-10T00:10:00Z"


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (
            (
                "observe-success",
                "--evidence-ref",
                "sanctioned-glmcp-usage-001",
                *SUCCESS_METADATA_ARGS,
                "--stale-after-seconds",
                "0",
            ),
            "--stale-after-seconds must be between 1 and 3600",
        ),
        (
            (
                "observe-success",
                "--evidence-ref",
                "sanctioned-glmcp-usage-001",
                *SUCCESS_METADATA_ARGS,
                "--stale-after-seconds",
                "3601",
            ),
            "--stale-after-seconds must be between 1 and 3600",
        ),
        (
            (
                "--receipt-name",
                "glmcp-quota-admission-secret-token.yaml",
                "observe-success",
                "--evidence-ref",
                "sanctioned-glmcp-usage-001",
                *SUCCESS_METADATA_ARGS,
            ),
            "unsafe receipt name",
        ),
        (
            ("observe-error", "--provider-code", "1308", "--reset-at", "not-a-date"),
            "invalid --reset-at",
        ),
        (
            ("observe-error", "--provider-code", "1302", "--backoff-until", "not-a-date"),
            "invalid --backoff-until",
        ),
        (
            ("observe-error", "--provider-code", "1308", "--jitter-seconds", "-1"),
            "--jitter-seconds must be non-negative",
        ),
        (
            ("observe-error", "--provider-code", "1302", "--backoff-seconds", "0"),
            "--backoff-seconds must be positive",
        ),
        (
            ("observe-error", "--provider-code", "1308", "--action", "hold_until_reset"),
            "--provider-code cannot be combined",
        ),
        (
            ("observe-error", "--provider-code", ""),
            "provider code must be a four-digit Z.ai diagnostic code",
        ),
    ],
)
def test_validation_errors_do_not_write_receipts(
    tmp_path: Path,
    args: tuple[str, ...],
    expected_message: str,
) -> None:
    result, receipt_dir = _run(tmp_path, *args)

    assert result.returncode == 2
    assert expected_message in result.stderr
    assert "next action:" in result.stderr
    assert not receipt_dir.exists()


def test_write_failure_reports_next_action_without_path_details(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.write_text("not a directory\n", encoding="utf-8")

    result, _ = _run(
        tmp_path,
        "observe-success",
        "--evidence-ref",
        "sanctioned-glmcp-usage-001",
        *SUCCESS_METADATA_ARGS,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "failed to write receipt: FileExistsError" in result.stderr
    assert "next action: check --receipt-dir permissions" in result.stderr
    assert str(receipt_dir) not in result.stderr


@pytest.mark.parametrize(
    ("provider_code", "failure_class", "action", "failure_code"),
    [
        ("1113", "account_balance_or_arrears", "hold_no_payg_fallback", "fair_use_restricted"),
        ("1211", "model_not_found", "check_model_configuration", "route_unavailable"),
        ("1311", "plan_model_unavailable", "switch_model_or_upgrade_plan", "route_unavailable"),
        ("1313", "fair_use_restricted", "hold_until_manual_clear", "fair_use_restricted"),
    ],
)
def test_observe_error_manual_failures_write_blocking_wall_not_positive_admission(
    tmp_path: Path,
    provider_code: str,
    failure_class: str,
    action: str,
    failure_code: str,
) -> None:
    result, receipt_dir = _run(tmp_path, "observe-error", "--provider-code", provider_code)

    assert result.returncode == 0, result.stderr
    fields = _read_flat_fields(receipt_dir / "cx-glmcp-quota-wall.yaml")
    assert fields["status"] == "quota_blocked"
    assert fields["provider_code"] == provider_code
    assert fields["failure_class"] == failure_class
    assert fields["action"] == action
    assert fields["failure_code"] == failure_code
    assert fields["positive_admission"] == "false"
    assert fields["payg_fallback"] == "false"
    assert fields["signal_kind"] == "glmcp_quota_admission_error"
    assert not any(path.name.startswith("glmcp-quota-admission") for path in receipt_dir.iterdir())


def test_observe_error_prompt_length_writes_non_admission_hold(tmp_path: Path) -> None:
    result, receipt_dir = _run(tmp_path, "observe-error", "--provider-code", "1261")

    assert result.returncode == 0, result.stderr
    fields = _read_flat_fields(receipt_dir / "glmcp-quota-hold.yaml")
    assert fields["status"] == "hold"
    assert fields["provider_code"] == "1261"
    assert fields["failure_class"] == "prompt_too_long"
    assert fields["action"] == "reduce_prompt_size"
    assert fields["failure_code"] == "invalid_output"
    assert fields["positive_admission"] == "false"
    assert fields["payg_fallback"] == "false"
    assert "signal_kind" not in fields
    assert not any(path.name.startswith("glmcp-quota-admission") for path in receipt_dir.iterdir())


@pytest.mark.parametrize(
    ("failure_class", "action"),
    [
        ("auth_failed", "check_api_key"),
        ("network_error", "manual_hold_no_quota_admission"),
        ("redirect_error", "manual_hold_no_quota_admission"),
        ("server_error", "manual_hold_no_quota_admission"),
        ("tls_error", "manual_hold_no_quota_admission"),
    ],
)
def test_observe_error_transport_and_auth_failures_never_create_positive_admission(
    tmp_path: Path,
    failure_class: str,
    action: str,
) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-error",
        "--failure-class",
        failure_class,
        "--action",
        action,
    )

    assert result.returncode == 0, result.stderr
    fields = _read_flat_fields(receipt_dir / "cx-glmcp-quota-wall.yaml")
    assert fields["status"] == "quota_blocked"
    assert fields["failure_class"] == failure_class
    assert fields["positive_admission"] == "false"
    assert fields["secret_value_persisted"] == "false"
    assert fields["prompt_or_output_persisted"] == "false"
    assert not (receipt_dir / "glmcp-quota-admission.yaml").exists()


def test_observe_error_rejects_misleading_non_provider_action(tmp_path: Path) -> None:
    result, receipt_dir = _run(
        tmp_path,
        "observe-error",
        "--failure-class",
        "fair_use_restricted",
        "--action",
        "backoff",
    )

    assert result.returncode == 2
    assert "is not valid for failure class 'fair_use_restricted'" in result.stderr
    assert "expected 'hold_until_manual_clear'" in result.stderr
    assert not receipt_dir.exists()
