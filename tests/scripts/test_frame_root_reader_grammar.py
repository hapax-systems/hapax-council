"""A colon means what the declared reader says it means, and the local readers say nothing.

The installed producer decides remoteness by **which reader a member declares**, never by the
shape of a string:

* ``fs.glob`` (``procedure/builtin.py:34``) takes ``Path(root_raw).expanduser()`` — no partition.
* ``fs.content_query`` (``:1121``) takes ``Path(str(raw_root)).expanduser()`` per root — no
  partition.
* ``ssh.glob`` (``:769``) is the only reader that partitions, and it *requires* the form:
  ``"ssh.glob requires location.path as '<host>:<remote-path>'"``.
* ``ssh_jsonl_meta`` (``:643``) does not partition either — it reads ``location.host`` and
  ``location.remote_path`` as separate declared fields and refuses without them.

The consumer applied one colon rule to every member regardless of reader, so a legal relative
directory whose *name* contains a colon was classified as a scheme-qualified surface and judged in
a different namespace. These pin the parity: for a member declaring a local reader, a colon is a
character in a filename.
"""

import pytest

from shared import frame_verdicts as fv
from tests.scripts.test_frame_root_entries import _root_dispatch

LOCAL_READERS = ("fs.content_query", "fs.glob")


def _location_for(reader, declared):
    location = {"patterns": ["*.txt"]}
    if reader == "fs.content_query":
        location.update(roots=[declared], query="NEEDLE")
    else:
        location.update(path=declared)
    return location


@pytest.mark.parametrize("reader", LOCAL_READERS)
@pytest.mark.parametrize(
    ("name", "spelling"),
    [
        ("notes:archive", "bare"),
        ("notes:archive", "dot-slash"),
        ("notes:archive", "absolute"),
        ("https:notes", "bare"),
        ("gh:hapax-systems", "bare"),
    ],
    ids=[
        "bare-colon-name",
        "dot-slash-colon-name",
        "absolute-colon-name",
        "url-lookalike",
        "scheme-lookalike",
    ],
)
def test_a_colon_in_a_local_root_name_is_part_of_the_name(
    tmp_path, monkeypatch, capsys, reader, name, spelling
):
    """A selected file under a decayed root must be refused whatever the root is spelled like."""

    root = tmp_path / name
    root.mkdir()
    candidate = root / "candidate.txt"
    candidate.write_bytes(b"NEEDLE\n")

    if spelling == "absolute":
        declared = str(root)
    elif spelling == "dot-slash":
        declared = f"./{name}"
    else:
        declared = name

    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location_for(reader, declared),
        reader=reader,
        cwd=tmp_path,
        candidate=candidate,
    )
    with capsys.disabled():
        print(f"{reader} declared={declared!r} ({spelling}): main()={rc}")

    assert rc == 10, "a selected scope_exited file must not be admitted"
    assert "lies in legacy-surface (scope_exited)" in err


@pytest.mark.parametrize("reader", LOCAL_READERS)
def test_a_disjoint_colon_root_admits_nothing_and_refuses_nothing(
    tmp_path, monkeypatch, capsys, reader
):
    """The control: a colon-bearing root that does not contain the candidate is simply disjoint.

    Without this, a repair that refused *every* colon-bearing declaration would look correct on
    the cases above while having replaced one wrong answer with another.
    """

    declared_root = tmp_path / "notes:archive"
    declared_root.mkdir()
    (declared_root / "unrelated.txt").write_bytes(b"NEEDLE\n")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    candidate = elsewhere / "candidate.txt"
    candidate.write_bytes(b"NEEDLE\n")

    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location_for(reader, str(declared_root)),
        reader=reader,
        cwd=tmp_path,
        candidate=candidate,
    )
    with capsys.disabled():
        print(f"{reader} disjoint colon root: main()={rc}")

    assert rc == 0
    assert "lies in legacy-surface (scope_exited)" not in err


def _classify(reader_id, raw, tmp_path):
    # `fs.content_query` declares `location.roots`; the consumer ignores `location.path` for it
    # (`_member_location`: `if not content_query and isinstance(location.get("path"), str)`), so
    # handing it a `path` would test nothing.
    location = {"roots": [raw]} if reader_id == "fs.content_query" else {"path": raw}
    roots, _globs, _files, qualified, _qf, lexical, _lf = fv._member_location(
        {"id": "m1", "reader": {"id": reader_id}, "location": location},
        epoch_dir=tmp_path,
    )
    return roots, qualified, lexical


@pytest.mark.parametrize("reader_id", ["ssh.glob", "ssh.witness", "gh.api"])
def test_a_non_local_reader_keeps_its_qualified_interpretation(reader_id, tmp_path):
    """The negative control: remote and qualified semantics are untouched by the repair.

    ``ssh.glob`` genuinely partitions ``host:path`` at ``builtin.py:769``, and a reader this
    consumer does not model keeps exactly the handling it had — the repair is scoped to the
    local filesystem family by name, not applied as a general gate.
    """

    roots, qualified, _lexical = _classify(
        reader_id, "hapax-podium.local:~/.codex/sessions", tmp_path
    )

    assert qualified, f"{reader_id} must still resolve a qualified surface"
    assert not roots, f"{reader_id} must not acquire a filesystem root"


@pytest.mark.parametrize("reader_id", sorted(fv._LOCAL_FILESYSTEM_READERS))
def test_every_local_reader_reads_a_colon_as_part_of_the_name(reader_id, tmp_path):
    """All four `fs.*` readers share the grammar, so all four are pinned, not just the two seen.

    Declared absolutely on purpose: a *relative* root is anchored against the producer working
    directory, which this unit context does not supply, and the resulting refusal would be about
    anchoring rather than about the colon. The two local readers reachable end-to-end are covered
    relatively by the dispatch cases above.
    """

    declared = str(tmp_path / "notes:archive")
    roots, qualified, lexical = _classify(reader_id, declared, tmp_path)

    assert not qualified, f"{reader_id} must not produce a qualified surface"
    assert any(path.name == "notes:archive" for path in lexical), lexical
    assert roots
