"""Random preset cycling mode for the compositor."""

import random
import time
from pathlib import Path

PRESET_DIR = Path(__file__).parent.parent.parent / "presets"
SHM = Path("/dev/shm/hapax-compositor")
CONTROL_FILE = SHM / "random-mode.txt"  # write "on" to enable, "off" to disable


def get_preset_names() -> list[str]:
    return sorted(
        [
            p.stem
            for p in PRESET_DIR.glob("*.json")
            if not p.stem.startswith("_") and p.stem not in ("clean", "echo", "reverie_vocabulary")
        ]
    )


def run(interval: float = 30.0) -> None:
    """Run random preset cycling. Controlled via /dev/shm/hapax-compositor/random-mode.txt"""
    presets = get_preset_names()
    last = None

    while True:
        # Check control file
        if CONTROL_FILE.exists():
            state = CONTROL_FILE.read_text().strip().lower()
            if state == "off":
                time.sleep(1)
                continue

        # Pick random preset (avoid repeating)
        choices = [p for p in presets if p != last]
        pick = random.choice(choices)
        last = pick

        (SHM / "fx-request.txt").write_text(pick)
        time.sleep(interval)


if __name__ == "__main__":
    import sys

    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    print(f"Random mode: cycling every {interval}s")
    CONTROL_FILE.write_text("on")
    run(interval)
