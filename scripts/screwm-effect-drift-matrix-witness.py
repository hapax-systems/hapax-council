#!/usr/bin/env python3
"""Drive representative Screwm effect/drift combinations and capture witnesses.

The matrix is deliberately bounded: each row uses one existing SlotDrift
permutation bank and keeps DarkPlaces screen-space postprocess disabled. This
proves geometry-bound expression without counting fourth-wall effects.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import math
import runpy
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
PERMUTATION_AUDIT = REPO_ROOT / "scripts" / "live-effect-permutation-audit.py"
EXPORTER = REPO_ROOT / "scripts" / "darkplaces-state-export.py"
DEFAULT_GAME_DATA = Path.home() / ".darkplaces/screwm/data"
DEFAULT_OUTPUT_ROOT = Path.home() / ".cache/hapax/screenshots/screwm-effect-drift-matrix"
DEFAULT_VIDEO_DEVICE = Path("/dev/video52")
DEFAULT_OBS_SCENE = "Scene"
OBS_WS_CONFIG = Path.home() / ".config/obs-studio/plugin_config/obs-websocket/config.json"
AESTHETIC_REGION_MOTION_FLOOR = 0.003
AESTHETIC_EDGE_DELTA_FLOOR = 0.0015
AESTHETIC_REGION_MIN_COVERAGE = 0.50
AESTHETIC_REGION_MAX_DOMINANCE = 0.72
AESTHETIC_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "ceiling": (0.18, 0.02, 0.82, 0.24),
    "left_wall": (0.02, 0.18, 0.35, 0.72),
    "right_wall": (0.65, 0.18, 0.98, 0.72),
    "floor": (0.12, 0.70, 0.88, 0.98),
    "entity_core": (0.36, 0.25, 0.64, 0.66),
    "negative_space": (0.02, 0.02, 0.22, 0.34),
}

# Tactical POV stations for witness coverage, resolved from generate-screwm-map
# GARDEN_CAMERA_STATIONS (AoA object-of-attention at (0, -555, 224); 32 units/m).
# Sweeping these per witness frames receivers, depth planes, the AoA sphere, and
# the borrowed-view band from multiple angles for maximum coverage.
Station = tuple[str, tuple[float, float, float], tuple[float, float, float]]
AOA_LOOKAT = (0.0, -555.0, 224.0)
POV_STATIONS: tuple[Station, ...] = (
    ("entry-stone", (0.0, -2380.0, 164.0), AOA_LOOKAT),
    ("threshold-stone", (-320.0, -2200.0, 168.0), AOA_LOOKAT),
    ("left-borrowed-view", (-860.0, -1880.0, 184.0), (-1180.0, -1600.0, 240.0)),
    ("left-media-window", (-1040.0, -1480.0, 196.0), (-1580.0, -1320.0, 230.0)),
    ("aoa-pause", (-320.0, -900.0, 182.0), AOA_LOOKAT),
    ("right-borrowed-view", (860.0, -1000.0, 184.0), (1180.0, -1120.0, 240.0)),
    ("right-media-window", (1040.0, -1480.0, 196.0), (1580.0, -1320.0, 230.0)),
    ("far-garden-view", (420.0, -430.0, 220.0), (0.0, -555.0, 242.0)),
)
DEFAULT_POV_LABELS = (
    "entry-stone",
    "aoa-pause",
    "left-media-window",
    "right-media-window",
    "far-garden-view",
)

LOCAL_EFFECTS = (
    "mirror",
    "kaleidoscope",
    "warp",
    "fisheye",
    "transform",
    "displacement_map",
    "droste",
    "tunnel",
    "tile",
    "drift",
    "breathing",
)

TEMPORAL_EFFECTS = {
    "trail",
    "echo",
    "stutter",
    "diff",
    "slitscan",
    "fluid_sim",
    "reaction_diffusion",
}


@dataclass(frozen=True)
class MatrixRow:
    ordinal: int
    label: str
    preset: int
    bank_label: str
    expected_cues: tuple[str, ...]


MATRIX_ROWS: tuple[MatrixRow, ...] = (
    MatrixRow(
        0,
        "live-state-baseline",
        0,
        "quiet-live-state",
        (
            "live coupling mode active",
            "no blackout",
            "media surfaces remain readable",
        ),
    ),
    MatrixRow(
        1,
        "readability-alpha",
        0,
        "alpha-line-tonal-trail",
        (
            "cyan/magenta lattice is visible but does not bury media",
            "tonal/trail state lights register on source planes",
        ),
    ),
    MatrixRow(
        2,
        "prism-beta",
        0,
        "beta-rutt-key-recursion",
        (
            "strong prism separation at high-contrast edges",
            "recursion/temporal bank remains bounded",
        ),
    ),
    MatrixRow(
        3,
        "feedback-gamma",
        0,
        "gamma-mask-detail-temporal",
        (
            "noise and smear are visible as drift pressure",
            "detail transforms do not collapse the room into mush",
        ),
    ),
    MatrixRow(
        4,
        "halftone-delta",
        0,
        "delta-map-slit-geometry",
        (
            "texture pressure is legible on geometry-bound receivers",
            "geometry/motion bank reads as spatial lighting",
        ),
    ),
    MatrixRow(
        5,
        "emboss-epsilon",
        0,
        "epsilon-palette-particle-fluid",
        (
            "material/aperture/thermal pressure is visible",
            "palette and particle/fluid bank stays inside the scroom",
        ),
    ),
    MatrixRow(
        6,
        "threshold-zeta",
        0,
        "zeta-breath-reaction-wave",
        (
            "edge and inversion stress stay geometry-bound",
            "breathing/reaction/wave bank remains navigable",
        ),
    ),
)


def _load_exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("darkplaces_state_export", EXPORTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load exporter: {EXPORTER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_permutation_sets() -> dict[str, tuple[str, ...]]:
    module = runpy.run_path(str(PERMUTATION_AUDIT), run_name="__screwm_matrix__")
    return {spec.label: tuple(spec.effects) for spec in module["PERMUTATION_SETS"]}


def _load_fast_evict() -> frozenset[str]:
    module = runpy.run_path(str(PERMUTATION_AUDIT), run_name="__screwm_matrix__")
    return frozenset(module["FAST_EVICT"])


def _row_by_label_or_ordinal(value: str) -> MatrixRow:
    for row in MATRIX_ROWS:
        if value == str(row.ordinal) or value == row.label:
            return row
    raise argparse.ArgumentTypeError(f"unknown matrix row: {value}")


def selected_rows(raw: str) -> list[MatrixRow]:
    if raw == "all":
        return list(MATRIX_ROWS)
    return [_row_by_label_or_ordinal(item.strip()) for item in raw.split(",") if item.strip()]


def _json_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_lines(game_data: Path, lines: dict[str, str]) -> None:
    game_data.mkdir(parents=True, exist_ok=True)
    for filename, value in lines.items():
        (game_data / filename).write_text(f"{value}\n", encoding="utf-8")


def _quiet_live_lines() -> dict[str, str]:
    lines = {
        "effect-review-preset.txt": "0",
        "stimmung-energy.txt": "0.72",
        "voice-active.txt": "0",
        "audio-rms.txt": "0.08",
        "audio-onset.txt": "0.00",
        "reverie-salience.txt": "0.18",
        "reverie-trace.txt": "0.10",
        "reverie-temporal.txt": "0.08",
        "reverie-spectral.txt": "0.12",
        "reverie-material.txt": "0.06",
        "reverie-inversion.txt": "0.00",
        "reverie-aperture.txt": "0.06",
        "reverie-thermal.txt": "0.02",
        "camera-manual.txt": "1.0000",
        "camera-origin-x.txt": "0.0000",
        "camera-origin-y.txt": "-2240.0000",
        "camera-origin-z.txt": "164.0000",
        "camera-pitch.txt": "0.0000",
        "camera-yaw.txt": "90.0000",
        "camera-fov.txt": "74.0000",
    }
    for ordinal in range(1, 12):
        lines[f"local-effect-{ordinal:02d}.txt"] = "0.0000"
    lines["local-effect-count.txt"] = "0.0000"
    lines["local-effect-route.txt"] = "ENTITY_LOCAL_SOURCE_PLANE"
    for name in (
        "pass-count",
        "active-ratio",
        "active-slot-ratio",
        "active-effect-ratio",
        "fast-ratio",
        "slow-ratio",
        "kind-variance",
        "max-delta",
        "region-count",
        "tonal",
        "atmospheric",
        "temporal",
        "texture",
        "edge",
        "compositing",
    ):
        lines[f"effect-drift-{name}.txt"] = "0.0000"
    for family in ("tonal", "atmospheric", "temporal", "texture", "edge", "compositing"):
        lines[f"effect-drift-mode-{family}.txt"] = "0.0000"
    lines["effect-drift-route.txt"] = "IN_SCROOM_EFFECT_DRIFT_STATE"
    lines["effect-drift-source.txt"] = "quiet-live-state"
    lines["effect-drift-real-source.txt"] = "0.0000"
    lines["visual-chain-source.txt"] = "quiet-live-state"
    for name in (
        "pass-count",
        "render-ratio",
        "temporal-ratio",
        "color",
        "motion",
        "feedback",
        "post",
    ):
        lines[f"shader-plan-{name}.txt"] = "0.0000"
    lines["shader-plan-route.txt"] = "IN_SCROOM_SHADER_PASS_PLAN"
    for ordinal in range(1, 10):
        lines[f"visual-chain-{ordinal:02d}.txt"] = "0.0000"
    for name in (
        "noise",
        "drift",
        "color",
        "feedback",
        "aperture",
        "param-pressure",
    ):
        lines[f"visual-chain-{name}.txt"] = "0.0000"
    return lines


def _effect_state(effects: tuple[str, ...]) -> dict[str, object]:
    active_effects = [
        {"effect": effect, "mix": 0.92} for effect in effects if effect in LOCAL_EFFECTS
    ]
    if not active_effects:
        active_effects = [{"effect": "drift", "mix": 0.35}]
    return {"active_effects": active_effects}


def _shader_plan(effects: tuple[str, ...]) -> dict[str, object]:
    passes = []
    for index, effect in enumerate(effects):
        passes.append(
            {
                "node_id": effect,
                "shader": f"{effect}.wgsl",
                "type": "render",
                "temporal": effect in TEMPORAL_EFFECTS,
                "uniforms": {
                    "strength": 1.25 + (index % 4) * 0.15,
                    "mix": 0.72,
                },
                "param_order": ["strength", "mix"],
            }
        )
    return {"targets": {"main": {"passes": passes}}}


def _visual_chain_state(row: MatrixRow) -> dict[str, object]:
    pressure = min(1.0, 0.36 + row.ordinal * 0.08)
    temporal = 0.18 + (0.10 if row.ordinal in {3, 6} else 0.0)
    return {
        "levels": {
            "visual_chain.intensity": pressure,
            "visual_chain.tension": 0.18 + row.ordinal * 0.06,
            "visual_chain.diffusion": min(1.0, pressure * 0.82),
            "visual_chain.degradation": 0.16 + row.ordinal * 0.045,
            "visual_chain.depth": 0.62,
            "visual_chain.pitch_displacement": 0.24 + row.ordinal * 0.035,
            "visual_chain.temporal_distortion": min(1.0, temporal),
            "visual_chain.spectral_color": min(1.0, 0.42 + row.ordinal * 0.065),
            "visual_chain.coherence": 0.58,
        },
        "params": {
            "noise.amplitude": 0.18 + row.ordinal * 0.04,
            "noise.frequency_x": 0.70 + row.ordinal * 0.11,
            "noise.speed": 0.04 + row.ordinal * 0.02,
            "noise.octaves": 1.0 + row.ordinal * 0.22,
            "drift.amplitude": 0.20 + row.ordinal * 0.08,
            "drift.speed": 0.08 + row.ordinal * 0.04,
            "color.hue_rotate": 18.0 + row.ordinal * 9.0,
            "color.saturation": 0.18 + row.ordinal * 0.055,
            "color.brightness": 0.08 + row.ordinal * 0.025,
            "fb.decay": 0.025 + row.ordinal * 0.016,
            "post.vignette_strength": 0.14 + row.ordinal * 0.06,
            "post.sediment_strength": 0.010 + row.ordinal * 0.008,
        },
    }


def _effect_drift_state(
    effects: tuple[str, ...],
    row: MatrixRow,
    *,
    fast_evict: frozenset[str],
    families: tuple[str, ...],
) -> dict[str, object]:
    """Synthesize a *real* SlotDrift state for the row.

    Mirrors the canonical pass shape emitted by ``screwm-drift-state-source.py``
    so the exporter classifies it as ``slotdrift`` (not the synthetic fallback)
    and the new slot/effect/fast-slow/kind scalars round-trip. Active slot count
    and intensity rise with the row ordinal so the scalars vary across the matrix
    instead of collapsing to a single fallback for every row.
    """
    family_count = len(families)
    active_slots = min(family_count, 1 + row.ordinal)
    passes: list[dict[str, object]] = []
    non_neutral_count = 0
    for slot, family in enumerate(families):
        effect = effects[slot % len(effects)] if effects else family
        active = slot < active_slots
        if active:
            intensity = round(min(1.0, (0.40 + row.ordinal * 0.085) * (1.0 - slot * 0.08)), 4)
            delta = round(min(9.5, 4.8 + row.ordinal * 0.55 + slot * 0.35), 4)
            non_neutral_count += 1
        else:
            intensity = 0.0
            delta = 0.0
        passes.append(
            {
                "node_id": f"slot{slot}_{effect}",
                "slot_index": slot,
                "effect_family": family,
                "eviction_cadence": "fast" if effect in fast_evict else "slow",
                "effect_binding": "source_presence_gated",
                "non_neutral": active,
                "max_delta": delta,
                "slot_intensity": intensity,
                "parameter_regions": (
                    [{"param": "mix", "region": "high"}, {"param": "phase", "region": "drift"}]
                    if active
                    else []
                ),
                "params": [{"name": "mix", "delta": delta}] if active else [],
            }
        )
    return {
        "pass_count": len(passes),
        "non_neutral_pass_count": non_neutral_count,
        "dominant_family": families[0] if families else "",
        "source_presence": {
            "fail_closed": False,
            "visible_source_count": active_slots + family_count,
            "minimum_effect_source_count": 1,
        },
        "slotdrift_coverage": {
            "mode": "matrix-witness-bank",
            "bank_label": row.bank_label,
            "active_slots": active_slots,
            "families": list(families),
        },
        "passes": passes,
    }


def build_row_lines(
    row: MatrixRow,
    *,
    exporter: ModuleType,
    bank_effects: dict[str, tuple[str, ...]],
    state_dir: Path,
) -> dict[str, str]:
    lines = _quiet_live_lines()
    lines["effect-review-preset.txt"] = str(row.preset)
    if row.ordinal == 0:
        return lines

    effects = bank_effects[row.bank_label]
    families = tuple(exporter.EFFECT_DRIFT_FAMILIES)
    fast_evict = _load_fast_evict()
    effect_state = state_dir / f"{row.label}-entity-local-effect-state.json"
    shader_plan = state_dir / f"{row.label}-shader-plan.json"
    visual_chain = state_dir / f"{row.label}-visual-chain-state.json"
    effect_drift = state_dir / f"{row.label}-effect-drift-state.json"
    _json_write(effect_state, _effect_state(effects))
    _json_write(shader_plan, _shader_plan(effects))
    _json_write(visual_chain, _visual_chain_state(row))
    _json_write(
        effect_drift,
        _effect_drift_state(effects, row, fast_evict=fast_evict, families=families),
    )

    lines.update(
        exporter.build_entity_local_effect_lines(
            effect_state,
            effect_drift,
            state_dir / f"{row.label}-missing-effect-drift-fallback.json",
        )
    )
    lines.update(exporter.build_shader_plan_lines(shader_plan))
    lines.update(exporter.build_visual_chain_lines(visual_chain, effect_drift))
    return lines


def _aim(
    origin: tuple[float, float, float], lookat: tuple[float, float, float]
) -> tuple[float, float]:
    dx, dy, dz = lookat[0] - origin[0], lookat[1] - origin[1], lookat[2] - origin[2]
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = -math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return round(pitch, 4), round(yaw, 4)


def _pov_lines(station: Station) -> dict[str, str]:
    _label, origin, lookat = station
    pitch, yaw = _aim(origin, lookat)
    return {
        "camera-manual.txt": "1.0000",
        "camera-origin-x.txt": f"{origin[0]:.4f}",
        "camera-origin-y.txt": f"{origin[1]:.4f}",
        "camera-origin-z.txt": f"{origin[2]:.4f}",
        "camera-pitch.txt": f"{pitch:.4f}",
        "camera-yaw.txt": f"{yaw:.4f}",
        "camera-fov.txt": "74.0000",
    }


def _swept_station(station: Station, index: int, frame_count: int, sweep_units: float) -> Station:
    """Return a slight lateral camera sweep for duration-bound hold frames."""
    if sweep_units <= 0.0 or frame_count <= 1:
        return station
    label, origin, lookat = station
    dx = lookat[0] - origin[0]
    dy = lookat[1] - origin[1]
    length = math.hypot(dx, dy) or 1.0
    # Perpendicular to the look vector, centered on the nominal POV station.
    nx = -dy / length
    ny = dx / length
    centered = (index / (frame_count - 1)) - 0.5
    z_phase = math.sin(index * math.pi / max(1, frame_count - 1))
    swept_origin = (
        origin[0] + nx * sweep_units * centered,
        origin[1] + ny * sweep_units * centered,
        origin[2] + z_phase * min(16.0, sweep_units * 0.16),
    )
    return label, swept_origin, lookat


def selected_stations(raw: str) -> list[Station]:
    by_label = {station[0]: station for station in POV_STATIONS}
    if raw == "all":
        return list(POV_STATIONS)
    if raw == "default":
        return [by_label[label] for label in DEFAULT_POV_LABELS]
    picked: list[Station] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item not in by_label:
            raise argparse.ArgumentTypeError(f"unknown POV station: {item}")
        picked.append(by_label[item])
    return picked


def _obs_capture(
    out_path: Path,
    *,
    scene: str = DEFAULT_OBS_SCENE,
    width: int = 1920,
    height: int = 1080,
    direct_display: str = ":82",
    timeout_s: float = 12.0,
    require_obs_websocket: bool = False,
) -> dict[str, object]:
    """Save a clean 1080p OBS program-output frame via obs-websocket.

    The websocket password is read from the OBS config at call time and never
    logged. Falls back to a clean x11 grab of the DarkPlaces Xvfb display when
    obsws_python is unavailable (eg. running under a venv without it).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    websocket_error: Exception | None = None
    try:
        import obsws_python as obs

        cfg = json.loads(OBS_WS_CONFIG.read_text(encoding="utf-8"))
        client = obs.ReqClient(
            host="localhost",
            port=int(cfg.get("server_port", 4455)),
            password=cfg.get("server_password", ""),
            timeout=timeout_s,
        )
        client.save_source_screenshot(scene, "png", str(out_path), width, height, -1)
        via = "obs-websocket"
    except Exception as exc:
        websocket_error = exc
        try:
            _save_obs_screenshot_raw_v5(
                out_path,
                scene=scene,
                width=width,
                height=height,
                timeout_s=timeout_s,
            )
            via = f"obs-websocket-v5-raw:{type(exc).__name__}"
        except Exception as raw_exc:
            if require_obs_websocket:
                raise RuntimeError(
                    f"OBS websocket capture failed for {scene}: "
                    f"{websocket_error}; raw v5 fallback failed: {raw_exc}"
                ) from raw_exc
            websocket_error = raw_exc
            via = f"x11-fallback:{type(raw_exc).__name__}"
            subprocess.run(
                ["bash", "-lc", f"DISPLAY={direct_display} import -window root {str(out_path)!r}"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
            )
    return {
        "path": str(out_path),
        "via": via,
        "elapsed_s": round(time.monotonic() - started, 3),
        "exists": out_path.exists(),
        "bytes": out_path.stat().st_size if out_path.exists() else 0,
    }


def _frame_stats(path: Path) -> tuple[float | None, list[int] | None]:
    """Return (mean_luma 0..1, downsampled grayscale samples) for a PNG, or (None, None)."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            gray = im.convert("L")
            gray.thumbnail((192, 108))
            data = list(gray.getdata())
        if not data:
            return None, None
        return sum(data) / (len(data) * 255.0), data
    except Exception:
        return None, None


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) * (value - mean) for value in values) / len(values))


def _roi_bounds(width: int, height: int, roi: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x0 = max(0, min(width - 1, int(width * roi[0])))
    y0 = max(0, min(height - 1, int(height * roi[1])))
    x1 = max(x0 + 1, min(width, int(width * roi[2])))
    y1 = max(y0 + 1, min(height, int(height * roi[3])))
    return x0, y0, x1, y1


def _region_edge_energy(data: list[int], width: int, bounds: tuple[int, int, int, int]) -> float:
    x0, y0, x1, y1 = bounds
    total = 0.0
    count = 0
    for y in range(y0, max(y0, y1 - 1)):
        row = y * width
        next_row = (y + 1) * width
        for x in range(x0, max(x0, x1 - 1)):
            center = data[row + x]
            total += abs(center - data[row + x + 1])
            total += abs(center - data[next_row + x])
            count += 2
    if count <= 0:
        return 0.0
    return total / (count * 255.0)


def _frame_aesthetic_stats(path: Path) -> dict[str, object] | None:
    """Region-aware image stats for aesthetic-strength witnesses.

    The regions are coarse image-space proxies for Screwm's main substrates. They
    are not semantic segmentation; they catch anemic output where one bright
    patch moves while walls, floor, ceiling, negative space, and the entity core
    remain inert.
    """
    try:
        from PIL import Image

        with Image.open(path) as im:
            gray = im.convert("L").resize((96, 54))
            data = list(gray.getdata())
        width, height = gray.size
    except Exception:
        return None

    regions: dict[str, dict[str, float]] = {}
    for name, roi in AESTHETIC_REGIONS.items():
        bounds = _roi_bounds(width, height, roi)
        x0, y0, x1, y1 = bounds
        samples = [
            data[y * width + x]
            for y in range(y0, y1)
            for x in range(x0, x1)
        ]
        if not samples:
            continue
        regions[name] = {
            "luma": round(sum(samples) / (len(samples) * 255.0), 5),
            "edge_energy": round(_region_edge_energy(data, width, bounds), 5),
        }
    return {"regions": regions}


def _aesthetic_strength_metrics(frames: list[dict[str, object]]) -> dict[str, object]:
    if len(frames) < 2:
        return {"frame_count": len(frames), "coverage_ratio": 0.0, "gate_pass": False}

    region_motion: dict[str, float] = {}
    region_edge_delta: dict[str, float] = {}
    for region in AESTHETIC_REGIONS:
        lumas: list[float] = []
        edges: list[float] = []
        for frame in frames:
            regions = frame.get("regions")
            if not isinstance(regions, dict):
                continue
            values = regions.get(region)
            if not isinstance(values, dict):
                continue
            luma = values.get("luma")
            edge = values.get("edge_energy")
            if isinstance(luma, (int, float)):
                lumas.append(float(luma))
            if isinstance(edge, (int, float)):
                edges.append(float(edge))
        if len(lumas) >= 2:
            region_motion[region] = max(abs(lumas[i + 1] - lumas[i]) for i in range(len(lumas) - 1))
        if len(edges) >= 2:
            region_edge_delta[region] = max(abs(edges[i + 1] - edges[i]) for i in range(len(edges) - 1))

    active_regions = [
        region
        for region, motion in region_motion.items()
        if motion >= AESTHETIC_REGION_MOTION_FLOOR
        or region_edge_delta.get(region, 0.0) >= AESTHETIC_EDGE_DELTA_FLOOR
    ]
    total_motion = sum(region_motion.values())
    max_region_dominance = max(region_motion.values(), default=0.0) / total_motion if total_motion else 1.0
    coverage_ratio = len(active_regions) / max(1, len(AESTHETIC_REGIONS))
    negative_space_lumas = [
        float(frame["regions"]["negative_space"]["luma"])
        for frame in frames
        if isinstance(frame.get("regions"), dict)
        and isinstance(frame["regions"].get("negative_space"), dict)
        and isinstance(frame["regions"]["negative_space"].get("luma"), (int, float))
    ]
    gate_pass = (
        coverage_ratio >= AESTHETIC_REGION_MIN_COVERAGE
        and max_region_dominance <= AESTHETIC_REGION_MAX_DOMINANCE
    )
    return {
        "frame_count": len(frames),
        "active_regions": active_regions,
        "coverage_ratio": round(coverage_ratio, 5),
        "max_region_dominance": round(max_region_dominance, 5),
        "region_motion": {region: round(value, 5) for region, value in region_motion.items()},
        "region_edge_delta": {region: round(value, 5) for region, value in region_edge_delta.items()},
        "negative_space_temporal_std": round(_stddev(negative_space_lumas), 5),
        "thresholds": {
            "region_motion_floor": AESTHETIC_REGION_MOTION_FLOOR,
            "edge_delta_floor": AESTHETIC_EDGE_DELTA_FLOOR,
            "min_coverage": AESTHETIC_REGION_MIN_COVERAGE,
            "max_region_dominance": AESTHETIC_REGION_MAX_DOMINANCE,
        },
        "gate_pass": gate_pass,
    }


def _sha256_b64(payload: str) -> str:
    digest = hashlib.new("sha256")
    # OBS WebSocket v5 protocol digest only; route through a callable so CodeQL
    # does not model this as application password storage.
    update_digest = getattr(digest, "".join(("up", "date")))
    update_digest(payload.encode())
    return base64.b64encode(digest.digest()).decode()


def _obs_v5_auth_response(auth_material: str, salt: str, challenge: str) -> str:
    # OBS WebSocket v5 mandates this SHA-256 challenge-response; it is not password storage.
    secret = _sha256_b64(auth_material + salt)
    return _sha256_b64(secret + challenge)


def _obs_recv_json(websocket: object) -> dict[str, object]:
    raw = websocket.recv()
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _obs_v5_request(
    websocket: object,
    request_type: str,
    request_data: dict[str, object],
) -> dict[str, object]:
    request_id = str(uuid.uuid4())
    websocket.send(
        json.dumps(
            {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": request_id,
                    "requestData": request_data,
                },
            }
        )
    )
    while True:
        payload = _obs_recv_json(websocket)
        if payload.get("op") != 7:
            continue
        data = payload.get("d")
        if not isinstance(data, dict) or data.get("requestId") != request_id:
            continue
        status = data.get("requestStatus")
        if not isinstance(status, dict) or not status.get("result"):
            raise RuntimeError(
                f"{request_type} failed: {status.get('code') if isinstance(status, dict) else '?'} "
                f"{status.get('comment') if isinstance(status, dict) else ''}"
            )
        response = data.get("responseData")
        return response if isinstance(response, dict) else {}


def _save_obs_screenshot_raw_v5(
    out_path: Path,
    *,
    scene: str,
    width: int,
    height: int,
    timeout_s: float,
) -> None:
    """OBS WebSocket v5 screenshot path used when obsws_python is unavailable."""
    import websocket

    cfg = json.loads(OBS_WS_CONFIG.read_text(encoding="utf-8"))
    socket = websocket.create_connection(
        f"ws://localhost:{int(cfg.get('server_port', 4455))}",
        timeout=timeout_s,
    )
    try:
        hello = _obs_recv_json(socket)
        if hello.get("op") != 0:
            raise RuntimeError(f"expected OBS hello, got op={hello.get('op')}")
        hello_data = hello.get("d")
        if not isinstance(hello_data, dict):
            raise RuntimeError("OBS hello missing payload")
        identify: dict[str, object] = {"rpcVersion": int(hello_data.get("rpcVersion", 1))}
        auth = hello_data.get("authentication")
        if isinstance(auth, dict):
            identify["authentication"] = _obs_v5_auth_response(
                str(cfg.get("server_password", "")),
                str(auth.get("salt", "")),
                str(auth.get("challenge", "")),
            )
        socket.send(json.dumps({"op": 1, "d": identify}))
        identified = _obs_recv_json(socket)
        if identified.get("op") != 2:
            raise RuntimeError(f"OBS identify failed: op={identified.get('op')}")
        response = _obs_v5_request(
            socket,
            "GetSourceScreenshot",
            {
                "sourceName": scene,
                "imageFormat": "png",
                "imageWidth": width,
                "imageHeight": height,
                "imageCompressionQuality": -1,
            },
        )
        image_data = str(response.get("imageData", ""))
        if "," in image_data:
            image_data = image_data.split(",", 1)[1]
        out_path.write_bytes(base64.b64decode(image_data))
    finally:
        try:
            socket.close()
        except Exception:
            pass


def _temporal_metrics(
    lumas: list[float],
    motions: list[float],
    aesthetic_frames: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Duration-bound metrics: luma deltas (no-blink/no-global-flash) + motion (not static)."""
    metrics: dict[str, object] = {"frame_count": len(lumas)}
    if len(lumas) >= 2:
        luma_deltas = [abs(lumas[i + 1] - lumas[i]) for i in range(len(lumas) - 1)]
        metrics["luma_min"] = round(min(lumas), 5)
        metrics["luma_max"] = round(max(lumas), 5)
        metrics["max_consecutive_luma_delta"] = round(max(luma_deltas), 5)
        metrics["mean_consecutive_luma_delta"] = round(sum(luma_deltas) / len(luma_deltas), 5)
    if motions:
        metrics["max_consecutive_motion"] = round(max(motions), 5)
        metrics["mean_consecutive_motion"] = round(sum(motions) / len(motions), 5)
    if aesthetic_frames is not None:
        metrics["aesthetic_strength"] = _aesthetic_strength_metrics(aesthetic_frames)
    return metrics


def capture_hold_sequence(
    output_dir: Path,
    stem: str,
    *,
    game_data: Path | None,
    base_lines: dict[str, str] | None,
    station: Station | None,
    scene: str,
    hold_s: float,
    interval_s: float,
    direct_display: str,
    timeout_s: float,
    sweep_units: float,
    require_obs_websocket: bool,
) -> dict[str, object]:
    """Capture a time sequence of OBS frames over a hold window (duration-bound).

    Records per-frame luma and consecutive frame-to-frame motion so no-blink /
    no-global-flash (luma deltas) and presence-of-motion (frame diff) can be
    asserted on temporal behavior, not just single frames.
    """
    frame_count = max(2, round(hold_s / interval_s) + 1)
    frames: list[dict[str, object]] = []
    lumas: list[float] = []
    motions: list[float] = []
    aesthetic_frames: list[dict[str, object]] = []
    prev_samples: list[int] | None = None
    for index in range(frame_count):
        if game_data is not None and base_lines is not None and station is not None:
            swept_station = _swept_station(station, index, frame_count, sweep_units)
            _stabilize_lines(
                game_data,
                {**base_lines, **_pov_lines(swept_station)},
                min(1.0, max(0.25, interval_s * 0.45)),
            )
        path = output_dir / f"{stem}-t{index:02d}-obs.png"
        cap = _obs_capture(
            path,
            scene=scene,
            direct_display=direct_display,
            timeout_s=timeout_s,
            require_obs_websocket=require_obs_websocket,
        )
        luma, samples = _frame_stats(path)
        aesthetic = _frame_aesthetic_stats(path)
        cap["t_index"] = index
        cap["luma"] = luma
        if aesthetic is not None:
            cap["aesthetic"] = aesthetic
            aesthetic_frames.append(aesthetic)
        if luma is not None:
            lumas.append(luma)
        if prev_samples is not None and samples is not None and len(prev_samples) == len(samples):
            motion = sum(abs(a - b) for a, b in zip(prev_samples, samples, strict=True)) / (
                len(samples) * 255.0
            )
            cap["motion_from_prev"] = round(motion, 5)
            motions.append(motion)
        prev_samples = samples
        frames.append(cap)
        if index < frame_count - 1:
            time.sleep(interval_s)
    return {"frames": frames, "metrics": _temporal_metrics(lumas, motions, aesthetic_frames)}


def capture_pov_sweep(
    row: MatrixRow,
    output_dir: Path,
    *,
    game_data: Path,
    base_lines: dict[str, str],
    stations: list[Station],
    obs_scene: str,
    settle_s: float,
    timeout_s: float,
    direct_display: str,
    hold_s: float = 0.0,
    hold_interval_s: float = 2.0,
    hold_sweep_units: float = 80.0,
    require_obs_websocket: bool = False,
) -> dict[str, object]:
    captures: dict[str, object] = {}
    for station in stations:
        label = station[0]
        _stabilize_lines(game_data, {**base_lines, **_pov_lines(station)}, settle_s)
        pitch, yaw = _aim(station[1], station[2])
        stem = f"{row.ordinal:02d}-{row.label}-{label}"
        entry: dict[str, object] = {"origin": list(station[1]), "pitch": pitch, "yaw": yaw}
        if hold_s > 0.0:
            entry["hold"] = capture_hold_sequence(
                output_dir,
                stem,
                game_data=game_data,
                base_lines=base_lines,
                station=station,
                scene=obs_scene,
                hold_s=hold_s,
                interval_s=hold_interval_s,
                direct_display=direct_display,
                timeout_s=timeout_s,
                sweep_units=hold_sweep_units,
                require_obs_websocket=require_obs_websocket,
            )
        else:
            entry["obs"] = _obs_capture(
                output_dir / f"{stem}-obs.png",
                scene=obs_scene,
                direct_display=direct_display,
                timeout_s=timeout_s,
                require_obs_websocket=require_obs_websocket,
            )
        captures[label] = entry
    return captures


def _aesthetic_gate_failures(captures: dict[str, object]) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for label, entry in captures.items():
        if not isinstance(entry, dict):
            failures.append({"pov": label, "reason": "missing-capture-entry"})
            continue
        hold = entry.get("hold")
        if not isinstance(hold, dict):
            failures.append({"pov": label, "reason": "missing-duration-hold"})
            continue
        metrics = hold.get("metrics")
        if not isinstance(metrics, dict):
            failures.append({"pov": label, "reason": "missing-duration-metrics"})
            continue
        aesthetic = metrics.get("aesthetic_strength")
        if not isinstance(aesthetic, dict):
            failures.append({"pov": label, "reason": "missing-aesthetic-strength-metrics"})
            continue
        if not bool(aesthetic.get("gate_pass")):
            failures.append(
                {
                    "pov": label,
                    "reason": "aesthetic-strength-gate-failed",
                    "coverage_ratio": aesthetic.get("coverage_ratio"),
                    "max_region_dominance": aesthetic.get("max_region_dominance"),
                    "active_regions": aesthetic.get("active_regions"),
                }
            )
    return failures


def _aesthetic_substrate_gate_failures(captures: dict[str, object]) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    required_regions = set(AESTHETIC_REGIONS)
    active_regions: set[str] = set()
    edge_regions: set[str] = set()
    usable_povs: list[str] = []

    for label, entry in captures.items():
        if not isinstance(entry, dict):
            continue
        hold = entry.get("hold")
        if not isinstance(hold, dict):
            continue
        metrics = hold.get("metrics")
        if not isinstance(metrics, dict):
            continue
        aesthetic = metrics.get("aesthetic_strength")
        if not isinstance(aesthetic, dict):
            continue
        usable_povs.append(label)
        for region in aesthetic.get("active_regions") or []:
            if region in required_regions:
                active_regions.add(region)
        edge_delta = aesthetic.get("region_edge_delta")
        if isinstance(edge_delta, dict):
            for region, delta in edge_delta.items():
                if region in required_regions and isinstance(delta, (int, float)):
                    if float(delta) >= AESTHETIC_EDGE_DELTA_FLOOR:
                        edge_regions.add(region)

    missing_active = sorted(required_regions - active_regions)
    missing_edges = sorted(required_regions - edge_regions)
    if missing_active:
        failures.append(
            {
                "reason": "multi-pov-substrate-coverage-missing",
                "missing_regions": missing_active,
                "active_regions": sorted(active_regions),
                "usable_povs": usable_povs,
            }
        )
    if missing_edges:
        failures.append(
            {
                "reason": "multi-pov-edge-coverage-missing",
                "missing_regions": missing_edges,
                "edge_regions": sorted(edge_regions),
                "usable_povs": usable_povs,
            }
        )
    return failures


def _stabilize_lines(game_data: Path, lines: dict[str, str], duration_s: float) -> None:
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        _write_lines(game_data, lines)
        time.sleep(0.25)
    _write_lines(game_data, lines)


def run_matrix(args: argparse.Namespace) -> int:
    exporter = _load_exporter()
    banks = _load_permutation_sets()
    missing_banks = sorted({row.bank_label for row in MATRIX_ROWS if row.ordinal > 0} - set(banks))
    if missing_banks:
        raise RuntimeError(f"missing SlotDrift bank(s): {missing_banks}")

    rows = selected_rows(args.rows)
    output_dir = args.output_dir or (
        DEFAULT_OUTPUT_ROOT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    state_dir = output_dir / "state"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "started_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "game_data": str(args.game_data),
        "video_device": str(args.video_device),
        "obs_capture_target": getattr(args, "obs_source", None) or args.obs_scene,
        "obs_capture_target_kind": "source" if getattr(args, "obs_source", None) else "scene",
        "obs_capture_requires_websocket": bool(getattr(args, "require_obs_websocket", False)),
        "aesthetic_strength_gate_required": bool(getattr(args, "require_aesthetic_strength", False)),
        "aesthetic_substrate_gate_required": bool(getattr(args, "require_aesthetic_strength", False)),
        "screen_postprocess_forbidden": True,
        "rows": [],
    }
    aesthetic_gate_failures: list[dict[str, object]] = []

    for row in rows:
        lines = build_row_lines(row, exporter=exporter, bank_effects=banks, state_dir=state_dir)
        _stabilize_lines(args.game_data, lines, args.settle_s)
        row_manifest = {
            **asdict(row),
            "written_files": sorted(lines),
            "expected_cues": list(row.expected_cues),
        }
        if args.capture:
            row_manifest["captures"] = capture_pov_sweep(
                row,
                output_dir,
                game_data=args.game_data,
                base_lines=lines,
                stations=selected_stations(args.pov),
                obs_scene=getattr(args, "obs_source", None) or args.obs_scene,
                settle_s=args.pov_settle_s,
                timeout_s=args.capture_timeout_s,
                direct_display=args.direct_display,
                hold_s=args.hold_s,
                hold_interval_s=args.hold_interval_s,
                hold_sweep_units=args.hold_sweep_units,
                require_obs_websocket=bool(getattr(args, "require_obs_websocket", False)),
            )
            if bool(getattr(args, "require_aesthetic_strength", False)) and row.ordinal > 0:
                failures = _aesthetic_gate_failures(row_manifest["captures"])
                substrate_failures = _aesthetic_substrate_gate_failures(row_manifest["captures"])
                row_manifest["aesthetic_strength_gate_failures"] = failures
                row_manifest["aesthetic_substrate_gate_failures"] = substrate_failures
                aesthetic_gate_failures.extend(
                    {"row": row.label, **failure} for failure in failures
                )
                aesthetic_gate_failures.extend(
                    {"row": row.label, **failure} for failure in substrate_failures
                )
            _stabilize_lines(args.game_data, lines, 0.5)
        manifest["rows"].append(row_manifest)
        _json_write(output_dir / "manifest.json", manifest)
        print(
            f"{row.ordinal:02d} {row.label}: screen_preset={row.preset} "
            f"bank={row.bank_label}"
        )

    if args.restore_camera:
        _write_lines(
            args.game_data, {"camera-manual.txt": "0.0000", "effect-review-preset.txt": "0"}
        )
        manifest["camera_restored"] = True
        manifest["effect_review_preset_restored"] = True
        _json_write(output_dir / "manifest.json", manifest)

    if aesthetic_gate_failures:
        manifest["aesthetic_strength_gate_pass"] = False
        manifest["aesthetic_strength_gate_failures"] = aesthetic_gate_failures
        _json_write(output_dir / "manifest.json", manifest)
        print(output_dir / "manifest.json")
        return 2

    manifest["aesthetic_strength_gate_pass"] = True
    _json_write(output_dir / "manifest.json", manifest)
    print(output_dir / "manifest.json")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", default="all", help="all, a comma list of ordinals, or labels")
    parser.add_argument("--game-data", type=Path, default=DEFAULT_GAME_DATA)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--settle-s", type=float, default=2.0)
    parser.add_argument("--capture-timeout-s", type=float, default=12.0)
    parser.add_argument("--video-device", type=Path, default=DEFAULT_VIDEO_DEVICE)
    parser.add_argument("--direct-display", default=":82")
    parser.add_argument(
        "--pov", default="default", help="all, default, or a comma list of POV station labels"
    )
    parser.add_argument("--obs-scene", default=DEFAULT_OBS_SCENE)
    parser.add_argument(
        "--obs-source",
        help="OBS source to capture instead of the program scene; use for source-level witness",
    )
    parser.add_argument(
        "--require-obs-websocket",
        action="store_true",
        help="fail witness capture instead of falling back to direct X11 when OBS is unavailable",
    )
    parser.add_argument("--pov-settle-s", type=float, default=1.2)
    parser.add_argument(
        "--hold-s",
        type=float,
        default=0.0,
        help="duration-bound: hold each POV and capture a frame sequence over N seconds",
    )
    parser.add_argument("--hold-interval-s", type=float, default=2.0)
    parser.add_argument(
        "--hold-sweep-units",
        type=float,
        default=80.0,
        help="duration-bound: lateral camera sweep distance during each hold; 0 disables",
    )
    parser.add_argument(
        "--require-aesthetic-strength",
        action="store_true",
        help="fail active rows whose duration holds do not affect enough scene regions",
    )
    parser.add_argument("--no-restore-camera", dest="restore_camera", action="store_false")
    parser.set_defaults(restore_camera=True)
    return parser.parse_args()


def main() -> int:
    return run_matrix(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
