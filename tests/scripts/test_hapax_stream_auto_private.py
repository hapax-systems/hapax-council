"""Tests for scripts/hapax-stream-auto-private."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "hapax-stream-auto-private"


def test_symlink_invocation_resolves_repo_import_path(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    symlink = bin_dir / "hapax-stream-auto-private"
    symlink.symlink_to(SCRIPT)

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["HAPAX_DISABLE_AUTO_PRIVATE"] = "1"

    result = subprocess.run(
        [sys.executable, "-S", str(symlink)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
