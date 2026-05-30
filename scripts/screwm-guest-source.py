#!/usr/bin/env python3
"""screwm-guest-source — consent-gated Meet-guest -> Screwm live-texture producer.

Grabs a fixed region of the operator's Meet window (the pinned / spotlighted
guest) and writes it into a Screwm live-texture slot buffer ONLY while an active
`world_render` consent contract names the guest. Default output is a borderless
quiet void (FAIL-CLOSED): no consent -> no guest pixels. Consent is re-checked
~once per second, so revocation returns the guest to void within one cycle.

Anti-parasocial geometry: the guest renders wherever its slot's ward is mounted.
The MVP reuses slot 7 (cam_cov, the off-centerline overhead-camera ward) so NO
DarkPlaces relaunch is needed -- mask the overhead-camera producer for the
meeting, point this producer at slot 7's buffer, and the guest develops out of
the void as a transformed instrument in the world (NOT a centerline face; OARB
is never repurposed). The screwm render supplies the ward geometry, scrim, and
drift treatment; this producer only gates and grabs.

Consent contracts live in the stable runtime dir shared with hapax-guest-consent
(NOT the worktree's axioms/contracts, which source-activate force-resets):
    ~/.cache/hapax/guest-consent/contracts/    ($HAPAX_GUEST_CONSENT_DIR)

Lawful under interpersonal_transparency (wt 88): no persistent state on a
non-operator without consent.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "packages" / "agentgov" / "src"))

from agentgov.consent import ConsentRegistry  # noqa: E402

SCOPE_CATEGORY = "world_render"
# Slot 7 (cam_cov) buffer — reused for the guest so no relaunch is needed.
DEFAULT_OUTPUT = "/dev/shm/hapax-compositor/quake-live-cam-c920-overhead.bgra"
# Borderless quiet void: a near-black warm tint (BGRA), no border/text.
VOID_BGRA = (16, 11, 14, 255)


def consent_dir() -> Path:
    raw = os.environ.get("HAPAX_GUEST_CONSENT_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / "hapax" / "guest-consent" / "contracts"


def void_frame(width: int, height: int) -> bytes:
    return bytes(VOID_BGRA) * (width * height)


def consented(person: str, directory: Path) -> bool:
    """Fresh load + contract_check. Fail-closed: any error -> False."""
    try:
        reg = ConsentRegistry(_contracts_dir=directory)
        reg.load(directory)
        return reg.contract_check(person, SCOPE_CATEGORY)
    except Exception as exc:  # noqa: BLE001 — fail-closed on any consent error
        print(f"[screwm-guest-source] consent check error (fail-closed): {exc}", file=sys.stderr)
        return False


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def grab_command(display: str, geom: str, width: int, height: int, fps: int) -> list[str]:
    """x11grab a 'WxH+X+Y' region of `display` -> scaled/padded BGRA on stdout."""
    size, _, offset = geom.partition("+")
    x, _, y = offset.partition("+")
    x = x or "0"
    y = y or "0"
    vf = (
        f"fps={fps},"
        f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        "format=bgra"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-f",
        "x11grab",
        "-video_size",
        size,
        "-framerate",
        str(fps),
        "-i",
        f"{display}+{x},{y}",
        "-an",
        "-vf",
        vf,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-",
    ]


def run(args: argparse.Namespace) -> int:
    directory = consent_dir()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height, fps = args.width, args.height, args.fps
    frame_size = width * height * 4
    void = void_frame(width, height)
    recheck_every = max(1, fps)  # re-check consent ~once per second

    stop = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # Start in the void; only grab while consent holds.
    write_atomic(output, void)

    while not stop:
        if not consented(args.person, directory):
            write_atomic(output, void)
            time.sleep(1.0)
            continue

        command = grab_command(args.display, args.grab, width, height, fps)
        try:
            with subprocess.Popen(command, stdout=subprocess.PIPE) as proc:
                assert proc.stdout is not None
                frames = 0
                while not stop:
                    data = proc.stdout.read(frame_size)
                    if len(data) != frame_size:
                        break
                    frames += 1
                    if frames % recheck_every == 0 and not consented(args.person, directory):
                        break  # consent revoked mid-stream -> drop to void
                    write_atomic(output, data)
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
        except Exception as exc:  # noqa: BLE001 — never let a grab error leak guest pixels
            print(f"[screwm-guest-source] grab error: {exc}", file=sys.stderr)

        if not stop:
            write_atomic(output, void)  # back to void on grab end / revoke
            time.sleep(0.5)

    write_atomic(output, void)  # leave the slot in void on exit
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="screwm-guest-source", description=__doc__)
    parser.add_argument(
        "--person", required=True, help="consent subject (must hold a world_render contract)"
    )
    parser.add_argument("--display", default=os.environ.get("SCREWM_GUEST_DISPLAY", ":0"))
    parser.add_argument(
        "--grab",
        default=os.environ.get("SCREWM_GUEST_GRAB", "1280x720+0+0"),
        help="x11grab region as WxH+X+Y of the Meet/pinned-guest area",
    )
    parser.add_argument("--output", default=os.environ.get("SCREWM_GUEST_OUTPUT", DEFAULT_OUTPUT))
    parser.add_argument(
        "--width", type=int, default=int(os.environ.get("SCREWM_GUEST_WIDTH", "1280"))
    )
    parser.add_argument(
        "--height", type=int, default=int(os.environ.get("SCREWM_GUEST_HEIGHT", "720"))
    )
    parser.add_argument("--fps", type=int, default=int(os.environ.get("SCREWM_GUEST_FPS", "15")))
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args(sys.argv[1:])))
