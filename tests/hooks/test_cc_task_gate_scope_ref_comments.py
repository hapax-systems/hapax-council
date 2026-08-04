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
    start = src.find("    while idx < len(lines):\n        child = lines[idx].strip()")
    assert start != -1, (
        "could not locate the block-sequence collector in cc-task-gate.impl.sh. If the parser was "
        "restructured, re-anchor this extraction rather than inlining a copy — a copied parser "
        "passes forever while the real one rots."
    )
    end = src.find("\n        break\n", start)
    assert end != -1, "collector loop end anchor not found"
    block = src[start : end + len("\n        break\n")]
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
