"""Atomic JSON write helper shared by compositor state publishers.

Extracted from :mod:`agents.studio_compositor.budget` per delta drop
#41 finding 2. Previously ``atomic_write_json`` lived on ``budget.py``
and ``budget_signal.py`` imported it from there, creating a circular
import with ``metrics.py``'s force-import of ``budget_signal``. The
cycle surfaced as a startup warning:

    ImportError: cannot import name 'atomic_write_json' from
    partially initialized module 'agents.studio_compositor.budget'
    (most likely due to a circular import)

Moving the helper to a standalone module with zero compositor
dependencies breaks the cycle. ``budget.py`` and ``budget_signal.py``
both re-import it from here, and the original attribute path
``agents.studio_compositor.budget.atomic_write_json`` remains
patchable because ``budget.py`` keeps it in its module namespace via
the re-export.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(payload: object, path: Path) -> None:
    """Write ``payload`` as JSON to ``path`` atomically.

    Beta pass-4 M-01 upgrade: matches the robustness guarantees of
    :func:`shared.stream_archive.atomic_write_json` (the gold-standard
    implementation flagged in pass-1 audit). Keeps the
    ``(payload, path)`` signature for backwards compat with all
    existing callers (``budget.py::publish_costs``,
    ``budget_signal.py::publish_degraded_signal``, and the test mocks
    at ``agents.studio_compositor.budget.atomic_write_json``).

    Steps (in order, matching shared/stream_archive.py):

    1. Ensure the parent directory exists.
    2. Serialize ``payload`` via ``json.dumps(..., indent=2)``.
    3. Create a unique temp file via ``tempfile.mkstemp`` with a
       ``.{name}.`` prefix + ``.tmp`` suffix in the same directory.
       Unique per-call, so concurrent writers never collide on a
       fixed ``.tmp`` sibling (previous implementation).
    4. Write + ``flush()`` + ``os.fsync(fd)`` before rename — the
       durability guarantee that matters when callers write to a
       disk-backed target. On tmpfs the fsync is a cheap no-op.
    5. ``os.replace`` the tmp file onto the final path.
    6. On any exception, unlink the tmp file so it doesn't linger.

    External readers either see the previous file or the new one —
    never a partial write, even across crashes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_s = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_s, path)
    except Exception:
        tmp_path = Path(tmp_path_s)
        if tmp_path.exists():
            tmp_path.unlink()
        raise
