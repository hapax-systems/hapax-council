"""Random preset cycling mode with smooth transitions."""

import json
import random
import time
from pathlib import Path

PRESET_DIR = Path(__file__).parent.parent.parent / "presets"
SHM = Path("/dev/shm/hapax-compositor")
CONTROL_FILE = SHM / "random-mode.txt"
MUTATION_FILE = SHM / "graph-mutation.json"

TRANSITION_STEPS = 12  # frames for fade
TRANSITION_STEP_MS = 80  # ~1 second total


def get_preset_names() -> list[str]:
    return sorted(
        [
            p.stem
            for p in PRESET_DIR.glob("*.json")
            if not p.stem.startswith("_") and p.stem not in ("clean", "echo", "reverie_vocabulary")
        ]
    )


def load_preset_graph(name: str) -> dict | None:
    path = PRESET_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def apply_graph_with_brightness(graph: dict, brightness: float) -> None:
    """Apply a preset graph with modified colorgrade brightness for transitions."""
    g = json.loads(json.dumps(graph))  # deep copy
    for node in g.get("nodes", {}).values():
        if node.get("type") == "colorgrade":
            node["params"]["brightness"] = node["params"].get("brightness", 1.0) * brightness
            break
    MUTATION_FILE.write_text(json.dumps(g))


def transition_out(current_graph: dict | None) -> None:
    """Fade current preset to black."""
    if current_graph is None:
        return
    for i in range(TRANSITION_STEPS):
        brightness = 1.0 - (i + 1) / TRANSITION_STEPS
        apply_graph_with_brightness(current_graph, max(brightness, 0.0))
        time.sleep(TRANSITION_STEP_MS / 1000.0)


def transition_in(new_graph: dict) -> None:
    """Fade new preset from black to full."""
    for i in range(TRANSITION_STEPS):
        brightness = (i + 1) / TRANSITION_STEPS
        apply_graph_with_brightness(new_graph, brightness)
        time.sleep(TRANSITION_STEP_MS / 1000.0)


def run(interval: float = 30.0) -> None:
    """Run random preset cycling with smooth transitions."""
    presets = get_preset_names()
    last = None
    current_graph = None

    while True:
        if CONTROL_FILE.exists():
            state = CONTROL_FILE.read_text().strip().lower()
            if state == "off":
                time.sleep(1)
                continue

        # Pick random preset (avoid repeating)
        choices = [p for p in presets if p != last]
        pick = random.choice(choices)
        last = pick

        new_graph = load_preset_graph(pick)
        if new_graph is None:
            continue

        # Smooth transition: fade out → switch → fade in
        transition_out(current_graph)
        transition_in(new_graph)
        current_graph = new_graph

        # Hold at full brightness for the interval
        time.sleep(max(0, interval - 2.0))  # subtract transition time


if __name__ == "__main__":
    import sys

    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    print(f"Random mode: cycling every {interval}s with fade transitions")
    CONTROL_FILE.write_text("on")
    run(interval)
