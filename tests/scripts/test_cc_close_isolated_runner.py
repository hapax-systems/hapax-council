"""cc-close must load the checkout under python -I, not the source-activation pin.

Worktree `.venv` is a symlink onto a pinned release. `python -I -m shared.sdlc_close`
therefore imports that pin and close snapshots cache/claim-publications while
cc-claim (same worktree, stdin runner with sys.path.insert) writes Gate 0B
journals. The wrapper has to inject SCRIPT_DIR/.. the way cc-claim already does.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"


def test_cc_close_isolated_python_injects_repo_root() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "sys.path.insert(0, str(repo_root))" in text
    assert "-I -m shared.sdlc_close" not in text
