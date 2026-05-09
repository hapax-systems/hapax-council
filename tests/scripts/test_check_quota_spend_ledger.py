"""Tests for scripts/check-quota-spend-ledger."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-quota-spend-ledger"
FIXTURE = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"
NOW = "2026-05-09T21:00:00Z"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_dashboard_json_exposes_non_green_bootstrap_state() -> None:
    result = _run("--fixture", str(FIXTURE), "--dashboard-json", "--now", NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["paid_api_budget_state"] == "expired"
    assert payload["bootstrap_dependency_state"] == "expired"
    assert payload["paid_api_route_eligible"] is False
    assert "bootstrap_dependency_state:expired" in payload["non_green_states"]


def test_paid_route_check_refuses_default_fixture() -> None:
    result = _run(
        "--fixture",
        str(FIXTURE),
        "--check-paid-route",
        "--route-id",
        "opaque.route.bootstrap",
        "--provider",
        "opaque-provider-a",
        "--profile",
        "opaque-profile-full",
        "--task-class",
        "authority-case-implementation",
        "--quality-floor",
        "frontier_required",
        "--estimated-cost-usd",
        "1.00",
        "--capacity-pool",
        "bootstrap_budget",
        "--now",
        NOW,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["eligible"] is False
    assert payload["state"] == "refused_expired_budget"
    assert "tb-20260509-bootstrap-expired" in payload["evidence_refs"]


def test_dashboard_json_and_paid_route_check_emit_combined_payload() -> None:
    result = _run(
        "--fixture",
        str(FIXTURE),
        "--dashboard-json",
        "--check-paid-route",
        "--route-id",
        "opaque.route.bootstrap",
        "--provider",
        "opaque-provider-a",
        "--profile",
        "opaque-profile-full",
        "--task-class",
        "authority-case-implementation",
        "--quality-floor",
        "frontier_required",
        "--estimated-cost-usd",
        "1.00",
        "--capacity-pool",
        "bootstrap_budget",
        "--now",
        NOW,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["dashboard"]["paid_api_budget_state"] == "expired"
    assert payload["eligibility"]["eligible"] is False


def test_invalid_fixture_exits_2(tmp_path: Path) -> None:
    bad_fixture = tmp_path / "bad.json"
    bad_fixture.write_text("[]", encoding="utf-8")

    result = _run("--fixture", str(bad_fixture), "--dashboard-json", "--now", NOW)

    assert result.returncode == 2
    assert "invalid quota/spend ledger" in result.stderr


def test_script_has_no_provider_sdk_network_credential_or_runtime_wiring() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    forbidden_tokens = [
        "import openai",
        "from openai",
        "import anthropic",
        "from anthropic",
        "google.generativeai",
        "google.cloud",
        "mistralai",
        "requests",
        "httpx",
        "urllib.request",
        "os.environ",
        "pass show",
        "hapax_secrets",
        "subprocess",
        "logos",
        "grafana",
        "health-monitor",
        "hapax-rte-state",
        "dispatch_task",
    ]
    for token in forbidden_tokens:
        assert token not in source
