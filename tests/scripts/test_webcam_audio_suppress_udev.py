"""Tests for cc-task audio-audit-O1-webcam-audio-suppress.

Pin the udev rule shape (vendor/product IDs of the 3 webcam variants,
PULSE_IGNORE=1, audio-class match) and the installer script. The
``pactl list cards short`` regression assertion lives in a separate
hardware-mode probe (operator-runnable); it's not exercised at CI time
because CI doesn't have webcams or PulseAudio.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UDEV_RULE = REPO_ROOT / "config" / "udev" / "rules.d" / "56-hapax-webcam-audio-suppress.rules"
INSTALLER = REPO_ROOT / "scripts" / "install-webcam-audio-suppress-udev.sh"

# (vendor, product, label) — exhaustive list of webcam USB IDs the operator
# has connected (per `lsusb` capture 2026-05-03). The test pins all three.
EXPECTED_DEVICES: list[tuple[str, str, str]] = [
    ("046d", "085e", "BRIO Ultra HD Webcam"),
    ("046d", "08e5", "C920 PRO HD Webcam"),
    ("046d", "082d", "HD Pro Webcam C920"),
]


class TestUdevRuleShape:
    def test_rule_exists(self) -> None:
        assert UDEV_RULE.is_file()

    @pytest.mark.parametrize(("vendor", "product", "label"), EXPECTED_DEVICES)
    def test_each_device_id_has_rule(self, vendor: str, product: str, label: str) -> None:
        content = UDEV_RULE.read_text()
        assert vendor in content, f"vendor {vendor} ({label}) missing from udev rule"
        assert product in content, f"product {product} ({label}) missing from udev rule"

    def test_rule_uses_pulse_ignore(self) -> None:
        """Each rule line must set PULSE_IGNORE=1 — that's the actual
        suppression mechanism. Without it, the udev rule is a no-op."""
        content = UDEV_RULE.read_text()
        # PULSE_IGNORE must appear once per device (3 devices = 3 occurrences).
        assert content.count('ENV{PULSE_IGNORE}="1"') == len(EXPECTED_DEVICES)

    def test_rule_matches_audio_interface_class_only(self) -> None:
        """bInterfaceClass==01 is USB-Audio. The rule must scope to this
        interface only — otherwise the V4L2 video interface (class 0e) would
        also be ignored, breaking studio-compositor ingest."""
        content = UDEV_RULE.read_text()
        assert content.count('ATTR{bInterfaceClass}=="01"') == len(EXPECTED_DEVICES)
        # Negative: the rule must NOT broadly match all interface classes.
        assert 'ATTR{bInterfaceClass}=="0e"' not in content
        assert 'ATTR{bInterfaceClass}=="0E"' not in content

    def test_rule_only_matches_add_action(self) -> None:
        """remove/change actions don't need handling — PULSE_IGNORE is read
        at registration time. Pin to add only so the rule doesn't fire on
        unplug-replug churn."""
        content = UDEV_RULE.read_text()
        assert content.count('ACTION=="add"') == len(EXPECTED_DEVICES)
        assert 'ACTION=="remove"' not in content

    def test_rule_carries_id_hapax_audio_suppressed_marker(self) -> None:
        """ENV marker lets `udevadm info /dev/...` report which devices were
        suppressed by this rule, so the operator can debug surprising
        absences from `pactl list cards short`."""
        content = UDEV_RULE.read_text()
        for label_short in ("brio", "c920-pro", "c920-hd-pro"):
            assert f'ENV{{ID_HAPAX_AUDIO_SUPPRESSED}}="{label_short}"' in content, (
                f"missing ID_HAPAX_AUDIO_SUPPRESSED={label_short!r} marker"
            )


class TestInstallerScript:
    def test_installer_exists_and_executable(self) -> None:
        assert INSTALLER.is_file()
        assert INSTALLER.stat().st_mode & stat.S_IXUSR

    def test_installer_bash_syntax_clean(self) -> None:
        result = subprocess.run(["bash", "-n", str(INSTALLER)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_installer_references_correct_destination(self) -> None:
        """The dest path is what `pactl list cards short` operators will check;
        any silent rename here would break the verification flow."""
        content = INSTALLER.read_text()
        assert "/etc/udev/rules.d/56-hapax-webcam-audio-suppress.rules" in content

    def test_installer_reloads_and_triggers_udev(self) -> None:
        """Both steps are required; without trigger the rule won't fire on
        already-enumerated devices until next replug."""
        content = INSTALLER.read_text()
        assert "udevadm control --reload" in content
        assert "udevadm trigger" in content
