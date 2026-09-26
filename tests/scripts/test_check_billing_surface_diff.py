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
    line = (
        "    client = OpenAI(base_url=base, api_key=read_key())"  # billing-scan:allow: fixture data
    )
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
    line = "    client = OpenAI(api_key=read_key())"
    diff = _diff("docs/runbooks/foo.md", [line])
    assert scanner.scan_unified_diff(diff).findings == ()
    diff = _diff("notes.txt", [line])
    assert scanner.scan_unified_diff(diff).findings == ()


def test_removed_and_context_lines_are_ignored(scanner: ModuleType) -> None:
    diff = _diff(
        "shared/foo.py",
        ["    return 42"],
        removed=["    client = OpenAI(api_key=read_key())"],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()


def test_allow_marker_records_and_passes(scanner: ModuleType) -> None:
    # The marker exempts a REAL call: under the structural (round-2) path a string
    # literal that merely mentions ``api_key=`` is not a route at all, so the marker
    # must be pinned on a line that would otherwise be a finding.
    line = "client = OpenAI(api_key=key)  # billing-scan:allow (fixture data)"
    diff = _diff("tests/scripts/test_something.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()
    assert any(f.kind == "api-key-route" for f in result.allowed)


def test_empty_diff_passes(scanner: ModuleType) -> None:
    assert scanner.scan_unified_diff("").findings == ()


# ── review round 1 (2026-09-26): codex critical + gemini major + docs ────────────


def test_proxy_hint_in_a_comment_does_not_exempt_a_direct_api_key_route(
    scanner: ModuleType,
) -> None:
    """A bare mention of the proxy anywhere on the line must not exempt it.

    The exemption is bound to the ROUTE TARGET (a base_url/api_base bound to a
    governed proxy host), never to a substring of the line: a comment, a variable
    name or a neighbouring literal cannot buy an exemption.
    """

    line = "    client = OpenAI(api_key=key)  # localhost"  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a proxy name in a comment exempted a direct API-key route"
    )


def test_proxy_name_only_in_a_neighbouring_literal_does_not_exempt(
    scanner: ModuleType,
) -> None:
    """The same class, second shape: the proxy name lives in another literal."""

    line = '    client = OpenAI(api_key=key); note = "litellm"'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a proxy name in a neighbouring literal exempted a direct API-key route"
    )


def test_route_bound_to_governed_proxy_is_still_exempt(scanner: ModuleType) -> None:
    """Positive control: the legitimate exemption must survive the fix."""

    line = '    client = OpenAI(api_key=LITELLM_KEY, base_url="http://127.0.0.1:4000/v1")'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == (), "a client genuinely bound to the proxy must stay exempt"


def test_bearer_token_in_a_python_fstring_fails(scanner: ModuleType) -> None:
    """gemini major: the f-string form of a Bearer header must be flagged."""

    line = '    headers = {"Authorization": f"Bearer {token}"}'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "the bearer-token regex did not cover a Python f-string"
    )


def test_bearer_token_fstring_attribute_form_fails(scanner: ModuleType) -> None:
    """The same class, second shape: an f-string built from an attribute."""

    line = "    self.headers['Authorization'] = f'Bearer {self._api_key}'"  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "the bearer-token regex did not cover the f-string attribute form"
    )


def test_main_clean_diff_exits_zero(scanner: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "clean.diff"
    path.write_text(_diff("shared/foo.py", ["x = 1"]), encoding="utf-8")
    assert scanner.main(["--diff-file", str(path)]) == 0


def test_main_flagged_diff_exits_one(scanner: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "flagged.diff"
    path.write_text(
        _diff(
            "shared/foo.py", ["    client = OpenAI(api_key=read_key())  # billing-scan:allow"]
        ),  # billing-scan:allow: fixture data
        encoding="utf-8",
    )
    # A marker on a NON-fixture path no longer passes the scan: this test used to pin the
    # self-exemption hole as desired behaviour (rounds 1–2 inherited it from the original
    # scanner). It now pins the closure of that hole: the marker is itself a finding.
    assert scanner.main(["--diff-file", str(path)]) == 1
    result = scanner.scan_unified_diff(path.read_text(encoding="utf-8"))
    assert [f.kind for f in result.findings] == [
        "billing-scan-allow-outside-fixtures",
        "api-key-route",
    ]
    path.write_text(
        _diff(
            "shared/foo.py", ["    client = OpenAI(api_key=read_key())"]
        ),  # billing-scan:allow: fixture data
        encoding="utf-8",
    )
    # Without the marker the same content fails on the route alone.
    assert scanner.main(["--diff-file", str(path)]) == 1


def test_main_missing_diff_file_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    assert scanner.main(["--diff-file", str(tmp_path / "absent.diff")]) == 2


def test_main_without_input_mode_fails_closed(scanner: ModuleType) -> None:
    assert scanner.main([]) == 2


def test_main_empty_diff_input_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    """codex major: empty input is not evidence. A gate must not report success on it."""

    path = tmp_path / "empty.diff"
    path.write_text("", encoding="utf-8")
    assert scanner.main(["--diff-file", str(path)]) == 2


def test_main_whitespace_only_diff_input_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "blank.diff"
    path.write_text("\n\n   \n", encoding="utf-8")
    assert scanner.main(["--diff-file", str(path)]) == 2


def test_main_malformed_diff_input_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    """Text that is not a unified diff at all is unusable input, not a clean scan."""

    path = tmp_path / "prose.diff"
    path.write_text("this is not a unified diff\nit has no file headers\n", encoding="utf-8")
    assert scanner.main(["--diff-file", str(path)]) == 2


def test_main_diff_with_no_file_headers_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    """A truncated diff (hunks with no ``diff --git``/``+++`` header) is unusable."""

    path = tmp_path / "truncated.diff"
    path.write_text(
        "@@ -1,1 +1,1 @@\n+client = OpenAI(api_key=key)\n", encoding="utf-8"
    )  # billing-scan:allow: fixture data
    assert scanner.main(["--diff-file", str(path)]) == 2


def test_scanner_docs_state_only_what_success_proves(scanner: ModuleType) -> None:
    """codex major: the docs must not overstate the scan's guarantee.

    Success proves that no ADDED line matched this scan's syntactic patterns. It
    does not prove the change cannot spend: semantic spend routing is the review
    quorum's layer. A docstring that claims the former is a false claim.
    """

    # Whitespace-normalised: the claim is what matters, not the line wrapping.
    doc = " ".join((scanner.__doc__ or "").split())
    assert "proves no ADDED line opens a billing surface" not in doc, (
        "the scanner docs still claim proof that a syntactic scan cannot give"
    )
    assert "not proof" in doc or "does not prove" in doc, (
        "the scanner docs must say what success does not prove"
    )


# ── review round 2 (2026-09-26): the exemption must be structural, not textual ──
#
# All three families found the same residual bypass: the exemption window spanned
# every call on the line, so a proxy target in a *neighbouring* call exempted a
# direct API-key route. The fix parses the Python post-image with `ast` and
# exempts a Call only when THAT Call carries both the credential and a literal
# governed-proxy target. These cases pin the structure.


def test_neighbouring_call_proxy_target_does_not_exempt(scanner: ModuleType) -> None:
    """codex-1's round-2 critical: the proxy target belongs to the OTHER call."""

    line = '    OpenAI(api_key=key); other(base_url="http://localhost")'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a proxy target in a neighbouring call exempted a direct API-key route"
    )


def test_earlier_statement_proxy_name_does_not_exempt(scanner: ModuleType) -> None:
    """gemini-1's round-2 critical: the proxy name is in an EARLIER statement."""

    line = (
        "    print(base_url='litellm'); c = OpenAI(api_key=k)"  # billing-scan:allow: fixture data
    )
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a proxy name in an earlier statement exempted a later API-key route"
    )


def test_chained_call_proxy_target_does_not_exempt(scanner: ModuleType) -> None:
    """A chained call is a different node: its target cannot bind the inner call."""

    line = '    OpenAI(api_key=k).configure(base_url="http://localhost")'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a proxy target on a chained call exempted the credential-bearing call"
    )


def test_dynamic_base_url_is_not_exempt(scanner: ModuleType) -> None:
    """A non-literal target is not a governed-proxy binding (seat's round-2 spec)."""

    line = '    client = OpenAI(api_key=k, base_url=os.environ["OPENAI_BASE_URL"])'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a dynamic base_url was read as a governed-proxy binding"
    )


def test_multiline_proxy_bound_call_is_exempt(scanner: ModuleType) -> None:
    """Positive control for structure: the SAME call spans lines and is proxy-bound."""

    diff = _diff(
        "shared/foo_client.py",
        [
            "    client = OpenAI(",  # billing-scan:allow: fixture data
            "        api_key=LITELLM_KEY,",  # billing-scan:allow: fixture data
            '        base_url="http://127.0.0.1:4000/v1",',  # billing-scan:allow: fixture data
            "    )",  # billing-scan:allow: fixture data
        ],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == (), "a multi-line call genuinely bound to the proxy must stay exempt"


def test_multiline_call_without_proxy_target_fails(scanner: ModuleType) -> None:
    """The same multi-line shape with no target at all is a direct route."""

    diff = _diff(
        "shared/foo_client.py",
        [
            "    client = OpenAI(",  # billing-scan:allow: fixture data
            "        api_key=key,",  # billing-scan:allow: fixture data
            "    )",  # billing-scan:allow: fixture data
        ],
    )
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a multi-line call with a credential and no proxy target was not flagged"
    )


def test_non_python_file_gets_no_proxy_exemption(scanner: ModuleType) -> None:
    """Seat's round-2 spec: outside Python there is no structural binding, so no exemption."""

    line = 'client = OpenAI(api_key=K, base_url="http://127.0.0.1:4000/v1")'  # billing-scan:allow: fixture data
    diff = _diff("scripts/foo_client.sh", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a non-Python file was granted a proxy exemption it cannot have"
    )


def test_file_header_without_a_hunk_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    """codex-1's other major: a header with no hunk means the content was never read."""

    path = tmp_path / "header-only.diff"
    path.write_text(
        "diff --git a/shared/foo.py b/shared/foo.py\n--- a/shared/foo.py\n+++ b/shared/foo.py\n",
        encoding="utf-8",
    )
    assert scanner.main(["--diff-file", str(path)]) == 1


def test_binary_file_section_is_not_unusable_input(scanner: ModuleType) -> None:
    """A binary section has no added text to scan, so it is not unusable input."""

    diff = (
        "diff --git a/assets/logo.png b/assets/logo.png\n"
        "index 1111111..2222222 100644\n"
        "Binary files a/assets/logo.png and b/assets/logo.png differ\n"
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()


def test_mid_diff_header_without_a_hunk_fails_closed(scanner: ModuleType) -> None:
    """The mid-diff arm of the no-hunk guard: a header-only file, then another file.

    The end-of-diff guard alone would miss this one, because the header-only section is
    followed by a second file's section. Pinned separately so each arm is load-bearing.
    """

    diff = (
        "diff --git a/shared/ghost.py b/shared/ghost.py\n"
        "--- a/shared/ghost.py\n"
        "+++ b/shared/ghost.py\n"
        "diff --git a/shared/real.py b/shared/real.py\n"
        "--- a/shared/real.py\n"
        "+++ b/shared/real.py\n"
        "@@ -1,1 +1,2 @@\n"
        " x = 1\n"
        "+y = 2\n"
    )
    result = scanner.scan_unified_diff(diff)
    kinds = [f.kind for f in result.findings]
    assert "billing-scan-unusable-input" in kinds, (
        "a header-only file mid-diff was read as a clean scan"
    )
    assert all(
        f.path == "shared/ghost.py"
        for f in result.findings
        if f.kind == "billing-scan-unusable-input"
    )


def test_pre_existing_call_in_context_lines_is_not_flagged(scanner: ModuleType) -> None:
    """Attribution: only an ADDED line inside the call makes it this change's surface."""

    diff = (
        "diff --git a/shared/foo_client.py b/shared/foo_client.py\n"
        "--- a/shared/foo_client.py\n"
        "+++ b/shared/foo_client.py\n"
        "@@ -1,3 +1,4 @@\n"
        " client = OpenAI(api_key=pre_existing_key)\n"
        ' LOGGER.info("unchanged")\n'
        "+x = 1\n"
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == (), "a pre-existing credential call in the context lines was flagged"


def test_key_bearing_unparseable_python_region_fails_closed(scanner: ModuleType) -> None:
    """codex-1's major: unparseable credential-bearing text must never read as clean.

    Two shapes, because the fail-closed path has two arms: an unparseable region whose
    line rules DO match (flagged as api-key-route), and one whose line rules cannot
    match because the value sits on the next line (flagged as unusable input).
    """

    line_rule = _diff(
        "shared/foo_client.py",
        [
            "    client = OpenAI(",  # billing-scan:allow: fixture data
            "        api_key=key",  # billing-scan:allow: fixture data
            "    # missing closing paren — this region cannot parse",  # billing-scan:allow: fixture data
        ],
    )
    result = scanner.scan_unified_diff(line_rule)
    assert result.findings, "unparseable credential-bearing text was read as a clean scan"
    assert any(f.kind == "api-key-route" for f in result.findings)

    probe_rule = _diff(
        "shared/foo_client.py",
        [
            "    client = OpenAI(",  # billing-scan:allow: fixture data
            "        api_key =",  # billing-scan:allow: fixture data
            "            load_key(),",  # billing-scan:allow: fixture data
            "    # still no closing paren — unparseable, and the line rule cannot match",  # billing-scan:allow: fixture data
        ],
    )
    result = scanner.scan_unified_diff(probe_rule)
    assert any(f.kind == "billing-scan-unusable-input" for f in result.findings), (
        "an unparseable region whose line rules cannot match was read as clean"
    )


# ── round 3 (dev21's recommendation, 2026-09-26T22:59:52Z): the marker is not a ──
# ── self-exemption hole. It is honoured only under an explicit path allowlist. ──


def test_allow_marker_on_a_production_path_fails(scanner: ModuleType, tmp_path: Path) -> None:
    """The hole itself: a marker on a production API-key route must not make the scan pass."""

    path = tmp_path / "prod.diff"
    path.write_text(
        _diff(
            "shared/foo_client.py",
            [
                "    client = OpenAI(api_key=key)  # billing-scan:allow: production, please ignore"
            ],  # billing-scan:allow: fixture data
        ),
        encoding="utf-8",
    )
    assert scanner.main(["--diff-file", str(path)]) == 1
    result = scanner.scan_unified_diff(path.read_text(encoding="utf-8"))
    kinds = [f.kind for f in result.findings]
    assert "billing-scan-allow-outside-fixtures" in kinds, (
        "a marker outside the allowlist did not become a finding"
    )
    assert "api-key-route" in kinds, "the marker still exempted the underlying production route"
    assert result.allowed == (), "a production path was still granted an exemption"


def test_allow_marker_on_a_production_path_fails_even_without_a_route(
    scanner: ModuleType,
) -> None:
    """The marker alone is the violation: intent to self-exempt is not a silent ignore."""

    diff = _diff("shared/foo_client.py", ["    value = compute()  # billing-scan:allow"])
    result = scanner.scan_unified_diff(diff)
    assert [f.kind for f in result.findings] == ["billing-scan-allow-outside-fixtures"]


def test_allow_marker_is_honoured_under_tests(scanner: ModuleType) -> None:
    """The allowlist case that already existed — and must keep working."""

    diff = _diff(
        "tests/scripts/test_something.py",
        ["client = OpenAI(api_key=key)  # billing-scan:allow (fixture data)"],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()
    assert any(f.kind == "api-key-route" for f in result.allowed)
    assert all(f.path.startswith("tests/") for f in result.allowed)


def test_allow_marker_is_honoured_in_the_scanner_itself(scanner: ModuleType) -> None:
    """The scanner's own pattern source is the other allowlisted path."""

    diff = _diff(
        "scripts/check-billing-surface-diff.py",
        [
            "client = OpenAI(api_key=key)  # billing-scan:allow: pattern definition"
        ],  # billing-scan:allow: fixture data
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()
    assert result.allowed, "the scanner's own pattern source must still carry the marker"


def test_allowed_lines_are_listed_with_their_paths(scanner: ModuleType, tmp_path: Path) -> None:
    """dev21's point 3: the report shows every exemption the gate accepted, with its path."""

    import contextlib
    import io

    path = tmp_path / "fixture.diff"
    path.write_text(
        _diff(
            "tests/scripts/test_x.py", ["client = OpenAI(api_key=key)  # billing-scan:allow"]
        ),  # billing-scan:allow: fixture data
        encoding="utf-8",
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert scanner.main(["--diff-file", str(path)]) == 0
    out = buf.getvalue()
    assert "tests/scripts/test_x.py" in out and "billing-scan:allow" in out, (
        "the scan summary did not list the exempted line with its path"
    )
    assert "exempt" in out.lower(), "the summary does not name the exemption"


# ── round 3: the exemption CLASS. No exemption may be decided from line content. ──


def test_mixed_line_protective_strip_does_not_hide_a_credential_read(
    scanner: ModuleType,
) -> None:
    """codex-1's round-3 critical, verbatim: the strip must not exempt its neighbours."""

    line = 'os.environ.pop("OLD_API_KEY", None); key = os.environ["OPENAI_API_KEY"]'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_launcher.py", [line])
    result = scanner.scan_unified_diff(diff)
    kinds = [f.kind for f in result.findings]
    assert "credential-env-read" in kinds, (
        "a protective strip on the line exempted a credential read on the same line"
    )
    assert result.allowed == (), "the strip's own node is the only thing exempt, per node"


def test_mixed_line_strip_then_read_in_a_non_python_file(scanner: ModuleType) -> None:
    """The text-path analogue: exemptions there are per STATEMENT, never per line."""

    line = (
        'unset OLD_API_KEY; key = os.environ["OPENAI_API_KEY"]'  # billing-scan:allow: fixture data
    )
    diff = _diff("scripts/foo_launcher.sh", [line])
    result = scanner.scan_unified_diff(diff)
    assert "credential-env-read" in [f.kind for f in result.findings], (
        "a strip statement exempted a read statement on the same line"
    )


def test_mixed_line_strip_only_still_passes(scanner: ModuleType) -> None:
    """Positive control: a line that is ONLY a strip stays clean."""

    line = 'os.environ.pop("OLD_API_KEY", None)'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_launcher.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()


def test_header_without_a_file_section_fails_closed(scanner: ModuleType) -> None:
    """codex-1's round-3 major: the fourth fail-open arm — a header with no section."""

    diff = "diff --git a/shared/ghost.py b/shared/ghost.py\n"
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "billing-scan-unusable-input" for f in result.findings), (
        "a diff header with no file section was read as a clean scan"
    )


def test_no_exemption_is_decided_from_line_content(scanner: ModuleType) -> None:
    """THE GUARD (seat's round-3 item 3): a fourth whole-line exemption cannot land.

    It inspects this scanner's own source: every declared exemption site must exist,
    the node-decided ones must take AST nodes rather than text, and none of them may
    read a line-text carrier. Adding a line-level exemption breaks this test.
    """

    import ast as _ast

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = _ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, _ast.FunctionDef)}
    declared = getattr(scanner, "EXEMPTION_SITES", None)
    assert declared, "the scanner must declare its exemption sites in EXEMPTION_SITES"
    assert set(declared) == {"proxy", "protective_strip", "allow_marker"}, (
        "a new exemption site must be declared here and justified, not smuggled in"
    )
    for name in scanner.NODE_EXEMPTION_FUNCTIONS:
        node = functions.get(name)
        assert node is not None, f"declared exemption site {name} has no implementation"
        params = [arg.arg for arg in node.args.args]
        anns = [(_ast.unparse(arg.annotation) if arg.annotation else "") for arg in node.args.args]
        assert all(a.startswith("ast.") for a in anns), (
            f"{name} must take AST nodes, not text: annotations were {anns}"
        )
        assert not (set(params) & set(scanner._LINE_TEXT_NAMES)), (
            f"{name} takes a line-text carrier ({set(params) & set(scanner._LINE_TEXT_NAMES)})"
        )
        used = {
            n.id
            for n in _ast.walk(node)
            if isinstance(n, _ast.Name) and n.id in scanner._LINE_TEXT_NAMES
        }
        assert not used, f"{name} reads line text ({used}) — a whole-line exemption again"
    marker_fn = functions.get("_marker_is_allowed_on")
    assert marker_fn is not None, "the marker exemption must exist and be path-based"
    marker_params = [a.arg for a in marker_fn.args.args]
    assert "path" in marker_params, "the marker exemption must be decided from the PATH"
    assert not (set(marker_params) & set(scanner._LINE_TEXT_NAMES)), (
        "the marker exemption must not be decided from line content"
    )


def test_git_base_head_path_runs_as_the_production_entry_point(scanner: ModuleType) -> None:
    """claude minor (round 3): `--base/--head` is the production entry point, so pin it.

    The CI job and the autoqueue both invoke the scanner this way; only
    `--diff-file` was covered. Skipped (with a declared precondition) where the
    checkout has no parent commit to diff against.
    """

    import subprocess

    repo = Path(__file__).resolve().parents[2]

    def rev(expr: str) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", expr], capture_output=True, text=True
        )
        return proc.stdout.strip() if proc.returncode == 0 else None

    base = rev("HEAD~1")
    if base is None:
        pytest.skip("no parent commit available to diff against (shallow checkout)")
    head = rev("HEAD")
    assert head is not None
    code = scanner.main(["--base", base, "--head", head])
    assert code in (0, 1), (
        f"the production --base/--head path must scan a real diff, not fail closed: exit was {code}"
    )
