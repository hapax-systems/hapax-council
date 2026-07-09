"""CLI tests for scripts/hapax-platform-capability-freshness."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from shared.capability_availability_guarantor import (
    RefreshStrategyRegistry,
    evaluate_route_availability,
)
from shared.platform_capability_receipts import (
    CliEvidence,
    EvidenceStatus,
    PlatformCapabilityReceipt,
    ProviderDocsEvidence,
    SurfaceEvidence,
    WrapperEvidence,
)
from shared.platform_capability_registry import (
    check_registry_freshness,
    load_platform_capability_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-freshness"
FRESH_NOW = "2026-05-09T21:00:00Z"
INERT_RECEIPT_DIR = REPO_ROOT / ".pytest-nonexistent-platform-receipts"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    receipt_args = () if "--receipt-dir" in args else ("--receipt-dir", str(INERT_RECEIPT_DIR))
    return subprocess.run(
        [str(SCRIPT), *receipt_args, *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _write_registry(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "platform-capability-registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_codex_receipt(receipt_dir: Path, *, observed_at: datetime) -> Path:
    receipt = PlatformCapabilityReceipt(
        receipt_id="test-codex-receipt",
        platform="codex",
        routes=["codex.headless.full", "codex.headless.spark"],
        observed_at=observed_at,
        stale_after="24h",
        cli=CliEvidence(binary="codex", available=True, version="codex-cli test"),
        wrapper=WrapperEvidence(
            path="scripts/hapax-codex",
            exists=True,
            executable=True,
            sha256="abc123",
        ),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=[
                "test:codex:capability",
                "host:hapax-appendix:codex:exec:auth:saved-login:observed",
            ],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=[
                "test:codex:resource",
                "local:current-codex-session:filesystem-shell-browser-usable:test",
            ],
        ),
        quota=SurfaceEvidence(
            status=EvidenceStatus.UNOBSERVABLE,
            source="test",
            observed_at=observed_at,
            stale_after="15m",
            evidence_refs=["local:codex:quota-probe:unobservable"],
            reason_codes=["account_live_quota_receipt_absent"],
        ),
        provider_docs=ProviderDocsEvidence(
            refs=["test:codex:provider-docs"],
            fetched_at=observed_at,
            stale_after="30d",
        ),
    )
    receipt_dir.mkdir(parents=True)
    path = receipt_dir / "codex.json"
    path.write_text(json.dumps(receipt.model_dump(mode="json")), encoding="utf-8")
    return path


def _mark_fresh(route: dict) -> None:
    route["route_state"] = "active"
    route["blocked_reasons"] = []
    route["freshness"]["capability_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["quota_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["resource_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["provider_docs_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["evidence"] = {
        "capability": {
            "evidence_refs": ["test:fresh-capability"],
            "blocked_reasons": [],
        },
        "quota": {
            "evidence_refs": ["test:fresh-quota"],
            "blocked_reasons": [],
        },
        "resource": {
            "evidence_refs": ["test:fresh-resource"],
            "blocked_reasons": [],
        },
        "provider_docs": {
            "evidence_refs": ["test:fresh-provider-docs"],
            "blocked_reasons": [],
        },
    }
    for score in route["capability_scores"].values():
        score["observed_at"] = "2026-05-09T20:55:00Z"
    for tool in route["tool_state"]:
        tool["observed_at"] = "2026-05-09T20:55:00Z"


def test_json_reports_blocked_seed_registry_nonzero(tmp_path: Path) -> None:
    result = _run(
        "--json",
        "--now",
        "2026-05-17T08:14:00Z",
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["route_count"] == len(load_platform_capability_registry().routes)
    assert payload["routes"][0]["route_id"] == "codex.headless.full"
    errors = "\n".join(payload["routes"][0]["errors"])
    assert "quota blocked: account_live_quota_receipt_absent" in errors
    assert "freshness is unknown" not in errors
    assert "account_live_quota_receipt_absent" in payload["routes"][0]["blocked_reasons"]
    assert payload["routes"][0]["evidence_refs"]


def test_json_fails_nonzero_for_unsupported_route(tmp_path: Path) -> None:
    result = _run(
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex/headless/nope",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["routes"][0]["supported"] is False
    assert payload["routes"][0]["errors"] == ["unsupported route: codex.headless.nope"]


def test_json_fails_structured_for_malformed_now(tmp_path: Path) -> None:
    result = _run(
        "--json",
        "--now",
        "definitely-not-a-date",
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 2
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "Invalid isoformat string" in payload["error"]
    assert "next action" in payload["error"]


def test_plain_text_fails_structured_for_malformed_now(tmp_path: Path) -> None:
    result = _run(
        "--now",
        "definitely-not-a-date",
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR: ")
    assert "Invalid isoformat string" in result.stderr
    assert "next action" in result.stderr


def test_json_succeeds_for_fresh_route_fixture(tmp_path: Path) -> None:
    payload = load_platform_capability_registry().model_dump(mode="json")
    route = next(route for route in payload["routes"] if route["route_id"] == "codex.headless.full")
    _mark_fresh(route)
    path = _write_registry(tmp_path, payload)

    result = _run(
        "--registry",
        str(path),
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["routes"][0]["errors"] == []


def test_json_applies_receipt_overlay_and_current_codex_session_availability(
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "receipts"
    _write_codex_receipt(
        receipt_dir,
        observed_at=datetime(2026, 5, 9, 20, 55, tzinfo=UTC),
    )

    result = _run(
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(receipt_dir),
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    route = payload["routes"][0]
    assert payload["ok"] is True
    assert route["blocked_reasons"] == []
    assert "platform-capability-receipt:codex:test-codex-receipt" in route["evidence_refs"]

    checked_at = datetime(2026, 5, 9, 21, 0, tzinfo=UTC)
    registry = load_platform_capability_registry(receipt_dir=receipt_dir, now=checked_at)
    registry_route = registry.require("codex.headless.full")
    freshness_check = check_registry_freshness(
        registry,
        route_ids=["codex.headless.full"],
        now=checked_at,
    ).routes[0]
    availability = evaluate_route_availability(
        registry_route,
        freshness_check,
        refresh_strategies=RefreshStrategyRegistry(()),
        now=checked_at,
    )

    assert availability.available is True
    assert availability.reason_codes == ()


def test_json_fails_nonzero_for_stale_provider_docs(tmp_path: Path) -> None:
    payload = load_platform_capability_registry().model_dump(mode="json")
    route = next(route for route in payload["routes"] if route["route_id"] == "codex.headless.full")
    _mark_fresh(route)
    route["freshness"]["provider_docs_checked_at"] = "2026-03-01T00:00:00Z"
    path = _write_registry(tmp_path, payload)

    result = _run(
        "--registry",
        str(path),
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "provider_docs stale" in payload["routes"][0]["errors"][0]
