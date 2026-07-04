from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-dispatch-redemption-service-install"
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-dispatch-redemption.service"
UNIT_NAME = "hapax-dispatch-redemption.service"


def test_dispatch_redemption_service_installer_dry_run_names_activation_steps(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [str(SCRIPT), "--dry-run", "--root", str(tmp_path / "root")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"would install {tmp_path / 'root'}/etc/systemd/system/{UNIT_NAME}" in result.stdout
    assert "systemctl daemon-reload" in result.stdout
    assert f"systemctl enable {UNIT_NAME}" in result.stdout
    assert f"systemctl restart {UNIT_NAME}" in result.stdout


def test_dispatch_redemption_service_installer_root_fixture_install_and_check(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"

    install_result = subprocess.run(
        [str(SCRIPT), "--install", "--root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert install_result.returncode == 0, install_result.stderr
    installed = root / "etc" / "systemd" / "system" / UNIT_NAME
    assert installed.read_text(encoding="utf-8") == UNIT.read_text(encoding="utf-8")
    assert "root fixture mode: skipped systemctl activation and receipt" in install_result.stdout

    check_result = subprocess.run(
        [str(SCRIPT), "--check", "--root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert check_result.returncode == 0, check_result.stderr
    assert f"ok   {installed}" in check_result.stdout
