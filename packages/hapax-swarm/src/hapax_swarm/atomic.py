"""Atomic write helpers.

Peers must never observe a half-written yaml or markdown file. Every
mutation goes via a sibling tempfile + ``os.replace``, which is atomic
within the same filesystem on POSIX.

These primitives are deliberately tiny — they are the foundation
everything else in this package builds on.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically.

    The implementation writes to a tempfile in the same directory and
    then ``os.replace``\\ s it onto the target. ``os.replace`` is atomic
    on POSIX within a single filesystem.

    Parents of ``path`` must already exist; the caller is responsible
    for ``mkdir -p``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # Cleanup tmpfile if anything went wrong before replace().
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def atomic_write_yaml(path: Path, data: Any) -> None:
    """Atomically dump ``data`` as YAML to ``path``.

    Uses ``yaml.safe_dump`` with ``sort_keys=False`` so caller-controlled
    key order is preserved (humans care about this).
    """
    text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    atomic_write_text(path, text)
