"""Bound what a test's ``tmp_path`` may own (M117).

On appendix, pytest's default basetemp is under ``/tmp``, an 8 GB tmpfs (RAM). One test that
materialised a release venv there held 7.7 GB and stalled every lane. ``tests/conftest.py`` runs
:func:`budget_violation` after every test, and a test that needs more declares it with
``@pytest.mark.tmp_path_budget(<bytes>)``.

Cost is measured as the filesystem sees it: an inode counts only when every one of its hard links
lies inside the tree. A file hardlinked from a cache outside the tree allocated no new blocks, and
a symlink is never followed.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_TMP_PATH_BUDGET_BYTES = 512 * 1024 * 1024
_REPORTED_FILES = 5


def _owned_inodes(root: Path) -> dict[tuple[int, int], tuple[int, str]]:
    """Map each inode owned wholly by ``root`` to (allocated bytes, one path)."""

    seen: dict[tuple[int, int], list] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*filenames, *dirnames]:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except FileNotFoundError:
                continue
            key = (st.st_dev, st.st_ino)
            entry = seen.get(key)
            if entry is None:
                seen[key] = [st.st_nlink, 1, st.st_blocks * 512, path]
            else:
                entry[1] += 1
    return {
        key: (allocated, path)
        for key, (nlink, links_inside, allocated, path) in seen.items()
        if links_inside >= nlink
    }


def owned_bytes(root: Path) -> int:
    """Bytes the filesystem allocated for ``root`` and nothing outside it shares."""

    if not root.exists():
        return 0
    return sum(allocated for allocated, _ in _owned_inodes(root).values())


def budget_violation(root: Path, *, budget_bytes: int, nodeid: str) -> str | None:
    """A failure message when ``root`` owns more than ``budget_bytes``, else ``None``."""

    if not root.exists():
        return None
    inodes = _owned_inodes(root)
    total = sum(allocated for allocated, _ in inodes.values())
    if total <= budget_bytes:
        return None
    largest = sorted(inodes.values(), reverse=True)[:_REPORTED_FILES]
    listing = "\n  ".join(f"{allocated / 1048576:.1f} MiB  {path}" for allocated, path in largest)
    return (
        f"{nodeid}: tmp_path owns {total / 1048576:.1f} MiB, over its budget of "
        f"{budget_bytes / 1048576:.1f} MiB (M117: on appendix the default basetemp is an 8 GB "
        f"RAM tmpfs shared by every lane). Largest:\n  {listing}\n"
        "Next: write less, reuse a cache by hardlink, or declare the need with "
        "@pytest.mark.tmp_path_budget(<bytes>) and run with --basetemp on disk."
    )


def _unescape_mountinfo(field: str) -> str:
    # mountinfo octal-escapes space, tab, newline and backslash
    for code, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        field = field.replace(code, char)
    return field


def filesystem_type(path: Path, *, mountinfo_text: str | None = None) -> str:
    """The filesystem type of the mount holding ``path``: its longest mount-point prefix."""

    if mountinfo_text is None:
        mountinfo_text = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    target = os.path.normpath(str(path))
    best_point, best_type = "", "unknown"
    for line in mountinfo_text.splitlines():
        left, sep, right = line.partition(" - ")
        if not sep:
            continue
        fields = left.split()
        if len(fields) < 5 or not right.split():
            continue
        point = _unescape_mountinfo(fields[4])
        under = target == point or target.startswith(point.rstrip("/") + "/")
        if under and len(point) >= len(best_point):
            best_point, best_type = point, right.split()[0]
    return best_type
