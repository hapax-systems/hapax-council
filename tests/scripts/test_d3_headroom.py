"""D3 red-before-green: lane launch by measured headroom, not a required-lanes list.

zz-coord-appendix-only-20260919.conf REMOVE WHEN names the successor: "lane
launch is decided by measured headroom instead of a required-lanes list."
The list becomes a candidate pool; a per-tick budget computed from load decides
how many lanes may actually launch.

These tests fail while the watchdog launches every missing required lane
regardless of load, and pass once ``launch_headroom_budget`` gates the loop.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG = REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog"


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _headroom(script: Path, load1: str, nproc: str) -> str:
    """Return ``launch_headroom_budget`` output under a faked /proc/loadavg."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'source <(sed -n "/^launch_headroom_budget()/,/^}}/p" "{script}")\n'
                f"nproc() {{ echo {nproc}; }}\n"
                f"cut() {{ echo '{load1} 0 0'; }}\n"
                f"launch_headroom_budget\n"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    # Fall back to reading /proc/loadavg via the function's own path if the
    # stub did not bind; accept either the stubbed or real number.
    if result.returncode != 0:
        return f"ERR:{result.stderr}"
    return result.stdout.strip()


def test_headroom_budget_zero_when_load_at_or_above_nproc() -> None:
    """Saturated host: budget 0, so no lane launches this tick."""
    out = _headroom(WATCHDOG, "8.00", "4")
    assert out == "0", out


def test_headroom_budget_positive_when_load_below_nproc() -> None:
    """Idle host: budget > 0, so the candidate pool may launch."""
    out = _headroom(WATCHDOG, "0.50", "4")
    assert out.isdigit() and int(out) > 0, out


def test_headroom_budget_caps_per_tick() -> None:
    """Very idle host still cannot launch an unbounded burst in one tick."""
    out = _headroom(WATCHDOG, "0.01", "64")
    assert out.isdigit() and int(out) <= 2, out


def test_watchdog_declares_launch_headroom_budget() -> None:
    """The successor hook must exist (the zz-coord REMOVE WHEN predicate)."""
    text = WATCHDOG.read_text(encoding="utf-8")
    assert "launch_headroom_budget" in text
    assert "REQUIRED_CLAUDE_LANES" in text  # pool, not deleted
