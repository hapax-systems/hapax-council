"""Preset cycling — family-biased when director recruits, neutral fallback otherwise.

Phase 3 of the volitional-director epic (2026-04-18 rewrite of the
historical "random_mode"). The loop name + control file kept for
backward compatibility, but the inner logic no longer picks uniformly
from the entire preset corpus. See :mod:`agents.studio_compositor.preset_family_selector`
for the family-aware selection logic.

Phase 7 of the preset-variety plan (#166): per-chain-change the loop
also picks one of five transition primitives instead of always running
the historical brightness fade. When the director has recruited a
``transition.*`` capability within the cooldown the loop honors it;
otherwise it samples uniformly across the 5 primitives so transition
entropy stays well above the 0.6-bit acceptance bar without an
ordered rotation. See :mod:`agents.studio_compositor.transition_primitives`
for the primitive implementations.
"""

import json
import logging
import random
import time
from pathlib import Path

from agents.studio_compositor.preset_mutator import (
    DEFAULT_VARIANCE,
    mutate_preset,
    variety_enabled,
)
from agents.studio_compositor.transition_primitives import (
    PRIMITIVES,
    TRANSITION_NAMES,
    TransitionFn,
)

log = logging.getLogger(__name__)

PRESET_DIR = Path(__file__).parent.parent.parent / "presets"
SHM = Path("/dev/shm/hapax-compositor")
CONTROL_FILE = SHM / "random-mode.txt"
MUTATION_FILE = SHM / "graph-mutation.json"

# Transition cooldown: same shape as ``_PRESET_BIAS_COOLDOWN_S`` below.
# If the director recruited a ``transition.*`` capability within this
# window, defer to it; otherwise sample uniformly.
_TRANSITION_BIAS_COOLDOWN_S = 20.0


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


def _load_cycle_graph(
    name: str,
    *,
    seed: int | None = None,
    variance: float = DEFAULT_VARIANCE,
    mutate: bool | None = None,
) -> dict | None:
    """Load a preset for the automatic livestream cycle path.

    Manual/chat preset requests still use :func:`load_preset_graph` and get
    the canonical graph. The autonomous cycler uses bounded parametric
    mutation so repeated family picks do not render as identical chain states.
    """
    graph = load_preset_graph(name)
    if graph is None:
        return None
    do_mutate = variety_enabled() if mutate is None else mutate
    if not do_mutate:
        return graph
    rng = random.Random(seed) if seed is not None else random.Random()
    return mutate_preset(graph, rng=rng, variance=variance)


def _write_mutation(graph: dict) -> None:
    """Write a graph dict to the SHM mutation file (primitive callback)."""
    MUTATION_FILE.write_text(json.dumps(graph))


def _read_recruited_transition() -> str | None:
    """Return the recently-recruited transition capability name, or None.

    Reads ``recent-recruitment.json`` — the same surface used for
    preset-family bias. ``compositional_consumer._mark_recruitment``
    records each recruited capability under its full name; the newest
    ``transition.*`` entry within the cooldown wins. Returns ``None``
    so the caller falls back to uniform sampling when nothing matches.
    """
    try:
        path = SHM / "recent-recruitment.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        families = data.get("families") or {}
        best: tuple[float, str] | None = None
        for fam_name, entry in families.items():
            if not isinstance(fam_name, str) or not fam_name.startswith("transition."):
                continue
            ts = entry.get("last_recruited_ts") if isinstance(entry, dict) else None
            if not isinstance(ts, (int, float)):
                continue
            if time.time() - float(ts) >= _TRANSITION_BIAS_COOLDOWN_S:
                continue
            if best is None or float(ts) > best[0]:
                best = (float(ts), fam_name)
        if best is None:
            return None
        name = best[1]
        return name if name in PRIMITIVES else None
    except Exception:
        return None


def _select_transition() -> tuple[str, TransitionFn]:
    """Pick a transition for the next chain change.

    Recruitment-bias first, uniform fallback second. The success
    criterion (``rg 'transition.*if.*rotate' returns 0``) requires no
    ordered rotation; each call samples independently.
    """
    recruited = _read_recruited_transition()
    if recruited is not None:
        return recruited, PRIMITIVES[recruited]
    name = random.choice(TRANSITION_NAMES)
    return name, PRIMITIVES[name]


def apply_graph_with_brightness(graph: dict, brightness: float) -> None:
    """Backwards-compatible shim. Pre-Phase-7 callers may still use this.

    New callers should select a transition primitive from
    ``transition_primitives.PRIMITIVES`` and run it with
    ``_write_mutation`` instead.
    """
    g = json.loads(json.dumps(graph))
    for node in g.get("nodes", {}).values():
        if node.get("type") == "colorgrade":
            node["params"]["brightness"] = node["params"].get("brightness", 1.0) * brightness
            break
    MUTATION_FILE.write_text(json.dumps(g))


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

        new_graph = _load_cycle_graph(pick, seed=time.time_ns())
        if new_graph is None:
            continue

        # Phase 7 — pick a transition primitive per chain change so the
        # chain-level vocabulary doesn't collapse to the historical fade.
        transition_name, transition_fn = _select_transition()
        log.info("random_mode transition: %s", transition_name)
        try:
            from shared.director_observability import emit_transition_pick

            emit_transition_pick(transition_name)
        except Exception:
            pass
        transition_fn(current_graph, new_graph, _write_mutation)
        current_graph = new_graph

        # Hold at full brightness for the interval (transition runtime
        # bounded by primitive constants — at most ~1.4 s for the longest
        # primitive, well within the original 2 s subtraction).
        time.sleep(max(0, interval - 2.0))


if __name__ == "__main__":
    import sys

    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    print(f"Random mode: cycling every {interval}s with fade transitions")
    CONTROL_FILE.write_text("on")
    run(interval)
