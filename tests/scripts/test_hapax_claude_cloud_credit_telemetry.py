"""Tests for the claude cloud-credit quota admission fold.

A ``hapax.claude_cloud_credit_quota_admission.v1`` receipt is folded by
``scripts/hapax-quota-telemetry-writer`` into a live-ledger quota snapshot for
``claude.review.cloud`` on the ``promotional_credit_quota`` pool — paced
separately from every subscription-pool route. Subscription receipts never
admit the cloud route, subscription walls never exhaust it, and untrusted
evidence keeps it unknown.
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-quota-telemetry-writer"
CLOUD_ADMISSION_SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-cloud-credit-quota-admission"
NOW = "2026-09-25T23:20:00Z"
CLOUD_ROUTE_ID = "claude.review.cloud"


def _fake_nvidia_smi(tmp_path: Path) -> Path:
    stub = tmp_path / "nvidia-smi"
    stub.write_text("#!/bin/sh\necho '1000, 32000'\n", encoding="utf-8")
    stub.chmod(0o700)
    return stub


def _cloud_admission(
    relay: Path,
    *,
    observed_at: str = "2026-09-25T23:19:00Z",
    stale_after_seconds: str = "900",
    evidence_ref: str = "claude-cloud-credit-quota-headroom-observed-20260925t2319z",
    observation: str = "cloud_credit_quota_headroom_observed",
    billing_mode: str = "promotional_cloud_credit",
    provider: str = "anthropic-claude-cloud-credit",
    capacity_pool: str = "promotional_credit_quota",
    auth_surface: str = "oauth",
    schema: str = "hapax.claude_cloud_credit_quota_admission.v1",
    route_id: str = CLOUD_ROUTE_ID,
    name: str = "claude-cloud-credit-quota-admission-claude-review-cloud-20260925t2319z.yaml",
) -> Path:
    path = relay / name
    path.write_text(
        f"schema: {schema}\n"
        "status: quota_available\n"
        f"provider: {provider}\n"
        f"route_id: {route_id}\n"
        f"capacity_pool: {capacity_pool}\n"
        f"auth_surface: {auth_surface}\n"
        f"observation: {observation}\n"
        f"observed_at: {observed_at}\n"
        f"stale_after_seconds: {stale_after_seconds}\n"
        f"evidence_ref: {evidence_ref}\n"
        "secret_source: claude:operator-session-oauth\n"
        "secret_value_persisted: false\n"
        "prompt_or_output_persisted: false\n"
        f"billing_mode: {billing_mode}\n"
        "account_live_quota_observed: true\n"
        "lane_presence_used_as_quota_evidence: false\n"
        "positive_admission: true\n",
        encoding="utf-8",
    )
    return path


def _subscription_admission_for_cloud_route(relay: Path) -> Path:
    path = relay / "claude-subscription-quota-admission.yaml"
    path.write_text(
        "schema: hapax.claude_quota_admission.v1\n"
        "status: quota_available\n"
        "provider: anthropic-claude-subscription\n"
        f"route_id: {CLOUD_ROUTE_ID}\n"
        "capacity_pool: subscription_quota\n"
        "auth_surface: subscription\n"
        "observation: subscription_quota_headroom_observed\n"
        "observed_at: 2026-09-25T23:19:00Z\n"
        "stale_after_seconds: 900\n"
        "evidence_ref: claude-subscription-headroom-observed-20260925t2319z\n"
        "secret_source: claude:operator-session-subscription\n"
        "secret_value_persisted: false\n"
        "prompt_or_output_persisted: false\n"
        "billing_mode: operator_session_subscription\n"
        "account_live_quota_observed: true\n"
        "lane_presence_used_as_quota_evidence: false\n"
        "positive_admission: true\n",
        encoding="utf-8",
    )
    return path


def _claude_wall(relay: Path) -> Path:
    path = relay / "theta-quota-wall.yaml"
    path.write_text(
        "role: theta\n"
        "status: quota_blocked\n"
        "detected_at: 2026-09-25T23:00:00Z\n"
        "signal_kind: rate_limit_event\n"
        "failure_class: quota_exhausted\n"
        "rate_limit_type: quota_exhausted\n"
        "resets_at: 2026-09-26T06:00:00Z\n"
        "is_overage: False\n"
        "action: exit_clean_await_restart\n",
        encoding="utf-8",
    )
    return path


def _run_writer(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    relay = tmp_path / "relay-receipts"
    relay.mkdir(exist_ok=True)
    stub = _fake_nvidia_smi(tmp_path)
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR": str(tmp_path / "platform-receipts"),
        "HAPAX_DISPATCH_HOST": "",
        "HAPAX_DEFAULT_DISPATCH_HOST": "",
    }
    (tmp_path / "platform-receipts").mkdir(exist_ok=True)
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
            "--platform-capability-receipt-dir",
            str(tmp_path / "platform-receipts"),
            "--nvidia-smi",
            str(stub),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=env,
    )
    return result, out


def _cloud_snapshot(payload: dict) -> dict | None:
    for snapshot in payload.get("quota_snapshots", []):
        if snapshot.get("route_id") == CLOUD_ROUTE_ID:
            return snapshot
    return None


def test_cloud_credit_receipt_folds_to_fresh_promotional_snapshot(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _cloud_admission(relay)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _cloud_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot is not None
    assert snapshot["capacity_pool"] == "promotional_credit_quota"
    assert snapshot["capacity_pool"] != "subscription_quota"
    assert snapshot["provider"] == "anthropic-claude-cloud-credit"
    assert snapshot["subscription_quota_state"] == "fresh"
    assert snapshot["fresh_until"] == "2026-09-25T23:34:00Z"
    assert any(ref.endswith(":cloud-credit-quota:observed") for ref in snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["claude_cloud_credit_admissions"] == 1


def test_subscription_receipt_never_admits_cloud_route(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _subscription_admission_for_cloud_route(relay)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _cloud_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot is not None
    assert snapshot["subscription_quota_state"] != "fresh"
    assert not any(
        "claude-subscription-quota-admission" in ref for ref in snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["claude_cloud_credit_admissions"] == 0


def test_wrong_billing_mode_receipt_is_ignored(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _cloud_admission(relay, billing_mode="operator_session_subscription")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _cloud_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot is not None
    assert snapshot["subscription_quota_state"] != "fresh"
    summary = json.loads(result.stdout)
    assert summary["claude_cloud_credit_admissions"] == 0
    assert summary["claude_cloud_credit_ignored_admissions"] == 1


def test_subscription_wall_does_not_exhaust_cloud_route(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_wall(relay)
    _cloud_admission(relay)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    cloud = _cloud_snapshot(payload)
    assert cloud is not None
    assert cloud["subscription_quota_state"] == "fresh"
    # The subscription wall still bites the subscription-pool claude routes.
    headless = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot.get("route_id") == "claude.headless.full"
    )
    assert headless["subscription_quota_state"] == "exhausted"


def test_absent_receipt_keeps_cloud_route_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _cloud_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot is not None
    assert snapshot["subscription_quota_state"] == "unknown"


def test_ledger_route_state_is_fresh_only_with_trusted_cloud_evidence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _cloud_admission(relay)
    result, out = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import (
        SubscriptionQuotaState,
        load_quota_spend_ledger,
        subscription_quota_state_for_route,
    )

    ledger = load_quota_spend_ledger(out)
    state, refs = subscription_quota_state_for_route(ledger, CLOUD_ROUTE_ID, now=_parse_now())
    assert state is SubscriptionQuotaState.FRESH
    assert any("cloud-credit-quota:observed" in ref for ref in refs)

    payload = json.loads(out.read_text(encoding="utf-8"))
    for snapshot in payload["quota_snapshots"]:
        if snapshot.get("route_id") == CLOUD_ROUTE_ID:
            snapshot["evidence_refs"] = ["relay-receipt:untrusted.yaml:witness:none"]
    out.write_text(json.dumps(payload), encoding="utf-8")
    ledger = load_quota_spend_ledger(out)
    state, _refs = subscription_quota_state_for_route(ledger, CLOUD_ROUTE_ID, now=_parse_now())
    assert state is not SubscriptionQuotaState.FRESH


def test_promotional_snapshot_never_counts_as_subscription_capacity(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _cloud_admission(relay)
    result, out = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import (
        SubscriptionQuotaState,
        _subscription_quota_state,
        load_quota_spend_ledger,
    )

    ledger = load_quota_spend_ledger(out)
    aggregate = _subscription_quota_state(ledger, now=_parse_now())
    assert aggregate is not SubscriptionQuotaState.FRESH


def _parse_now():
    from datetime import UTC, datetime

    return datetime.fromisoformat(NOW.replace("Z", "+00:00")).astimezone(UTC)


@pytest.mark.parametrize(
    "telemetry_name,admission_name,ledger_name",
    [
        (
            "CLAUDE_CLOUD_CREDIT_ADMISSION_LANE_PRESENCE_RE",
            "LANE_PRESENCE_RE",
            "CLAUDE_CLOUD_CREDIT_ADMISSION_LANE_PRESENCE_RE",
        ),
        (
            "CLAUDE_CLOUD_CREDIT_ADMISSION_BILLINGISH_RE",
            "BILLINGISH_RE",
            "CLAUDE_CLOUD_CREDIT_ADMISSION_BILLINGISH_RE",
        ),
        (
            "CLAUDE_CLOUD_CREDIT_ADMISSION_WITNESS_ALLOWLIST_RE",
            "WITNESS_ALLOWLIST_RE",
            "CLAUDE_CLOUD_CREDIT_ADMISSION_WITNESS_ALLOWLIST_RE",
        ),
        (
            "CLAUDE_CLOUD_CREDIT_ADMISSION_SECRETISH_RE",
            "SECRETISH_RE",
            "CLAUDE_CLOUD_CREDIT_ADMISSION_SECRETISH_RE",
        ),
    ],
)
def test_cloud_credit_regexes_are_consistent_across_receipt_layers(
    telemetry_name: str, admission_name: str, ledger_name: str
) -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLOUD_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    import shared.quota_spend_ledger as ledger_module

    assert (
        telemetry_namespace[telemetry_name].pattern
        == admission_namespace[admission_name].pattern
        == getattr(ledger_module, ledger_name).pattern
    )
