"""cc-close must load the checkout under python -I, not the source-activation pin.

Worktree `.venv` is a symlink onto a pinned release. `python -I -m shared.sdlc_close`
therefore imports that pin and close snapshots cache/claim-publications while
cc-claim (same worktree, stdin runner with sys.path.insert) writes Gate 0B
journals. The wrapper has to inject SCRIPT_DIR/.. the way cc-claim already does.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"


def test_cc_close_isolated_python_injects_repo_root() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "sys.path.insert(0, str(repo_root))" in text
    assert "-I -m shared.sdlc_close" not in text


def test_cc_close_isolated_python_loads_checkout_shared(tmp_path: Path) -> None:
    python = REPO_ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        python = Path(os.environ.get("PYTHON", "python3"))
    probe = subprocess.run(
        [
            str(python),
            "-I",
            "-",
            str(REPO_ROOT),
        ],
        input=(
            "import sys\n"
            "from pathlib import Path\n"
            "repo_root = Path(sys.argv[1]).resolve()\n"
            "if str(repo_root) not in sys.path:\n"
            "    sys.path.insert(0, str(repo_root))\n"
            "import shared.sdlc_close\n"
            "print(Path(shared.sdlc_close.__file__).resolve())\n"
        ),
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    loaded = Path(probe.stdout.strip()).resolve()
    expected = (REPO_ROOT / "shared" / "sdlc_close.py").resolve()
    assert loaded == expected
