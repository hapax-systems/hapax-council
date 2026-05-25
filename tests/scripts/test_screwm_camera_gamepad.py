from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-camera-gamepad.py"


def _load_gamepad() -> ModuleType:
    spec = importlib.util.spec_from_file_location("screwm_camera_gamepad", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_gamepad_axis_normalization_uses_reviewable_deadzone() -> None:
    gamepad = _load_gamepad()

    assert gamepad.normalize_axis(0) == 0
    assert gamepad.normalize_axis(2000) == 0
    assert gamepad.normalize_axis(32767) == 1
    assert gamepad.normalize_axis(-32767) == -1
    assert gamepad.trigger_value(-32767) == 0
    assert gamepad.trigger_value(32767) == 1


def test_gamepad_device_discovery_prefers_xbox_controller(tmp_path: Path) -> None:
    gamepad = _load_gamepad()
    sys_class = tmp_path / "sys" / "class" / "input"
    dev_root = tmp_path / "dev" / "input"
    dev_root.mkdir(parents=True)

    for node, label in (
        ("js0", "Keychron Keychron K2 HE"),
        ("js2", "Microsoft Xbox Series S|X Controller"),
    ):
        (sys_class / node / "device").mkdir(parents=True)
        (sys_class / node / "device" / "name").write_text(label, encoding="utf-8")
        (dev_root / node).touch()

    devices = gamepad.discover_joysticks(sys_class=sys_class, dev_root=dev_root)

    assert [device.path.name for device in devices] == ["js0", "js2"]
    assert gamepad.choose_device(devices).path == dev_root / "js2"


def test_gamepad_device_discovery_does_not_fall_back_to_keyboard_joystick(
    tmp_path: Path,
) -> None:
    gamepad = _load_gamepad()
    sys_class = tmp_path / "sys" / "class" / "input"
    dev_root = tmp_path / "dev" / "input"
    dev_root.mkdir(parents=True)

    (sys_class / "js0" / "device").mkdir(parents=True)
    (sys_class / "js0" / "device" / "name").write_text(
        "Keychron Keychron K2 HE",
        encoding="utf-8",
    )
    (dev_root / "js0").touch()

    devices = gamepad.discover_joysticks(sys_class=sys_class, dev_root=dev_root)

    assert gamepad.choose_device(devices) is None
    assert gamepad.choose_device(devices, allow_any=True).path == dev_root / "js0"


def test_gamepad_state_writes_headless_camera_files(tmp_path: Path) -> None:
    gamepad = _load_gamepad()
    state = gamepad.CameraState()

    state.update_axis(0, 32767, activate=False)
    state.tick(0.5)
    state.write(tmp_path)
    assert (tmp_path / "camera-manual.txt").read_text(encoding="utf-8").strip() == "0.0000"

    state.update_button(0, 1)
    state.update_axis(3, -32767)
    state.tick(0.5)
    state.write(tmp_path)

    assert (tmp_path / "camera-manual.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (tmp_path / "camera-origin-x.txt").read_text(encoding="utf-8").strip() != "0.0000"
    assert (tmp_path / "camera-yaw.txt").read_text(encoding="utf-8").strip() != "90.0000"
    assert (tmp_path / "camera-pitch.txt").exists()
    assert "axis:3" in (tmp_path / "camera-debug.txt").read_text(encoding="utf-8")

    state.update_button(1, 1)
    state.write(tmp_path)
    assert (tmp_path / "camera-manual.txt").read_text(encoding="utf-8").strip() == "0.0000"
    assert "button:1:1" in (tmp_path / "camera-debug.txt").read_text(encoding="utf-8")


def test_gamepad_camera_motion_is_visible_enough_for_live_pov() -> None:
    gamepad = _load_gamepad()
    state = gamepad.CameraState()

    state.update_axis(0, 32767)
    state.update_axis(3, 32767)
    state.tick(1.0)

    assert abs(state.origin_x) + abs(state.origin_y + 575) > 400
    assert state.yaw > 300


def test_gamepad_freecam_horizontal_axes_match_first_person_expectations() -> None:
    gamepad = _load_gamepad()
    look = gamepad.CameraState()
    strafe = gamepad.CameraState()

    look.update_axis(3, 32767)
    look.tick(0.25)
    strafe.update_axis(0, 32767)
    strafe.tick(0.25)

    assert look.yaw < gamepad.DEFAULT_YAW
    assert strafe.origin_x > gamepad.DEFAULT_ORIGIN[0]
