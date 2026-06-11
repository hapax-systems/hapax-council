"""Tests for scripts/hapax-systemd-inventory-reconcile."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-systemd-inventory-reconcile"


def _load_module():
    loader = SourceFileLoader("hapax_systemd_inventory_reconcile", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _completed(
    cmd: Sequence[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def test_collect_tracked_units_uses_git_tracked_install_visible_scope(tmp_path: Path) -> None:
    module = _load_module()

    def runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        assert list(cmd[:3]) == ["git", "-C", str(tmp_path)]
        return _completed(
            cmd,
            stdout="\n".join(
                [
                    "systemd/units/matched.service",
                    "systemd/units/tracked-only.timer",
                    "systemd/units/ignore.conf",
                    "systemd/units-pi6/pi-only.service",
                ]
            ),
        )

    tracked = module.collect_tracked_units(tmp_path, runner=runner)

    assert sorted(tracked) == ["matched.service", "tracked-only.timer"]
    assert tracked["matched.service"].path == "systemd/units/matched.service"
    assert tracked["tracked-only.timer"].kind == "timer"


def test_reconciliation_reports_matched_tracked_only_and_runtime_only(tmp_path: Path) -> None:
    module = _load_module()

    def tracked_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _completed(
            cmd,
            stdout="\n".join(
                [
                    "systemd/units/matched.service",
                    "systemd/units/tracked-only.timer",
                ]
            ),
        )

    def runtime_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = " ".join(cmd)
        if "list-unit-files" in command:
            return _completed(
                cmd,
                stdout="\n".join(
                    [
                        "matched.service enabled",
                        "runtime-only.service generated",
                    ]
                ),
            )
        if "list-units" in command:
            return _completed(
                cmd,
                stdout="\n".join(
                    [
                        "matched.service loaded active running Matched Service",
                        "runtime-only.service loaded inactive dead Runtime Only",
                    ]
                ),
            )
        raise AssertionError(command)

    report = module.build_report(
        tmp_path,
        tracked_runner=tracked_runner,
        runtime_runner=runtime_runner,
    )

    assert report.tracked_count == 2
    assert report.runtime_count == 2
    assert report.matched_count == 1
    assert report.tracked_only_count == 1
    assert report.runtime_only_count == 1
    assert report.tracked_by_kind == {"service": 1, "timer": 1}
    assert report.runtime_by_kind == {"service": 2}

    tracked_only = report.differences["tracked_only"][0]
    runtime_only = report.differences["runtime_only"][0]
    assert tracked_only["name"] == "tracked-only.timer"
    assert tracked_only["source_path"] == "systemd/units/tracked-only.timer"
    assert runtime_only["name"] == "runtime-only.service"
    assert runtime_only["unit_file_state"] == "generated"
    assert runtime_only["active_state"] == "inactive"

    matched = [row for row in report.units if row["status"] == "matched"]
    assert matched[0]["name"] == "matched.service"
    assert "git -C" in report.tracked_command
    assert any("systemctl --user list-unit-files" in cmd for cmd in report.runtime_commands)


def test_runtime_collection_records_unavailable_systemctl_without_mutation() -> None:
    module = _load_module()
    calls: list[tuple[str, ...]] = []

    def runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(cmd))
        return _completed(cmd, stderr="Failed to connect to bus", returncode=1)

    collection = module.collect_runtime_units(runner=runner)

    assert collection.available is False
    assert collection.units == {}
    assert "Failed to connect to bus" in collection.error
    assert calls == [
        (
            "systemctl",
            "--user",
            "list-unit-files",
            "--type=service,timer",
            "--no-legend",
            "--no-pager",
        )
    ]
    assert all("enable" not in call and "restart" not in call for cmd in calls for call in cmd)
