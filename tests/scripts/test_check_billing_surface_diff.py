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


def test_a_garbage_line_makes_the_section_unusable(scanner: ModuleType) -> None:
    """Clause 1 of the re-land predicate: an unparseable line is damage, never content.

    Measured before making this strict: a 72 KB real `gh pr diff` carries no blank body lines,
    so real output never contains a line outside the section grammar unless it was cut.
    """

    head = "diff --git a/shared/foo.py b/shared/foo.py\nold mode 100644\nnew mode 100755\n"
    # A section that is otherwise COMPLETE (a mode-only change is a whole diff), so the only
    # thing that can make it unusable is the stray line itself — the previous shapes drew their
    # unusable finding from a spent hunk budget instead, which is why this one isolates the
    # grammar rather than the arithmetic.
    for label, garbage in (
        ("a bare line", "this is not diff syntax"),
        ("a header-looking stray", "no newline at end of file"),
    ):
        result = scanner.scan_unified_diff(head + garbage + "\n")
        assert "billing-scan-unusable-input" in [f.kind for f in result.findings], (
            f"{label} was tolerated as content: {[f.kind for f in result.findings]}"
        )
    assert scanner.scan_unified_diff(head).findings == (), (
        "the mode-only control section was flagged, so the test proves nothing about the stray line"
    )
    # A BLANK line is the one tolerated stray, and it is stated rather than left implicit: a
    # blank line cannot carry content in any section shape, so a patch file that ends with an
    # extra newline is not damage. Every non-empty stray fails closed.
    assert scanner.scan_unified_diff(head + "\n").findings == ()


def test_eof_no_newline_marker_is_metadata_not_content(scanner: ModuleType) -> None:
    """gemini-1's round-7 major: the `\\ No newline` marker must not join the post-image.

    Before the fix the marker fell through to the region, so a perfectly valid diff whose last
    added line is a governed strip failed to parse — and, being key-bearing, was reported as
    unusable input instead of exempt.
    """

    diff = (
        "diff --git a/shared/foo_launcher.py b/shared/foo_launcher.py\n"
        "index d95f3ad..94b334d 100644\n"
        "--- a/shared/foo_launcher.py\n"
        "+++ b/shared/foo_launcher.py\n"
        "@@ -1,0 +1,1 @@\n"
        '+os.environ.pop("OLD_API_KEY", None)\n'
        "\\ No newline at end of file\n"
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == (), (
        "a valid EOF hunk whose last line is a governed strip was not read as valid: "
        f"{[(f.kind, f.text[:60]) for f in result.findings]}"
    )
    assert any(f.kind == "protective-strip" for f in result.allowed), (
        "the strip in the EOF hunk was not recognised at all"
    )


def test_combined_section_fuzz_never_reads_a_cut_section_as_whole(
    scanner: ModuleType, tmp_path: Path
) -> None:
    """The class-level test: real `git diff` output whose sections COMBINE marks.

    #4795's r5, r6 and r7 were the same class one level deeper each time (index-only header; short
    hunk; short hunk plus a rename or mode pair). The previous fuzz only ever exercised one shape
    per section, so it never combined them. Here each fixture is one REAL section that carries a
    content mark AND a contentless mark — rename+content, mode+content, empty-blob+content,
    binary, and a `\\ No newline` EOF hunk — and every strict prefix of every fixture is scanned
    and required to report something, except at the boundaries this test names in advance:

    * a prefix that stops right after a **mode pair** is a legitimate mode-only diff (git emits
      the pair and then, only if content changed, an `index` line — so that truncation window is
      one line wide and indistinguishable in the text; this is the one ambiguity the table has,
      and it is named here rather than left implicit);
    * everything else must report `billing-scan-unusable-input` (a cut section) or the planted
      credential read (a section that arrived whole). A rename is NOT such a boundary: git writes
      `similarity index 100%` for a pure rename and a lower percentage whenever content follows,
      which is what makes that prefix a truncation rather than a diff.
    """

    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        )
        return proc.stdout.strip()

    # Big enough that git's rename detection actually fires (measured: a five-line file is
    # reported as a delete+add even with -M, while a fifty-line file with one line appended is
    # `similarity index 98%` — a fixture that is not a rename cannot fuzz one).
    body = "".join(f"line{index} = {index}\n" for index in range(50))
    git("init", "-q", ".")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "renamed.py").write_text(body, encoding="utf-8")
    (repo / "moded.py").write_text(body, encoding="utf-8")
    (repo / "was_empty.py").write_text("", encoding="utf-8")
    (repo / "binary.bin").write_bytes(b"\x00\x01\x02\x03" * 64)
    (repo / "eof.py").write_text(body, encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")

    git("mv", "renamed.py", "renamed_after.py")
    (repo / "renamed_after.py").write_text(
        f'{body}key = os.environ["OPENAI_API_KEY"]\n', encoding="utf-8"
    )
    (repo / "moded.py").write_text(f'{body}key = os.environ["OPENAI_API_KEY"]\n', encoding="utf-8")
    (repo / "moded.py").chmod(0o755)
    (repo / "was_empty.py").write_text('key = os.environ["OPENAI_API_KEY"]\n', encoding="utf-8")
    (repo / "binary.bin").write_bytes(b"\x00\x09\x08\x07" * 64)
    (repo / "eof.py").write_text(
        'a = 1\nb = 2\nkey = os.environ["OPENAI_API_KEY"]', encoding="utf-8"
    )
    git("add", "-A")
    git("commit", "-qm", "combined")

    def section(path: str) -> str:
        return git("diff", "--find-renames", "--unified=0", "HEAD~1..HEAD", "--", path)

    fixtures = {
        # Both sides of the rename must be inside the pathspec, or git shows the new name as an
        # addition instead of a rename.
        "rename+content": git(
            "diff",
            "--find-renames",
            "--unified=0",
            "HEAD~1..HEAD",
            "--",
            "renamed.py",
            "renamed_after.py",
        ),
        "mode+content": section("moded.py"),
        "empty-blob+content": section("was_empty.py"),
        "binary": section("binary.bin"),
        "eof-no-newline": section("eof.py"),
    }
    assert "rename from" in fixtures["rename+content"] and "@@" in fixtures["rename+content"]
    assert "old mode" in fixtures["mode+content"] and "@@" in fixtures["mode+content"]
    assert "e69de29" in fixtures["empty-blob+content"] and "@@" in fixtures["empty-blob+content"]
    assert "Binary files" in fixtures["binary"]
    assert "\\ No newline at end of file" in fixtures["eof-no-newline"]

    for label, diff in fixtures.items():
        # The whole fixture must be readable: the corpus of combined sections is not all damage.
        whole = scanner.scan_unified_diff(diff)
        assert not any(f.kind == "billing-scan-unusable-input" for f in whole.findings), (
            f"a complete combined section ({label}) was read as damaged: "
            f"{[(f.kind, f.text[:60]) for f in whole.findings]}"
        )
        lines = diff.splitlines(True)
        clean_allowed = 0
        for boundary in range(1, len(lines)):
            prefix = "".join(lines[:boundary])
            result = scanner.scan_unified_diff(prefix)
            if result.findings:
                continue
            # No findings: only the one named ambiguity may be clean, and only where the prefix
            # is exactly a mode pair with nothing after it.
            last = prefix.splitlines()[-1]
            assert label == "mode+content" and last.startswith("new mode"), (
                f"{label}: a strict prefix scanned clean at line {boundary} "
                f"(last line {last!r}) — a cut section read as whole"
            )
            clean_allowed += 1
        if label == "mode+content":
            assert clean_allowed == 1, (
                f"expected exactly the one mode-pair boundary to be clean, got {clean_allowed}"
            )
        else:
            assert clean_allowed == 0


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
