"""Filesystem whitespace belongs to a declared FILE too, at receipt-only dispatch.

`test_frame_root_spelling.py` pins this for `location.roots`. `location.files` was the sibling
that still trimmed, so a member declaring `"…/zz-review-future "` did not contain the scope ref
naming that exact file, and the ref was admitted although the frame recorded the member as
`scope_exited` (gemini and codex independently, at `63bf526e4`).

Repairing only the declaration side is measurably worse: the scope-ref side trimmed as well, so
the literal spelling matched *because two errors cancelled*, and removing one turned a refusing
case into an admitting one. These rows pin both spellings — the exact name, and a glob whose
character class matches the whitespace.

**The member shape is chosen from the reader grammar, not for convenience.** Read from the
producer (`procedure/builtin.py`) and the consumer's containment gate:

- `fs_glob` requires `location.path` and refuses without it (*"declaration has no
  location.path"*). It does not itself read `location.files`.
- `fs_content_query` requires a non-empty `location.roots` and refuses otherwise. The consumer
  likewise skips `location.files` for it outright (`files_raw = None if content_query else …`),
  so a content-query member declaring only `files` has NO surface and refuses every candidate.
- `fs_filelist` is the one reader that reads `location.files`, and the consumer's containment
  gate does not list it — a decayed `fs.filelist` member raises *"unimplemented containment
  reader"* for any scope at all.

So the member here declares a real `location.path` (valid for `fs.glob`) **and** the explicit
`location.files` the consumer's containment reads. Two earlier drafts got this wrong in opposite
directions and both were discarded: one declared `files` under `fs.glob`/`fs.content_query`,
which the producer would refuse to read, so a synthesized `scope_exited` receipt asked the
consumer about a member that could not exist (cx-blue); the next moved to `fs.filelist`, where
every row then "passed" on the unimplemented-containment refusal and measured nothing.

**What these rows are evidence OF, stated narrowly.** Giving `fs.glob` a readable
`location.path` makes the declaration one the producer will read; it does NOT make the producer
select the separately declared `files`, which that reader ignores. So these are controls on the
CONSUMER's explicit-file containment, and they are not producer-selection evidence for those
files (cx-blue, 2026-09-08). Real `fs.glob` selection for the whitespace cases, with exact
subject and digest binding, is covered by a separate producer-backed run and the two claims are
kept apart. Nothing here should be read as the consumer's extra keys being a producer contract.

The declared root deliberately does not contain the trimmed neighbour. That is the real member's
own structure — `agents-md-and-per-repo-claude-md-agents-md` declares roots across the estate
*plus* two individually named files — and not a twin moved out of an overbroad directory to
obtain green: the neighbour is outside because it was never declared, and the row would still
discriminate if the root were removed entirely.
"""

import pytest

from tests.scripts.test_frame_root_entries import _root_dispatch
from tests.scripts.test_hapax_methodology_dispatch import (
    _dispatcher_module,
    _frame_procedure_root,
    _governed_source_frontmatter,
    _spec,
    _task,
)

WHITESPACE_NAMES = ("zz-review-future ", "zz-review-future\t", " zz-leading")


def _glob_class_ref(declared) -> str:
    """Wrap exactly the whitespace character of a declared name in a glob character class.

    A previous revision parametrized a `spelling` label and used it only in the printed output,
    so the "glob-class" rows re-ran the literal row under a different name and pinned nothing
    (cx-blue, 2026-09-08). The spelling has to change the REF, which is the only thing the
    dispatcher is given.
    """
    name = declared.name
    if name.startswith((" ", "\t")):
        return str(declared.parent / f"[{name[0]}]{name[1:]}")
    return str(declared.parent / f"{name[:-1]}[{name[-1]}]")


def _member(root, declared_files) -> dict:
    """A member `fs.glob` can actually read, whose containment surface includes explicit files."""
    return {
        "path": str(root),
        "patterns": ["*.md"],
        "files": [str(item) for item in declared_files],
    }


def _fixture(tmp_path):
    """A readable declared root, and a separately named file whose spelling is under test."""
    base = tmp_path / "producer"
    base.mkdir(parents=True, exist_ok=True)
    root = base / "declared-root"
    root.mkdir(exist_ok=True)
    (root / "unrelated.md").write_bytes(b"UNRELATED\n")
    return base, root


@pytest.mark.parametrize("spelling", ["literal", "glob-class"])
@pytest.mark.parametrize(
    "name", WHITESPACE_NAMES, ids=["trailing-space", "trailing-tab", "leading-space"]
)
def test_main_declared_file_spelling_is_not_trimmed(tmp_path, monkeypatch, capsys, name, spelling):
    """A declared file's whitespace is part of its name, so the scope must not be admitted.

    `main()` returning 0 is ADMISSION — the dispatch proceeding over a surface the frame marked
    decayed — which is the defect. A non-zero receipt-only refusal is the contract's other
    permitted outcome: same subject, or refused by name.

    **What each row does and does not pin.** Restoring the declaration-side strip reddens the
    four trailing rows and the neighbour; restoring the metadata-side strip reddens the two
    trailing literals. The two LEADING-space rows are reddened by neither, and the reason is
    worth stating rather than leaving as apparent coverage: the strip these repairs removed acted
    on the whole declared PATH string, and a leading space in the basename of
    `…/producer/ zz-leading` sits in that string's interior, where `.strip()` never reached it.
    Only a trailing-whitespace basename is also the string's boundary. So these rows assert a
    true property — a leading-space file is inside the member that declares it — but they are not
    regression cover for trimming, and a relative one-segment spelling would be the case that is.
    """
    base, root = _fixture(tmp_path)
    declared = base / name
    declared.write_bytes(b"NEEDLE\n")
    ref = str(declared) if spelling == "literal" else _glob_class_ref(declared)

    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _member(root, [declared]),
        reader="fs.glob",
        cwd=base,
        candidate=ref,
    )
    with capsys.disabled():
        print(f"file={name!r} {spelling} ref={ref[len(str(base)) + 1 :]!r}: main()={rc}")

    assert rc != 0, (
        f"{spelling}: a scope ref naming the declared file of a DECAYED member was admitted; "
        "trimming the declaration or the ref changed the subject"
    )
    assert err, "a refusal must carry its reason"


def test_main_a_plain_declared_file_still_refuses(tmp_path, monkeypatch, capsys):
    """The twin with no whitespace: a declared file is inside its member however it is spelled.

    This row does NOT discriminate "refuse whenever the names look similar" — it refuses too, so
    a gate that refused everything would satisfy it (cx-blue, 2026-09-08). The earlier docstring
    claimed otherwise. Only the admitting neighbour row below discriminates that.
    """
    base, root = _fixture(tmp_path)
    declared = base / "zz-plain"
    declared.write_bytes(b"NEEDLE\n")

    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _member(root, [declared]),
        reader="fs.glob",
        cwd=base,
        candidate=declared,
    )
    with capsys.disabled():
        print(f"file='zz-plain': main()={rc}")
    assert rc != 0, "a declared file of a decayed member is inside it whatever its spelling"
    assert err


def test_main_the_trimmed_neighbour_is_a_different_file(tmp_path, monkeypatch, capsys):
    """The discriminating row: `…future` and `…future ` are two files, and one is not declared.

    Without this, "refuse whenever the names look similar" would satisfy every row above. The
    member declares ONLY the trailing-space file; the candidate is its trimmed neighbour, with a
    different name AND different content, so it is a different surface and must be admitted.
    """
    base, root = _fixture(tmp_path)
    declared = base / "zz-review-future "
    declared.write_bytes(b"NEEDLE\n")
    # DISTINCT content. Giving the twin the same bytes made it legitimately inside a
    # content-addressed member's surface, so the row would have failed for a true reason and
    # measured nothing about the name. The twin must differ in both name AND content.
    neighbour = base / "zz-review-future"
    neighbour.write_bytes(b"DIFFERENT\n")

    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _member(root, [declared]),
        reader="fs.glob",
        cwd=base,
        candidate=neighbour,
    )
    with capsys.disabled():
        print(f"declared='zz-review-future ' candidate=trimmed neighbour: main()={rc}")
    assert rc == 0, "the trimmed neighbour is a different file, outside the declared surface"
    assert not err


def _dispatch_with_declared_refs(tmp_path, monkeypatch, capsys, frame_root, refs_literal: str):
    """Receipt-only `main()` with `mutation_scope_refs` written verbatim into the task.

    `_dispatch_receipt_only_scope` always spells the refs as a JSON list, so it cannot express
    the SCALAR form — which is exactly where the erasure differed. This takes the YAML text.
    """
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        _governed_source_frontmatter(
            spec,
            mutation_scope_refs=refs_literal,
            allowed_platforms="[codex]",
            required_mode="headless",
            required_profile="full",
        ),
        route_metadata_defaults=False,
    )
    monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(tmp_path / "tasks"))
    monkeypatch.setenv("HAPAX_FRAME_PROCEDURE_ROOT", str(frame_root))
    monkeypatch.setenv("HAPAX_DISPATCH_CLAIM_SWEEP", "0")
    monkeypatch.setenv("HAPAX_ORCHESTRATION_LEDGER_DIR", str(tmp_path / "ledger"))
    rc = _dispatcher_module().main(
        [
            "--task",
            "governed-build",
            "--lane",
            "cx-green",
            "--platform",
            "codex",
            "--mode",
            "receipt-only",
            "--skip-worktree-check",
        ]
    )
    return rc, capsys.readouterr().err


@pytest.mark.parametrize("spelling", ["scalar", "list"])
def test_main_a_whitespace_only_scope_ref_does_not_skip_the_uncontainable_guard(
    tmp_path, monkeypatch, capsys, spelling
):
    """The erasure's bite at the actual gate: a name trimmed to nothing skipped a refusal.

    A decayed member with no containable location makes EVERY declared scope undecidable, and
    the dispatcher must refuse. That refusal is reached through `if declared_refs and
    verdicts.unmatchable`, so a scope that trimmed away to nothing never reached it: the
    dispatch proceeded exactly where it had the least ground to (review finding, codex, at
    `5007ed238`). Whitespace is a legal POSIX filename, so `" "` is a declaration and must reach
    the same refusal as any other reference.

    This is the gate-observable form of the defect, and deliberately not "a ref naming a
    whitespace file". A bare `" "` resolves against the council root rather than the producer
    directory, so it is genuinely outside the member and BOTH the erasing and the repaired code
    admit it — such a row would pass either way and read as coverage it does not provide.

    Both spellings run because the erasure was asymmetric: the scalar form was dropped during
    frontmatter extraction while the list form survived, so one declaration got two answers
    depending only on how it was written (cx-blue, 2026-09-08).
    """
    frame = _frame_procedure_root(
        tmp_path / "frame",
        decayed_root=tmp_path / "producer",
        reader="fs.glob",
        location={"endpoints": ["undisclosed"]},
    )

    literal = '" "' if spelling == "scalar" else '[" "]'
    rc, err = _dispatch_with_declared_refs(tmp_path, monkeypatch, capsys, frame, literal)
    with capsys.disabled():
        print(f"uncontainable member, whitespace-only {spelling} ref: main()={rc}")

    assert rc != 0, (
        f"{spelling}: a whitespace-only scope ref skipped the uncontainable-member refusal; "
        "trimming a name to nothing turned a refusal into a verdict"
    )
    assert err, "a refusal must carry its reason"
