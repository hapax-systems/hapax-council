from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


ROLE_DEVICES = {
    "brio-operator": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0",
    "c920-overhead": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_7B88C71F-video-index0",
}


def test_compositor_seed_configs_do_not_reintroduce_stale_pi_loopbacks() -> None:
    files = [
        REPO_ROOT / "agents" / "studio_compositor" / "config.py",
        REPO_ROOT / "config" / "layouts" / "garage-door.json",
        REPO_ROOT / "config" / "camera-loopbacks" / "brio-operator.env",
        REPO_ROOT / "config" / "camera-loopbacks" / "c920-overhead.env",
    ]

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "/dev/video60" not in text, f"{path} still points at stale brio loopback"
        assert "/dev/video61" not in text, f"{path} still points at stale overhead loopback"


def test_repaired_camera_roles_use_stable_by_id_devices() -> None:
    config_text = (REPO_ROOT / "agents" / "studio_compositor" / "config.py").read_text(
        encoding="utf-8"
    )
    layout_text = (REPO_ROOT / "config" / "layouts" / "garage-door.json").read_text(
        encoding="utf-8"
    )

    for device in ROLE_DEVICES.values():
        assert device in config_text
        assert device in layout_text
