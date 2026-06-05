from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess
from collections.abc import Mapping

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hapax-storage-pressure-check"
SERVICE = REPO / "systemd" / "units" / "hapax-storage-pressure-check.service"


def _gib(value: float) -> int:
    return int(value * 1024 * 1024 * 1024)


def _fixture(
    *,
    metadata_size_gib: float,
    metadata_used_gib: float,
    unallocated_gib: float,
    global_reserve_used_bytes: int = 0,
    metadata_ratio: float = 2.0,
) -> str:
    metadata_used_pct = metadata_used_gib * 100 / metadata_size_gib
    return f"""Overall:
    Device size:                    {_gib(928)}
    Device allocated:               {_gib(928 - unallocated_gib)}
    Device unallocated:             {_gib(unallocated_gib)}
    Device missing:                 0
    Device slack:                   0
    Used:                           {_gib(372)}
    Free (estimated):               {_gib(unallocated_gib + 120)}    (min: {_gib(unallocated_gib + 20)})
    Free (statfs, df):              {_gib(unallocated_gib + 120)}
    Data ratio:                     1.00
    Metadata ratio:                 {metadata_ratio:.2f}
    Global reserve:                 {_gib(0.5)}    (used: {global_reserve_used_bytes})
    Multiple profiles:              no

Data,single: Size:{_gib(507.01)}, Used:{_gib(181.17)} (35.73%)

Metadata,DUP: Size:{_gib(metadata_size_gib)}, Used:{_gib(metadata_used_gib)} ({metadata_used_pct:.2f}%)

System,DUP: Size:{_gib(0.03)}, Used:114688 (0.34%)
"""


def _write_executable(path: pathlib.Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_check(
    tmp_path: pathlib.Path,
    fixture: str,
    *,
    root_pct: int = 41,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fixture_path = tmp_path / "btrfs.txt"
    fixture_path.write_text(fixture)
    report_path = tmp_path / "storage-pressure-status.md"

    _write_executable(
        bin_dir / "df",
        """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  "--output=pcent /") printf 'Use%%\\n%s%%\\n' "${ROOT_PCT:-41}" ;;
  "--output=avail /"|"-h --output=avail /") printf 'Avail\\n%s\\n' "${ROOT_AVAIL:-553G}" ;;
  "--output=pcent /data") printf 'Use%%\\n%s%%\\n' "${DATA_PCT:-28}" ;;
  "--output=avail /data"|"-h --output=avail /data") printf 'Avail\\n%s\\n' "${DATA_AVAIL:-672G}" ;;
  "--output=pcent /store") printf 'Use%%\\n%s%%\\n' "${STORE_PCT:-16}" ;;
  "--output=avail /store"|"-h --output=avail /store") printf 'Avail\\n%s\\n' "${STORE_AVAIL:-736G}" ;;
  *) printf 'unsupported df args: %s\\n' "$*" >&2; exit 1 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "btrfs",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" != "filesystem usage -b /" ]]; then
  printf 'unsupported btrfs args: %s\\n' "$*" >&2
  exit 1
fi
cat "$BTRFS_FIXTURE"
""",
    )
    _write_executable(bin_dir / "logger", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "notify-send", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "BTRFS_FIXTURE": str(fixture_path),
            "HAPAX_STORAGE_PRESSURE_NOTIFY": "0",
            "HAPAX_STORAGE_PRESSURE_REPORT": str(report_path),
            "ROOT_PCT": str(root_pct),
        }
    )
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    report = report_path.read_text() if report_path.exists() else ""
    return result, report


def test_ok_when_capacity_and_metadata_have_headroom(tmp_path: pathlib.Path) -> None:
    result, report = _run_check(
        tmp_path,
        _fixture(metadata_size_gib=40, metadata_used_gib=20, unallocated_gib=240),
    )

    assert result.returncode == 0
    assert "severity=ok" in result.stdout
    assert "Severity: `ok`" in report
    assert "ok: thresholds are not crossed" in report


def test_warns_for_absolute_metadata_context(tmp_path: pathlib.Path) -> None:
    result, report = _run_check(
        tmp_path,
        _fixture(metadata_size_gib=100, metadata_used_gib=90, unallocated_gib=240),
    )

    assert result.returncode == 0
    assert "severity=warning" in result.stdout
    assert "root Btrfs metadata is 90.00GiB used" in report
    assert "critical:" not in report


def test_2026_06_04_high_metadata_high_headroom_is_not_critical(
    tmp_path: pathlib.Path,
) -> None:
    result, report = _run_check(
        tmp_path,
        _fixture(metadata_size_gib=97.00, metadata_used_gib=95.04, unallocated_gib=226.35),
    )

    assert result.returncode == 0
    assert "severity=warning" in result.stdout
    assert "metadata_used_pct=97.98%" in result.stdout
    assert "unallocated=226.35GiB" in result.stdout
    assert "Severity: `critical`" not in report
    assert "absolute metadata size alone is context" in report


def test_critical_for_low_root_capacity(tmp_path: pathlib.Path) -> None:
    result, report = _run_check(
        tmp_path,
        _fixture(metadata_size_gib=40, metadata_used_gib=20, unallocated_gib=240),
        root_pct=91,
    )

    assert result.returncode == 0
    assert "severity=critical" in result.stdout
    assert "critical: root is 91% used" in report


def test_critical_for_high_metadata_percent_plus_low_unallocated(
    tmp_path: pathlib.Path,
) -> None:
    result, report = _run_check(
        tmp_path,
        _fixture(metadata_size_gib=100, metadata_used_gib=98, unallocated_gib=8),
    )

    assert result.returncode == 0
    assert "severity=critical" in result.stdout
    assert "critical: root Btrfs metadata is 98.00% used with 8.00GiB" in report


def test_critical_for_global_reserve_use(tmp_path: pathlib.Path) -> None:
    result, report = _run_check(
        tmp_path,
        _fixture(
            metadata_size_gib=40,
            metadata_used_gib=20,
            unallocated_gib=240,
            global_reserve_used_bytes=_gib(0.25),
        ),
    )

    assert result.returncode == 0
    assert "severity=critical" in result.stdout
    assert "critical: root Btrfs global reserve is using 0.25GiB" in report


def test_parse_failure_is_critical_and_writes_report(tmp_path: pathlib.Path) -> None:
    result, report = _run_check(tmp_path, "not btrfs usage\n")

    assert result.returncode == 2
    assert "severity=critical" in result.stdout
    assert "could not parse root Btrfs usage" in result.stderr
    assert "Severity: `critical`" in report
    assert "Raw Btrfs Usage" in report


def test_report_includes_btrfs_root_cause_fields(tmp_path: pathlib.Path) -> None:
    result, report = _run_check(
        tmp_path,
        _fixture(metadata_size_gib=97.00, metadata_used_gib=95.04, unallocated_gib=226.35),
    )

    assert result.returncode == 0
    for expected in [
        "Metadata logical used percent",
        "Metadata raw allocation estimate",
        "Device unallocated headroom",
        "Global reserve used",
    ]:
        assert expected in report


def test_timer_path_has_timeout_and_no_unbounded_hotspot_scans() -> None:
    script_text = SCRIPT.read_text()
    service_text = SERVICE.read_text()

    assert "TimeoutStartSec=60" in service_text
    assert not re.search(r"(^|[;&|({]\s*)(find|du|mc)\b", script_text, re.MULTILINE)
