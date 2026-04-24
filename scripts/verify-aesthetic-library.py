#!/usr/bin/env python3
"""Verify aesthetic-library integrity — intended for CI + pre-commit.

Two checks in order:

  1. Manifest currency — `_manifest.yaml` and `_NOTICES.md` match what
     the generator would produce from the current on-disk asset tree
     (delegates to `generate-aesthetic-manifest.py --check`).
  2. Byte-level integrity — every asset's on-disk SHA-256 matches the
     manifest entry (delegates to `AestheticLibrary.verify_integrity()`).

Exit status:
  0 — clean
  1 — drift detected (see stderr for specifics)
  2 — structural error (missing manifest, invalid YAML, etc.)

Usage:
  uv run python scripts/verify-aesthetic-library.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_generator_check() -> int:
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate-aesthetic-manifest.py"),
            "--check",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.stderr.write(proc.stdout)
    else:
        sys.stdout.write(proc.stdout)
    return proc.returncode


def _run_integrity() -> int:
    # Import inside the function so the script itself stays importable without
    # the full Pydantic stack (useful if the hook runs before uv sync finishes).
    try:
        from shared.aesthetic_library.loader import (
            ASSETS_ROOT_DEFAULT,
            AestheticLibrary,
        )
    except ImportError as e:
        sys.stderr.write(f"ERROR: shared.aesthetic_library not importable: {e}\n")
        return 2

    lib_root = ASSETS_ROOT_DEFAULT / "aesthetic-library"
    if not lib_root.is_dir():
        sys.stderr.write(f"ERROR: aesthetic-library root missing: {lib_root}\n")
        return 2

    lib = AestheticLibrary(root=lib_root)
    drift = lib.verify_integrity()
    if drift:
        sys.stderr.write("DRIFT: on-disk bytes diverged from _manifest.yaml SHA-256:\n")
        for item in drift:
            sys.stderr.write(f"  - {item}\n")
        return 1
    print(f"OK: integrity verified for {len(lib.list())} assets")
    return 0


def main() -> int:
    checks = [
        ("generator --check", _run_generator_check),
        ("integrity", _run_integrity),
    ]
    for name, fn in checks:
        rc = fn()
        if rc != 0:
            sys.stderr.write(f"aesthetic-library verify: FAILED at {name}\n")
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
