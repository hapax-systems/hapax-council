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
    """gemini's r7 major: the marker must not join the post-image region.

    A governed strip whose hunk ends at an unterminated last line must stay exempt, not fail to
    parse.
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
    """The class test: real `git diff` sections that COMBINE a content mark with a contentless one.

    rename+content, mode+content, empty-blob+content, binary and an EOF `\ No newline` hunk, each
    scanned at every line boundary, every character, and with each header deleted in turn. One
    clean prefix is allowed and named: a prefix ending exactly after a mode pair, which IS a
    legitimate mode-only diff (git omits the `index` line when no content follows).
    """

    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        )
        return proc.stdout.strip()

    def git_raw(*args: str) -> str:
        """Like `git`, but WITHOUT stripping: a real diff ends with a newline, and the scanner
        now treats an unterminated last line as a cut one (the character-level fuzz found that
        case). A stripped fixture is not a diff git would ever produce."""

        proc = subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        )
        return proc.stdout

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
        return git_raw("diff", "--find-renames", "--unified=0", "HEAD~1..HEAD", "--", path)

    fixtures = {
        # Both sides of the rename must be inside the pathspec, or git shows the new name as an
        # addition instead of a rename.
        "rename+content": git_raw(
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

        # ── round 2 (codex's major): the predicate claims EVERY prefix, so widen past line
        # ── boundaries. Character-level prefixes cut inside lines, inside headers and inside
        # ── marks; the positive grammar must call each of those damage.
        clean_char = 0
        for width in range(1, len(diff)):
            prefix = diff[:width]
            result = scanner.scan_unified_diff(prefix)
            if result.findings:
                continue
            last = prefix.splitlines()[-1] if prefix.splitlines() else ""
            assert label == "mode+content" and last.startswith("new mode"), (
                f"{label}: a character-level prefix scanned clean at width {width} "
                f"(last line {last!r})"
            )
            clean_char += 1
        assert clean_char <= 1, (
            f"{label}: {clean_char} character-level prefixes scanned clean; at most the one "
            "named mode-pair boundary may"
        )

        # And header DELETION: drop each structural line in turn. Whatever survives, the scan
        # must never come back clean — either the cut structure fails closed, or the canary read
        # in the surviving content is still reported.
        if label == "binary":
            # A binary section carries no content at all, so deleting its `index` line cannot
            # hide a line: the note is the whole story and the section stays legitimately whole.
            # Asserted rather than skipped silently.
            without_index = "".join(line for line in lines if not line.startswith("index "))
            assert scanner.scan_unified_diff(without_index).findings == (), (
                "a binary section without its index line should still read as whole"
            )
            continue
        for index, line in enumerate(lines):
            if not line.startswith(
                ("diff --git", "--- ", "+++ ", "index ", "old mode", "new mode")
            ):
                continue
            without = "".join(lines[:index] + lines[index + 1 :])
            result = scanner.scan_unified_diff(without)
            assert result.findings, (
                f"{label}: deleting the {line.split()[0]!r} line at {index} left a clean scan"
            )


# ── round 2 (dev21's reproduced fail-opens): a POSITIVE grammar — every line must be ──
# ── legal for the parser's current state, and illegal lines fail closed. ──


def test_a_hunk_before_any_path_fails_closed(scanner: ModuleType) -> None:
    """dev21's first reproduction, verbatim: a hunk straight after `diff --git`.

    With no `---`/`+++` the path stayed `None`, the added lines never entered a region, and the
    scan printed `OK … 0 changed file(s)` over an `OPENAI_API_KEY` read.
    """

    diff = 'diff --git a/x.py b/x.py\n@@ -0,0 +1,1 @@\n+key = os.environ["OPENAI_API_KEY"]\n'
    result = scanner.scan_unified_diff(diff)
    assert [f.kind for f in result.findings] == ["billing-scan-unusable-input"], (
        f"a hunk before any path did not fail closed: {[(f.kind, f.path) for f in result.findings]}"
    )


def test_content_before_any_file_header_fails_closed(scanner: ModuleType) -> None:
    """dev21's second reproduction: no section owns a line before the first header."""

    for label, diff in (
        (
            "a bare +++ and a read",
            '+++ b/x.py\n+key = os.environ["OPENAI_API_KEY"]\n',
        ),
        (
            "junk before a valid section",
            "this is not a diff\n"
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+x = 1\n",
        ),
        ("a lone read line", '+key = os.environ["OPENAI_API_KEY"]\n'),
    ):
        result = scanner.scan_unified_diff(diff)
        assert "billing-scan-unusable-input" in [f.kind for f in result.findings], (
            f"{label} did not fail closed: {[(f.kind, f.path) for f in result.findings]}"
        )


def test_the_governed_proxy_exemption_applies_and_does_not(scanner: ModuleType) -> None:
    """claude's r2 major: both halves of the proxy exemption, because only the pair means anything.

    Bound to a governed proxy → exempt and reported in `allowed`; unbound, neighbour-named,
    dynamic or non-governed → a finding.
    """

    exempt = (
        "diff --git a/shared/foo_client.py b/shared/foo_client.py\n"
        "--- a/shared/foo_client.py\n"
        "+++ b/shared/foo_client.py\n"
        "@@ -0,0 +1,1 @@\n"
        '+client = OpenAI(api_key=key, base_url="http://127.0.0.1:4000/v1")\n'
    )
    result = scanner.scan_unified_diff(exempt)
    assert result.findings == (), f"the proxy-bound route was flagged: {result.findings}"
    assert any(f.kind == "governed-proxy-route" for f in result.allowed), (
        "the exemption was granted but not reported in allowed"
    )

    for label, line in (
        ("no target at all", "    client = OpenAI(api_key=key)"),
        (
            "the proxy in a neighbour literal",
            '    client = OpenAI(api_key=key); note = "localhost"',
        ),
        ("a dynamic target", "    client = OpenAI(api_key=key, base_url=PROXY_URL)"),
        (
            "a non-governed host",
            '    client = OpenAI(api_key=key, base_url="https://api.openai.com/v1")',
        ),
    ):
        diff = (
            "diff --git a/shared/foo_client.py b/shared/foo_client.py\n"
            "--- a/shared/foo_client.py\n"
            "+++ b/shared/foo_client.py\n"
            "@@ -0,0 +1,1 @@\n"
            f"+{line}\n"
        )
        result = scanner.scan_unified_diff(diff)
        assert "api-key-route" in [f.kind for f in result.findings], (
            f"the proxy exemption applied where it must not ({label})"
        )


def test_a_marker_on_an_unparseable_key_bearing_line_is_reported_as_allowed(
    scanner: ModuleType,
) -> None:
    """gemini's round-2 minor: the marker decision must be the ONE decision.

    The key-bearing unparseable arm appended to `findings` directly, so an exemption that the
    rest of the scanner would have reported in `allowed` was silently a failure here.
    """

    diff = (
        "diff --git a/tests/scripts/test_x.py b/tests/scripts/test_x.py\n"
        "--- a/tests/scripts/test_x.py\n"
        "+++ b/tests/scripts/test_x.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+key = os.environ[  # billing-scan:allow fixture\n"
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == (), (
        f"an allowlisted marker did not exempt the unparseable finding: {result.findings}"
    )
    assert any(f.kind == "billing-scan-unusable-input" for f in result.allowed), (
        "the exemption was not reported in allowed (it was swallowed)"
    )


# ── the round-2 packet: the detector classes, the marker, and the exit codes ──
# ── moved in from #4805 so this PR's evidence is self-contained (seat's ruling). ──


def test_provider_api_host_literal_fails(scanner: ModuleType) -> None:
    line = 'API_BASE = "https://api.example-anthropic-mirror.invalid/v1"'
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert result.findings == ()
    line = 'API_BASE = "https://api.tavily.com"'  # billing-scan:allow: fixture data
    diff = _diff("shared/foo_client.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "provider-api-endpoint" for f in result.findings)


def test_bare_provider_sdk_constructor_fails(scanner: ModuleType) -> None:
    # A zero-argument provider client reads its credential from the environment
    # implicitly — the bare/API invocation path.
    line = "    client = anthropic.Anthropic()"  # billing-scan:allow: fixture data
    diff = _diff("scripts/foo_judge.py", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "provider-api-endpoint" for f in result.findings)


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


def test_plan_type_api_binding_fails(scanner: ModuleType) -> None:
    line = '      "plan_type": "api",'  # billing-scan:allow: fixture data
    diff = _diff("config/quota-spend-ledger-fixtures.json", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "capacity-pool-payg" for f in result.findings)


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


def test_non_python_file_gets_no_proxy_exemption(scanner: ModuleType) -> None:
    """Seat's round-2 spec: outside Python there is no structural binding, so no exemption."""

    line = 'client = OpenAI(api_key=K, base_url="http://127.0.0.1:4000/v1")'  # billing-scan:allow: fixture data
    diff = _diff("scripts/foo_client.sh", [line])
    result = scanner.scan_unified_diff(diff)
    assert any(f.kind == "api-key-route" for f in result.findings), (
        "a non-Python file was granted a proxy exemption it cannot have"
    )


def test_non_python_file_grants_no_exemption_at_all(scanner: ModuleType) -> None:
    """The text path grants no structural exemption to a non-Python file (r3 class fix)."""

    diff = _diff("scripts/foo_launcher.sh", ['del os.environ["ANTHROPIC_API_KEY"]'])
    result = scanner.scan_unified_diff(diff)
    assert "credential-env-read" in [f.kind for f in result.findings], (
        "a text-path exemption exempted a strip in a non-Python file"
    )
    assert result.allowed == (), "a non-Python file was granted an exemption"


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


def test_marker_allowlist_does_not_admit_a_prefixed_path(scanner: ModuleType) -> None:
    """codex-1's round-5 major: a FILE entry must match exactly, not by prefix."""

    diff = _diff(
        "scripts/check-billing-surface-diff.py_helper.py",
        ["client = OpenAI(api_key=key)  # billing-scan:allow"],  # billing-scan:allow: fixture data
    )
    result = scanner.scan_unified_diff(diff)
    kinds = [f.kind for f in result.findings]
    assert "billing-scan-allow-outside-fixtures" in kinds, (
        "a path that merely begins with an allowlisted file's name bought the exemption"
    )
    assert "api-key-route" in kinds, "the route beside the marker was exempted"
    assert result.allowed == (), "a prefixed path was granted an exemption"


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


def test_main_without_input_mode_fails_closed(scanner: ModuleType) -> None:
    assert scanner.main([]) == 2


def test_main_empty_diff_input_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    """codex major: empty input is not evidence. A gate must not report success on it."""

    path = tmp_path / "empty.diff"
    path.write_text("", encoding="utf-8")
    assert scanner.main(["--diff-file", str(path)]) == 2


def test_main_malformed_diff_input_fails_closed(scanner: ModuleType, tmp_path: Path) -> None:
    """Text that is not a unified diff at all is unusable input, not a clean scan."""

    path = tmp_path / "prose.diff"
    path.write_text("this is not a unified diff\nit has no file headers\n", encoding="utf-8")
    assert scanner.main(["--diff-file", str(path)]) == 2


# ── round 3 (codex's critical, reproduced by dev21): the marker's contract is exactly ──
# ── the marked line — a finding may never be exempted by another line's marker. ──


def _hunk(path: str, body: list[str]) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(body)} @@\n" + "".join(f"+{line}\n" for line in body)
    )


def test_a_marker_on_one_line_does_not_exempt_another_lines_finding(
    scanner: ModuleType,
) -> None:
    """dev21's r2 reproduction: marker on line 1, key on line 2, exit 0.

    The unusable finding was attributed to `added[0]`, so the marked line moved it to `allowed`
    and the unmarked key-bearing line was never judged. The marker's contract is exactly the
    marked line.
    """

    diff = _hunk(
        "tests/test_probe.py",
        ["# billing-scan:allow", "client = OpenAI(api_key"],
    )
    result = scanner.scan_unified_diff(diff)
    assert [f.line for f in result.findings] == [2], (
        f"the unmarked line was not the finding: {[(f.line, f.kind) for f in result.findings]}"
    )
    # And the marked line exempts NOTHING here, because it carries no finding of its own: an
    # exemption speaks for the line it is on, so a marked line with no finding has nothing to
    # exempt. Asserted rather than left implicit — it is the other half of "the contract is
    # exactly the marked line".
    assert result.allowed == (), f"the marked line exempted something: {result.allowed}"


def test_a_marker_on_the_second_line_does_not_exempt_the_first(scanner: ModuleType) -> None:
    """The mirror: the key on line 1, the marker on line 2. An exemption speaks for one line."""

    diff = _hunk(
        "tests/test_probe.py",
        ["client = OpenAI(api_key", "# billing-scan:allow"],
    )
    result = scanner.scan_unified_diff(diff)
    assert [f.line for f in result.findings] == [1], (
        f"the marked line exempted the line above it: {[(f.line, f.kind) for f in result.findings]}"
    )


def test_both_lines_marked_is_allowed(scanner: ModuleType) -> None:
    """The positive control: when every line the finding names carries the marker, it is allowed."""

    diff = _hunk(
        "tests/test_probe.py",
        ["# billing-scan:allow", "client = OpenAI(api_key  # billing-scan:allow"],
    )
    result = scanner.scan_unified_diff(diff)
    assert result.findings == (), f"a fully marked region was not exempt: {result.findings}"
    assert result.allowed, "the exemptions were not reported in allowed"


def test_no_emitter_exempts_a_finding_by_another_lines_marker(scanner: ModuleType) -> None:
    """The attribution audit (r3 item 3): five emitter shapes, marker above and below.

    `emit_line` is the single place an exemption is decided (four call sites, listed in the PR
    body), and it decides from the finding's own line. Shapes are UNINDENTED so the region parses
    and reaches the parsed emitter — an indented first line sends them down the unparseable arm,
    which is how a mis-attribution mutant survived the first version of this test.
    """

    marked = "# billing-scan:allow"
    # UNINDENTED on purpose: an indented first line makes the whole region unparseable, which
    # would send every parsed shape down the unparseable arm and leave the parsed emitter
    # untested — measured, because a mutant that mis-attributed the parsed emitter survived the
    # first version of this test.
    shapes = {
        "unparseable region": ["client = OpenAI(api_key"],
        "parsed AST route": ["client = OpenAI(api_key=key)"],
        "credential read": ['key = os.environ["OPENAI_API_KEY"]'],
        "bearer header": ['headers = {"Authorization": "Bearer " + token}'],
        "pattern-only class": ['url = "https://api.openai.com/v1"'],
    }
    for label, body in shapes.items():
        for marked_first in (True, False):
            lines = [marked, *body] if marked_first else [*body, marked]
            diff = _hunk("tests/test_probe.py", lines)
            result = scanner.scan_unified_diff(diff)
            assert result.findings, (
                f"{label} (marker {'above' if marked_first else 'below'}): a marked neighbour "
                "line exempted the finding"
            )
