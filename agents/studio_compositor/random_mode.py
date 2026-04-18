"""Preset cycling — family-biased when director recruits, neutral fallback otherwise.

Phase 3 of the volitional-director epic (2026-04-18 rewrite of the
historical "random_mode"). The loop name + control file kept for
backward compatibility, but the inner logic no longer picks uniformly
from the entire preset corpus. See :mod:`agents.studio_compositor.preset_family_selector`
for the family-aware selection logic.
"""

import json
import logging
import random
import time
from pathlib import Path

log = logging.getLogger(__name__)

PRESET_DIR = Path(__file__).parent.parent.parent / "presets"
SHM = Path("/dev/shm/hapax-compositor")
CONTROL_FILE = SHM / "random-mode.txt"
MUTATION_FILE = SHM / "graph-mutation.json"

TRANSITION_STEPS = 12  # frames for fade
# Drop #46 MB-1: 10 Hz write rate aligns 1:1 with state_reader_loop's 10 Hz
# poll. Previously 80 ms (12.5 Hz) undersampled against the 10 Hz reader,
# collapsing the 12-step fade to ~5-6 effective brightness steps per the
# perceptual side.
TRANSITION_STEP_MS = 100  # 12 steps × 100 ms ≈ 1.2 s total


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


_PRESET_BIAS_COOLDOWN_S = 20.0  # if a preset-bias was recruited within this
# window, random_mode defers to the biased family instead of picking uniformly.
# Epic 2 Phase B: compositional_consumer writes the bias timestamp; this loop
# reads it via recent_recruitment_age_s("preset.bias").


def _read_recruited_family() -> str | None:
    """Return the currently-active preset.bias family name, or None.

    Reads ``recent-recruitment.json`` directly so we get the family
    name (not just an "is recruited?" boolean). Returns None when the
    bias has expired, the file is missing/malformed, or no family was
    recorded.
    """
    try:
        path = SHM / "recent-recruitment.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = (data.get("families") or {}).get("preset.bias") or {}
        ts = entry.get("last_recruited_ts")
        if not isinstance(ts, (int, float)):
            return None
        if time.time() - float(ts) >= _PRESET_BIAS_COOLDOWN_S:
            return None
        family = entry.get("family")
        return family if isinstance(family, str) and family else None
    except Exception:
        return None


def run(interval: float = 30.0) -> None:
    """Run preset cycling: family-biased when director recruits, neutral fallback otherwise.

    Phase 3 (volitional-director epic): when the director's compositional
    impingement recruits ``fx.family.<family>``, this loop picks the next
    preset *from that family* via :func:`preset_family_selector.pick_from_family`.
    When no family is recruited, falls back to ``neutral-ambient`` rather
    than uniform random across all presets — eliminating the operator-
    flagged "shuffle feel" where effects appeared to be randomly cycling
    instead of being actively chosen.
    """
    from agents.studio_compositor.preset_family_selector import (
        FAMILY_PRESETS,
        pick_from_family,
    )

    presets = get_preset_names()
    last = None
    current_graph = None

    while True:
        if CONTROL_FILE.exists():
            state = CONTROL_FILE.read_text().strip().lower()
            if state == "off":
                time.sleep(1)
                continue

        # Family-biased pick path (Phase 3): if director recruited a
        # specific family within the cooldown window, pick a preset from
        # that family. Otherwise, use the neutral-ambient fallback so we
        # NEVER fall back to uniform random across the whole corpus —
        # the operator's "no shuffle feel" directive.
        recruited_family = _read_recruited_family()
        if recruited_family is not None and recruited_family in FAMILY_PRESETS:
            pick = pick_from_family(recruited_family, available=presets, last=last)
            chosen_via = f"family={recruited_family}"
        else:
            pick = pick_from_family("neutral-ambient", available=presets, last=last)
            chosen_via = "fallback=neutral-ambient"
        if pick is None:
            # Family map empty or all candidates filtered out — last-resort
            # uniform random so the loop never silently stalls.
            choices = [p for p in presets if p != last]
            if not choices:
                time.sleep(1.0)
                continue
            pick = random.choice(choices)
            chosen_via = "uniform-fallback"
        log.info("random_mode pick: %s (%s)", pick, chosen_via)
        # S2: Prometheus observability — distinguishes family-recruited
        # picks from the neutral-ambient fallback so Grafana can alert
        # when fallback rate approaches old shuffle behaviour.
        try:
            from shared.director_observability import emit_random_mode_pick

            emit_random_mode_pick(chosen_via)
        except Exception:
            pass
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
