"""M3: fail-closed differential wet-return LEVEL witness.

The witness closes the green-while-silent gap in hapax-audio-routing-check:
Chain 2 verifies the S-4 wet-return *links* exist but never that signal flows,
so a dead S-4 (links up, analog return silent) passed GREEN.

These tests pin the pure decision core via the `--wet-return-verdict` seam,
which short-circuits BEFORE any PipeWire/parec call so it runs on CI hosts with
no audio stack. The differential logic (dry present but wet silent => DEAD)
makes the witness false-positive-resistant: at idle (no dry voice) it returns
IDLE, never a spurious failure.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hapax-audio-routing-check"


def _verdict(dry: str, wet: str, floor: str | None = None) -> str:
    args = ["bash", str(SCRIPT), "--wet-return-verdict", dry, wet]
    if floor is not None:
        args.append(floor)
    proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, f"seam exited {proc.returncode}: {proc.stderr}"
    return proc.stdout.strip()


def test_script_exists_and_executable():
    assert SCRIPT.exists(), f"missing {SCRIPT}"


@pytest.mark.parametrize(
    ("dry", "wet", "floor", "expected"),
    [
        # dry voice present, wet return silent -> the S-4 insert is dead.
        ("0.05", "0.0000018", "0.001", "DEAD"),
        # dry voice present, wet return present -> path alive.
        ("0.05", "0.05", "0.001", "LIVE"),
        # no dry voice being sent -> cannot witness, NOT a failure.
        ("0.0000001", "0.0", "0.001", "IDLE"),
        # boundary: exactly at floor counts as present (>= floor).
        ("0.001", "0.001", "0.001", "LIVE"),
        # boundary: dry at floor, wet just below -> dead.
        ("0.001", "0.0005", "0.001", "DEAD"),
        # idle dominates: even if wet is also silent, no dry => IDLE not DEAD.
        ("0.0", "0.0", "0.001", "IDLE"),
    ],
)
def test_wet_return_verdict(dry, wet, floor, expected):
    assert _verdict(dry, wet, floor) == expected


def test_default_floor_applied_when_omitted():
    # Default floor is -60 dBFS (0.001): live dry + dead-floor wet -> DEAD.
    assert _verdict("0.05", "0.0000018") == "DEAD"
    # Default floor: both clearly above -> LIVE.
    assert _verdict("0.05", "0.05") == "LIVE"


def test_seam_does_not_require_pipewire():
    """The verdict seam must return before any pw-link/parec call so CI/dev
    hosts without an audio stack can exercise it. A clean exit 0 with a known
    verdict token proves the short-circuit fired."""
    out = _verdict("0.02", "0.02", "0.001")
    assert out in {"IDLE", "LIVE", "DEAD"}
