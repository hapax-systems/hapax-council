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


def test_route_bound_to_governed_proxy_is_still_exempt(scanner: ModuleType) -> None:
    """Positive control: the legitimate exemption must survive the fix."""

    line = '    client = OpenAI(api_key=LITELLM_KEY, base_url="http://127.0.0.1:4000/v1")'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == (), "a client genuinely bound to the proxy must stay exempt"


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


def test_truncation_inside_a_hunk_fails_closed(scanner: ModuleType) -> None:
    """codex-1's round-6 critical: a hunk header alone must not prove a section whole.

    The header declares how many lines each side owes; input cut off right after ``@@`` or
    mid-hunk used to scan clean because only the header's presence was checked.
    """

    head = (
        "diff --git a/shared/foo.py b/shared/foo.py\n"
        "index d95f3ad..94b334d 100644\n"
        "--- a/shared/foo.py\n"
        "+++ b/shared/foo.py\n"
    )
    hunk = "@@ -1,2 +1,3 @@\n"
    body = " ctx\n-old\n+one\n+two\n"
    shapes = {
        "right after @@": head + hunk,
        "mid-hunk (one line in)": head + hunk + " ctx\n",
        "short of the old count": head + hunk + " ctx\n+one\n+two\n",
        "short of the new count": head + hunk + " ctx\n-old\n+one\n",
        "a body line after both counts were spent": head + hunk + body + "+three\n",
        "a short hunk closed by the next file's header": (
            head + hunk + " ctx\n" + "diff --git a/b.py b/b.py\n"
        ),
    }
    for label, diff in shapes.items():
        result = scanner.scan_unified_diff(diff)
        assert "billing-scan-unusable-input" in [f.kind for f in result.findings], (
            f"a hunk that did not deliver its header's counts scanned clean: {label}"
        )
    whole = scanner.scan_unified_diff(head + hunk + body)
    assert whole.findings == (), "a hunk that delivered its counts exactly was flagged"
    # Attribution, not just the fact of the finding: a short hunk must be blamed on the file
    # it was cut in. Without the close at the next file's header the state stays open, the
    # NEXT section inherits it, and the finding names the wrong file (measured: that mutant is
    # otherwise equivalent, so this assertion is what pins the boundary).
    misattributed = scanner.scan_unified_diff(head + hunk + " ctx\n" + "diff --git a/b.py b/b.py\n")
    blamed = [f.path for f in misattributed.findings if f.kind == "billing-scan-unusable-input"]
    assert "shared/foo.py" in blamed, (
        f"a short hunk closed by the next file's header was blamed on {blamed} instead"
    )


def test_empty_file_index_forms_all_read_as_contentless(scanner: ModuleType) -> None:
    """gemini-1's round-6 major: the zero side is any run of zeros, not exactly seven.

    This repo's ``gh pr diff`` abbreviates to ten characters
    (``index 0000000000..fe91c83f72``), so a fixed ``"0000000"`` made every ten-character
    empty-file section read as unusable input — a false positive on ordinary diffs.

    Every hash here is *derived* from git at runtime rather than written as a literal: a
    40-character hex literal is a "Hex High Entropy String" to the pre-push secret scan, and a
    git blob hash is not a credential. Deriving it keeps the test honest — it uses the real
    empty blob git actually produces — and needs no allowlist pragma.
    """

    import subprocess

    empty_blob = subprocess.run(
        ["git", "hash-object", "-t", "blob", "/dev/null"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert len(empty_blob) == 40, f"unexpected empty-blob hash form: {empty_blob!r}"
    forms = {
        "7-char": "0" * 7,
        "10-char": "0" * 10,
        "40-char": "0" * len(empty_blob),
    }
    for label, zero in forms.items():
        short = empty_blob[: len(zero)]
        added = (
            "diff --git a/shared/empty.py b/shared/empty.py\n"
            "new file mode 100644\n"
            f"index {zero}..{short}\n"
        )
        result = scanner.scan_unified_diff(added)
        assert result.findings == (), f"an empty-file {label} index was flagged: {result.findings}"
        removed = (
            "diff --git a/shared/gone.py b/shared/gone.py\n"
            "deleted file mode 100644\n"
            f"index {short}..{zero}\n"
        )
        assert scanner.scan_unified_diff(removed).findings == (), (
            f"a deleted-empty-file {label} index was flagged"
        )
    # And a NON-empty index must still be held: it promises content that never arrived.
    truncated = (
        "diff --git a/shared/foo.py b/shared/foo.py\n"
        "new file mode 100644\n"
        "index 0000000000..fe91c83f72\n"
    )
    kinds = [f.kind for f in scanner.scan_unified_diff(truncated).findings]
    assert "billing-scan-unusable-input" in kinds, (
        "a non-empty index with no content was read as a clean scan"
    )


def test_truncation_at_every_line_boundary_of_a_real_diff_fails_closed(
    scanner: ModuleType, tmp_path: Path
) -> None:
    """The class-level test the seat asked for: fuzz every line boundary of a REAL diff.

    A real ``git diff --find-renames --unified=0`` over a mode-only change, a pure rename, an
    empty new file and a content file whose added line is a credential read is generated here,
    then every prefix at a line boundary is scanned. The invariant: **no prefix may report a
    clean scan** — it either still contains the canary read, or the section it cut short is
    flagged incomplete. The per-shape tests above are this test's instances; this is the one
    that ends the class rather than the instance.
    """

    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    git("init", "-q", ".")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "aaa_canary.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "modeonly.py").write_text("y = 1\n", encoding="utf-8")
    (repo / "oldname.py").write_text("z = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    (repo / "aaa_canary.py").write_text(
        'x = 1\nkey = os.environ["OPENAI_API_KEY"]\n', encoding="utf-8"
    )
    (repo / "modeonly.py").chmod(0o755)
    git("mv", "oldname.py", "newname.py")
    (repo / "empty_new.py").write_text("", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "change")
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--find-renames", "--unified=0", "HEAD~1..HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    # The fixture must be a diff this scanner reads WHOLE, or the fuzz would pass vacuously:
    # exactly one finding, and it is the canary read.
    whole = scanner.scan_unified_diff(diff)
    assert [f.kind for f in whole.findings] == ["credential-env-read"], (
        "the real-diff fixture is not a clean baseline: "
        f"{[(f.kind, f.path) for f in whole.findings]}"
    )

    lines = diff.splitlines(True)
    assert len(lines) > 15, f"fixture too small to fuzz meaningfully: {len(lines)} lines"
    for boundary in range(1, len(lines)):
        prefix = "".join(lines[:boundary])
        result = scanner.scan_unified_diff(prefix)
        assert result.findings, (
            "a prefix of a real diff reported a clean scan at line "
            f"{boundary} (last line: {prefix.splitlines()[-1]!r})"
        )


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
