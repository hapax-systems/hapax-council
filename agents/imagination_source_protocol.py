"""Content source protocol writer for imagination fragments.

Writes the new per-fragment directory format under sources/ for native
Rust text rendering. RGBA frame conversion deferred to Phase 3.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.imagination import ImaginationFragment

SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")


def write_source_protocol(
    fragment: ImaginationFragment,
    resolved_paths: list[Path],
    sources_dir: Path | None = None,
) -> None:
    """Write content using the new source protocol.

    Creates a directory per fragment in sources/ with manifest.json.
    Currently writes text content for native Rust rendering.
    RGBA frame writing deferred to Phase 3 integration.
    """
    if sources_dir is None:
        sources_dir = SOURCES_DIR

    source_id = f"imagination-{fragment.id}"
    source_dir = sources_dir / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source_id": source_id,
        "content_type": "text",
        "text": fragment.narrative,
        "opacity": fragment.salience,
        "layer": 1,
        "blend_mode": "screen",
        "z_order": 10,
        "ttl_ms": 10000,
        "tags": ["imagination"],
    }

    tmp = source_dir / "manifest.tmp"
    tmp.write_text(json.dumps(manifest))
    tmp.rename(source_dir / "manifest.json")
