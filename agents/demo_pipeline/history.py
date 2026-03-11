"""Demo history — list and inspect generated demos."""
from __future__ import annotations

import json
from pathlib import Path


def list_demos(output_dir: Path) -> list[dict]:
    """List all generated demos, newest first."""
    if not output_dir.exists():
        return []

    demos = []
    for d in sorted(output_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["dir"] = str(d)
            meta["id"] = d.name
            demos.append(meta)
    return demos


def get_demo(demo_dir: Path) -> dict | None:
    """Get metadata and file listing for a single demo."""
    if not demo_dir.exists():
        return None

    meta_path = demo_dir / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    files = [str(f.relative_to(demo_dir)) for f in sorted(demo_dir.rglob("*")) if f.is_file()]
    meta["files"] = files
    meta["dir"] = str(demo_dir)
    return meta
