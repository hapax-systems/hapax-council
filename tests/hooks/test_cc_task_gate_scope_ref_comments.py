"""A YAML comment must never silently shorten a mutation_scope_refs list.

All three review seats on PR #4501 raised the same Major: the behaviour change to a T1 governance
gate shipped with no automated test, and its exit-predicate evidence was a one-off hand count against
a vault note that is not in the repo — irreproducible by anyone else, at any later time.

Both are fixed here. The collector is EXTRACTED FROM THE SHIPPED SCRIPT rather than restated, so the
test cannot pass while the real parser diverges, and the fixtures are inline, so the evidence travels
with the repo instead of depending on a note that may be edited or closed.

WHY THIS MATTERS MORE THAN A PARSER BUG. A dropped scope ref does not fail loudly. It NARROWS the
authorized surface, so the gate later BLOCKS a mutation the operator actually authorized, and the
diagnostic points at the mutation rather than at the parser. That is how it cost real time: it was
diagnosed as an undeclarable-scope-ref deadlock in the tooling, and an entire reasoning chain was
built on that false premise before anyone read the parser.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"


def _extract_collector() -> str:
    """Lift the block-sequence collector out of the real gate script.

    The gate is bash with an embedded python parser. Restating that parser here would let this test
    keep passing after the real one changed — the exact drift the estate keeps rediscovering. So the
    loop is read from the shipped file and executed as-is.
    """
    src = GATE.read_text(encoding="utf-8")
    anchor = "    while idx < len(lines):\n        child = lines[idx].strip()"
    # UNIQUENESS IS THE POINT, not merely presence. Blind review on PR #4501 flagged that a
    # `find()` anchor plus the next `break` can silently capture a DIFFERENT loop if the gate
    # grows another nested one — the test would keep passing while testing the wrong code, which
    # is the exact rot this extraction was chosen to avoid.
    occurrences = src.count(anchor)
    assert occurrences == 1, (
        f"the collector anchor matches {occurrences} times in cc-task-gate.impl.sh, so this "
        "extraction cannot prove WHICH loop it lifted. Re-anchor on something unique rather than "
        "letting the test silently bind to the wrong parser."
    )
    start = src.find(anchor)
    end = src.find("\n        break\n", start)
    assert end != -1, "collector loop end anchor not found"
    block = src[start : end + len("\n        break\n")]
    # The slice must BE the collector, checked structurally rather than by counting `break`s in
    # the rest of the file — other loops legitimately end in `break`, so a global count is a false
    # constraint. These two assertions pin the slice to the right loop instead.
    assert 'child.startswith("- ")' in block, (
        "the extracted slice does not contain the sequence-item branch, so it is not the "
        "block-sequence collector — re-anchor rather than testing whatever loop this is."
    )
    # The slice must reach the END of the collector, not stop at some inner `break`. Counting
    # `while` was the first attempt and was WRONG: the collector legitimately grew a nested loop
    # (quoted-scalar scanning), and the assertion then rejected correct code. What actually matters
    # is that the slice contains the whole body, so assert on its terminal constructs instead.
    for marker in ("items.append(", 'for sep in ("\\t#", " #")'):
        assert marker in block, (
            f"the extracted slice is missing {marker!r}, so the `break` anchor terminated it early "
            "and the test would execute a TRUNCATED parser that silently parses fewer refs."
        )
    # The collector lives inside a function in the gate, so it arrives indented. Dedent it to
    # module level for splicing; textwrap.dedent handles the blank/comment lines correctly.
    return textwrap.dedent(block)


def _collect(note_lines: list[str]) -> list[str]:
    """Run the REAL collector over a synthetic note and return the parsed refs."""
    collector = _extract_collector()
    program = (
        "import json, sys\n"
        f"lines = json.loads(sys.argv[1])\n"
        "idx = 0\n"
        "while idx < len(lines):\n"
        "    if lines[idx].strip().startswith('mutation_scope_refs:'):\n"
        "        idx += 1\n"
        "        break\n"
        "    idx += 1\n"
        "items = []\n"
        f"{collector}"
        "\nprint(json.dumps(items))\n"
    )
    import json

    result = subprocess.run(
        ["python3", "-c", program, json.dumps(note_lines)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


NOTE = [
    "mutation_scope_refs:",
    "  - ~/projects/x/first.py",
    "  # widened 2026-08-04 to cover the installer as well",
    "  - ~/projects/x/second.py",
    "  - ~/projects/x/third.py   # the one that actually changed",
    "",
    "  - ~/projects/x/fourth.py",
    "exit_predicate: something",
]

EXPECTED = [
    "~/projects/x/first.py",
    "~/projects/x/second.py",
    "~/projects/x/third.py",
    "~/projects/x/fourth.py",
]


def test_full_line_comment_does_not_terminate_the_list() -> None:
    """The original defect: a `#` line was treated as a sequence terminator.

    Measured on a live note before the fix: 6 refs written, 4 parsed, 2 silently lost.
    """
    refs = _collect(NOTE)
    assert refs == EXPECTED, (
        "a comment inside the block sequence changed the parsed refs. Anything short of the full "
        f"list is a SILENT scope reduction.\n  expected {EXPECTED}\n  got      {refs}"
    )


def test_trailing_comment_is_not_part_of_the_path() -> None:
    """The defect the first fix left behind, caught by review on PR #4501.

    Fixing full-line comments and not trailing ones left the same hole one keystroke away — and a
    trailing note is the MORE natural way to annotate a single ref. A ref carrying its comment
    matches no file on disk, so the surface narrows exactly as before.
    """
    refs = _collect(NOTE)
    corrupted = [r for r in refs if "#" in r]
    assert not corrupted, (
        "a trailing comment was absorbed into the ref, producing a path that matches nothing: "
        f"{corrupted}"
    )
    assert "~/projects/x/third.py" in refs, (
        f"the annotated ref did not survive with its comment stripped. got {refs}"
    )


def test_blank_lines_still_do_not_terminate_the_list() -> None:
    """Regression guard on the pre-existing behaviour the comment fix sits beside."""
    refs = _collect(NOTE)
    assert "~/projects/x/fourth.py" in refs, f"a ref after a blank line was dropped. got {refs}"


def test_hash_without_leading_whitespace_is_kept_as_a_path_character() -> None:
    """Do not over-strip. `#` is legal in a path; YAML only starts a comment after whitespace."""
    refs = _collect(
        [
            "mutation_scope_refs:",
            "  - ~/projects/x/od#d-name.py",
            "exit_predicate: something",
        ]
    )
    assert refs == ["~/projects/x/od#d-name.py"], (
        f"a literal '#' inside a path was stripped as if it were a comment. got {refs}"
    )


def test_a_quoted_scalar_keeps_a_hash_that_looks_like_a_comment() -> None:
    """MAJOR from blind review on PR #4501: the comment fix broke quoted paths.

    In YAML a `#` inside a quoted scalar is a literal character; a comment can only start after
    the closing quote. The first version of this fix stripped on ` #` BEFORE unquoting, so
    `- "~/projects/x/b #2.py"` became `~/projects/x/b` — a ref matching no file, silently
    narrowing the authorized surface. That is the identical fail-quiet defect this collector was
    written to remove, reintroduced by the fix for it.
    """
    refs = _collect(
        [
            "mutation_scope_refs:",
            '  - "~/projects/x/b #2.py"',
            "  - '~/projects/x/c #3.py'   # annotated, and the annotation must still go",
            "  - ~/projects/x/plain.py   # this one IS a comment",
            "exit_predicate: something",
        ]
    )
    assert refs == [
        "~/projects/x/b #2.py",
        "~/projects/x/c #3.py",
        "~/projects/x/plain.py",
    ], (
        "a '#' inside a QUOTED scalar was treated as a comment and truncated the path, or a real "
        f"trailing comment survived on the unquoted one. got {refs}"
    )


def test_the_gate_script_is_syntactically_valid() -> None:
    """A parser fix that breaks the gate blocks every mutation in the estate."""
    result = subprocess.run(["bash", "-n", str(GATE)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"bash -n failed on the gate:\n{result.stderr}"


def test_comment_handling_is_documented_accurately() -> None:
    """The comment must not claim more than the code does.

    Review flagged that the shipped comment asserted general YAML comment support while only
    full-line comments were handled. A comment that overstates the code is how the next reader
    stops checking.
    """
    src = GATE.read_text(encoding="utf-8")
    assert re.search(r"trailing comment", src, re.I), (
        "the collector handles trailing comments but does not say so; the next reader will assume "
        "only full-line comments are covered and re-introduce the gap"
    )


def test_escaped_quotes_inside_a_quoted_scalar_do_not_truncate_the_path() -> None:
    """MAJOR from blind review (codex-1) on PR #4501, both YAML escape forms.

    `find(quote, 1)` stops at the first quote character. A double-quoted scalar escapes one as
    `\\"` and a single-quoted scalar doubles it (`''`), so either form terminated the value early
    and silently shortened the path — narrowing the authorized surface, which is the defect this
    collector exists to prevent, reappearing one layer down from where it was fixed.
    """
    refs = _collect(
        [
            "mutation_scope_refs:",
            '  - "~/projects/x/we\\"ird.py"',
            "  - '~/projects/x/it''s.py'",
            "exit_predicate: something",
        ]
    )
    assert refs == ['~/projects/x/we"ird.py', "~/projects/x/it's.py"], (
        "an escaped quote inside a quoted scalar truncated the path. Double-quoted uses "
        f"backslash (\\\"), single-quoted doubles the quote (''). got {refs}"
    )
