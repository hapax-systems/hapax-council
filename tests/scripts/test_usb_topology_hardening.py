"""USB S-4/L-12 topology hardening contract tests."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
WITNESS = REPO_ROOT / "scripts" / "hapax-usb-topology-witness"
INSTALLER = REPO_ROOT / "scripts" / "install-usb-topology-hardening.sh"
WATCHDOG = REPO_ROOT / "scripts" / "hapax-usb-bandwidth-watchdog"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "usb-s4-l12-topology-hardening.md"
S4_UDEV = REPO_ROOT / "config" / "udev" / "rules.d" / "90-hapax-s4-composite.rules"
USB_NOAUTOSUSPEND_UDEV = (
    REPO_ROOT / "config" / "udev" / "rules.d" / "50-hapax-usb-audio-video-noautosuspend.rules"
)
MIDI_ROUTE = REPO_ROOT / "systemd" / "units" / "midi-route.service"
USB_POLICY = REPO_ROOT / "config" / "usb-topology-policy.json"
USB_WITNESS_SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-usb-topology-witness.service"

S4_SINK = "alsa_output.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-output"
S4_SOURCE = "alsa_input.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-input"
L12_SINK = (
    "alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"
)
L12_SOURCE = (
    "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"
)


def load_witness_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_usb_topology_witness", str(WITNESS))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise AssertionError("could not load hapax-usb-topology-witness spec")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def known_good_snapshot() -> dict[str, object]:
    return {
        "kernel": {"usbfs_memory_mb": "128", "uvcvideo_quirks": "256"},
        "s4": {
            "device": "3-1.5",
            "sysfs_path": "/sys/bus/usb/devices/3-1.5",
            "path": "pci-0000:71:00.0-usb-0:1.5",
            "serial": "fedcba9876543220",
            "vendor_id": "1d6b",
            "product_id": "0104",
            "product": "S-4",
            "manufacturer": "Torso Electronics",
            "stable_id": "usb:1d6b:0104:fedcba9876543220",
            "power_control": "on",
            "block": {
                "node": "/dev/disk/by-id/usb-Linux_File-Stor_Gadget_fedcba9876543220-0:0",
                "devname": "/dev/sdz",
                "match_source": "dev-disk-by-id",
                "udisks_ignore": "1",
                "modemmanager_ignore": "1",
                "id_serial_short": "fedcba9876543220",
                "id_vendor_id": "1d6b",
                "id_model_id": "0104",
            },
            "net": {
                "interface": "enp113s0u1u5",
                "nm_unmanaged": "1",
                "modemmanager_ignore": "1",
                "nmcli_state": "unmanaged",
            },
        },
        "l12": {
            "device": "3-1.1.2.2",
            "sysfs_path": "/sys/bus/usb/devices/3-1.1.2.2",
            "path": "pci-0000:71:00.0-usb-0:1.1.2.2",
            "serial": "8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF",
            "vendor_id": "1686",
            "product_id": "03d5",
            "product": "L-12",
            "manufacturer": "ZOOM Corporation",
            "stable_id": "usb:1686:03d5:8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF",
            "default_sink": L12_SINK,
            "default_source": L12_SOURCE,
        },
        "sinks": [S4_SINK, L12_SINK],
        "sources": [S4_SOURCE, L12_SOURCE],
        "alsa_playback": "card 11: S4 [S-4], device 0: USB Audio [USB Audio]",
        "alsa_capture": "card 11: S4 [S-4], device 0: USB Audio [USB Audio]",
        "midi_clients": "client 60: 'S-4' [type=kernel,card=11]",
        "amidi_ports": "IO  hw:11,0,0  S-4 MIDI 1",
        "cameras": [
            {
                "serial": "5342C819",
                "path": "pci-0000:73:00.4-usb-0:2:1.0",
                "on_caldigit_audio_controller": "false",
            }
        ],
    }


def run_witness(tmp_path: Path, snapshot: dict[str, object]) -> subprocess.CompletedProcess[str]:
    fixture = tmp_path / "snapshot.json"
    status = tmp_path / "status.json"
    fixture.write_text(json.dumps(snapshot), encoding="utf-8")
    return subprocess.run(
        [str(WITNESS), "--fixture", str(fixture), "--status-path", str(status)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_witness_accepts_known_good_snapshot(tmp_path: Path) -> None:
    result = run_witness(tmp_path, known_good_snapshot())

    assert result.returncode == 0, result.stdout
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["issues"] == []
    assert status["s4"]["block"]["udisks_ignore"] == "1"
    assert status["s4"]["net"]["nmcli_state"] == "unmanaged"


def test_witness_accepts_current_nested_s4_caldigit_path(tmp_path: Path) -> None:
    snapshot = known_good_snapshot()
    snapshot["s4"]["device"] = "3-1.1.1.3"
    snapshot["s4"]["path"] = "pci-0000:71:00.0-usb-0:1.1.1.3"

    result = run_witness(tmp_path, snapshot)

    assert result.returncode == 0, result.stdout
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["issues"] == []


def test_witness_ignores_s4_bus_path_drift_when_stable_attrs_match(tmp_path: Path) -> None:
    """Path drift is diagnostic only, not a warning or failure.

    S-4 routing is pinned by serial+vid:pid via the persistent ALSA
    card-id rules (PR #2222). Sink/source identity is what drives
    routing, so a fresh enumeration path (e.g. moving between CalDigit
    ports) should not flap the witness into a failed or degraded unit
    state. The current bus path remains in the JSON snapshot for
    diagnostics.
    """
    snapshot = known_good_snapshot()
    snapshot["s4"]["device"] = "1-9"
    snapshot["s4"]["path"] = "pci-0000:09:00.0-usb-0:9"

    result = run_witness(tmp_path, snapshot)

    assert result.returncode == 0, result.stdout
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["s4"]["stable_id"] == "usb:1d6b:0104:fedcba9876543220"
    assert status["s4"]["path"] == "pci-0000:09:00.0-usb-0:9"
    assert not any(warning.startswith("s4_path_drift") for warning in status["warnings"])
    assert not any(issue.startswith("s4_path_drift") for issue in status["issues"])


def test_witness_accepts_post_128gb_l12_path(tmp_path: Path) -> None:
    snapshot = known_good_snapshot()
    snapshot["l12"]["device"] = "9-1"
    snapshot["l12"]["path"] = "pci-0000:74:00.0-usb-0:1"

    result = run_witness(tmp_path, snapshot)

    assert result.returncode == 0, result.stdout
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["l12"]["stable_id"] == "usb:1686:03d5:8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF"
    assert not any(warning.startswith("l12_path_drift") for warning in status["warnings"])


def test_s4_block_policy_falls_back_to_udev_attrs_without_by_id(
    monkeypatch, tmp_path: Path
) -> None:
    witness = load_witness_module()
    block_root = tmp_path / "sys" / "class" / "block"
    block_dev = block_root / "sdz"
    block_dev.mkdir(parents=True)

    monkeypatch.setattr(witness.glob, "glob", lambda _pattern: [])

    def fake_udev_props_for_path(path: Path) -> dict[str, str]:
        assert path == block_dev
        return {
            "DEVNAME": "/dev/sdz",
            "ID_SERIAL_SHORT": "fedcba9876543220",
            "ID_VENDOR_ID": "1d6b",
            "ID_MODEL_ID": "0104",
            "UDISKS_IGNORE": "1",
            "UDISKS_PRESENTATION_HIDE": "1",
            "ID_MM_DEVICE_IGNORE": "1",
        }

    monkeypatch.setattr(witness, "udev_props_for_path", fake_udev_props_for_path)

    policy = witness.s4_block_policy(block_root=block_root)

    assert policy["match_source"] == "udev-attrs"
    assert policy["node"] == ""
    assert policy["devname"] == "/dev/sdz"
    assert policy["id_serial_short"] == "fedcba9876543220"
    assert policy["udisks_ignore"] == "1"


def test_witness_reports_kernel_policy_and_camera_drift(tmp_path: Path) -> None:
    snapshot = known_good_snapshot()
    snapshot["kernel"] = {"usbfs_memory_mb": "16", "uvcvideo_quirks": "0"}
    snapshot["cameras"] = [
        {
            "serial": "9726C031",
            "path": "pci-0000:71:00.0-usb-0:1.4:1.0",
            "on_caldigit_audio_controller": "true",
        }
    ]

    result = run_witness(tmp_path, snapshot)

    assert result.returncode == 2
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert "kernel_usbfs_memory_mb_drift:16" in status["issues"]
    assert "kernel_uvcvideo_quirks_drift:0" in status["issues"]
    assert any(issue.startswith("camera_on_caldigit:9726C031") for issue in status["issues"])


def test_witness_demotes_configured_s4_absence_and_c920_placement(tmp_path: Path) -> None:
    snapshot = known_good_snapshot()
    snapshot["s4"] = {
        "device": "",
        "path": "",
        "power_control": "",
        "block": {
            "node": "",
            "udisks_ignore": "",
            "modemmanager_ignore": "",
        },
        "net": {
            "interface": "",
            "nm_unmanaged": "",
            "modemmanager_ignore": "",
            "nmcli_state": "",
        },
    }
    snapshot["sinks"] = [L12_SINK]
    snapshot["sources"] = [L12_SOURCE]
    snapshot["alsa_playback"] = ""
    snapshot["alsa_capture"] = ""
    snapshot["midi_clients"] = ""
    snapshot["amidi_ports"] = ""
    snapshot["cameras"] = [
        {
            "serial": "86B6B75F",
            "path": "pci-0000:71:00.0-usb-0:1.1.2.2:1.0",
            "on_caldigit_audio_controller": "true",
        }
    ]

    result = run_witness(tmp_path, snapshot)

    assert result.returncode == 0, result.stdout
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["issues"] == []
    assert "s4_usb_missing_known_absence:hardware_fault_diagnosed_2026-05-08" in status["warnings"]
    assert any(
        warning.startswith("camera_on_caldigit_accepted:86B6B75F") for warning in status["warnings"]
    )
    assert "cameras_off_caldigit=0" in result.stdout


def test_witness_keeps_l12_absence_hard_even_with_policy(tmp_path: Path) -> None:
    snapshot = known_good_snapshot()
    snapshot["l12"] = {
        "device": "",
        "path": "",
        "power_control": "",
        "default_sink": "",
        "default_source": "",
    }
    snapshot["sinks"] = [S4_SINK]
    snapshot["sources"] = [S4_SOURCE]

    result = run_witness(tmp_path, snapshot)

    assert result.returncode == 2
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert "l12_usb_missing" in status["issues"]
    assert "l12_sink_missing" in status["issues"]
    assert "l12_source_missing" in status["issues"]


def test_copied_witness_uses_installed_policy_env_path(tmp_path: Path) -> None:
    copied = tmp_path / "home" / ".local" / "bin" / "hapax-usb-topology-witness"
    policy = tmp_path / "home" / ".config" / "hapax" / "usb-topology-policy.json"
    copied.parent.mkdir(parents=True)
    policy.parent.mkdir(parents=True)
    shutil.copy2(WITNESS, copied)
    shutil.copy2(USB_POLICY, policy)

    snapshot = known_good_snapshot()
    snapshot["s4"] = {
        "device": "",
        "path": "",
        "power_control": "",
        "block": {"node": "", "udisks_ignore": "", "modemmanager_ignore": ""},
        "net": {
            "interface": "",
            "nm_unmanaged": "",
            "modemmanager_ignore": "",
            "nmcli_state": "",
        },
    }
    snapshot["sinks"] = [L12_SINK]
    snapshot["sources"] = [L12_SOURCE]
    snapshot["alsa_playback"] = ""
    snapshot["alsa_capture"] = ""
    snapshot["midi_clients"] = ""
    snapshot["amidi_ports"] = ""
    fixture = tmp_path / "snapshot.json"
    status = tmp_path / "status.json"
    fixture.write_text(json.dumps(snapshot), encoding="utf-8")

    env = {**os.environ, "HAPAX_USB_TOPOLOGY_POLICY": str(policy)}
    result = subprocess.run(
        [str(copied), "--fixture", str(fixture), "--status-path", str(status)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout
    output = json.loads(status.read_text(encoding="utf-8"))
    assert output["issues"] == []
    assert "s4_usb_missing_known_absence:hardware_fault_diagnosed_2026-05-08" in output["warnings"]


def test_start_user_unit_reports_repair_only_when_start_needed() -> None:
    witness = load_witness_module()
    active = subprocess.CompletedProcess(["systemctl"], 0, "", "")
    inactive = subprocess.CompletedProcess(["systemctl"], 3, "", "")
    started = subprocess.CompletedProcess(["systemctl"], 0, "", "")
    mocked_run = Mock(side_effect=[active, inactive, started])

    with patch.object(witness, "run", mocked_run):
        assert witness.start_user_unit("hapax-audio-router.service") is False
        assert witness.start_user_unit("hapax-usb-router.service") is True

    assert mocked_run.call_args_list[0].args[0] == [
        "systemctl",
        "--user",
        "is-active",
        "--quiet",
        "hapax-audio-router.service",
    ]
    assert mocked_run.call_args_list[1].args[0] == [
        "systemctl",
        "--user",
        "is-active",
        "--quiet",
        "hapax-usb-router.service",
    ]
    assert mocked_run.call_args_list[2].args[0] == [
        "systemctl",
        "--user",
        "start",
        "hapax-usb-router.service",
    ]


def test_installer_dry_run_lists_durable_policy_files(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(INSTALLER),
            "--dry-run",
            "--root",
            str(tmp_path / "root"),
            "--home",
            str(tmp_path / "home"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "/etc/udev/rules.d/90-hapax-s4-composite.rules" in result.stdout
    assert "/etc/NetworkManager/conf.d/90-hapax-s4-unmanaged.conf" in result.stdout
    assert "/etc/modprobe.d/99-hapax-usb-reliability-override.conf" in result.stdout
    assert ".config/hapax/usb-topology-policy.json" in result.stdout
    assert "hapax-usb-topology-witness.timer" in result.stdout
    assert "hapax-usb-reliability.params" in result.stdout
    assert not (tmp_path / "root").exists()


def test_bandwidth_watchdog_uses_dmesg_not_journalctl_follower() -> None:
    text = WATCHDOG.read_text(encoding="utf-8")

    assert "dmesg --follow --decode" in text
    assert "journalctl -k -f" not in text


def test_s4_udev_policy_pins_desktop_probe_suppression() -> None:
    text = S4_UDEV.read_text(encoding="utf-8")

    assert 'ATTR{serial}=="fedcba9876543220"' in text
    assert 'ATTR{power/control}="on"' in text
    assert 'ENV{UDISKS_IGNORE}="1"' in text
    assert 'ENV{ID_MM_DEVICE_IGNORE}="1"' in text
    assert 'ENV{NM_UNMANAGED}="1"' in text


def test_l12_udev_policy_runs_critical_guard_and_hotplug_recovery() -> None:
    noautosuspend = USB_NOAUTOSUSPEND_UDEV.read_text(encoding="utf-8")
    s4_policy = S4_UDEV.read_text(encoding="utf-8")

    assert 'ATTR{idVendor}=="1686"' in noautosuspend
    assert 'ATTR{idProduct}=="03d5"' in noautosuspend
    assert 'ATTR{power/control}="on"' in noautosuspend
    assert 'ATTR{power/autosuspend_delay_ms}="-1"' in noautosuspend
    assert 'RUN+="/usr/local/bin/hapax-l12-critical-usb-guard"' in noautosuspend

    assert 'ENV{SYSTEMD_USER_WANTS}+="hapax-usb-topology-witness.service"' in s4_policy
    assert 'ENV{SYSTEMD_USER_WANTS}+="hapax-l12-hotplug-recover.service"' in s4_policy


def test_usb_topology_installer_deploys_l12_guard_and_recovery() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "/usr/local/bin/hapax-l12-critical-usb-guard" in text
    assert "/etc/systemd/system/hapax-l12-critical-usb-guard.service" in text
    assert "/etc/systemd/system/hapax-l12-critical-usb-guard.timer" in text
    assert ".local/bin/hapax-l12-hotplug-recover" in text
    assert ".config/systemd/user/hapax-l12-hotplug-recover.service" in text
    assert "systemctl enable --now hapax-l12-critical-usb-guard.timer" in text
    assert "hapax-usb-topology-witness.service" in text


def test_usb_topology_witness_service_sets_policy_path() -> None:
    text = USB_WITNESS_SERVICE.read_text(encoding="utf-8")

    assert "Environment=HAPAX_USB_TOPOLOGY_POLICY=%h/.config/hapax/usb-topology-policy.json" in text
    assert "ExecStartPre=/usr/bin/udevadm settle --timeout=30" in text


def test_midi_route_skips_cleanly_when_legacy_binary_absent() -> None:
    text = MIDI_ROUTE.read_text(encoding="utf-8")

    assert "ConditionPathExists=%h/.local/bin/midi-route" in text
    assert "Legacy optional route" in text


def test_runbook_names_required_validation_and_emergency_cases() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    for required in [
        "usbcore.usbfs_memory_mb=128",
        "uvcvideo.quirks=0x100",
        "UDISKS_IGNORE=1",
        "NM_UNMANAGED=1",
        "MX Ergo S",
        "Keychron K2 HE",
        "S-4 absent",
        "L-12 absent",
        "Bandwidth `-28`",
        "Camera branch drift",
        "CalDigit reset churn",
    ]:
        assert required in text
