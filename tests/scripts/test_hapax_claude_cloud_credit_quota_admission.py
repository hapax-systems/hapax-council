"""Tests for ``scripts/hapax-claude-cloud-credit-quota-admission``.

The writer attests bounded account-live observations of the promotional cloud
credit (``ccr_promotional``) for ``claude.review.cloud`` only. It never records
subscription headroom, never pay-as-you-go, never lane/session presence, and
never secret or billing identifiers.
"""

from __future__ import annotations

import json
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-cloud-credit-quota-admission"


def _load_module() -> ModuleType:
    loader = SourceFileLoader("hapax_claude_cloud_credit_quota_admission_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def _run(argv: list[str]) -> int:
    return _load_module().main(argv)


def test_writes_short_lived_safe_cloud_credit_receipt(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    receipt_dir = tmp_path / "receipts"

    rc = _run(
        [
            "--receipt-dir",
            str(receipt_dir),
            "--now",
            "2026-09-25T23:11:00Z",
            "--evidence-ref",
            "claude-cloud-credit-quota-headroom-observed-20260925t2311z",
            "--observation",
            "cloud_credit_quota_headroom_observed",
            "--stale-after-seconds",
            "900",
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["route_id"] == "claude.review.cloud"
    assert summary["capacity_pool"] == "promotional_credit_quota"
    assert summary["auth_surface"] == "oauth"
    assert summary["observation"] == "cloud_credit_quota_headroom_observed"
    assert summary["observed_at"] == "2026-09-25T23:11:00Z"
    assert summary["fresh_until"] == "2026-09-25T23:26:00Z"
    assert summary["account_live_quota_observed"] is True
    assert summary["lane_presence_used_as_quota_evidence"] is False

    path = Path(summary["path"])
    assert "claude-cloud-credit-quota-admission" in path.name
    assert "claude-review-cloud" in path.name
    receipt = path.read_text(encoding="utf-8")
    assert "schema: hapax.claude_cloud_credit_quota_admission.v1" in receipt
    assert "status: quota_available" in receipt
    assert "provider: anthropic-claude-cloud-credit" in receipt
    assert "route_id: claude.review.cloud" in receipt
    assert "capacity_pool: promotional_credit_quota" in receipt
    assert "auth_surface: oauth" in receipt
    assert "observation: cloud_credit_quota_headroom_observed" in receipt
    assert "evidence_ref: claude-cloud-credit-quota-headroom-observed-20260925t2311z" in receipt
    assert "billing_mode: promotional_cloud_credit" in receipt
    assert "secret_source: claude:operator-session-oauth" in receipt
    assert "account_live_quota_observed: true" in receipt
    assert "lane_presence_used_as_quota_evidence: false" in receipt
    assert "positive_admission: true" in receipt
    assert path.stat().st_mode & 0o777 == 0o600


def test_refuses_subscription_and_paid_routes(tmp_path: Path) -> None:
    for route_id in (
        "claude.review.opus",
        "claude.headless.full",
        "glmcp.review.direct",
        "api.headless.provider_gateway",
    ):
        rc = _run(
            [
                "--receipt-dir",
                str(tmp_path),
                "--evidence-ref",
                "claude-cloud-credit-quota-headroom-observed-20260925t2311z",
                "--route-id",
                route_id,
            ]
        )
        assert rc == 2, route_id
    assert not list(tmp_path.glob("*.yaml"))


def test_refuses_non_credit_observations(tmp_path: Path) -> None:
    for observation in (
        "subscription_quota_headroom_observed",
        "operator_confirmed_subscription_headroom",
        "payg_quota_headroom_observed",
    ):
        rc = _run(
            [
                "--receipt-dir",
                str(tmp_path),
                "--evidence-ref",
                "claude-cloud-credit-quota-headroom-observed-20260925t2311z",
                "--observation",
                observation,
            ]
        )
        assert rc == 2, observation
    assert not list(tmp_path.glob("*.yaml"))


def test_refuses_lane_presence_and_billing_or_secret_refs(tmp_path: Path) -> None:
    for ref in (
        "claude-cloud-credit-quota-headroom-observed-tmux-cx-blue",
        "claude-cloud-credit-quota-headroom-observed-session-present",
        "claude-cloud-credit-quota-headroom-observed-20260925t2311z-billing-cus_9x",  # pragma: allowlist secret
        "claude-cloud-credit-quota-headroom-observed-20260925t2311z-sk-abcd1234",  # pragma: allowlist secret
        "claude-subscription-headroom-observed-20260925t2311z",  # pragma: allowlist secret
    ):
        rc = _run(["--receipt-dir", str(tmp_path), "--evidence-ref", ref])
        assert rc == 2, ref
    assert not list(tmp_path.glob("*.yaml"))


def test_refuses_subscription_window_fields(tmp_path: Path) -> None:
    # The credit exposes no five-hour/seven-day subscription windows; those
    # flags belong to the subscription writer and argparse rejects them here.
    import pytest

    with pytest.raises(SystemExit) as excinfo:
        _run(
            [
                "--receipt-dir",
                str(tmp_path),
                "--evidence-ref",
                "claude-cloud-credit-quota-headroom-observed-20260925t2311z",
                "--five-hour-used-percent",
                "7",
            ]
        )
    assert excinfo.value.code == 2
    assert not list(tmp_path.glob("*.yaml"))


def test_stale_after_bounds(tmp_path: Path) -> None:
    for value in ("59", "3601"):
        rc = _run(
            [
                "--receipt-dir",
                str(tmp_path),
                "--evidence-ref",
                "claude-cloud-credit-quota-headroom-observed-20260925t2311z",
                "--stale-after-seconds",
                value,
            ]
        )
        assert rc == 2, value
    assert not list(tmp_path.glob("*.yaml"))


def test_receipt_name_must_carry_writer_identity(tmp_path: Path) -> None:
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--receipt-name",
            "random-name.yaml",
            "--evidence-ref",
            "claude-cloud-credit-quota-headroom-observed-20260925t2311z",
        ]
    )
    assert rc == 2
    assert not list(tmp_path.glob("*.yaml"))


def test_receipt_name_must_not_persist_billing_identifiers(tmp_path: Path) -> None:
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--receipt-name",
            "claude-cloud-credit-quota-admission-billing-cus-9x.yaml",
            "--evidence-ref",
            "claude-cloud-credit-quota-headroom-observed-20260925t2311z",
        ]
    )
    assert rc == 2
    assert not list(tmp_path.glob("*.yaml"))


def test_receipt_name_must_not_persist_lane_presence(tmp_path: Path) -> None:
    rc = _run(
        [
            "--receipt-dir",
            str(tmp_path),
            "--receipt-name",
            "claude-cloud-credit-quota-admission-tmux-alpha.yaml",
            "--evidence-ref",
            "claude-cloud-credit-quota-headroom-observed-20260925t2311z",
        ]
    )
    assert rc == 2
    assert not list(tmp_path.glob("*.yaml"))
