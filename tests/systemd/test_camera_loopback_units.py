from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS = REPO_ROOT / "systemd" / "units"
CONFIG = REPO_ROOT / "config" / "camera-loopbacks"
MODPROBE = REPO_ROOT / "config" / "modprobe.d" / "v4l2loopback-hapax.conf"

EXPECTED = {
    "brio-operator": "/dev/video70",
    "c920-desk": "/dev/video71",
    "c920-room": "/dev/video72",
    "c920-overhead": "/dev/video73",
    "brio-room": "/dev/video74",
    "brio-synths": "/dev/video75",
}


def _read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        result[key] = value
    return result


def test_setup_unit_is_system_scoped_for_modprobe() -> None:
    body = (UNITS / "hapax-camera-loopback-setup.service").read_text(encoding="utf-8")

    assert "Hapax-Install-Scope: system" in body
    assert "Type=oneshot" in body
    assert "scripts/hapax-camera-loopback-setup" in body
    assert "WantedBy=multi-user.target" in body


def test_sidecar_template_uses_repo_env_files_and_does_not_bind_compositor() -> None:
    body = (UNITS / "hapax-camera-loopback@.service").read_text(encoding="utf-8")

    assert "config/camera-loopbacks/%i.env" in body
    assert "scripts/hapax-camera-loopback-sidecar --check" in body
    assert "scripts/hapax-camera-loopback-sidecar" in body
    assert "BindsTo=studio-compositor.service" not in body


def test_target_wants_every_camera_instance() -> None:
    body = (UNITS / "hapax-camera-loopbacks.target").read_text(encoding="utf-8")

    for role in EXPECTED:
        assert f"hapax-camera-loopback@{role}.service" in body


def test_env_files_cover_unique_camera_loopbacks() -> None:
    seen_devices: set[str] = set()
    for role, device in EXPECTED.items():
        env = _read_env(CONFIG / f"{role}.env")
        assert env["HAPAX_CAMERA_LOOPBACK_ENABLED"] == "1"
        assert env["HAPAX_CAMERA_LOOPBACK_ROLE"] == role
        assert env["HAPAX_CAMERA_LOOPBACK_DEVICE"] == device
        assert env["HAPAX_CAMERA_LOOPBACK_INPUT_FORMAT"] == "mjpeg"
        seen_devices.add(device)

    assert seen_devices == set(EXPECTED.values())


def test_modprobe_config_declares_chrome_compatible_camera_devices() -> None:
    body = MODPROBE.read_text(encoding="utf-8")

    assert "devices=14" in body
    assert "70,71,72,73,74,75" in body
    assert "Hapax BRIO Operator" in body
    assert "Hapax C920 Desk" in body
    assert "exclusive_caps=1,0,0,0,0,1,1,1,0,0,0,0,0,0" in body
