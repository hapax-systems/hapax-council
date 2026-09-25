"""Filesystem whitespace belongs to the declared root at receipt-only dispatch."""

import pytest

from tests.scripts.test_frame_root_entries import _root_dispatch


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
@pytest.mark.parametrize(
    ("name", "trimmed_exists", "relative"),
    [
        ("member", False, False),
        ("member ", True, False),
        ("member\t", True, False),
        ("member ", False, False),
        (" member", True, True),
    ],
    ids=["plain", "space", "tab", "space-no-trimmed-root", "leading-space-relative"],
)
def test_main_declared_root_spelling(
    tmp_path, monkeypatch, capsys, reader, name, trimmed_exists, relative
):
    root = tmp_path / name
    root.mkdir()
    if trimmed_exists:
        trimmed = tmp_path / name.strip()
        trimmed.mkdir()
        assert trimmed != root and not tuple(trimmed.iterdir())
    elif name != name.strip():
        assert not (tmp_path / name.strip()).exists()
    candidate = root / "candidate.txt"
    candidate.write_bytes(b"NEEDLE\n")
    # The installed reader uses Path(str(raw_root)).expanduser(): leading spaces
    # survive too. A relative declaration puts that space at the start of raw.
    declared = name if relative else str(root)
    location = {"patterns": ["*.txt"]}
    if reader == "fs.content_query":
        location.update(roots=[declared], query="NEEDLE")
    else:
        location.update(path=declared)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        location,
        reader=reader,
        cwd=tmp_path,
        candidate=candidate,
    )
    with capsys.disabled():
        print(f"{reader} root={declared!r} trimmed_exists={trimmed_exists}: main()={rc}")
    assert rc == 10, "a selected scope_exited file must not be admitted"
    assert "lies in legacy-surface (scope_exited)" in err


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
def test_main_trimmed_directory_is_a_different_surface(tmp_path, monkeypatch, capsys, reader):
    declared = tmp_path / "member "
    declared.mkdir()
    trimmed = tmp_path / "member"
    trimmed.mkdir()
    candidate = trimmed / "candidate.txt"
    candidate.write_bytes(b"NEEDLE\n")
    location = {"patterns": ["*.txt"]}
    if reader == "fs.content_query":
        location.update(roots=[str(declared)], query="NEEDLE")
    else:
        location.update(path=str(declared))
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        location,
        reader=reader,
        cwd=tmp_path,
        candidate=candidate,
    )
    with capsys.disabled():
        print(f"{reader} root={str(declared)!r}, candidate in trimmed directory: main()={rc}")
    assert rc == 0, "a file in the trimmed directory is outside the declared surface"
    assert not err
