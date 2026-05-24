#!/usr/bin/env python3
"""Headless Xbox/gamepad camera bridge for Screwm DarkPlaces.

Reads Linux joystick events from /dev/input/js* and writes normalized camera
control scalars into the DarkPlaces game data directory. QuakeC reads these
files in headless mode, so OBS preview control does not depend on keyboard
focus in a visible DarkPlaces window.
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
EVENT = struct.Struct("IhBB")

DEFAULT_GAME_DIR = Path.home() / ".darkplaces" / "screwm" / "data"
PREFERRED_DEVICE_WORDS = ("xbox", "microsoft", "xinput")


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_axis(value: int, *, deadzone: float = 0.12) -> float:
    norm = max(-1.0, min(1.0, value / 32767.0))
    if abs(norm) < deadzone:
        return 0.0
    return norm


def trigger_value(value: int) -> float:
    return clamp01((max(-32767, min(32767, value)) + 32767) / 65534)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text.rstrip("\n") + "\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


@dataclass
class JoystickDevice:
    path: Path
    name: str


def discover_joysticks(
    *,
    sys_class: Path = Path("/sys/class/input"),
    dev_root: Path = Path("/dev/input"),
) -> list[JoystickDevice]:
    devices: list[JoystickDevice] = []
    for name_path in sorted(sys_class.glob("js*/device/name")):
        node = dev_root / name_path.parent.parent.name
        try:
            name = name_path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            name = node.name
        if node.exists():
            devices.append(JoystickDevice(node, name))
    return devices


def choose_device(
    devices: list[JoystickDevice], *, allow_any: bool = False
) -> JoystickDevice | None:
    for device in devices:
        lowered = device.name.lower()
        if any(word in lowered for word in PREFERRED_DEVICE_WORDS):
            return device
    return devices[0] if allow_any and devices else None


@dataclass
class CameraState:
    manual: bool = False
    pan_x: float = 0.5
    pan_y: float = 0.5
    target_z: float = 0.475
    yaw: float = 0.5
    distance: float = 0.54
    height: float = 0.384
    fov: float = 0.78
    axes: dict[int, float] = field(default_factory=dict)
    buttons: dict[int, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.manual = False
        self.pan_x = 0.5
        self.pan_y = 0.5
        self.target_z = 0.475
        self.yaw = 0.5
        self.distance = 0.54
        self.height = 0.384
        self.fov = 0.78

    def update_button(self, number: int, value: int) -> None:
        self.buttons[number] = value
        if value <= 0:
            return
        if number == 0:  # A
            self.manual = True
        elif number == 1:  # B
            self.reset()
        elif number == 2:  # X
            was_manual = self.manual
            self.reset()
            self.manual = was_manual
        elif number == 7:  # Start/Menu
            self.manual = True

    def update_axis(self, number: int, value: int, *, activate: bool = True) -> None:
        if number in (2, 5):
            self.axes[number] = trigger_value(value)
        else:
            self.axes[number] = normalize_axis(value)
        if activate and abs(self.axes[number]) > 0.01:
            self.manual = True

    def tick(self, dt: float) -> None:
        left_x = self.axes.get(0, 0.0)
        left_y = self.axes.get(1, 0.0)
        right_x = self.axes.get(3, 0.0)
        right_y = self.axes.get(4, 0.0)
        dpad_x = self.axes.get(6, 0.0)
        dpad_y = self.axes.get(7, 0.0)
        lt = self.axes.get(2, 0.0)
        rt = self.axes.get(5, 0.0)

        self.pan_x = clamp01(self.pan_x + left_x * dt * 0.28)
        self.target_z = clamp01(self.target_z - left_y * dt * 0.28)
        self.yaw = clamp01(self.yaw + right_x * dt * 0.22)
        self.height = clamp01(self.height - right_y * dt * 0.22)
        self.pan_y = clamp01(self.pan_y + dpad_y * dt * 0.20)
        self.fov = clamp01(self.fov + dpad_x * dt * 0.24)
        self.distance = clamp01(self.distance + (rt - lt) * dt * 0.24)

        if self.buttons.get(4):  # LB narrows
            self.fov = clamp01(self.fov - dt * 0.26)
        if self.buttons.get(5):  # RB widens
            self.fov = clamp01(self.fov + dt * 0.26)

    def write(self, game_dir: Path) -> None:
        values = {
            "camera-manual.txt": 1.0 if self.manual else 0.0,
            "camera-pan-x.txt": self.pan_x,
            "camera-pan-y.txt": self.pan_y,
            "camera-target-z.txt": self.target_z,
            "camera-yaw.txt": self.yaw,
            "camera-distance.txt": self.distance,
            "camera-height.txt": self.height,
            "camera-fov.txt": self.fov,
        }
        for filename, value in values.items():
            _write_atomic(game_dir / filename, f"{value:.4f}")


def run_bridge(device: Path, game_dir: Path, *, once: bool = False) -> int:
    state = CameraState()
    fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    stop = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    last = time.monotonic()
    try:
        while not stop:
            now = time.monotonic()
            dt = min(0.1, max(0.0, now - last))
            last = now
            readable, _, _ = select.select([fd], [], [], 0.02)
            if readable:
                while True:
                    try:
                        data = os.read(fd, EVENT.size)
                    except BlockingIOError:
                        break
                    if len(data) != EVENT.size:
                        break
                    _ts, value, event_type, number = EVENT.unpack(data)
                    is_init = bool(event_type & JS_EVENT_INIT)
                    event_type &= ~JS_EVENT_INIT
                    if event_type == JS_EVENT_AXIS:
                        state.update_axis(number, value, activate=not is_init)
                    elif event_type == JS_EVENT_BUTTON:
                        if not is_init:
                            state.update_button(number, value)
            state.tick(dt)
            state.write(game_dir)
            if once:
                return 0
    finally:
        os.close(fd)
        state.manual = False
        state.write(game_dir)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=Path, default=None)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument(
        "--allow-any-joystick",
        action="store_true",
        help="fall back to the first joystick when no Xbox/Microsoft/XInput device is present",
    )
    parser.add_argument("--list", action="store_true", help="list joystick devices and exit")
    parser.add_argument("--once", action="store_true", help="write one state sample and exit")
    args = parser.parse_args()

    devices = discover_joysticks()
    if args.list:
        chosen = choose_device(devices, allow_any=args.allow_any_joystick)
        for device in devices:
            marker = "*" if chosen == device else " "
            print(f"{marker} {device.path}: {device.name}")
        return 0

    device = args.device
    if device is None:
        chosen = choose_device(devices, allow_any=args.allow_any_joystick)
        if chosen is None:
            print(
                "screwm-camera-gamepad: no Xbox/Microsoft/XInput joystick found; "
                "pass --device or --allow-any-joystick to override",
                file=sys.stderr,
            )
            return 69
        device = chosen.path
        print(f"screwm-camera-gamepad: using {chosen.path} ({chosen.name})", file=sys.stderr)

    return run_bridge(device, args.game_dir, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
