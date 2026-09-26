"""Tests for scripts/check-billing-surface-diff.py — the provider_billing_sensitive
release class's deterministic arm-time evidence (RELEASE_MITIGATION_CHECKS,
shared/sdlc_lifecycle.py).

The scan reads a PR's unified diff and fails on any ADDED line that opens a
billing surface: a new credential env read, an API-key client route, a bare
provider SDK constructor or provider API endpoint literal, or a capacity_pool /
plan_type rebinding to the api_paid_spend (PAYG) class. Removed and context
lines, doc files, protective env strips, and lines carrying the visible
``billing-scan:allow`` marker (test fixtures, pattern definitions — each use is
review-visible) never fail the scan.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/check-billing-surface-diff.py"


@pytest.fixture(scope="module")
def scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_billing_surface_diff", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_billing_surface_diff"] = module
    spec.loader.exec_module(module)
    return module


def _diff(path: str, added: list[str], removed: list[str] | None = None) -> str:
    lines = [
        f"diff --git a/{path} b/{path}",
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -1,{len(removed or [])} +1,{len(added)} @@",
    ]
    lines.extend(f"-{line}" for line in removed or [])
    lines.extend(f"+{line}" for line in added)
    return "\n".join(lines) + "\n"


def test_clean_diff_reports_no_findings(scanner: ModuleType) -> None:
    diff = _diff(
        "shared/foo.py",
        ["def helper():", "    return 42"],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()


def test_api_key_route_added_fails(scanner: ModuleType) -> None:
    # The spec's must-fail case: a PR that adds an API-key route.
    line = '    client = OpenAI(base_url=base, api_key=read_key())'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings)
    finding = next(f for f in result.findings if f.kind == "api-key-route")
    assert finding.path == "shared/foo_client.py"
    assert finding.line == 1


def test_new_credential_env_read_fails(scanner: ModuleType) -> None:
    line = '    token = os.environ.get("MOONSHOT_TEST_API_KEY")'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "credential-env-read" for f in result.findings)


def test_credential_env_injection_assignment_fails(scanner: ModuleType) -> None:
    line = '    os.environ["TESTPROVIDER_API_KEY"] = value'  # billing-scan:allow: fixture data
    diff = _diff("scripts/foo-lane", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "credential-env-read" for f in result.findings)


def test_shell_credential_export_fails(scanner: ModuleType) -> None:
    line = "export ACME_API_KEY=$ACME_VALUE"  # billing-scan:allow: fixture data
    diff = _diff("scripts/foo-lane", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "credential-env-read" for f in result.findings)


def test_process_env_credential_read_fails(scanner: ModuleType) -> None:
    line = "  const key = process.env.ACME_API_KEY;"  # billing-scan:allow: fixture data
    diff = _diff("vscode/src/settings.ts", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "credential-env-read" for f in result.findings)


def test_protective_env_strip_passes(scanner: ModuleType) -> None:
    diff = _diff(
        "scripts/hapax-foo",
        [
            'os.environ.pop("OPENAI_API_KEY", None)',
            "unset OPENAI_API_KEY",
            'del os.environ["ANTHROPIC_API_KEY"]',
            'env.pop("CODEX_API_KEY", None)',
        ],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()


def test_capacity_pool_payg_json_assignment_fails(scanner: ModuleType) -> None:
    line = '      "capacity_pool": "api_paid_spend",'  # billing-scan:allow: fixture data
    diff = _diff("config/platform-capability-registry.json", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "capacity-pool-payg" for f in result.findings)


def test_capacity_pool_payg_enum_assignment_fails(scanner: ModuleType) -> None:
    line = "    capacity_pool=CapacityPool.API_PAID_SPEND,"  # billing-scan:allow: fixture data
    diff = _diff("shared/foo.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "capacity-pool-payg" for f in result.findings)


def test_capacity_pool_subscription_passes(scanner: ModuleType) -> None:
    line = '      "capacity_pool": "subscription_quota",'
    diff = _diff("config/platform-capability-registry.json", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()


def test_plan_type_api_binding_fails(scanner: ModuleType) -> None:
    line = '      "plan_type": "api",'  # billing-scan:allow: fixture data
    diff = _diff("config/quota-spend-ledger-fixtures.json", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "capacity-pool-payg" for f in result.findings)


def test_bare_provider_sdk_constructor_fails(scanner: ModuleType) -> None:
    # A zero-argument provider client reads its credential from the environment
    # implicitly — the bare/API invocation path.
    line = "    client = anthropic.Anthropic()"  # billing-scan:allow: fixture data
    diff = _diff("scripts/foo_judge.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "provider-api-endpoint" for f in result.findings)


def test_provider_api_host_literal_fails(scanner: ModuleType) -> None:
    line = 'API_BASE = "https://api.example-anthropic-mirror.invalid/v1"'
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()
    line = 'API_BASE = "https://api.tavily.com"'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "provider-api-endpoint" for f in result.findings)


def test_governed_litellm_proxy_client_passes(scanner: ModuleType) -> None:
    # The LiteLLM proxy is the estate's governed, quota-ledgered route; a client
    # construction bound to it is not a new billing surface.
    line = '    client = OpenAI(base_url="http://127.0.0.1:4000/v1", api_key=LITELLM_KEY)'
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()


def test_doc_files_are_not_scanned(scanner: ModuleType) -> None:
    line = '    client = OpenAI(api_key=read_key())'
    diff = _diff("docs/runbooks/foo.md", [line])
    assert scanner.scan_unified_diff(diff).findings == ()
    diff = _diff("notes.txt", [line])
    assert scanner.scan_unified_diff(diff).findings == ()


def test_removed_and_context_lines_are_ignored(scanner: ModuleType) -> None:
    diff = _diff(
        "shared/foo.py",
        ["    return 42"],
        removed=['    client = OpenAI(api_key=read_key())'],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()


def test_allow_marker_records_and_passes(scanner: ModuleType) -> None:
    line = 'payload = "+client = OpenAI(api_key=key)"  # billing-scan:allow (fixture data)'
    diff = _diff("tests/scripts/test_something.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()
    assert any(f.kind == "api-key-route" for f in result.allowed)


def test_empty_diff_passes(scanner: ModuleType) -> None:
    assert scanner.scan_unified_diff("").findings == ()


def test_main_clean_diff_exits_zero(scanner: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "clean.diff"
    path.write_text(_diff("shared/foo.py", ["x = 1"]), encoding="utf-8")
    assert scanner.main(["--diff-file", str(path)]) == 0


def test_main_flagged_diff_exits_one(scanner: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "flagged.diff"
    path.write_text(
        _diff("shared/foo.py", ['    client = OpenAI(api_key=read_key())  # billing-scan:allow']),  # billing-scan:allow: fixture data
        encoding="utf-8",
    )
    # The allow marker passes the scan...
    assert scanner.main(["--diff-file", str(path)]) == 0
    path.write_text(
        _diff("shared/foo.py", ['    client = OpenAI(api_key=read_key())']),  # billing-scan:allow: fixture data
        encoding="utf-8",
    )
    # ...and without it the same content fails.
    assert scanner.main(["--diff-file", str(path)]) == 1


def test_main_missing_diff_file_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    assert scanner.main(["--diff-file", str(tmp_path / "absent.diff")]) == 2


def test_main_without_input_mode_fails_closed(scanner: ModuleType) -> None:
    assert scanner.main([]) == 2
