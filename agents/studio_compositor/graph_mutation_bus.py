"""Atomic writes for the compositor graph-mutation bus."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_MUTATION_FILE = Path("/dev/shm/hapax-compositor/graph-mutation.json")


def write_graph_mutation(
    payload: Mapping[str, Any],
    *,
    path: Path = DEFAULT_MUTATION_FILE,
    source: str | None = None,
) -> None:
    """Atomically publish one full graph mutation payload.

    The compositor's state reader treats ``graph-mutation.json`` as a full
    graph snapshot. Writers must therefore never expose a half-written JSON
    file; write to the same directory, then replace the target in one rename.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dict(payload)
    if source is not None:
        out["_source"] = source

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(out))
            fh.write("\n")
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
