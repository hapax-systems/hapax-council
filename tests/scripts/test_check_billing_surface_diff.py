"""Tests for scripts/check-billing-surface-diff.py — the provider_billing_sensitive
release class's deterministic arm-time evidence (RELEASE_MITIGATION_CHECKS,
shared/sdlc_lifecycle.py).

The scan reads a PR's unified diff and fails on any ADDED line that opens a
billing surface: a new credential env read, an API-key client route, a bare
provider SDK constructor or provider API endpoint literal, or a capacity_pool /
plan_type rebinding to the api_paid_spend (PAYG) class. Removed and context
lines, doc files, Python protective env strips (decided per ast node), and lines
carrying the visible ``billing-scan:allow`` marker on an allowlisted path (test
fixtures, pattern definitions — each use is review-visible) never fail the scan.
**Non-Python files are granted no exemption of any kind**, and every exemption
the scan grants is reported as ``allowed`` with its path, line and kind.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/check-billing-surface-diff.py"
#: The ONLY names the scanner's text path (non-Python files, unparseable Python) may
#: call. That path grants no exemptions of any kind, so a helper called there is a new
#: exemption site by construction: adding one means editing this list in the test — the
#: point being that it cannot land silently. Owned by the test, not the scanner, so a
#: change to the scanner cannot widen its own guard.
TEXT_PATH_ALLOWED_CALLS = frozenset(
    {
        "_text_classes",
        "emit_line",
        "_pattern_only_classes",
        "_KEY_BEARING_PROBE",
        "_marker_is_allowed_on",
        "search",
        "append",
        "Finding",
        "any",
        "strip",
        # Names the text-path loop legitimately reads/uses. None of them can suppress a
        # finding: `path`/`endswith` are the file-kind test the fail-closed probe needs,
        # and `findings` is only ever `.append`ed to (a finding, never an exemption).
        "path",
        "endswith",
        "findings",
    }
)
#: Every function in the scanner that decides a **boolean from text** — the only shape an
#: exemption can take if it is decided from line content. Each is a DETECTOR, not an
#: exemption: none of them is consulted to suppress a finding. A fourth entry is a fourth
#: exemption site by construction, so it must be declared here and justified.
TEXT_BOOL_PREDICATES = frozenset(
    {
        "_credential_name_matches",  # does this literal name a credential variable?
        "_is_doc_path",  # is this path a doc file (a SCOPE decision, not an exemption)?
        "_marker_is_allowed_on",  # is this PATH allowlisted (never line content)?
    }
)


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


def test_protective_env_strip_passes(scanner: ModuleType) -> None:
    """The governed launcher strip, in Python: exempt per node — and reported."""

    diff = _diff(
        "shared/foo_launcher.py",
        [
            'os.environ.pop("OPENAI_API_KEY", None)',
            'del os.environ["ANTHROPIC_API_KEY"]',
        ],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()
    assert {f.kind for f in result.allowed} == {"protective-strip"}, (
        "a granted structural exemption must be reported, with its kind"
    )


def test_launcher_strip_spellings_are_not_findings_even_without_an_exemption(
    scanner: ModuleType,
) -> None:
    """The spellings the estate's launchers use match no pattern, exempt or not.

    Measured over every line of ``scripts/hapax-codex``, ``-headless``, ``-send``,
    ``-mcp-config-scrub`` and ``install-codex-config.sh``: with text-path exemptions
    refused, **0** of their lines are flagged — ``unset``/``pop``/``update`` are
    neither reads nor injections. This is why refusing the text-path exemption is
    safe for the estate's own convention (it was measured, not assumed).
    """

    diff = _diff(
        "scripts/hapax-foo",
        [
            "unset OPENAI_API_KEY",
            'env.pop("CODEX_API_KEY", None)',
            'os.environ.pop("OPENAI_API_KEY", None)',
        ],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()
    assert result.allowed == (), "a non-Python file was granted an exemption"


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


def test_neighbouring_call_proxy_target_does_not_exempt(scanner: ModuleType) -> None:
    """codex-1's round-2 critical: the proxy target belongs to the OTHER call."""

    line = '    OpenAI(api_key=key); other(base_url="http://localhost")'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a proxy target in a neighbouring call exempted a direct API-key route"
    )


def test_dynamic_base_url_is_not_exempt(scanner: ModuleType) -> None:
    """A non-literal target is not a governed-proxy binding (seat's round-2 spec)."""

    line = '    client = OpenAI(api_key=k, base_url=os.environ["OPENAI_BASE_URL"])'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a dynamic base_url was read as a governed-proxy binding"
    )


def test_non_python_file_gets_no_proxy_exemption(scanner: ModuleType) -> None:
    """Seat's round-2 spec: outside Python there is no structural binding, so no exemption."""

    line = 'client = OpenAI(api_key=K, base_url="http://127.0.0.1:4000/v1")'  # billing-scan:allow: fixture data
    diff = _diff("scripts/foo_client.sh", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a non-Python file was granted a proxy exemption it cannot have"
    )


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
    assert {f.kind for f in result.allowed} == {"protective-strip"}, (
        "the strip's own node is the only thing exempt: the read elsewhere on the line "
        "must be a finding, and the granted exemption must name the strip alone"
    )


def test_mixed_line_strip_then_read_in_a_non_python_file(scanner: ModuleType) -> None:
    """The text-path analogue: and there, NOTHING is exempt — not even a strip."""

    line = (
        'unset OLD_API_KEY; key = os.environ["OPENAI_API_KEY"]'  # billing-scan:allow: fixture data
    )
    diff = _diff("scripts/foo_launcher.sh", [line])
    result = scanner.scan_unified_diff(diff)
    assert "credential-env-read" in [f.kind for f in result.findings], (
        "a strip statement exempted a read statement on the same line"
    )
    assert result.allowed == (), "a non-Python file was granted an exemption"


def test_non_python_file_grants_no_exemption_at_all(scanner: ModuleType) -> None:
    """Seat round 3, item 2: no exemptions for non-Python, per statement or per line.

    Red-first pin for the removal: at ``79c5d1cd7`` the statement-level strip exemption
    exempted exactly this line (a ``;``-delimited fragment of one line is still line
    content). It must now be a finding, and nothing may be recorded as allowed.
    """

    diff = _diff("scripts/foo_launcher.sh", ['del os.environ["ANTHROPIC_API_KEY"]'])
    result = scanner.scan_unified_diff(diff)
    assert "credential-env-read" in [f.kind for f in result.findings], (
        "a text-path exemption exempted a strip in a non-Python file"
    )
    assert result.allowed == (), "a non-Python file was granted an exemption"


def test_strip_default_argument_is_scanned(scanner: ModuleType) -> None:
    """codex-1's round-4 critical, verbatim, on the AST path.

    At `c34dd481b` the exemption covered every node inside the strip, so the added read
    in the default argument was never reported and the gate could pass.
    """

    line = 'os.environ.pop("OLD_API_KEY", os.environ["OPENAI_API_KEY"])'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_launcher.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert "credential-env-read" in [f.kind for f in result.findings], (
        "the strip's default argument was exempted with the strip: the added read passed"
    )
    assert {f.kind for f in result.allowed} == {"protective-strip"}, (
        "the granted exemption must name the strip alone, not the read inside it"
    )


def test_strip_default_argument_is_scanned_on_the_text_path(scanner: ModuleType) -> None:
    """The text-path equivalent. Already closed at `c34dd481b` (no text-path exemption
    exists), red against `79c5d1cd7`, which is the head dev21's round 4 reviewed —
    there the whole line matched the statement-strip regex, default argument included.
    """

    line = 'os.environ.pop("OLD_API_KEY", os.environ["OPENAI_API_KEY"])'  # billing-scan:allow: fixture data
    diff = _diff("scripts/foo_launcher.sh", [line])
    result = scanner.scan_unified_diff(diff)
    assert "credential-env-read" in [f.kind for f in result.findings], (
        "a strip-shaped line in a non-Python file exempted its own default argument"
    )
    assert result.allowed == (), "a non-Python file was granted an exemption"


def test_strip_default_argument_read_shapes_are_all_scanned(scanner: ModuleType) -> None:
    """Every spelling of a read in the default argument, not just the subscript form."""

    lines = [
        'os.environ.pop("OLD_API_KEY", os.environ.get("OPENAI_API_KEY"))',
        'os.environ.pop("OLD_API_KEY", os.getenv("OPENAI_API_KEY"))',
        'os.environ.pop("OLD_API_KEY", os.environ.setdefault("OPENAI_API_KEY", ""))',
        'del os.environ["ANTHROPIC_API_KEY" if os.environ["OPENAI_API_KEY"] else "X"]',
    ]
    for line in lines:
        diff = _diff("shared/foo_launcher.py", [line])  # billing-scan:allow: fixture data
        result = scanner.scan_unified_diff(diff)
        assert "credential-env-read" in [f.kind for f in result.findings], (
            f"a read in the strip's own arguments was exempted: {line!r}"
        )


def test_strip_without_a_read_in_its_arguments_stays_clean(scanner: ModuleType) -> None:
    """Positive control: the governed strip is still exempt, and still reported."""

    lines = [
        'os.environ.pop("OLD_API_KEY", None)',
        'os.environ.pop("ANTHROPIC_API_KEY")',
        'del os.environ["OPENAI_API_KEY"]',
    ]
    diff = _diff("shared/foo_launcher.py", lines)
    result = scanner.scan_unified_diff(diff)
    assert result.findings == (), "the target-only exemption stopped exempting the target"
    assert {f.kind for f in result.allowed} == {"protective-strip"}
    assert len(result.allowed) == len(lines), "each strip must be reported on its own line"


def test_mixed_line_proxy_class_does_not_hide_a_route(scanner: ModuleType) -> None:
    """The proxy class: a governed-proxy literal on the line must not exempt a route."""

    line = '    note = "http://localhost:4000"; client = OpenAI(api_key=key)'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert "api-key-route" in [f.kind for f in result.findings], (
        "a proxy literal elsewhere on the line exempted a direct API-key route"
    )
    assert result.allowed == (), "the neighbouring literal bought a structural exemption"


def test_mixed_line_allow_marker_class_does_not_hide_a_route(scanner: ModuleType) -> None:
    """The marker class: the marker plus a production route is two findings, not none."""

    line = "    client = OpenAI(api_key=key)  # billing-scan:allow (production)"  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    kinds = [f.kind for f in result.findings]
    assert "billing-scan-allow-outside-fixtures" in kinds, "the marker was not reported"
    assert "api-key-route" in kinds, "the marker exempted the route beside it"
    assert result.allowed == (), "a production path was granted an exemption"


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
    assert set(declared) == {
        "proxy",
        "protective_strip",
        "allow_marker",
        "text_path_non_python",
    }, "a new exemption site must be declared here and justified, not smuggled in"
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

    # The text path must grant NOTHING (seat round 3, item 2). This is the clause that
    # would have caught the statement-level strip exemption that survived this guard's
    # first version: find `flush`'s text branch — the one that classifies with
    # `_text_classes` — and assert it can suppress no finding, by any mechanism.
    # `flush` is nested inside `scan_unified_diff`, so it is found by walking, not from
    # the module-level function table.
    flush = next(
        (
            node
            for node in _ast.walk(tree)
            if isinstance(node, _ast.FunctionDef) and node.name == "flush"
        ),
        None,
    )
    assert flush is not None, "the region analyser must exist"
    text_branches = [
        node.orelse
        for node in _ast.walk(flush)
        if isinstance(node, _ast.If)
        and any(
            isinstance(sub, _ast.Call)
            and isinstance(sub.func, _ast.Name)
            and sub.func.id == "_text_classes"
            for statement in node.orelse
            for sub in _ast.walk(statement)
        )
    ]
    assert len(text_branches) == 1, (
        f"expected exactly one text-path branch in `flush`, found {len(text_branches)}"
    )
    branch = [sub for statement in text_branches[0] for sub in _ast.walk(statement)]
    assert not any(isinstance(n, _ast.Continue) for n in branch), (
        "the text path contains a `continue`: that is a suppression, and it grants none"
    )
    assert not any(isinstance(n, _ast.Name) and n.id == "allowed" for n in branch), (
        "the text path appends to `allowed`: a non-Python exemption has re-appeared"
    )
    called: set[str] = set()
    for node in branch:
        if not isinstance(node, _ast.Call):
            continue
        if isinstance(node.func, _ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, _ast.Attribute):
            called.add(node.func.attr)
            if isinstance(node.func.value, _ast.Name):
                called.add(node.func.value.id)
    unexpected = called - TEXT_PATH_ALLOWED_CALLS
    assert not unexpected, (
        f"the text path calls {sorted(unexpected)}; it may only call "
        f"{sorted(TEXT_PATH_ALLOWED_CALLS)}. A helper called here is a fourth exemption "
        "site: declare it in EXEMPTION_SITES and justify it, or do not call it."
    )

    # And no such helper may even EXIST undeclared, called or not: a `str -> bool`
    # predicate is the only shape a line-content exemption can take in this module.
    text_bool_predicates = {
        node.name
        for node in _ast.walk(tree)
        if isinstance(node, _ast.FunctionDef)
        and any(
            arg.arg != "self" and (arg.annotation is None or _ast.unparse(arg.annotation) == "str")
            for arg in node.args.args
        )
        and {arg.arg for arg in node.args.args}
        and node.returns is not None
        and _ast.unparse(node.returns) == "bool"  # exactly `-> bool`, not a tuple member
    }
    undeclared = text_bool_predicates - TEXT_BOOL_PREDICATES
    assert not undeclared, (
        f"new text->bool predicate(s) in the scanner: {sorted(undeclared)}. That is the "
        "shape an exemption decided from line content takes: declare it in "
        "TEXT_BOOL_PREDICATES with its justification, or do not add it."
    )
