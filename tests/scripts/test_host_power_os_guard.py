"""Tests for OS-level host power guard artifacts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SUDOERS = REPO_ROOT / "config" / "sudoers.d" / "zz-hapax-host-power-deny"
POLKIT = REPO_ROOT / "config" / "polkit-1" / "rules.d" / "49-hapax-host-power-deny.rules"
INSTALLER = REPO_ROOT / "scripts" / "install-host-power-os-guard"


def test_sudoers_denies_incident_shape() -> None:
    text = SUDOERS.read_text()
    assert "sort after broad NOPASSWD drop-ins" in text
    assert "/usr/bin/systemctl *poweroff*" in text
    assert "/usr/bin/poweroff" in text
    assert "hapax ALL=(root) ALL, !HAPAX_HOST_POWER" in text
    assert "hapax ALL=(ALL:ALL) ALL, !HAPAX_HOST_POWER" in text


def test_sudoers_covers_power_verbs() -> None:
    text = SUDOERS.read_text()
    for verb in (
        "poweroff",
        "reboot",
        "halt",
        "shutdown",
        "kexec",
        "suspend",
        "hibernate",
        "hybrid-sleep",
        "suspend-then-hibernate",
    ):
        assert verb in text


def test_sudoers_syntax_valid_when_visudo_available() -> None:
    if shutil.which("visudo") is None:
        return
    result = subprocess.run(
        ["visudo", "-cf", str(SUDOERS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_polkit_denies_login1_power_actions_for_hapax() -> None:
    text = POLKIT.read_text()
    assert 'subject.user !== "hapax"' in text
    assert "polkit.Result.NO" in text
    for action in (
        "org.freedesktop.login1.power-off",
        "org.freedesktop.login1.power-off-multiple-sessions",
        "org.freedesktop.login1.power-off-ignore-inhibit",
        "org.freedesktop.login1.reboot",
        "org.freedesktop.login1.reboot-ignore-inhibit",
        "org.freedesktop.login1.halt",
        "org.freedesktop.login1.suspend",
        "org.freedesktop.login1.hibernate",
        "org.freedesktop.login1.set-reboot-to-firmware-setup",
    ):
        assert action in text


def test_installer_check_mode_validates_artifacts() -> None:
    result = subprocess.run(
        ["bash", str(INSTALLER), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "host power OS guard check complete" in result.stdout


def test_installer_uses_safe_install_modes() -> None:
    text = INSTALLER.read_text()
    assert 'install -o root -g root -m 0440 "$SUDOERS_SRC" "$SUDOERS_DEST"' in text
    assert 'LEGACY_SUDOERS_DEST="/etc/sudoers.d/99-hapax-host-power-deny"' in text
    assert 'install -o root -g "$polkit_group" -m 0640 "$POLKIT_SRC" "$POLKIT_DEST"' in text
    assert "systemctl try-reload-or-restart polkit.service" in text
    assert "sudo -n -l /usr/bin/systemctl poweroff" in text
    assert "pkcheck --action-id org.freedesktop.login1.power-off" in text
