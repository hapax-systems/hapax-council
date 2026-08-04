"""Tests for coding-platform capability receipts."""

from __future__ import annotations

import base64
import json
import os
import runpy
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from shared.dispatcher_policy import (
    DispatchAction,
    RouteAuthorityReceipt,
    build_dispatch_request,
    evaluate_dispatch_policy,
    load_dispatch_policy_sources,
    route_authority_receipt_payload_hash,
    route_decision_receipt_payload,
)
from shared.platform_capability_receipts import (
    PLATFORM_CAPABILITY_RECEIPT_DIR_ENV,
    load_platform_capability_receipt,
    receipt_is_fresh,
)
from shared.platform_capability_registry import load_platform_capability_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"
QUOTA_LEDGER = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"
NOW = "2026-05-17T19:55:00Z"
NOW_DT = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
API_NOW = "2026-06-04T16:00:00Z"
API_NOW_DT = datetime.fromisoformat(API_NOW.replace("Z", "+00:00"))
SECRET = "sk-live-secret-value"

if TYPE_CHECKING:
    import pytest


def _route_wrapper_receipt_payload() -> dict:
    return {
        "receipt_schema": 1,
        "receipt_id": "agy-test",
        "platform": "agy",
        "routes": ["agy.review.direct"],
        "observed_at": "2026-07-09T17:14:38Z",
        "stale_after": "24h",
        "cli": {
            "binary": "agy",
            "available": True,
            "version": "1.0.16",
            "error": None,
        },
        "wrapper": {
            "path": "~/projects/hapax-council/scripts/hapax-agy-reviewer",
            "exists": True,
            "executable": True,
            "sha256": "abc123",
        },
        "route_wrappers": {
            "agy.review.direct": {
                "path": "~/projects/hapax-council/scripts/hapax-agy-reviewer",
                "exists": True,
                "executable": True,
                "sha256": "route123",
            }
        },
        "config_refs": [],
        "tool_state": [],
        "mcp_status": [],
        "capability": {
            "status": "observed",
            "source": "local_receipt_probe",
            "observed_at": "2026-07-09T17:14:38Z",
            "stale_after": "24h",
            "evidence_refs": ["local:agy:cli-version:1.0.16"],
            "reason_codes": [],
        },
        "resource": {
            "status": "observed",
            "source": "local_receipt_probe",
            "observed_at": "2026-07-09T17:14:38Z",
            "stale_after": "24h",
            "evidence_refs": ["local:wrapper:exists:true"],
            "reason_codes": [],
        },
        "quota": {
            "status": "unobservable",
            "source": "local_receipt_probe",
            "observed_at": "2026-07-09T17:14:38Z",
            "stale_after": "15m",
            "evidence_refs": ["local:agy:quota-probe:unobservable"],
            "reason_codes": ["account_live_quota_receipt_absent"],
        },
        "provider_docs": {
            "refs": ["local:agy-docs"],
            "fetched_at": "2026-07-09T17:14:38Z",
            "stale_after": "30d",
            "fetch_status": "observed",
        },
        "known_unknowns": [],
    }


def test_load_receipt_accepts_route_specific_wrapper_evidence(tmp_path: Path) -> None:
    path = tmp_path / "agy.json"
    payload = _route_wrapper_receipt_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")

    receipt = load_platform_capability_receipt(path)

    assert receipt.route_wrappers["agy.review.direct"].sha256 == "route123"


def test_load_receipt_rejects_route_wrapper_for_undeclared_route(tmp_path: Path) -> None:
    path = tmp_path / "agy.json"
    payload = _route_wrapper_receipt_payload()
    payload["route_wrappers"]["agy.review.other"] = {
        "path": "~/projects/hapax-council/scripts/hapax-agy-reviewer-other",
        "exists": True,
        "executable": True,
        "sha256": "other123",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="route_wrappers keys must be declared routes"):
        load_platform_capability_receipt(path)


def _run_receipts(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    now: str = NOW,
    platform: str = "codex",
    registry: Path = REGISTRY,
    codex_exec_auth_probe: bool = True,
    codex_access_token: bool = True,
    timeout: float | None = None,
    codex_exec_auth_timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    # These receipt unit tests use fake local Codex binaries. Make that host
    # selection explicit so the helper does not accidentally exercise the
    # production no-env default of appendix.
    if platform == "codex" and (env is None or "HAPAX_CODEX_EXEC_AUTH_HOST" not in env):
        merged_env["HAPAX_CODEX_EXEC_AUTH_HOST"] = "local"
    if platform == "codex" and (env is None or "HAPAX_CODEX_BIN" not in env):
        merged_env.pop("HAPAX_CODEX_BIN", None)
    if platform == "codex" and (env is None or "HAPAX_CODEX_BIN_PATH" not in env):
        merged_env.pop("HAPAX_CODEX_BIN_PATH", None)
    if (
        platform == "codex"
        and codex_exec_auth_probe
        and codex_access_token
        and (env is None or "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE" not in env)
    ):
        merged_env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(
            _write_codex_access_token(tmp_path / "codex-oauth")
        )
    args = [
        sys.executable,
        str(SCRIPT),
        "--registry",
        str(registry),
        "--receipt-dir",
        str(tmp_path),
        "--platform",
        platform,
        "--now",
        now,
    ]
    if timeout is not None:
        args += ["--timeout", str(timeout)]
    if codex_exec_auth_timeout is not None:
        args += ["--codex-exec-auth-timeout", str(codex_exec_auth_timeout)]
    if codex_exec_auth_probe:
        args.append("--codex-exec-auth-probe")
    args.append("--json")
    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        env=merged_env,
    )


def _fake_binary(bin_dir: Path, name: str, output: str) -> None:
    target = bin_dir / name
    target.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR)


def _write_codex_access_token(root: Path, *, exp: int | None = None) -> Path:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": exp or int(time.time()) + 3600}).encode())
        .decode()
        .rstrip("=")
    )
    root.mkdir(parents=True, exist_ok=True)
    target = root / "access_token"
    target.write_text(f"{header}.{payload}.sig", encoding="utf-8")
    target.chmod(0o600)
    return target


def _fake_codex_exec_failure(bin_dir: Path, stderr: str) -> None:
    target = bin_dir / "codex"
    target.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "--version" ]; then',
                "  printf '%s\\n' 'codex-cli 9.9.9'",
                "  exit 0",
                "fi",
                'if [ "$1" = "exec" ]; then',
                f"  printf '%s\\n' '{stderr}' >&2",
                "  exit 1",
                "fi",
                "exit 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target.chmod(target.stat().st_mode | stat.S_IXUSR)


def _fake_codex_exec_success(
    path: Path,
    marker: Path,
    token_marker: Path | None = None,
    codex_home_marker: Path | None = None,
    codex_api_key_marker: Path | None = None,
    openai_api_key_marker: Path | None = None,
    stdout: str = (
        '{"type":"item.completed","item":{"type":"agent_message",'
        '"text":"HAPAX_CODEX_EXEC_AUTH_OK"}}'
    ),
) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "--version" ]; then',
                "  printf '%s\\n' 'codex-cli configured 9.9.9'",
                "  exit 0",
                "fi",
                'if [ "$1" = "exec" ]; then',
                f"  printf '%s\\n' exec > '{marker}'",
                *(
                    [f'  printf "%s\\n" "${{CODEX_ACCESS_TOKEN:-}}" > "{token_marker}"']
                    if token_marker is not None
                    else []
                ),
                *(
                    [f'  printf "%s\\n" "${{CODEX_HOME:-}}" > "{codex_home_marker}"']
                    if codex_home_marker is not None
                    else []
                ),
                *(
                    [f'  printf "%s\\n" "${{CODEX_API_KEY:-}}" > "{codex_api_key_marker}"']
                    if codex_api_key_marker is not None
                    else []
                ),
                *(
                    [f'  printf "%s\\n" "${{OPENAI_API_KEY:-}}" > "{openai_api_key_marker}"']
                    if openai_api_key_marker is not None
                    else []
                ),
                f"  printf '%s\\n' '{stdout}'",
                "  exit 0",
                "fi",
                "exit 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_codex_exec_timeout(bin_dir: Path) -> None:
    target = bin_dir / "codex"
    target.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "--version" ]; then',
                "  printf '%s\\n' 'codex-cli 9.9.9'",
                "  exit 0",
                "fi",
                'if [ "$1" = "exec" ]; then',
                "  /bin/sleep 2",
                "  exit 0",
                "fi",
                "exit 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target.chmod(target.stat().st_mode | stat.S_IXUSR)


def _fake_wrapper(home_dir: Path, relative_path: str) -> None:
    target = home_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR)


def _fresh_quota_ledger(tmp_path: Path, *, captured_at: str) -> Path:
    payload = json.loads(QUOTA_LEDGER.read_text(encoding="utf-8"))
    payload["ledger_id"] = "quota-spend-ledger-test-fresh"
    payload["captured_at"] = captured_at
    target_dir = tmp_path / "quota-ledger"
    target_dir.mkdir()
    target = target_dir / "quota-spend-ledger.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def _current_iso_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_route_authority_receipt(
    receipt_dir: Path,
    *,
    receipt_id: str,
    route_id: str,
    receipt_type: str,
    quality_floors: list[str] | None = None,
    task_ids: list[str] | None = None,
    mutation_surfaces: list[str] | None = None,
    issued_at: str | None = None,
    stale_after: str = "24h",
    payload_hash: str | None = None,
) -> Path:
    payload: dict[str, object] = {
        "route_authority_receipt_schema": 1,
        "receipt_id": receipt_id,
        "receipt_type": receipt_type,
        "route_id": route_id,
        "issued_at": issued_at or _current_iso_z(),
        "stale_after": stale_after,
        "signed_by": "operator",
        "evidence_refs": [f"test:{receipt_id}"],
        "quality_floors": quality_floors or [],
        "task_ids": task_ids or [],
        "mutation_surfaces": mutation_surfaces or [],
    }
    payload["signed_payload_sha256"] = payload_hash or route_authority_receipt_payload_hash(payload)
    target_dir = receipt_dir / "route-authority"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{receipt_id}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def _mark_platform_receipt_account_live_quota_observed(
    receipt_dir: Path,
    *,
    platform: str = "codex",
) -> None:
    receipt_path = receipt_dir / f"{platform}.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    quota = payload["quota"]
    quota["status"] = "observed"
    quota["reason_codes"] = []
    quota["evidence_refs"] = list(
        dict.fromkeys(
            [
                *quota.get("evidence_refs", []),
                f"test:{platform}:account-live-quota:observed",
            ]
        )
    )
    payload["known_unknowns"] = [
        item
        for item in payload.get("known_unknowns", [])
        if "Account-live subscription quota" not in item
    ]
    receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def test_receipt_refresh_redacts_secret_env_and_records_missing_cli(tmp_path: Path) -> None:
    result = _run_receipts(
        tmp_path,
        env={"PATH": "", "OPENAI_API_KEY": SECRET},
    )

    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout
    receipt_text = (tmp_path / "codex.json").read_text(encoding="utf-8")
    assert SECRET not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["cli"]["available"] is False
    assert "cli_missing_or_unusable" in receipt["capability"]["reason_codes"]
    assert all(item["redacted"] is True for item in receipt["config_refs"])


def test_fresh_subscription_receipt_clears_account_live_quota_blocker(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_success(bin_dir / "codex", tmp_path / "codex-used")

    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir), "OPENAI_API_KEY": SECRET})

    assert result.returncode == 0, result.stderr
    assert SECRET not in (tmp_path / "codex.json").read_text(encoding="utf-8")
    registry = load_platform_capability_registry(REGISTRY, receipt_dir=tmp_path, now=NOW_DT)
    route = registry.require("codex.headless.full")

    assert route.freshness.quota_checked_at is not None
    assert "account_live_quota_receipt_absent" not in route.blocked_reasons
    assert "account_live_quota_receipt_absent" not in route.freshness.evidence.quota.blocked_reasons
    assert route.route_state.value == "active"
    assert any(
        ref.startswith("platform-capability-receipt:codex:")
        for ref in route.freshness.evidence.quota.evidence_refs
    )
    assert route.tool_state[0].evidence_ref.startswith("platform-capability-receipt:codex:")


def test_codex_receipt_without_exec_auth_probe_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir)},
        codex_exec_auth_probe=False,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert receipt["capability"]["status"] == "blocked"
    assert "codex_exec_auth_probe_not_requested" in receipt["capability"]["reason_codes"]
    assert not any(
        ref == "local:codex:exec:auth:observed" for ref in receipt["capability"]["evidence_refs"]
    )


def test_codex_receipt_exec_auth_failure_fails_closed_with_classified_reason(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_failure(
        bin_dir,
        "agent identity JWT payload is not valid JSON; refresh_token_invalidated; login required",
    )

    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)})

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    reasons = receipt["capability"]["reason_codes"]
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "blocked"
    assert "codex_exec_auth_failed" in reasons
    assert "codex_exec_auth_agent_identity_jwt_invalid_json" in reasons
    assert "codex_exec_auth_refresh_token_invalidated" in reasons
    assert "codex_exec_auth_token_invalidated" not in reasons
    assert "codex_exec_auth_login_required" in reasons
    assert not any(
        ref == "local:codex:exec:auth:observed" for ref in receipt["capability"]["evidence_refs"]
    )


def test_codex_receipt_exec_auth_failure_classifies_mixed_streams(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target = bin_dir / "codex"
    target.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "--version" ]; then',
                "  printf '%s\\n' 'codex-cli 9.9.9'",
                "  exit 0",
                "fi",
                'if [ "$1" = "exec" ]; then',
                "  printf '%s\\n' 'Reading additional input from stdin...' >&2",
                "  printf '%s\\n' 'auth error code: token_invalidated'",
                "  printf '%s\\n' 'code: refresh_token_invalidated'",
                "  exit 1",
                "fi",
                "exit 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target.chmod(target.stat().st_mode | stat.S_IXUSR)

    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)})

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    reasons = receipt["capability"]["reason_codes"]
    assert "codex_exec_auth_failed" in reasons
    assert "codex_exec_auth_token_invalidated" in reasons
    assert "codex_exec_auth_refresh_token_invalidated" in reasons


def test_codex_receipt_exec_auth_failure_does_not_overmatch_login_substring(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_failure(bin_dir, "cataloging metadata failed")

    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)})

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    reasons = receipt["capability"]["reason_codes"]
    assert "codex_exec_auth_failed" in reasons
    assert "codex_exec_auth_login_required" not in reasons
    assert not any(
        ref == "local:codex:exec:auth:observed" for ref in receipt["capability"]["evidence_refs"]
    )


def test_codex_receipt_exec_auth_zero_exit_without_sentinel_fails_closed(
    tmp_path: Path,
) -> None:
    configured = tmp_path / "configured-codex"
    marker = tmp_path / "configured-codex-used"
    _fake_codex_exec_success(configured, marker, stdout="not the auth sentinel")

    result = _run_receipts(
        tmp_path,
        env={
            "PATH": "",
            "NPM_CONFIG_PREFIX": "",
            "HAPAX_CODEX_BIN_PATH": str(configured),
        },
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert marker.read_text(encoding="utf-8").strip() == "exec"
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "blocked"
    assert "codex_exec_auth_sentinel_missing" in receipt["capability"]["reason_codes"]
    assert not any(
        ref == "local:codex:exec:auth:observed" for ref in receipt["capability"]["evidence_refs"]
    )


def test_codex_exec_auth_sentinel_parser_accepts_complete_output_shapes() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    observed = namespace["codex_exec_auth_sentinel_observed"]

    assert observed("HAPAX_CODEX_EXEC_AUTH_OK\n") is False
    assert (
        observed('{"type":"response.output_text.done","text":"HAPAX_CODEX_EXEC_AUTH_OK"}\n') is True
    )
    assert (
        observed(
            '{"role":"assistant","content":[{"type":"text","text":"HAPAX_CODEX_EXEC_AUTH_OK"}]}\n'
        )
        is True
    )
    assert (
        observed(
            '{"message":{"role":"assistant","content":[{"type":"output_text","text":"HAPAX_CODEX_EXEC_AUTH_OK"}]}}\n'
        )
        is True
    )
    assert observed('{"message":"HAPAX_CODEX_EXEC_AUTH_OK"}\n') is False
    assert (
        observed('{"type":"response.output_text.delta","text":"HAPAX_CODEX_EXEC_AUTH_OK"}\n')
        is False
    )


def test_codex_receipt_exec_auth_missing_binary_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = _run_receipts(
        tmp_path,
        env={"PATH": "", "HOME": str(home), "NPM_CONFIG_PREFIX": ""},
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    reasons = receipt["capability"]["reason_codes"]
    assert receipt["cli"]["available"] is False
    assert receipt["capability"]["status"] == "blocked"
    assert "cli_missing_or_unusable" in reasons
    assert "codex_exec_auth_binary_missing" in reasons


def test_codex_receipt_exec_auth_timeout_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_timeout(bin_dir)

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir)},
        codex_exec_auth_timeout=0.1,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    reasons = receipt["capability"]["reason_codes"]
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "blocked"
    assert "codex_exec_auth_timeout" in reasons


def test_codex_exec_auth_timeout_env_malformed_falls_back_to_default(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_failure(bin_dir, "login required")

    result = _run_receipts(
        tmp_path,
        env={
            "PATH": "",
            "HAPAX_CODEX_BIN_PATH": str(bin_dir / "codex"),
            "HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS": "not-a-float",
        },
        codex_access_token=False,
    )

    assert result.returncode == 0, result.stderr
    assert "invalid HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS" in result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "blocked"
    assert "codex_exec_auth_failed" in receipt["capability"]["reason_codes"]


def test_codex_exec_auth_timeout_env_nonpositive_falls_back_to_default(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_failure(bin_dir, "login required")

    result = _run_receipts(
        tmp_path,
        env={
            "PATH": "",
            "HAPAX_CODEX_BIN_PATH": str(bin_dir / "codex"),
            "HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS": "0",
        },
        codex_access_token=False,
    )

    assert result.returncode == 0, result.stderr
    assert "nonpositive HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS" in result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "blocked"
    assert "codex_exec_auth_failed" in receipt["capability"]["reason_codes"]


def test_codex_exec_auth_timeout_env_nonfinite_falls_back_to_default(
    tmp_path: Path,
) -> None:
    for raw in ("nan", "inf"):
        case_dir = tmp_path / raw
        bin_dir = case_dir / "bin"
        bin_dir.mkdir(parents=True)
        _fake_codex_exec_failure(bin_dir, "login required")

        result = _run_receipts(
            case_dir,
            env={
                "PATH": "",
                "HAPAX_CODEX_BIN_PATH": str(bin_dir / "codex"),
                "HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS": raw,
            },
            codex_access_token=False,
        )

        assert result.returncode == 0, result.stderr
        assert "invalid HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS" in result.stderr
        receipt = json.loads((case_dir / "codex.json").read_text(encoding="utf-8"))
        assert receipt["cli"]["available"] is True
        assert receipt["capability"]["status"] == "blocked"
        assert "codex_exec_auth_failed" in receipt["capability"]["reason_codes"]


def test_codex_exec_auth_timeout_cli_invalid_fails_closed(tmp_path: Path) -> None:
    for raw in ("0", "nan", "inf"):
        case_dir = tmp_path / raw
        bin_dir = case_dir / "bin"
        bin_dir.mkdir(parents=True)
        marker = case_dir / "codex-marker.txt"
        _fake_codex_exec_success(bin_dir / "codex", marker)

        result = _run_receipts(
            case_dir,
            env={"PATH": str(bin_dir)},
            codex_exec_auth_timeout=float(raw),
        )

        assert result.returncode == 0, result.stderr
        assert not marker.exists()
        receipt = json.loads((case_dir / "codex.json").read_text(encoding="utf-8"))
        assert receipt["cli"]["available"] is True
        assert receipt["capability"]["status"] == "blocked"
        assert "codex_exec_auth_invalid_timeout" in receipt["capability"]["reason_codes"]


def test_codex_receipt_exec_auth_timeout_is_separate_from_cli_timeout(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "codex-marker.txt"
    target = bin_dir / "codex"
    _fake_codex_exec_success(target, marker)
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "  printf '%s\\n' exec >",
            "  /bin/sleep 0.2\n  printf '%s\\n' exec >",
        ),
        encoding="utf-8",
    )

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir)},
        timeout=0.1,
        codex_exec_auth_timeout=1.0,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "observed"
    assert "codex_exec_auth_timeout" not in receipt["capability"]["reason_codes"]


def test_codex_receipt_exec_auth_ignores_missing_published_token(
    tmp_path: Path,
) -> None:
    configured = tmp_path / "configured-codex"
    marker = tmp_path / "configured-codex-used"
    _fake_codex_exec_success(configured, marker)

    result = _run_receipts(
        tmp_path,
        env={
            "PATH": "",
            "NPM_CONFIG_PREFIX": "",
            "HAPAX_CODEX_BIN_PATH": str(configured),
            "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE": str(tmp_path / "missing-access-token"),
            "CODEX_ACCESS_TOKEN": "ambient-token-must-not-admit",
        },
        codex_access_token=False,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert marker.read_text(encoding="utf-8").strip() == "exec"
    assert receipt["capability"]["status"] == "observed"
    assert "local:codex:exec:auth:observed" in receipt["capability"]["evidence_refs"]


def test_codex_receipt_exec_auth_ignores_unsafe_published_token(
    tmp_path: Path,
) -> None:
    configured = tmp_path / "configured-codex"
    marker = tmp_path / "configured-codex-used"
    _fake_codex_exec_success(configured, marker)
    token_file = _write_codex_access_token(tmp_path / "codex-oauth")
    token_file.chmod(0o644)

    result = _run_receipts(
        tmp_path,
        env={
            "PATH": "",
            "NPM_CONFIG_PREFIX": "",
            "HAPAX_CODEX_BIN_PATH": str(configured),
            "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE": str(token_file),
        },
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert marker.read_text(encoding="utf-8").strip() == "exec"
    assert receipt["capability"]["status"] == "observed"
    assert "local:codex:exec:auth:observed" in receipt["capability"]["evidence_refs"]


def test_codex_receipt_exec_auth_ignores_expiring_published_token(
    tmp_path: Path,
) -> None:
    configured = tmp_path / "configured-codex"
    marker = tmp_path / "configured-codex-used"
    _fake_codex_exec_success(configured, marker)
    token_file = _write_codex_access_token(tmp_path / "codex-oauth", exp=int(time.time()) - 60)

    result = _run_receipts(
        tmp_path,
        env={
            "PATH": "",
            "NPM_CONFIG_PREFIX": "",
            "HAPAX_CODEX_BIN_PATH": str(configured),
            "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE": str(token_file),
        },
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert marker.read_text(encoding="utf-8").strip() == "exec"
    assert receipt["capability"]["status"] == "observed"
    assert "local:codex:exec:auth:observed" in receipt["capability"]["evidence_refs"]


def test_codex_receipt_exec_auth_exec_oserror_fails_closed(tmp_path: Path) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="__test__")
    token_file = _write_codex_access_token(tmp_path / "codex-oauth")
    configured = tmp_path / "configured-codex"
    configured.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    configured.chmod(0o755)

    with (
        patch.dict(
            os.environ,
            {
                "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE": str(token_file),
                "HAPAX_CODEX_BIN_PATH": str(configured),
            },
        ),
        patch("subprocess.run", side_effect=OSError("exec failed")),
    ):
        refs, reasons = module["observe_codex_exec_auth"](enabled=True, timeout=1.0)

    assert refs == []
    assert reasons == ["codex_exec_auth_exec_failed"]


def test_codex_receipt_remote_exec_auth_strips_access_token_without_local_binary(
    tmp_path: Path,
) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="__test__")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fail_if_local_binary_resolved(_platform: str) -> tuple[None, None, None]:
        raise AssertionError("remote exec auth must not require a local codex binary")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                '{"type":"item.completed","item":{"type":"agent_message",'
                '"text":"HAPAX_CODEX_EXEC_AUTH_OK"}}'
            ),
            stderr="",
        )

    module["resolve_platform_binary"] = fail_if_local_binary_resolved
    current_host = module["current_host"]()
    remote_alias = "podium" if current_host == "hapax-appendix" else "appendix"
    remote_host = module["normalize_host"](remote_alias)
    with (
        patch.dict(
            os.environ,
            {
                "HAPAX_CODEX_EXEC_AUTH_HOST": remote_alias,
                "HAPAX_CODEX_EXEC_AUTH_REMOTE_CWD": str(tmp_path / "remote cwd"),
                "CODEX_ACCESS_TOKEN": "ambient-token-must-not-prove-auth",
                "CODEX_HOME": str(tmp_path / "ambient-codex-home"),
                "CODEX_API_KEY": "ambient-codex-api-key-must-not-prove-auth",
                "OPENAI_API_KEY": "ambient-openai-api-key-must-not-prove-auth",
            },
        ),
        patch("subprocess.run", side_effect=fake_run),
    ):
        refs, reasons = module["observe_codex_exec_auth"](enabled=True, timeout=7.0)

    assert reasons == []
    assert refs == [
        f"remote:{remote_host}:codex:exec:auth:observed",
        f"host:{remote_host}:codex:exec:auth:saved-login:observed",
    ]
    assert len(calls) == 1
    ssh_args, kwargs = calls[0]
    assert ssh_args[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=7"]
    assert ssh_args[5] == remote_alias
    remote_command = ssh_args[6]
    assert remote_command.startswith("bash -lc ")
    assert (
        "unset CODEX_ACCESS_TOKEN CODEX_HOME CODEX_API_KEY OPENAI_API_KEY; exec codex exec"
    ) in remote_command
    assert "--cd " in remote_command
    assert str(tmp_path / "remote cwd") in remote_command
    assert "ambient-token-must-not-prove-auth" not in remote_command
    ssh_env = kwargs["env"]
    assert isinstance(ssh_env, dict)
    assert "CODEX_ACCESS_TOKEN" not in ssh_env
    assert "CODEX_HOME" not in ssh_env
    assert "CODEX_API_KEY" not in ssh_env
    assert "OPENAI_API_KEY" not in ssh_env
    assert kwargs["timeout"] == 12.0


def test_codex_receipt_current_host_alias_emits_current_host_witness(
    tmp_path: Path,
) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="__test__")
    configured = tmp_path / "configured-codex"
    marker = tmp_path / "configured-codex-used"
    _fake_codex_exec_success(configured, marker)

    module["observe_codex_exec_auth"].__globals__["current_host"] = lambda: "hapax-appendix"
    module["observe_codex_exec_auth"].__globals__["resolve_platform_binary"] = lambda _platform: (
        None,
        str(configured),
        None,
    )
    with patch.dict(
        os.environ,
        {
            "HAPAX_CODEX_EXEC_AUTH_HOST": "appendix",
            "HAPAX_CODEX_BIN_PATH": str(configured),
        },
    ):
        refs, reasons = module["observe_codex_exec_auth"](enabled=True, timeout=7.0)

    assert reasons == []
    assert refs == [
        "local:codex:exec:auth:observed",
        "host:hapax-appendix:codex:exec:auth:saved-login:observed",
    ]
    assert marker.read_text(encoding="utf-8").strip() == "exec"


def test_codex_default_exec_auth_host_matches_admission_predicates(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_CODEX_EXEC_AUTH_HOST", raising=False)
    monkeypatch.delenv("HAPAX_DISPATCH_HOST", raising=False)
    monkeypatch.delenv("HAPAX_DEFAULT_DISPATCH_HOST", raising=False)
    receipts = runpy.run_path(str(SCRIPT), run_name="__test__")
    telemetry = runpy.run_path(
        str(REPO_ROOT / "scripts" / "hapax-quota-telemetry-writer"),
        run_name="__test__",
    )
    import shared.capability_availability_guarantor as guarantor

    default_host = receipts["codex_exec_auth_host"]()

    assert default_host == "appendix"
    assert receipts["normalize_host"](default_host) == "hapax-appendix"
    assert telemetry["expected_codex_exec_auth_hosts"]() == telemetry["host_token_variants"](
        default_host
    )
    assert guarantor._expected_exec_auth_hosts() == guarantor._host_token_variants(default_host)


def test_codex_receipt_exec_auth_probe_strips_codex_auth_env(
    tmp_path: Path,
) -> None:
    configured = tmp_path / "configured-codex"
    marker = tmp_path / "configured-codex-used"
    token_marker = tmp_path / "configured-codex-token"
    codex_home_marker = tmp_path / "configured-codex-home"
    codex_api_key_marker = tmp_path / "configured-codex-api-key"
    openai_api_key_marker = tmp_path / "configured-openai-api-key"
    _fake_codex_exec_success(
        configured,
        marker,
        token_marker=token_marker,
        codex_home_marker=codex_home_marker,
        codex_api_key_marker=codex_api_key_marker,
        openai_api_key_marker=openai_api_key_marker,
    )
    token_file = _write_codex_access_token(tmp_path / "codex-oauth")
    ambient_codex_home = tmp_path / "ambient-codex-home"

    result = _run_receipts(
        tmp_path,
        env={
            "PATH": "",
            "NPM_CONFIG_PREFIX": "",
            "HAPAX_CODEX_BIN_PATH": str(configured),
            "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE": str(token_file),
            "CODEX_ACCESS_TOKEN": "ambient-token-must-be-replaced",
            "CODEX_HOME": str(ambient_codex_home),
            "CODEX_API_KEY": "ambient-codex-api-key-must-not-prove-auth",
            "OPENAI_API_KEY": "ambient-openai-api-key-must-not-prove-auth",
        },
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert marker.read_text(encoding="utf-8").strip() == "exec"
    assert token_marker.read_text(encoding="utf-8").strip() == ""
    observed_codex_home = codex_home_marker.read_text(encoding="utf-8").strip()
    assert observed_codex_home == ""
    assert codex_api_key_marker.read_text(encoding="utf-8").strip() == ""
    assert openai_api_key_marker.read_text(encoding="utf-8").strip() == ""
    assert receipt["capability"]["status"] == "observed"
    assert "local:codex:exec:auth:observed" in receipt["capability"]["evidence_refs"]


def test_codex_receipt_exec_auth_probe_uses_bin_path_fallback_when_path_missing(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    configured = tmp_path / "configured-codex"
    marker = tmp_path / "configured-codex-used"
    _fake_codex_exec_success(configured, marker)

    result = _run_receipts(
        tmp_path,
        env={
            "PATH": "",
            "HOME": str(home),
            "NPM_CONFIG_PREFIX": "",
            "HAPAX_CODEX_BIN_PATH": str(configured),
        },
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert marker.read_text(encoding="utf-8").strip() == "exec"
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "observed"
    assert "local:codex:exec:auth:observed" in receipt["capability"]["evidence_refs"]


def test_codex_receipt_exec_auth_probe_ignores_wrapper_bin_env_for_cli_probe(
    tmp_path: Path,
) -> None:
    bad_bin_dir = tmp_path / "bad-bin"
    bad_bin_dir.mkdir()
    _fake_codex_exec_failure(bad_bin_dir, "PATH codex failed")
    wrapper_bin = tmp_path / "hapax-codex-wrapper"
    wrapper_marker = tmp_path / "wrapper-bin-used"
    _fake_codex_exec_success(wrapper_bin, wrapper_marker)

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bad_bin_dir), "HAPAX_CODEX_BIN": str(wrapper_bin)},
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert not wrapper_marker.exists()
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "blocked"
    assert "codex_exec_auth_failed" in receipt["capability"]["reason_codes"]
    assert not any(
        ref == "local:codex:exec:auth:observed" for ref in receipt["capability"]["evidence_refs"]
    )


def test_codex_receipt_exec_auth_probe_keeps_path_before_bin_path_fallback(
    tmp_path: Path,
) -> None:
    bad_bin_dir = tmp_path / "bad-bin"
    bad_bin_dir.mkdir()
    _fake_codex_exec_failure(bad_bin_dir, "PATH codex failed")
    configured_path = tmp_path / "configured-codex-path"
    marker = tmp_path / "configured-codex-path-used"
    _fake_codex_exec_success(configured_path, marker)

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bad_bin_dir), "HAPAX_CODEX_BIN_PATH": str(configured_path)},
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "codex.json").read_text(encoding="utf-8"))
    assert not marker.exists()
    assert receipt["cli"]["available"] is True
    assert receipt["capability"]["status"] == "blocked"
    assert "codex_exec_auth_failed" in receipt["capability"]["reason_codes"]
    assert not any(
        ref == "local:codex:exec:auth:observed" for ref in receipt["capability"]["evidence_refs"]
    )


def test_future_platform_receipt_is_not_fresh(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir)},
        now="2026-07-05T15:00:00Z",
    )
    assert result.returncode == 0, result.stderr
    receipt = load_platform_capability_receipt(tmp_path / "codex.json")

    assert receipt_is_fresh(receipt, now=NOW_DT) is False


def test_fresh_subscription_receipt_allows_local_dispatch_without_account_live_quota_api(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_success(bin_dir / "codex", tmp_path / "codex-used")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HAPAX_CODEX_EXEC_AUTH_HOST": "local"},
        now=_current_iso_z(),
    )
    assert result.returncode == 0, result.stderr

    with patch.dict(os.environ, {"HAPAX_CODEX_EXEC_AUTH_HOST": "local"}):
        sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
        task_fields = {
            "status": "claimed",
            "assigned_to": "cx-green",
            "authority_case": "CASE-CAPACITY-ROUTING-001",
            "authority_item": "PLATFORM-RECEIPT-TEST",
            "priority": "p0",
            "wsjf": 12,
            "route_metadata_schema": 1,
            "quality_floor": "frontier_required",
            "authority_level": "authoritative",
            "mutation_surface": "source",
            "mutation_scope_refs": ["shared/platform_capability_registry.py"],
        }
        request = build_dispatch_request(
            task_id="platform-receipt-present",
            lane="cx-green",
            platform="codex",
            mode="headless",
            profile="full",
            task_fields=task_fields,
            registry=sources.registry,
            registry_error=sources.registry_error,
            quota_ledger=sources.quota_ledger,
            quota_error=sources.quota_error,
        )

        decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert decision.registry_freshness_green is True
    assert "policy_launch" in decision.reason_codes
    assert "account_live_quota_evidence_absent" not in decision.reason_codes
    assert "capability_availability_degraded" not in decision.reason_codes


def test_antigrav_receipt_cannot_reintroduce_excised_route(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "agy", "1.0.0")
    wrapper = tmp_path / "home" / ".local" / "bin" / "hapax-antigrav"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    for platform in ("antigrav", "Antigrav", "antigravity", "gemini-cli"):
        result = _run_receipts(
            tmp_path,
            env={"PATH": str(bin_dir), "HOME": str(tmp_path / "home")},
            platform=platform,
        )

        assert result.returncode == 2
        assert f"platform '{platform.lower()}' is retired/excised" in result.stderr
        assert "agy.review.direct" in result.stderr
        assert not (tmp_path / f"{platform}.json").exists()


def test_agy_receipt_records_live_review_route_without_unblocking_quota(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))
    bin_dir = tmp_path / "bin"
    home_dir = tmp_path / "home"
    bin_dir.mkdir()
    bundled_cli_ref = (
        home_dir
        / ".gemini"
        / "antigravity-cli"
        / "builtin"
        / "skills"
        / "antigravity_guide"
        / "references"
        / "cli.md"
    )
    bundled_cli_ref.parent.mkdir(parents=True)
    bundled_cli_ref.write_text("# agy CLI reference\n", encoding="utf-8")
    _fake_binary(bin_dir, "agy", "1.0.10")

    result = _run_receipts(
        tmp_path,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home_dir)},
        platform="agy",
        now="2026-07-05T14:51:11Z",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["receipts"][0]["platform"] == "agy"
    assert payload["receipts"][0]["cli_available"] is True
    assert payload["receipts"][0]["wrapper_exists"] is True
    assert payload["receipts"][0]["quota_status"] == "unobservable"
    receipt = json.loads((tmp_path / "agy.json").read_text(encoding="utf-8"))
    assert receipt["platform"] == "agy"
    assert receipt["routes"] == ["agy.review.direct"]
    assert receipt["cli"]["version"] == "1.0.10"
    assert receipt["quota"]["reason_codes"] == ["account_live_quota_receipt_absent"]
    config_refs = {item["path"]: item for item in receipt["config_refs"]}
    assert (
        config_refs["~/.gemini/antigravity-cli/builtin/skills/antigravity_guide/references/cli.md"][
            "exists"
        ]
        is True
    )
    assert all(item["redacted"] is True for item in receipt["config_refs"])

    registry = load_platform_capability_registry(
        REGISTRY,
        receipt_dir=tmp_path,
        now=datetime(2026, 7, 5, 14, 52, tzinfo=UTC),
    )
    route = registry.require("agy.review.direct")
    assert route.route_state.value == "blocked"
    assert "agy_review_seat_receipt_admission_required" not in route.blocked_reasons
    assert "route_specific_quota_receipt_absent" in route.blocked_reasons


def test_claude_receipt_records_unusable_wrapper_per_route(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "claude", "claude-cli 2.1.143")
    good_wrapper = tmp_path / "hapax-claude-headless"
    good_wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    good_wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    bad_wrapper = tmp_path / "hapax-claude-reviewer"
    bad_wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    bad_wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR)
    registry_payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for route in registry_payload["routes"]:
        if route["platform"] != "claude":
            continue
        route["sanctioned_wrapper"] = (
            str(bad_wrapper) if route["route_id"] == "claude.review.opus" else str(good_wrapper)
        )
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    registry_path = registry_dir / "platform-capability-registry.json"
    registry_path.write_text(json.dumps(registry_payload), encoding="utf-8")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir)},
        platform="claude",
        registry=registry_path,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "claude.json").read_text(encoding="utf-8"))
    assert receipt["wrapper"]["path"] == str(good_wrapper)
    assert receipt["capability"]["status"] == "blocked"
    assert "sanctioned_wrapper_not_executable" not in receipt["capability"]["reason_codes"]
    assert (
        "sanctioned_wrapper_not_executable:hapax-claude-reviewer"
        in receipt["capability"]["reason_codes"]
    )
    assert not any(
        ref.endswith(f"{bad_wrapper}:sha256") or str(bad_wrapper) in ref
        for ref in receipt["capability"]["evidence_refs"]
    )
    assert receipt["route_wrappers"]["claude.review.opus"]["executable"] is False
    assert receipt["route_wrappers"]["claude.review.opus"]["sha256"] is not None
    assert receipt["resource"]["status"] == "blocked"
    assert "wrapper_not_executable" in receipt["resource"]["reason_codes"]
    assert any(ref.endswith("executable:false") for ref in receipt["resource"]["evidence_refs"])

    registry = load_platform_capability_registry(
        registry_path,
        receipt_dir=tmp_path,
        now=datetime(2026, 5, 17, 20, 0, tzinfo=UTC),
    )
    review_route = registry.require("claude.review.opus")
    headless_route = registry.require("claude.headless.full")
    assert "sanctioned_wrapper_not_executable" in review_route.blocked_reasons
    assert "wrapper_not_executable" in review_route.blocked_reasons
    assert "sanctioned_wrapper_not_executable" not in headless_route.blocked_reasons
    assert "wrapper_not_executable" not in headless_route.blocked_reasons


def test_agy_receipt_requires_executable_review_wrapper(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "agy", "1.0.10")
    wrapper = tmp_path / "non-executable-hapax-agy-reviewer"
    wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR)
    registry_payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for route in registry_payload["routes"]:
        if route["route_id"] == "agy.review.direct":
            route["sanctioned_wrapper"] = str(wrapper)
            break
    else:  # pragma: no cover - fixture invariant
        raise AssertionError("agy.review.direct route missing from registry fixture")
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    registry = registry_dir / "platform-capability-registry.json"
    registry.write_text(json.dumps(registry_payload), encoding="utf-8")

    result = _run_receipts(
        tmp_path,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path / "home")},
        platform="agy",
        registry=registry,
        now="2026-07-05T14:51:11Z",
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "agy.json").read_text(encoding="utf-8"))
    assert receipt["wrapper"]["exists"] is True
    assert receipt["wrapper"]["executable"] is False
    assert receipt["capability"]["status"] == "blocked"
    assert "sanctioned_wrapper_not_executable" in receipt["capability"]["reason_codes"]
    assert receipt["resource"]["status"] == "blocked"
    assert receipt["resource"]["reason_codes"] == ["wrapper_not_executable"]

    registry_with_receipt = load_platform_capability_registry(
        registry,
        receipt_dir=tmp_path,
        now=datetime(2026, 7, 5, 14, 52, tzinfo=UTC),
    )
    route = registry_with_receipt.require("agy.review.direct")
    assert route.route_state.value == "blocked"
    assert "agy_review_seat_receipt_admission_required" in route.blocked_reasons
    assert "sanctioned_wrapper_not_executable" in route.blocked_reasons
    assert "wrapper_not_executable" in route.blocked_reasons


def test_api_provider_gateway_receipt_allows_paid_gateway_dispatch(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "python3", f"Python 3.12.3 api_key={SECRET}")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "OPENAI_API_KEY": SECRET},
        now=API_NOW,
        platform="api",
    )

    assert result.returncode == 0, result.stderr
    receipt_text = (tmp_path / "api.json").read_text(encoding="utf-8")
    assert SECRET not in receipt_text
    receipt = json.loads(receipt_text)
    assert "api.headless.provider_gateway" in receipt["routes"]
    assert "api.headless.openrouter" in receipt["routes"]
    assert receipt["quota"]["status"] == "unobservable"
    assert receipt["known_unknowns"][0].startswith("Provider spend is authorized")

    registry = load_platform_capability_registry(REGISTRY, receipt_dir=tmp_path, now=API_NOW_DT)
    gateway = registry.require("api.headless.provider_gateway")
    cloud = registry.require("api.headless.api_frontier")
    openrouter = registry.require("api.headless.openrouter")

    assert gateway.route_state.value == "active"
    assert "provider_budget_receipt_absent" not in gateway.blocked_reasons
    assert "provider_gateway_evidence_absent" not in gateway.blocked_reasons
    assert cloud.route_state.value == "blocked"
    assert "cloud_burst_release_gate_absent" in cloud.blocked_reasons
    assert openrouter.route_state.value == "blocked"
    assert "capabilityio_measurement_absent" in openrouter.blocked_reasons
    assert "openrouter_paid_budget_receipt_absent" in openrouter.blocked_reasons

    sources = load_dispatch_policy_sources(
        registry_path=REGISTRY,
        quota_ledger_path=_fresh_quota_ledger(tmp_path, captured_at=API_NOW),
        receipt_dir=tmp_path,
        now=API_NOW_DT,
    )
    task_fields = {
        "status": "claimed",
        "assigned_to": "cctv-gateway",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "PROVIDER-GATEWAY-RECEIPT-TEST",
        "priority": "p0",
        "wsjf": 12,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "provider_spend",
        "mutation_scope_refs": ["~/llm-stack/litellm-config.yaml"],
        "risk_flags": {"provider_billing_sensitive": True},
    }
    request = build_dispatch_request(
        task_id="provider-gateway-receipt-present",
        lane="cctv-gateway",
        platform="api",
        mode="headless",
        profile="provider_gateway",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
        now=API_NOW_DT,
    )

    decision = evaluate_dispatch_policy(request, now=API_NOW_DT)

    assert request.capability is not None
    assert request.capability.paid_provider == "google"
    assert request.capability.paid_profile == "frontier-fast"
    assert request.quota is not None
    assert "tb-20260510-anthropic-api-steady-state" in request.quota.evidence_refs
    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert "policy_launch" in decision.reason_codes


def test_glmcp_known_unknowns_disclose_secret_read_without_persistence() -> None:
    namespace = runpy.run_path(str(SCRIPT))

    unknowns = namespace["known_unknowns_for"]("glmcp")

    assert any("may read the pass-backed secret" in item for item in unknowns)
    assert any("never persists the secret value" in item for item in unknowns)
    assert not any("never reads secret values" in item for item in unknowns)


def test_codex_known_unknowns_disclose_secret_read_without_persistence() -> None:
    namespace = runpy.run_path(str(SCRIPT))

    unknowns = namespace["known_unknowns_for"]("codex")

    assert any("saved-login codex exec sentinel" in item for item in unknowns)
    assert any("never injects or persists bearer tokens" in item for item in unknowns)
    assert not any("never reads secret values" in item for item in unknowns)


def test_stale_receipt_is_not_consumed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir)},
        now="2026-05-01T00:00:00Z",
    )
    assert result.returncode == 0, result.stderr

    registry = load_platform_capability_registry(REGISTRY, receipt_dir=tmp_path)
    route = registry.require("codex.headless.full")

    assert not any(
        ref.startswith("platform-capability-receipt:codex:")
        for ref in route.freshness.evidence.quota.evidence_refs
    )


def test_dispatch_policy_holds_when_receipts_are_absent(tmp_path: Path) -> None:
    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    task_fields = {
        "status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "PLATFORM-RECEIPT-TEST",
        "priority": "p0",
        "wsjf": 12,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/platform_capability_registry.py"],
    }
    request = build_dispatch_request(
        task_id="platform-receipt-absent",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )

    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.HOLD
    assert "quota_telemetry_stale_or_unknown" in decision.reason_codes
    assert any("account_live_quota_receipt_absent" in reason for reason in decision.reason_codes)


def test_signed_opus_entitlement_receipt_allows_dispatch_without_policy_rollback(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    home_dir = tmp_path / "home"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "claude", "claude-cli 2.1.143")
    _fake_wrapper(home_dir, ".local/bin/hapax-claude-headless")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HOME": str(home_dir)},
        now=_current_iso_z(),
        platform="claude",
    )
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path, platform="claude")
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="opus-entitlement-test",
        route_id="claude.headless.opus",
        receipt_type="opus_model_entitlement",
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    task_fields = {
        "status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "OPUS-ENTITLEMENT-TEST",
        "priority": "p1",
        "wsjf": 29,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/dispatcher_policy.py"],
    }
    request = build_dispatch_request(
        task_id="opus-entitlement-receipt-present",
        lane="cx-green",
        platform="claude",
        mode="headless",
        profile="opus",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )

    decision = evaluate_dispatch_policy(request)

    assert request.capability is not None
    assert any(
        record.startswith("route-authority-receipt:opus_model_entitlement:")
        for record in request.capability.explicit_equivalence_records
    )
    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert decision.compatibility_mode == "none"
    assert "policy_launch" in decision.reason_codes
    decision_payload = route_decision_receipt_payload(decision)
    assert any(
        ref.startswith("route-authority-receipt:opus_model_entitlement:")
        for ref in decision_payload["dimensional_evidence_refs"]
    )


def test_quality_equivalence_receipt_does_not_widen_authority_ceiling(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    home_dir = tmp_path / "home"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "claude", "claude-cli 2.1.143")
    _fake_wrapper(home_dir, ".local/bin/hapax-claude-headless")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HOME": str(home_dir)},
        now=_current_iso_z(),
        platform="claude",
    )
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path, platform="claude")
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="sonnet-equivalence-test",
        route_id="claude.headless.sonnet",
        receipt_type="quality_equivalence",
        quality_floors=["frontier_required"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    task_fields = {
        "status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "SONNET-EQUIVALENCE-TEST",
        "priority": "p1",
        "wsjf": 29,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/dispatcher_policy.py"],
        "review_requirement": {
            "support_artifact_allowed": True,
            "independent_review_required": True,
            "authoritative_acceptor_profile": "frontier_full",
        },
    }
    request = build_dispatch_request(
        task_id="sonnet-equivalence-receipt-present",
        lane="cx-green",
        platform="claude",
        mode="headless",
        profile="sonnet",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )

    decision = evaluate_dispatch_policy(request)

    assert request.capability is not None
    assert "frontier_required" in request.capability.eligible_quality_floors
    assert request.capability.authority_ceiling == "frontier_review_required"
    assert any(
        record.startswith("route-authority-receipt:quality_equivalence:")
        for record in request.capability.explicit_equivalence_records
    )
    assert decision.action is DispatchAction.SUPPORT_ONLY
    assert decision.launch_allowed is False
    assert decision.quality_floor_satisfied is True
    assert decision.authority_allowed is False
    assert "authority_ceiling_not_satisfied" in decision.reason_codes


def test_route_authority_receipt_signature_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="bad-signature-test",
        route_id="claude.headless.opus",
        receipt_type="opus_model_entitlement",
        payload_hash="sha256:not-the-payload",
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)

    assert sources.registry is None
    assert sources.registry_error is not None
    assert "signed payload hash mismatch" in sources.registry_error


def _runtime_dispatch_request(sources, *, task_id: str):  # type: ignore[no-untyped-def]
    task_fields = {
        "status": "claimed",
        "assigned_to": "codex-main",
        "authority_case": "CASE-SDLC-REFORM-001",
        "authority_item": "MINIO-OLD-ROOT-CLEANUP",
        "priority": "p0",
        "wsjf": 35,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "runtime",
        "mutation_scope_refs": ["/var/lib/hapax/minio"],
    }
    return build_dispatch_request(
        task_id=task_id,
        lane="codex-main",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
        route_authority_receipts=sources.route_authority_receipts,
    )


def test_runtime_actuation_receipt_allows_task_bound_runtime_dispatch(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_success(bin_dir / "codex", tmp_path / "codex-used")
    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HAPAX_CODEX_EXEC_AUTH_HOST": "local"},
        now=_current_iso_z(),
    )
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="minio-cleanup-runtime-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
    )

    with patch.dict(os.environ, {"HAPAX_CODEX_EXEC_AUTH_HOST": "local"}):
        sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
        request = _runtime_dispatch_request(
            sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
        )
        decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert any(
        reason.startswith("route-authority-receipt:runtime_actuation:codex.headless.full:")
        for reason in decision.reason_codes
    )


def test_runtime_actuation_receipt_wrong_task_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HAPAX_CODEX_EXEC_AUTH_HOST": "local"},
        now=_current_iso_z(),
    )
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="wrong-task-runtime-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["some-other-task"],
        mutation_surfaces=["runtime"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_task_mismatch" in decision.reason_codes


def test_runtime_actuation_receipt_wrong_route_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HAPAX_CODEX_EXEC_AUTH_HOST": "local"},
        now=_current_iso_z(),
    )
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="wrong-route-runtime-test",
        route_id="claude.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_route_mismatch" in decision.reason_codes


def test_runtime_actuation_receipt_wrong_surface_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HAPAX_CODEX_EXEC_AUTH_HOST": "local"},
        now=_current_iso_z(),
    )
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="wrong-surface-runtime-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["source"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_surface_mismatch" in decision.reason_codes


def test_runtime_actuation_receipt_stale_fails_closed_as_absent(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now=_current_iso_z())
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="stale-runtime-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
        issued_at="2026-01-01T00:00:00Z",
        stale_after="1h",
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_receipt_absent" in decision.reason_codes


def test_runtime_actuation_receipt_stale_on_request_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now="2026-06-05T11:00:00Z")
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)

    payload: dict[str, object] = {
        "route_authority_receipt_schema": 1,
        "receipt_id": "manually-stale-runtime-test",
        "receipt_type": "runtime_actuation",
        "route_id": "codex.headless.full",
        "issued_at": "2026-06-05T10:00:00Z",
        "stale_after": "1h",
        "signed_by": "operator",
        "evidence_refs": ["test:manually-stale-runtime-test"],
        "quality_floors": [],
        "task_ids": ["appendix-podium-minio-old-root-cleanup-20260605"],
        "mutation_surfaces": ["runtime"],
    }
    payload["signed_payload_sha256"] = route_authority_receipt_payload_hash(payload)
    stale_receipt = RouteAuthorityReceipt.model_validate(payload)
    sources = load_dispatch_policy_sources(
        registry_path=REGISTRY,
        receipt_dir=tmp_path,
        now=datetime.fromisoformat("2026-06-05T11:00:00+00:00"),
    )
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    ).model_copy(update={"route_authority_receipts": (stale_receipt,)})

    decision = evaluate_dispatch_policy(
        request,
        now=datetime.fromisoformat("2026-06-05T11:01:00+00:00"),
    )

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_receipt_stale" in decision.reason_codes


def test_runtime_actuation_receipt_allows_dimensional_runtime_candidate(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_codex_exec_success(bin_dir / "codex", tmp_path / "codex-used")
    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HAPAX_CODEX_EXEC_AUTH_HOST": "local"},
        now=_current_iso_z(),
    )
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="minio-cleanup-runtime-dimensional-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
    )

    with patch.dict(os.environ, {"HAPAX_CODEX_EXEC_AUTH_HOST": "local"}):
        sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
        request = _runtime_dispatch_request(
            sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
        )
        decision = evaluate_dispatch_policy(request, candidate_requests=(request,))

    assert decision.action is DispatchAction.LAUNCH
    assert decision.dimensional_receipt is not None
    [candidate] = decision.dimensional_receipt.candidates
    assert not any(veto.code == "mutation_surface_mismatch" for veto in candidate.vetoes)


MINT_SCRIPT = REPO_ROOT / "scripts" / "hapax-mint-route-authority-receipt"


def _mint_route_authority_receipt(
    receipt_dir: Path,
    *,
    receipt_type: str,
    route_id: str,
    quality_floors: list[str] | None = None,
    now: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [
        sys.executable,
        str(MINT_SCRIPT),
        "--receipt-type",
        receipt_type,
        "--route-id",
        route_id,
        "--receipt-dir",
        str(receipt_dir),
        "--json",
    ]
    for floor in quality_floors or []:
        args += ["--quality-floor", floor]
    if now:
        args += ["--now", now]
    return subprocess.run(args, text=True, capture_output=True, check=False)


def _fresh_claude_platform_receipt(tmp_path: Path) -> None:
    """Write a fresh claude platform-capability receipt (clears quota/freshness)."""

    bin_dir = tmp_path / "bin"
    home_dir = tmp_path / "home"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "claude", "claude-cli 2.1.143")
    _fake_wrapper(home_dir, ".local/bin/hapax-claude-headless")
    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HOME": str(home_dir)},
        now=_current_iso_z(),
        platform="claude",
    )
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path, platform="claude")


def _opus_dispatch_request(sources):  # type: ignore[no-untyped-def]
    task_fields = {
        "status": "claimed",
        "assigned_to": "eta",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "OPUS-REACHABILITY",
        "priority": "p0",
        "wsjf": 38,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/dispatcher_policy.py"],
    }
    return build_dispatch_request(
        task_id="opus-reachability-minted",
        lane="eta",
        platform="claude",
        mode="headless",
        profile="opus",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )


def test_minted_opus_receipt_undegrades_route_to_launch_via_cli(tmp_path: Path) -> None:
    """The mint CLI produces a receipt that drives opus to LAUNCH end-to-end.

    Mirrors the live dispatch policy read-path (hapax-methodology-dispatch
    lines ~1229-1248): load_dispatch_policy_sources -> build_dispatch_request
    -> evaluate_dispatch_policy.
    """
    _fresh_claude_platform_receipt(tmp_path)

    mint = _mint_route_authority_receipt(
        tmp_path,
        receipt_type="opus_model_entitlement",
        route_id="claude.headless.opus",
        now=_current_iso_z(),
    )
    assert mint.returncode == 0, mint.stderr
    minted = json.loads(mint.stdout)
    assert Path(minted["receipt_path"]).exists()
    assert minted["receipt_path"].endswith(".json")
    assert minted["receipt_reference"].startswith(
        "route-authority-receipt:opus_model_entitlement:claude.headless.opus:"
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _opus_dispatch_request(sources)
    decision = evaluate_dispatch_policy(request)

    assert request.capability is not None
    assert any(
        record.startswith("route-authority-receipt:opus_model_entitlement:")
        for record in request.capability.explicit_equivalence_records
    )
    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert "policy_launch" in decision.reason_codes


def test_minted_opus_receipt_unreachable_without_receipt(tmp_path: Path) -> None:
    """Guard: without the minted receipt, the opus route stays HELD/REFUSED."""

    _fresh_claude_platform_receipt(tmp_path)

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _opus_dispatch_request(sources)
    decision = evaluate_dispatch_policy(request)

    assert decision.action is not DispatchAction.LAUNCH


def test_live_read_path_defaults_receipt_dir_to_env_for_opus(tmp_path: Path) -> None:
    """The live read-path (no explicit receipt_dir) picks up receipts via env.

    Proves the dispatch CLI call site — which passes no receipt_dir — un-degrades
    opus once HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR points at the minted dir.
    """
    _fresh_claude_platform_receipt(tmp_path)
    mint = _mint_route_authority_receipt(
        tmp_path,
        receipt_type="opus_model_entitlement",
        route_id="claude.headless.opus",
        now=_current_iso_z(),
    )
    assert mint.returncode == 0, mint.stderr

    with patch.dict(os.environ, {PLATFORM_CAPABILITY_RECEIPT_DIR_ENV: str(tmp_path)}):
        sources = load_dispatch_policy_sources(registry_path=REGISTRY)
    request = _opus_dispatch_request(sources)
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.LAUNCH
    assert "policy_launch" in decision.reason_codes
