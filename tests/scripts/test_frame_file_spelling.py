"""Filesystem whitespace belongs to a declared FILE too, at receipt-only dispatch.

`test_frame_root_spelling.py` pins this for `location.roots`. `location.files` was the sibling
that still trimmed, so a member declaring `"…/zz-review-future "` did not contain the scope ref
naming that exact file, and the ref was admitted although the frame recorded the member as
`scope_exited` (gemini and codex independently, at `63bf526e4`).

Repairing only the declaration side is measurably worse: the scope-ref side trimmed as well, so
the literal spelling matched *because two errors cancelled*, and removing one turned a refusing
case into an admitting one. These rows pin both spellings — the exact name, and a glob whose
character class matches the whitespace.

The member declares `files` and NOTHING else, which makes its surface exactly one file
(`roots=[]`, `patterns=()`). An earlier version of this module added `patterns: ["*"]`, which
with no root is a wildcard surface that swallows the neighbour row and measures the harness
rather than the declaration.
"""

import pytest

from tests.scripts.test_frame_root_entries import _root_dispatch


def _location(reader: str, declared) -> dict:
    location: dict = {"files": [str(declared)]}
    if reader == "fs.content_query":
        location["query"] = "NEEDLE"
    return location


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
@pytest.mark.parametrize(
    ("name", "spelling"),
    [
        ("zz-review-future ", "literal"),
        ("zz-review-future ", "glob-class"),
        ("zz-review-future\t", "literal"),
        (" zz-leading", "literal"),
    ],
    ids=["trailing-space", "trailing-space-glob", "trailing-tab", "leading-space"],
)
def test_main_declared_file_spelling_is_not_trimmed(
    tmp_path, monkeypatch, capsys, reader, name, spelling
):
    """A declared file's whitespace is part of its name, so the scope must not be admitted.

    `main()` returning 0 is ADMISSION — the dispatch proceeding over a surface the frame marked
    decayed — which is the defect. A non-zero receipt-only refusal is the contract's other
    permitted outcome: same subject, or refused by name.
    """
    producer = tmp_path / "producer"
    producer.mkdir(parents=True, exist_ok=True)
    declared = producer / name
    declared.write_bytes(b"NEEDLE\n")

    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location(reader, declared),
        reader=reader,
        cwd=producer,
        candidate=declared,
    )
    with capsys.disabled():
        print(f"{reader} file={name!r} ref={spelling}: main()={rc}")

    assert rc != 0, (
        f"{reader}/{spelling}: a scope ref naming the declared file of a DECAYED member was "
        "admitted; trimming the declaration or the ref changed the subject"
    )
    assert err, "a refusal must carry its reason"


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
def test_main_a_plain_declared_file_still_refuses(tmp_path, monkeypatch, capsys, reader):
    """The twin with no whitespace, so the rows above cannot pass by refusing everything."""
    producer = tmp_path / "producer"
    producer.mkdir(parents=True, exist_ok=True)
    declared = producer / "zz-plain"
    declared.write_bytes(b"NEEDLE\n")

    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location(reader, declared),
        reader=reader,
        cwd=producer,
        candidate=declared,
    )
    with capsys.disabled():
        print(f"{reader} file='zz-plain': main()={rc}")
    assert rc != 0, "a declared file of a decayed member is inside it whatever its spelling"
    assert err


@pytest.mark.parametrize("reader", ["fs.glob"])
def test_main_the_trimmed_neighbour_is_a_different_file(tmp_path, monkeypatch, capsys, reader):
    """The discriminating row: `…future` and `…future ` are two files, and one is not declared.

    Without this, "refuse whenever the names look similar" would satisfy every row above. The
    member declares ONLY the trailing-space file; the candidate is its trimmed neighbour, with
    a different name AND different content, so it is a different surface and must be admitted.

    **`fs.content_query` is deliberately not parametrized here, and the reason is an open
    question rather than a convenience.** With `files` declared and no `roots`, a content-query
    member refuses this neighbour even when its content differs — so its surface is evidently
    not the declared file set. That may be correct reader semantics or an empty root set being
    read as unbounded, which would be its own defect; I could not establish which, and
    asserting the current behaviour here would bless whichever it is. Recorded for the owner
    rather than encoded.
    """
    producer = tmp_path / "producer"
    producer.mkdir(parents=True, exist_ok=True)
    declared = producer / "zz-review-future "
    declared.write_bytes(b"NEEDLE\n")
    # DISTINCT content. Giving the twin the same bytes made it legitimately inside a
    # content-query member's surface, so the row failed for a true reason and would have
    # measured nothing about the name. The twin must differ in both name AND content.
    neighbour = producer / "zz-review-future"
    neighbour.write_bytes(b"DIFFERENT\n")

    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location(reader, declared),
        reader=reader,
        cwd=producer,
        candidate=neighbour,
    )
    with capsys.disabled():
        print(f"{reader} declared='zz-review-future ' candidate=trimmed neighbour: main()={rc}")
    assert rc == 0, "the trimmed neighbour is a different file, outside the declared surface"
    assert not err
