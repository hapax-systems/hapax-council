#!/usr/bin/env python3
"""Publish live Screwm drift state without running the heavy frame renderer."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import time
from pathlib import Path
from typing import Any

DEFAULT_EFFECT_DRIFT = Path("/dev/shm/hapax-visual/screwm-effect-drift-fallback-state.json")
DEFAULT_VISUAL_CHAIN = Path("/dev/shm/hapax-visual/screwm-visual-chain-state.json")
DEFAULT_PLAN = Path("/dev/shm/hapax-visual/screwm-effect-drift-plan.json")

FAMILY_EFFECTS: dict[str, list[str]] = {
    "tonal": [
        "colorgrade",
        "bloom",
        "invert",
        "vignette",
        "thermal",
        "posterize",
        "palette",
        "palette_remap",
    ],
    "atmospheric": [
        "drift",
        "chromatic_aberration",
        "kaleidoscope",
        "fisheye",
        "mirror",
        "transform",
        "slitscan",
        "warp",
        "displacement_map",
        "pixsort",
        "droste",
        "tile",
        "tunnel",
        "breathing",
    ],
    "temporal": ["trail", "echo", "stutter", "diff", "fluid_sim", "reaction_diffusion", "feedback"],
    "texture": [
        "ascii",
        "vhs",
        "glitch_block",
        "scanlines",
        "emboss",
        "halftone",
        "sharpen",
        "kuwahara",
        "noise_overlay",
        "grain_bump",
        "dither",
        "noise_gen",
        "particle_system",
        "strobe",
    ],
    "edge": ["edge_detect", "rutt_etra", "voronoi_overlay", "threshold", "waveform_render"],
    "compositing": ["blend", "chroma_key", "crossfade", "luma_key"],
}

FAST_EVICT = {
    "ascii",
    "blend",
    "breathing",
    "chroma_key",
    "chromatic_aberration",
    "color_map",
    "crossfade",
    "dither",
    "displacement_map",
    "diff",
    "droste",
    "edge_detect",
    "echo",
    "fisheye",
    "fluid_sim",
    "glitch_block",
    "halftone",
    "kaleidoscope",
    "luma_key",
    "mirror",
    "noise_gen",
    "palette_remap",
    "particle_system",
    "pixsort",
    "posterize",
    "reaction_diffusion",
    "rutt_etra",
    "scanlines",
    "slitscan",
    "strobe",
    "stutter",
    "thermal",
    "threshold",
    "tile",
    "transform",
    "tunnel",
    "trail",
    "vhs",
    "warp",
    "waveform_render",
}

PARAMS_BY_FAMILY: dict[str, tuple[tuple[str, float], ...]] = {
    "tonal": (("saturation", 1.0), ("contrast", 1.0), ("hue_rotate", 0.0)),
    "atmospheric": (("amplitude", 0.0), ("speed", 0.0), ("phase", 0.0)),
    "temporal": (("decay", 0.0), ("delay", 0.0), ("opacity", 0.0)),
    "texture": (("density", 0.0), ("scale", 1.0), ("opacity", 0.0)),
    "edge": (("threshold", 0.5), ("thickness", 1.0), ("opacity", 0.0)),
    "compositing": (("blend", 0.0), ("key", 0.5), ("opacity", 0.0)),
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _pulse(t: float, speed: float, phase: float, lo: float, hi: float) -> float:
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(t * speed + phase))


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _effect_for_family(family: str, tick: int, offset: int) -> str:
    if family == "tonal" and offset == 0:
        return "colorgrade"
    bank = FAMILY_EFFECTS[family]
    step = 2 if offset % 2 else 1
    return bank[(tick * step + offset * 3) % len(bank)]


def build_states(now: float | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    t = time.time() if now is None else now
    tick = int(t // 3.0)
    families = ("tonal", "atmospheric", "temporal", "texture", "edge", "compositing")
    dominant_slot = tick % len(families)
    support_slot = (dominant_slot + 2 + (tick // len(families)) % 3) % len(families)
    adjacent_slot = (dominant_slot + 1) % len(families)
    slow_anchor_slot = (dominant_slot + len(families) - 1) % len(families)
    passes: list[dict[str, Any]] = []
    non_neutral_pass_count = 0

    for slot, family in enumerate(families):
        effect = _effect_for_family(family, tick, slot)
        if slot == dominant_slot:
            active_gain = 1.0
        elif slot == support_slot:
            active_gain = 0.68
        elif slot == adjacent_slot:
            active_gain = 0.52
        elif slot == slow_anchor_slot:
            active_gain = 0.38
        else:
            active_gain = 0.0
        intensity = active_gain * _pulse(t, 0.23 + slot * 0.07, slot * 1.7, 0.58, 0.96)
        if active_gain and effect in FAST_EVICT:
            intensity = max(
                intensity,
                active_gain * _pulse(t, 1.1 + slot * 0.11, slot, 0.44, 1.0),
            )
        params = []
        regions = []
        pass_max_delta = 0.0
        for index, (name, neutral) in enumerate(PARAMS_BY_FAMILY[family]):
            raw_delta = (
                active_gain * (0.28 + intensity * (1.8 + index * 0.7)) * (1 if index != 1 else -1)
            )
            if neutral == 1.0:
                value = max(0.05, neutral + raw_delta * 0.18)
                delta = value - neutral
            elif neutral == 0.5:
                value = _clamp01(neutral + raw_delta * 0.10)
                delta = value - neutral
            else:
                value = raw_delta
                delta = raw_delta
            pass_max_delta = max(pass_max_delta, abs(delta))
            params.append({"name": name, "neutral": neutral, "value": value, "delta": delta})
            if active_gain:
                regions.append(
                    {"param": name, "region": "high" if delta >= 0 else "low", "target": value}
                )
        non_neutral = bool(active_gain)
        if non_neutral:
            non_neutral_pass_count += 1
        passes.append(
            {
                "node_id": f"slot{slot}_{effect}",
                "slot_index": slot,
                "effect_family": family,
                "eviction_cadence": "fast" if effect in FAST_EVICT else "slow",
                "effect_scope": "composed_live_surface",
                "effect_application_plane": "entity_field_surface_treatment",
                "effect_binding": "source_presence_gated",
                "runtime_source_bound_mask": True,
                "fourth_wall_policy": "forbid_foreground_overlay",
                "route_authority": "composed_surface_drift",
                "non_neutral": non_neutral,
                "full_surface": family in {"tonal", "texture", "atmospheric"},
                "max_delta": pass_max_delta,
                "slot_intensity": intensity,
                "parameter_regions": regions,
                "params": params,
                "inputs": ["@live"] if slot == 0 else [f"main:layer_{slot - 1}"],
                "output": f"main:layer_{slot}",
            }
        )

    chain_intensity = _pulse(t, 0.19, 0.0, 0.58, 0.92)
    chain_tension = _pulse(t, 0.29, 0.7, 0.42, 0.88)
    chain_diffusion = _pulse(t, 0.13, 1.4, 0.36, 0.78)
    chain_degradation = _pulse(t, 0.43, 2.1, 0.28, 0.86)
    chain_depth = _pulse(t, 0.11, 2.8, 0.52, 0.94)
    visual_chain = {
        "timestamp": t,
        "levels": {
            "visual_chain.intensity": chain_intensity,
            "visual_chain.tension": chain_tension,
            "visual_chain.diffusion": chain_diffusion,
            "visual_chain.degradation": chain_degradation,
            "visual_chain.depth": chain_depth,
            "visual_chain.pitch_displacement": _pulse(t, 0.31, 0.2, 0.24, 0.74),
            "visual_chain.temporal_distortion": _pulse(t, 0.37, 1.2, 0.42, 0.96),
            "visual_chain.spectral_color": _pulse(t, 0.17, 2.2, 0.55, 0.98),
            "visual_chain.coherence": _pulse(t, 0.09, 3.2, 0.30, 0.72),
        },
        "params": {
            "noise.amplitude": _pulse(t, 0.67, 0.1, 0.04, 0.26),
            "noise.frequency_x": _pulse(t, 0.21, 0.3, 0.24, 0.86),
            "noise.speed": _pulse(t, 0.77, 0.5, 0.02, 0.09),
            "noise.octaves": _pulse(t, 0.12, 0.8, 1.0, 2.0),
            "drift.amplitude": _pulse(t, 0.33, 1.1, 0.35, 0.78),
            "drift.speed": _pulse(t, 0.47, 1.5, 0.18, 0.46),
            "color.hue_rotate": _pulse(t, 0.18, 1.9, 24.0, 72.0),
            "color.saturation": _pulse(t, 0.24, 2.3, 0.25, 0.62),
            "color.brightness": _pulse(t, 0.16, 2.9, 0.08, 0.28),
            "fb.decay": _pulse(t, 0.39, 3.1, 0.05, 0.15),
            "fb.hue_shift": _pulse(t, 0.26, 3.4, 1.4, 4.8),
            "post.vignette_strength": _pulse(t, 0.14, 3.8, 0.18, 0.46),
            "post.sediment_strength": _pulse(t, 0.62, 4.1, 0.01, 0.04),
            "rd.diffusion_a": _pulse(t, 0.08, 4.4, 0.18, 0.54),
            "rd.feed_rate": _pulse(t, 0.15, 4.7, 0.02, 0.07),
        },
    }
    effect_drift = {
        "timestamp_unix_ms": int(t * 1000),
        "frame_count": int(t * 30),
        "pass_count": len(passes),
        "non_neutral_pass_count": non_neutral_pass_count,
        "dominant_family": families[dominant_slot],
        "support_family": families[support_slot],
        "source_presence": "synthetic-fallback-live-state-only",
        "fallback_state": True,
        "route_authority": "screwm_darkplaces_synthetic_fallback",
        "slotdrift_coverage": "six-family-rotating-dominant-support-fast-slow-eviction",
        "passes": passes,
    }
    plan = {
        "timestamp": t,
        "consumer": "darkplaces-state-export",
        "route_authority": "screwm_darkplaces_state_only",
        "passes": [
            {"node_id": item["node_id"], "effect_family": item["effect_family"]} for item in passes
        ],
    }
    return effect_drift, visual_chain, plan


def run(args: argparse.Namespace) -> int:
    stop = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    period = 1.0 / max(0.1, args.fps)
    while not stop:
        started = time.monotonic()
        effect_drift, visual_chain, plan = build_states()
        _write_atomic(args.effect_drift, effect_drift)
        _write_atomic(args.visual_chain, visual_chain)
        _write_atomic(args.plan, plan)
        if args.once:
            break
        time.sleep(max(0.02, period - (time.monotonic() - started)))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effect-drift", type=Path, default=DEFAULT_EFFECT_DRIFT)
    parser.add_argument("--visual-chain", type=Path, default=DEFAULT_VISUAL_CHAIN)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
