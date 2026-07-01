#!/usr/bin/env python3
"""Headless Xbox/gamepad freecam bridge for Screwm DarkPlaces.

Reads Linux joystick events from /dev/input/js* and writes a noclip freecam
pose into the DarkPlaces game data directory. CSQC reads these files in
headless mode, so OBS preview control does not depend on keyboard focus in a
visible DarkPlaces window.
"""

from __future__ import annotations

import argparse
import math
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
DEFAULT_ORIGIN = (0.0, -2240.0, 164.0)
DEFAULT_YAW = 90.0
DEFAULT_PITCH = 0.0
DEFAULT_FOV = 74.0
MANUAL_HOLD_SECONDS = 120.0
EXTERNAL_MANUAL_STALE_SECONDS = MANUAL_HOLD_SECONDS
STARTUP_INPUT_GRACE_SECONDS = 3.0
MANUAL_ACTIVATE_THRESHOLD = 0.24
# Match the grown room + the CSQC freecam clamps (wards.qc -3700/-4000/-48..1690).
# The old (-2040,2040)/(-2520,1420)/(-48,820) box was sized for the pre-2026-06-20
# small room and trapped the camera in a central cube it could not leave, unable to
# reach the wall-mounted wards/cameras — the "useless / doesn't respond" symptom.
CAMERA_X_BOUNDS = (-3700.0, 3700.0)
CAMERA_Y_BOUNDS = (-4000.0, 3000.0)
CAMERA_Z_BOUNDS = (-48.0, 1690.0)

AXIS_MAPPINGS = {
    # Alternate routes seen through some SDL/XInput bridges:
    # left stick 0/1, right stick 2/3, triggers 4/5, dpad 6/7.
    "xpad": {
        "left_x": 0,
        "left_y": 1,
        "right_x": 2,
        "right_y": 3,
        "lt": 4,
        "rt": 5,
        "dpad_x": 6,
        "dpad_y": 7,
        "trigger_axes": (4, 5),
    },
    # Linux joystick API for the plugged Microsoft Xbox controller:
    # left stick 0/1, triggers 2/5, right stick 3/4, dpad 6/7.
    "sdl": {
        "left_x": 0,
        "left_y": 1,
        "right_x": 3,
        "right_y": 4,
        "lt": 2,
        "rt": 5,
        "dpad_x": 6,
        "dpad_y": 7,
        "trigger_axes": (2, 5),
    },
}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_axis(value: int, *, deadzone: float = 0.18) -> float:
    # Deadzone raised 0.12 -> 0.18 (2026-06-20): the operator's left stick rests at
    # ~0.14 (hardware drift), which leaked past the old 0.12 band and made the camera
    # self-creep. 0.18 absorbs the measured drift with margin.
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


def _read_manual_flag(game_dir: Path) -> float:
    try:
        return float((game_dir / "camera-manual.txt").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def _external_manual_fresh(game_dir: Path, *, stale_seconds: float) -> bool:
    try:
        stat = (game_dir / "camera-manual.txt").stat()
    except OSError:
        return False
    return time.time() - stat.st_mtime <= stale_seconds


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
    manual_hold_seconds: float = MANUAL_HOLD_SECONDS
    axis_mapping: str = "sdl"
    manual: bool = False
    origin_x: float = DEFAULT_ORIGIN[0]
    origin_y: float = DEFAULT_ORIGIN[1]
    origin_z: float = DEFAULT_ORIGIN[2]
    yaw: float = DEFAULT_YAW
    pitch: float = DEFAULT_PITCH
    fov: float = DEFAULT_FOV
    axes: dict[int, float] = field(default_factory=dict)
    buttons: dict[int, int] = field(default_factory=dict)
    event_count: int = 0
    last_event: str = "none"
    manual_until: float = 0.0
    last_written_manual: bool = False
    clear_external_manual: bool = False

    def mapping(self) -> dict[str, int | tuple[int, int]]:
        return AXIS_MAPPINGS.get(self.axis_mapping, AXIS_MAPPINGS["sdl"])

    def reset(self) -> None:
        self.manual = False
        self.origin_x, self.origin_y, self.origin_z = DEFAULT_ORIGIN
        self.yaw = DEFAULT_YAW
        self.pitch = DEFAULT_PITCH
        self.fov = DEFAULT_FOV
        self.manual_until = 0.0

    def activate_manual(self, now: float | None = None) -> None:
        self.manual = True
        if now is not None:
            self.manual_until = now + self.manual_hold_seconds

    def update_button(self, number: int, value: int, *, now: float | None = None) -> None:
        self.buttons[number] = value
        self.event_count += 1
        self.last_event = f"button:{number}:{value}"
        if value <= 0:
            return
        if number == 0:  # A
            self.activate_manual(now)
        elif number == 1:  # B
            self.reset()
            self.clear_external_manual = True
        elif number == 2:  # X recenters but keeps manual takeover active.
            was_manual = self.manual
            self.reset()
            self.manual = was_manual
            if was_manual:
                self.activate_manual(now)
        elif number == 7:  # Start/Menu
            self.activate_manual(now)

    def update_axis(
        self,
        number: int,
        value: int,
        *,
        activate: bool = True,
        now: float | None = None,
    ) -> None:
        trigger_axes = self.mapping()["trigger_axes"]
        if number in trigger_axes:
            self.axes[number] = trigger_value(value)
        else:
            self.axes[number] = normalize_axis(value)
        self.event_count += 1
        self.last_event = f"axis:{number}:{self.axes[number]:.3f}"
        if activate and abs(self.axes[number]) >= MANUAL_ACTIVATE_THRESHOLD:
            self.activate_manual(now)

    def tick(self, dt: float, *, now: float | None = None) -> None:
        mapping = self.mapping()
        left_x = self.axes.get(int(mapping["left_x"]), 0.0)
        left_y = self.axes.get(int(mapping["left_y"]), 0.0)
        right_x = self.axes.get(int(mapping["right_x"]), 0.0)
        right_y = self.axes.get(int(mapping["right_y"]), 0.0)
        dpad_x = self.axes.get(int(mapping["dpad_x"]), 0.0)
        dpad_y = self.axes.get(int(mapping["dpad_y"]), 0.0)
        lt = self.axes.get(int(mapping["lt"]), 0.0)
        rt = self.axes.get(int(mapping["rt"]), 0.0)

        if now is not None and self.manual and self.manual_until and now > self.manual_until:
            self.manual = False

        if not self.manual:
            return

        self.yaw = (self.yaw - right_x * dt * 105.0) % 360.0
        self.pitch = clamp(self.pitch + right_y * dt * 82.0, -78.0, 78.0)

        yaw_rad = math.radians(self.yaw)
        forward = -left_y
        side = left_x
        lift = rt - lt
        speed = 420.0
        if self.buttons.get(4):  # LB slows for inspection.
            speed = 150.0
        if self.buttons.get(5):  # RB speeds traversal.
            speed = 760.0

        self.origin_x += (math.cos(yaw_rad) * forward + math.sin(yaw_rad) * side) * speed * dt
        self.origin_y += (math.sin(yaw_rad) * forward - math.cos(yaw_rad) * side) * speed * dt
        self.origin_z += lift * speed * dt * 0.75

        # These are broad safety rails around the generated scroom volume, not
        # collision physics. The camera remains a noclip observation point.
        self.origin_x = clamp(self.origin_x, *CAMERA_X_BOUNDS)
        self.origin_y = clamp(self.origin_y, *CAMERA_Y_BOUNDS)
        self.origin_z = clamp(self.origin_z, *CAMERA_Z_BOUNDS)

        self.fov = clamp(self.fov + dpad_x * dt * 34.0 - dpad_y * dt * 20.0, 48.0, 112.0)

        if (
            abs(left_x)
            + abs(left_y)
            + abs(right_x)
            + abs(right_y)
            + abs(lift)
            + abs(dpad_x)
            + abs(dpad_y)
            > 0.01
        ):
            self.activate_manual(now)

    def write(self, game_dir: Path, *, respect_external_manual: bool = True) -> None:
        axis_debug = ",".join(f"{number}:{self.axes[number]:+.2f}" for number in sorted(self.axes))
        button_debug = ",".join(
            f"{number}:{value}" for number, value in sorted(self.buttons.items()) if value
        )
        hold_debug = max(0.0, self.manual_until - time.monotonic()) if self.manual else 0.0

        external_manual = (
            respect_external_manual
            and not self.manual
            and not self.last_written_manual
            and not self.clear_external_manual
            and _read_manual_flag(game_dir) > 0
            and _external_manual_fresh(
                game_dir,
                stale_seconds=max(1.0, self.manual_hold_seconds),
            )
        )
        if external_manual:
            _write_atomic(
                game_dir / "camera-debug.txt",
                (
                    f"manual=external mapping={self.axis_mapping} "
                    f"events={self.event_count} last={self.last_event} "
                    f"axes={axis_debug or 'none'} buttons={button_debug or 'none'}"
                ),
            )
            return

        values: dict[str, float | str] = {
            "camera-manual.txt": 1.0 if self.manual else 0.0,
            "camera-origin-x.txt": self.origin_x,
            "camera-origin-y.txt": self.origin_y,
            "camera-origin-z.txt": self.origin_z,
            "camera-yaw.txt": self.yaw,
            "camera-pitch.txt": self.pitch,
            "camera-fov.txt": self.fov,
            "camera-debug.txt": (
                f"manual={int(self.manual)} mapping={self.axis_mapping} "
                f"events={self.event_count} "
                f"last={self.last_event} origin="
                f"{self.origin_x:.1f},{self.origin_y:.1f},{self.origin_z:.1f} "
                f"angles={self.pitch:.1f},{self.yaw:.1f} "
                f"hold={hold_debug:.1f}s axes={axis_debug or 'none'} "
                f"buttons={button_debug or 'none'}"
            ),
        }
        for filename, value in values.items():
            text = value if isinstance(value, str) else f"{value:.4f}"
            _write_atomic(game_dir / filename, text)
        self.last_written_manual = self.manual
        self.clear_external_manual = False


def run_bridge(
    device: Path,
    game_dir: Path,
    *,
    once: bool = False,
    manual_hold_seconds: float = MANUAL_HOLD_SECONDS,
    axis_mapping: str = "sdl",
    startup_input_grace_seconds: float = STARTUP_INPUT_GRACE_SECONDS,
) -> int:
    state = CameraState(manual_hold_seconds=manual_hold_seconds, axis_mapping=axis_mapping)
    fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    stop = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    started = time.monotonic()
    last = started
    try:
        while not stop:
            now = time.monotonic()
            dt = min(0.1, max(0.0, now - last))
            last = now
            activation_allowed = now - started >= startup_input_grace_seconds
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
                        state.update_axis(
                            number,
                            value,
                            activate=not is_init and activation_allowed,
                            now=now,
                        )
                    elif event_type == JS_EVENT_BUTTON:
                        if not is_init and activation_allowed:
                            state.update_button(number, value, now=now)
            state.tick(dt, now=now)
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
        "--wait-for-device",
        action="store_true",
        help="keep waiting for the preferred joystick instead of exiting when it is not present",
    )
    parser.add_argument(
        "--wait-interval",
        type=float,
        default=1.0,
        help="seconds between joystick discovery attempts when --wait-for-device is active",
    )
    parser.add_argument(
        "--allow-any-joystick",
        action="store_true",
        help="fall back to the first joystick when no Xbox/Microsoft/XInput device is present",
    )
    parser.add_argument("--list", action="store_true", help="list joystick devices and exit")
    parser.add_argument("--once", action="store_true", help="write one state sample and exit")
    parser.add_argument(
        "--manual-hold-seconds",
        type=float,
        default=MANUAL_HOLD_SECONDS,
        help="seconds that external stick/button input keeps the headless noclip camera active",
    )
    parser.add_argument(
        "--axis-mapping",
        choices=sorted(AXIS_MAPPINGS),
        default="sdl",
        help="Linux joystick axis contract to use for the controller",
    )
    parser.add_argument(
        "--startup-input-grace-seconds",
        type=float,
        default=STARTUP_INPUT_GRACE_SECONDS,
        help="seconds to ignore non-init joystick activation after opening the device",
    )
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
        chosen = None
        while chosen is None:
            devices = discover_joysticks()
            chosen = choose_device(devices, allow_any=args.allow_any_joystick)
            if chosen is not None or not args.wait_for_device:
                break
            print(
                "screwm-camera-gamepad: waiting for Xbox/Microsoft/XInput joystick",
                file=sys.stderr,
            )
            time.sleep(max(0.2, args.wait_interval))
        if chosen is None:
            print(
                "screwm-camera-gamepad: no Xbox/Microsoft/XInput joystick found; "
                "pass --device or --allow-any-joystick to override",
                file=sys.stderr,
            )
            return 69
        device = chosen.path
        print(f"screwm-camera-gamepad: using {chosen.path} ({chosen.name})", file=sys.stderr)

    return run_bridge(
        device,
        args.game_dir,
        once=args.once,
        manual_hold_seconds=max(1.0, args.manual_hold_seconds),
        axis_mapping=args.axis_mapping,
        startup_input_grace_seconds=max(0.0, args.startup_input_grace_seconds),
    )


if __name__ == "__main__":
    raise SystemExit(main())
