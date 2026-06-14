"""The broadcast-master loudness SSOT↔conf drift guard."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-broadcast-master-loudness-ssot.py"

_OK_CONF = """
filter.graph = {
    nodes = [
        { control = {
            "Input gain (dB)" = 16.0
            "Limit (dB)"      = -1.0
            "Release time (s)" = 0.05
        } }
    ]
}
"""


def _run(conf_text: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    conf = tmp_path / "broadcast-master.conf"
    conf.write_text(conf_text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--conf", str(conf)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_guard_passes_on_ssot_values(tmp_path: Path) -> None:
    result = _run(_OK_CONF, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "matches SSOT" in result.stdout


def test_guard_flags_makeup_drift(tmp_path: Path) -> None:
    # The actual failure mode: a +6 makeup deployed against SSOT 16.
    result = _run(_OK_CONF.replace("16.0", "6.0"), tmp_path)
    assert result.returncode == 1
    assert "Input gain (dB)" in result.stderr
    assert "6.0" in result.stderr


def test_guard_ignores_stale_comment_lines(tmp_path: Path) -> None:
    # A stale comment carrying the old 14.0 must NOT trip the guard when the real
    # quoted control is the SSOT 16.0.
    conf = "#   Input gain (dB)   = 14.0   (stale recalibration note)\n" + _OK_CONF
    result = _run(conf, tmp_path)
    assert result.returncode == 0, result.stderr


def test_guard_flags_missing_control(tmp_path: Path) -> None:
    result = _run(_OK_CONF.replace('"Limit (dB)"      = -1.0\n', ""), tmp_path)
    assert result.returncode == 1
    assert "Limit (dB)" in result.stderr and "MISSING" in result.stderr
