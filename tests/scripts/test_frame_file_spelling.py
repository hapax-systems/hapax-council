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

The declared root deliberately does not contain the trimmed neighbour. That is the real member's
own structure — `agents-md-and-per-repo-claude-md-agents-md` declares roots across the estate
*plus* two individually named files — and not a twin moved out of an overbroad directory to
obtain green: the neighbour is outside because it was never declared, and the row would still
discriminate if the root were removed entirely.
"""

import pytest

from tests.scripts.test_frame_root_entries import _root_dispatch

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
    """The twin with no whitespace, so the rows above cannot pass by refusing everything."""
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
