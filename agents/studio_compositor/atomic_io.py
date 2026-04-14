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
from pathlib import Path


def atomic_write_json(payload: object, path: Path) -> None:
    """Write ``payload`` as JSON to ``path`` atomically.

    Steps:

    1. Ensure the parent directory exists.
    2. Serialize ``payload`` to ``path.tmp``.
    3. ``os.replace`` the tmp file onto the final path.

    External readers either see the previous file or the new one —
    never a partial write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2))
    os.replace(tmp_path, path)
