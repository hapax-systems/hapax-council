"""Tests for cc-task audio-audit-O3b-usb-bandwidth-preflight-udev-hook.

Pin the script via synthetic /sys/kernel/debug/usb/devices fixtures.
Tests run on any platform with awk + bash; no real USB hardware needed.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "usb-bandwidth-preflight.sh"
UDEV_RULE = REPO_ROOT / "config" / "udev" / "rules.d" / "55-hapax-l12-bandwidth-preflight.rules"


def _devices_fixture(bus_to_pct: dict[int, int]) -> str:
    """Build a synthetic /sys/kernel/debug/usb/devices excerpt with one
    controller line + one bandwidth line per bus."""
    lines: list[str] = []
    for bus, pct in bus_to_pct.items():
        # T: line establishes the current bus.
        lines.append(f"T:  Bus={bus:02d} Lev=00 Prnt=00 Port=00 Cnt=00 Dev#=  1 Spd=480 MxCh= 8")
        # B: line carries Alloc=N/800 us ( P%) — preflight reads the percent.
        # Alloc value is illustrative only; the script reads the pct in parens.
        lines.append(f"B:  Alloc= {pct * 8:>3}/800 us ({pct:>2}%), #Int=  0, #Iso=  0")
    return "\n".join(lines) + "\n"


def _run(
    tmp_path: Path,
    fixture: str,
    *,
    warn_pct: int = 80,
    device_name: str | None = None,
) -> subprocess.CompletedProcess[str]:
    devices = tmp_path / "usb-devices"
    devices.write_text(fixture)
    textfile_dir = tmp_path / "metrics"
    args = [
        str(SCRIPT),
        "--usb-devices",
        str(devices),
        "--warn-pct",
        str(warn_pct),
        "--textfile-dir",
        str(textfile_dir),
    ]
    if device_name:
        args.extend(["--device-name", device_name])
    return subprocess.run(args, capture_output=True, text=True, timeout=10)


class TestScriptShape:
    def test_script_executable(self) -> None:
        assert SCRIPT.is_file()
        assert SCRIPT.stat().st_mode & stat.S_IXUSR

    def test_bash_syntax_clean(self) -> None:
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_help_exits_zero(self, tmp_path: Path) -> None:
        result = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0
        assert result.stdout.strip(), "--help produced empty output"


class TestExitCodesMatchAcceptanceCriteria:
    def test_under_threshold_exits_zero(self, tmp_path: Path) -> None:
        fixture = _devices_fixture({1: 30, 2: 60})
        result = _run(tmp_path, fixture, warn_pct=80)
        assert result.returncode == 0, result.stderr

    def test_at_threshold_exits_two(self, tmp_path: Path) -> None:
        """80% with --warn-pct=80 is at-or-above; must trigger the warn path."""
        fixture = _devices_fixture({1: 80})
        result = _run(tmp_path, fixture, warn_pct=80)
        assert result.returncode == 2

    def test_above_threshold_exits_two(self, tmp_path: Path) -> None:
        fixture = _devices_fixture({1: 50, 2: 92})
        result = _run(tmp_path, fixture, warn_pct=80)
        assert result.returncode == 2
        assert "SATURATED" in result.stderr

    def test_missing_devices_file_exits_three(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [
                str(SCRIPT),
                "--usb-devices",
                str(tmp_path / "does-not-exist"),
                "--warn-pct",
                "80",
                "--textfile-dir",
                str(tmp_path / "metrics"),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 3
        assert "cannot read" in result.stderr


class TestPrometheusTextfileShape:
    def test_textfile_emits_per_bus_pct(self, tmp_path: Path) -> None:
        fixture = _devices_fixture({1: 30, 2: 60})
        _run(tmp_path, fixture, warn_pct=80)
        textfile = tmp_path / "metrics" / "hapax_usb_isoc_bw.prom"
        assert textfile.exists()
        content = textfile.read_text()
        assert 'hapax_usb_isoc_bw_pct{hc="1"} 30' in content
        assert 'hapax_usb_isoc_bw_pct{hc="2"} 60' in content
        assert "# HELP hapax_usb_isoc_bw_pct" in content
        assert "# TYPE hapax_usb_isoc_bw_pct gauge" in content

    def test_textfile_emits_warn_threshold(self, tmp_path: Path) -> None:
        fixture = _devices_fixture({1: 30})
        _run(tmp_path, fixture, warn_pct=75)
        textfile = tmp_path / "metrics" / "hapax_usb_isoc_bw.prom"
        content = textfile.read_text()
        assert "hapax_usb_isoc_bw_warn_threshold_pct 75" in content


class TestUdevRule:
    def test_udev_rule_exists(self) -> None:
        assert UDEV_RULE.is_file()

    def test_udev_rule_matches_l12(self) -> None:
        content = UDEV_RULE.read_text()
        assert "0a4a" in content, "udev rule must match SSL idVendor 0a4a"
        assert "12c0" in content, "udev rule must match L-12 idProduct 12c0"
        assert 'ACTION=="add"' in content
        assert "RUN+=" in content
        assert "usb-bandwidth-preflight.sh" in content


class TestThresholdMath:
    """Pin the warn-pct comparison: Alloc% > warn fires; Alloc% ≤ warn passes."""

    def test_just_below_threshold_passes(self, tmp_path: Path) -> None:
        fixture = _devices_fixture({1: 79})
        result = _run(tmp_path, fixture, warn_pct=80)
        assert result.returncode == 0

    def test_at_threshold_warns(self, tmp_path: Path) -> None:
        """80% with --warn-pct=80 is at-or-above; spec says warn path fires."""
        fixture = _devices_fixture({1: 80})
        result = _run(tmp_path, fixture, warn_pct=80)
        assert result.returncode == 2

    def test_only_worst_bus_drives_exit(self, tmp_path: Path) -> None:
        """Three buses, two below threshold + one above — must exit 2."""
        fixture = _devices_fixture({1: 10, 2: 30, 3: 95})
        result = _run(tmp_path, fixture, warn_pct=80)
        assert result.returncode == 2
        # Worst bus should be reported.
        assert "bus 3" in result.stderr.lower() or "bus=3" in result.stderr.lower()
