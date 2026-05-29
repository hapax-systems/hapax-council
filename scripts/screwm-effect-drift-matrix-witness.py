#!/usr/bin/env python3
"""Drive representative Screwm effect/drift combinations and capture witnesses.

The matrix is deliberately bounded: each DarkPlaces postprocess preset is paired
with one existing SlotDrift permutation bank. This proves the aggregate route
without exploding into a cosmetic cross product.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import runpy
import subprocess
import time
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
        1,
        "alpha-line-tonal-trail",
        (
            "cyan/magenta lattice is visible but does not bury media",
            "tonal/trail state lights register on source planes",
        ),
    ),
    MatrixRow(
        2,
        "prism-beta",
        2,
        "beta-rutt-key-recursion",
        (
            "strong prism separation at high-contrast edges",
            "recursion/temporal bank remains bounded",
        ),
    ),
    MatrixRow(
        3,
        "feedback-gamma",
        3,
        "gamma-mask-detail-temporal",
        (
            "noise and smear are visible as drift pressure",
            "detail transforms do not collapse the room into mush",
        ),
    ),
    MatrixRow(
        4,
        "halftone-delta",
        4,
        "delta-map-slit-geometry",
        (
            "posterize/halftone pressure is legible",
            "geometry/motion bank reads as spatial lighting",
        ),
    ),
    MatrixRow(
        5,
        "emboss-epsilon",
        5,
        "epsilon-palette-particle-fluid",
        (
            "material/aperture/thermal pressure is visible",
            "palette and particle/fluid bank stays inside the scroom",
        ),
    ),
    MatrixRow(
        6,
        "threshold-zeta",
        6,
        "zeta-breath-reaction-wave",
        (
            "threshold/inversion stress is controlled",
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

    lines.update(exporter.build_entity_local_effect_lines(effect_state))
    lines.update(exporter.build_shader_plan_lines(shader_plan))
    lines.update(exporter.build_visual_chain_lines(visual_chain, effect_drift))
    return lines


def _capture(command: list[str], output_path: Path, *, timeout_s: float) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    proc = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_s,
        check=False,
    )
    return {
        "path": str(output_path),
        "returncode": proc.returncode,
        "elapsed_s": round(time.monotonic() - started, 3),
        "output": proc.stdout[-1200:],
        "exists": output_path.exists(),
        "bytes": output_path.stat().st_size if output_path.exists() else 0,
    }


def capture_witnesses(
    row: MatrixRow,
    output_dir: Path,
    *,
    video_device: Path,
    direct_display: str,
    timeout_s: float,
) -> dict[str, object]:
    obs_path = output_dir / f"{row.ordinal:02d}-{row.label}-obs.png"
    direct_path = output_dir / f"{row.ordinal:02d}-{row.label}-video52.png"
    x11_path = output_dir / f"{row.ordinal:02d}-{row.label}-x11.png"
    captures: dict[str, object] = {
        "obs": _capture(
            ["spectacle", "-b", "-n", "-o", str(obs_path)], obs_path, timeout_s=timeout_s
        )
    }
    if video_device.exists():
        captures["video52"] = _capture(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "v4l2",
                "-video_size",
                "1920x1080",
                "-i",
                str(video_device),
                "-frames:v",
                "1",
                "-update",
                "1",
                str(direct_path),
            ],
            direct_path,
            timeout_s=timeout_s,
        )
    captures["x11"] = _capture(
        ["bash", "-lc", f"DISPLAY={direct_display} import -window root {str(x11_path)!r}"],
        x11_path,
        timeout_s=timeout_s,
    )
    return captures


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
        "rows": [],
    }

    for row in rows:
        lines = build_row_lines(row, exporter=exporter, bank_effects=banks, state_dir=state_dir)
        _stabilize_lines(args.game_data, lines, args.settle_s)
        row_manifest = {
            **asdict(row),
            "written_files": sorted(lines),
            "expected_cues": list(row.expected_cues),
        }
        if args.capture:
            row_manifest["captures"] = capture_witnesses(
                row,
                output_dir,
                video_device=args.video_device,
                direct_display=args.direct_display,
                timeout_s=args.capture_timeout_s,
            )
            _stabilize_lines(args.game_data, lines, 0.5)
        manifest["rows"].append(row_manifest)
        _json_write(output_dir / "manifest.json", manifest)
        print(f"{row.ordinal:02d} {row.label}: preset={row.preset} bank={row.bank_label}")

    if args.restore_camera:
        _write_lines(
            args.game_data, {"camera-manual.txt": "0.0000", "effect-review-preset.txt": "0"}
        )
        manifest["camera_restored"] = True
        manifest["effect_review_preset_restored"] = True
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
    parser.add_argument("--no-restore-camera", dest="restore_camera", action="store_false")
    parser.set_defaults(restore_camera=True)
    return parser.parse_args()


def main() -> int:
    return run_matrix(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
