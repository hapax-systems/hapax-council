"""CLI tests for scripts/hapax-platform-capability-freshness."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from shared.platform_capability_registry import load_platform_capability_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-freshness"
FRESH_NOW = "2026-05-09T21:00:00Z"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _write_registry(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "platform-capability-registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
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


def test_json_reports_blocked_seed_registry_nonzero() -> None:
    result = _run("--json", "--now", "2026-05-17T08:14:00Z", "--route", "codex.headless.full")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["route_count"] == 11
    assert payload["routes"][0]["route_id"] == "codex.headless.full"
    errors = "\n".join(payload["routes"][0]["errors"])
    assert "quota blocked: account_live_quota_receipt_absent" in errors
    assert "freshness is unknown" not in errors
    assert "account_live_quota_receipt_absent" in payload["routes"][0]["blocked_reasons"]
    assert payload["routes"][0]["evidence_refs"]


def test_json_fails_nonzero_for_unsupported_route() -> None:
    result = _run(
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex/headless/nope",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["routes"][0]["supported"] is False
    assert payload["routes"][0]["errors"] == ["unsupported route: codex.headless.nope"]


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
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["routes"][0]["errors"] == []


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
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "provider_docs stale" in payload["routes"][0]["errors"][0]
