#!/usr/bin/env python3
"""Exercise six stratified live-effect permutation sets.

This is an incident tool, not a taste tuner. It constrains the autonomous Rust
drift engine to one sampled set at a time, captures paired pre-FX/final frames,
then removes the constraint so the repaired inventory can run normally.
"""

from __future__ import annotations

import argparse
import atexit
import fcntl
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EFFECT_DRIFT_RS = REPO_ROOT / "hapax-logos/crates/hapax-visual/src/effect_drift.rs"
DROPIN = (
    Path.home() / ".config/systemd/user/hapax-imagination.service.d/effect-permutation-audit.conf"
)
PLAN_JSON = Path("/dev/shm/hapax-imagination/pipeline/plan.json")
EFFECT_DRIFT_STATE_JSON = Path("/dev/shm/hapax-visual/effect-drift-state.json")
SUMMARY_ROOT = Path.home() / ".cache/hapax/screenshots/paired-fx-audit/effect-permutation-bank"
LOCK_PATH = Path.home() / ".cache/hapax/locks/live-effect-permutation-audit.lock"
NON_AUTONOMOUS_EFFECTS = {"solid"}
_CLEANED_UP = False
_LOCK_FH = None


@dataclass(frozen=True)
class PermutationSet:
    label: str
    seed: int
    effects: tuple[str, ...]


# Six sampled sets. The union covers every autonomous shader in
# effect_drift.rs at least once. Each set also carries every high-level family
# needed for a meaningful live-surface pass: tonal, texture, edge, atmospheric,
# temporal, and compositing. Duplicates are intentional where a family has fewer
# members than the number of sets.
PERMUTATION_SETS: tuple[PermutationSet, ...] = (
    PermutationSet(
        "alpha-line-tonal-trail",
        0xA11CE001,
        (
            "colorgrade",
            "bloom",
            "drift",
            "ascii",
            "vhs",
            "edge_detect",
            "trail",
            "blend",
            "warp",
            "scanlines",
        ),
    ),
    PermutationSet(
        "beta-rutt-key-recursion",
        0xA11CE002,
        (
            "invert",
            "thermal",
            "rutt_etra",
            "glitch_block",
            "dither",
            "echo",
            "chroma_key",
            "droste",
            "fisheye",
            "posterize",
        ),
    ),
    PermutationSet(
        "gamma-mask-detail-temporal",
        0xA11CE003,
        (
            "vignette",
            "halftone",
            "grain_bump",
            "kaleidoscope",
            "kuwahara",
            "noise_overlay",
            "stutter",
            "crossfade",
            "diff",
            "nightvision_tint",
            "scanlines",
            "threshold",
            "tile",
        ),
    ),
    PermutationSet(
        "delta-map-slit-geometry",
        0xA11CE004,
        (
            "chromatic_aberration",
            "emboss",
            "mirror",
            "color_map",
            "transform",
            "voronoi_overlay",
            "slitscan",
            "luma_key",
            "noise_gen",
            "threshold",
            "echo",
        ),
    ),
    PermutationSet(
        "epsilon-palette-particle-fluid",
        0xA11CE005,
        (
            "palette",
            "palette_remap",
            "palette_extract",
            "displacement_map",
            "pixsort",
            "circular_mask",
            "particle_system",
            "tunnel",
            "fluid_sim",
            "edge_detect",
            "blend",
            "vhs",
            "posterize",
        ),
    ),
    PermutationSet(
        "zeta-breath-reaction-wave",
        0xA11CE006,
        (
            "sharpen",
            "breathing",
            "syrup",
            "reaction_diffusion",
            "strobe",
            "waveform_render",
            "blend",
            "trail",
            "vhs",
            "drift",
            "colorgrade",
            "ascii",
        ),
    ),
)

TEMPORAL = {
    "trail",
    "echo",
    "stutter",
    "diff",
    "slitscan",
    "fluid_sim",
    "reaction_diffusion",
}
LINE_OR_JITTER = {"vhs", "scanlines", "rutt_etra", "slitscan", "glitch_block"}
DETAIL = {
    "ascii",
    "dither",
    "grain_bump",
    "halftone",
    "posterize",
    "threshold",
    "kuwahara",
    "thermal",
}
NOISE_OR_PARTICLE = {"noise_overlay", "noise_gen", "particle_system", "glitch_block"}
COMPOSITE_OR_MASK = {
    "blend",
    "chroma_key",
    "crossfade",
    "luma_key",
    "circular_mask",
    "displacement_map",
}
TONAL = {
    "colorgrade",
    "bloom",
    "invert",
    "thermal",
    "posterize",
    "color_map",
    "palette",
    "palette_remap",
    "nightvision_tint",
    "syrup",
}
FAST_EVICT = {
    "ascii",
    "chromatic_aberration",
    "displacement_map",
    "droste",
    "fisheye",
    "fluid_sim",
    "glitch_block",
    "kaleidoscope",
    "mirror",
    "noise_gen",
    "palette_extract",
    "particle_system",
    "pixsort",
    "reaction_diffusion",
    "rutt_etra",
    "slitscan",
    "strobe",
    "stutter",
    "tile",
    "transform",
    "tunnel",
    "vhs",
    "warp",
    "waveform_render",
}


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def parse_shader_table() -> dict[str, dict[str, object]]:
    source = EFFECT_DRIFT_RS.read_text(encoding="utf-8")
    table = source.split("pub static SHADERS:", 1)[1].split("pub static FEEDBACK_DEF", 1)[0]
    out: dict[str, dict[str, object]] = {}
    pattern = re.compile(
        r'ShaderDef\s*\{.*?name:\s*"([^"]+)".*?family:\s*"([^"]+)".*?is_spatial:\s*(true|false)',
        re.S,
    )
    for name, family, is_spatial in pattern.findall(table):
        if name in NON_AUTONOMOUS_EFFECTS:
            continue
        out[name] = {"family": family, "is_spatial": is_spatial == "true"}
    return out


def dimensions_for(
    effects: tuple[str, ...], shader_table: dict[str, dict[str, object]]
) -> set[str]:
    dims = {str(shader_table[name]["family"]) for name in effects}
    if any(bool(shader_table[name]["is_spatial"]) for name in effects):
        dims.add("spatial")
    if set(effects) & TEMPORAL:
        dims.add("temporal_accumulator")
    if set(effects) & LINE_OR_JITTER:
        dims.add("line_or_jitter")
    if set(effects) & DETAIL:
        dims.add("detail_transform")
    if set(effects) & NOISE_OR_PARTICLE:
        dims.add("noise_or_particle")
    if set(effects) & COMPOSITE_OR_MASK:
        dims.add("composite_or_mask")
    if set(effects) & TONAL:
        dims.add("tonal_transform")
    if set(effects) & FAST_EVICT:
        dims.add("fast_evict")
    return dims


def validate_sets(shader_table: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    known = set(shader_table)
    union: set[str] = set()
    reports: list[dict[str, object]] = []
    required_per_set = {
        "tonal",
        "texture",
        "edge",
        "atmospheric",
        "temporal",
        "compositing",
        "spatial",
        "temporal_accumulator",
        "line_or_jitter",
        "detail_transform",
        "composite_or_mask",
        "tonal_transform",
        "fast_evict",
    }

    for spec in PERMUTATION_SETS:
        effects = set(spec.effects)
        unknown = sorted(effects - known)
        if unknown:
            raise SystemExit(f"{spec.label}: unknown effect(s): {unknown}")
        dims = dimensions_for(spec.effects, shader_table)
        missing = sorted(required_per_set - dims)
        if missing:
            raise SystemExit(f"{spec.label}: missing required dimensions: {missing}")
        if len(spec.effects) < 8:
            raise SystemExit(f"{spec.label}: too small to support rotation: {len(spec.effects)}")
        union |= effects
        reports.append(
            {
                "label": spec.label,
                "seed": spec.seed,
                "effects": list(spec.effects),
                "dimensions": sorted(dims),
            }
        )

    missing_from_bank = sorted(known - union)
    if missing_from_bank:
        raise SystemExit(f"permutation bank does not cover shader inventory: {missing_from_bank}")
    return reports


def write_dropin(spec: PermutationSet) -> None:
    DROPIN.parent.mkdir(parents=True, exist_ok=True)
    effects = ",".join(spec.effects)
    DROPIN.write_text(
        "\n".join(
            [
                "[Service]",
                f"Environment=HAPAX_EFFECT_DRIFT_ALLOWED_SET={effects}",
                f"Environment=HAPAX_EFFECT_DRIFT_SEED={spec.seed}",
                "Environment=HAPAX_EFFECT_DRIFT_DETERMINISTIC=1",
                "",
            ]
        ),
        encoding="utf-8",
    )


def remove_dropin() -> None:
    if DROPIN.exists():
        DROPIN.unlink()


def release_full_inventory() -> None:
    global _CLEANED_UP
    if _CLEANED_UP:
        return
    _CLEANED_UP = True
    remove_dropin()
    restart_imagination()


def handle_termination(signum: int, _frame: object) -> None:
    try:
        release_full_inventory()
    finally:
        raise SystemExit(128 + signum)


def acquire_singleton_lock() -> None:
    global _LOCK_FH
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_FH = LOCK_PATH.open("w", encoding="utf-8")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise SystemExit(
            f"another live-effect-permutation-audit is already running: {LOCK_PATH}"
        ) from exc
    _LOCK_FH.write(f"{os.getpid()}\n")
    _LOCK_FH.flush()


def restart_imagination() -> None:
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "stop", "hapax-imagination.service"], check=False)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        state = run(
            ["systemctl", "--user", "is-active", "hapax-imagination.service"],
            check=False,
        ).stdout.strip()
        if state in {"inactive", "failed", "unknown"}:
            break
        time.sleep(0.25)
    run(["systemctl", "--user", "start", "hapax-imagination.service"])
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        state = run(
            ["systemctl", "--user", "is-active", "hapax-imagination.service"],
            check=False,
        ).stdout.strip()
        if state == "active":
            return
        time.sleep(0.25)
    raise RuntimeError("hapax-imagination.service did not become active after restart")


def wait_for_plan_subset(spec: PermutationSet, timeout_s: float = 20.0) -> list[str]:
    allowed = set(spec.effects) | {"fb", "post"}
    deadline = time.monotonic() + timeout_s
    last_nodes: list[str] = []
    while time.monotonic() < deadline:
        if PLAN_JSON.exists():
            try:
                raw = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
                passes = raw["targets"]["main"]["passes"]
                last_nodes = [entry["node_id"] for entry in passes]
                if last_nodes and set(last_nodes).issubset(allowed):
                    return last_nodes
            except (KeyError, json.JSONDecodeError, OSError):
                pass
        time.sleep(0.5)
    raise RuntimeError(
        f"plan did not constrain to {spec.label}; last nodes={last_nodes}, allowed={sorted(allowed)}"
    )


def run_paired_audit(
    spec: PermutationSet,
    duration: float,
    interval_ms: int,
    *,
    round_index: int,
) -> tuple[str, Path]:
    label = f"permutation-{spec.label}-r{round_index:02d}"
    proc = run(
        [
            "scripts/compositor-paired-frame-audit.sh",
            label,
            "--duration",
            str(duration),
            "--interval-ms",
            str(interval_ms),
        ]
    )
    match = re.search(r"\| directory \| `([^`]+)` \|", proc.stdout)
    if not match:
        raise RuntimeError(f"{spec.label}: paired audit did not report an output directory")
    return proc.stdout, Path(match.group(1))


def observed_nodes_from_audit_dir(audit_dir: Path) -> set[str]:
    observed: set[str] = set()
    for state_path in sorted(audit_dir.glob("effect_state-*.json")):
        observed |= observed_nodes_from_effect_state_file(state_path)
    return observed


def observed_nodes_from_effect_state_file(state_path: Path) -> set[str]:
    observed: set[str] = set()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return observed
    for entry in state.get("passes", []):
        node_id = entry.get("node_id")
        if isinstance(node_id, str) and node_id not in {"fb", "post"}:
            observed.add(node_id)
    return observed


def sample_runtime_effect_state(duration_s: float, interval_s: float = 1.0) -> set[str]:
    observed: set[str] = set()
    deadline = time.monotonic() + max(0.0, duration_s)
    while time.monotonic() < deadline:
        observed |= observed_nodes_from_effect_state_file(EFFECT_DRIFT_STATE_JSON)
        time.sleep(max(0.25, interval_s))
    observed |= observed_nodes_from_effect_state_file(EFFECT_DRIFT_STATE_JSON)
    return observed


def plan_nodes() -> set[str]:
    observed: set[str] = set()
    try:
        raw = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
        passes = raw["targets"]["main"]["passes"]
    except (KeyError, json.JSONDecodeError, OSError):
        return observed
    for entry in passes:
        node_id = entry.get("node_id")
        if isinstance(node_id, str) and node_id not in {"fb", "post"}:
            observed.add(node_id)
    return observed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate and print sets only")
    parser.add_argument("--duration", type=float, default=45.0)
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=4,
        help="maximum paired-capture rounds per set while waiting for every set member to appear",
    )
    parser.add_argument(
        "--no-require-set-coverage",
        action="store_true",
        help="do not fail if some eligible effects in a set never appear in captured runtime state",
    )
    parser.add_argument(
        "--state-followup-s",
        type=float,
        default=45.0,
        help=(
            "seconds to sample live effect-drift state after each paired capture; "
            "covers rotations that occur while image metrics are being processed"
        ),
    )
    parser.add_argument(
        "--only-set",
        action="append",
        default=[],
        metavar="LABEL",
        help="run only the named permutation set; may be supplied more than once",
    )
    parser.add_argument(
        "--ad-hoc-label",
        default="ad-hoc-effect-coverage",
        help="label for an ad hoc exact effect set supplied with --ad-hoc-effects",
    )
    parser.add_argument(
        "--ad-hoc-effects",
        default="",
        help=(
            "comma-separated exact effect set for targeted coverage; must contain at "
            f"least {len(PERMUTATION_SETS[0].effects[:5])} known autonomous effects"
        ),
    )
    parser.add_argument(
        "--ad-hoc-seed",
        type=lambda value: int(value, 0),
        default=0xA11CE777,
        help="deterministic seed for --ad-hoc-effects; accepts decimal or 0x-prefixed hex",
    )
    parser.add_argument(
        "--leave-constrained",
        action="store_true",
        help="leave the last permutation constraint installed instead of letting all effects loose",
    )
    parser.add_argument(
        "--confirm-live-service-control",
        action="store_true",
        help=(
            "required for non-dry-run execution; this tool restarts and temporarily "
            "constrains hapax-imagination.service"
        ),
    )
    args = parser.parse_args()

    shader_table = parse_shader_table()
    reports = validate_sets(shader_table)
    available_sets = list(PERMUTATION_SETS)
    if args.ad_hoc_effects:
        effects = tuple(name.strip() for name in args.ad_hoc_effects.split(",") if name.strip())
        unknown_effects = sorted(set(effects) - set(shader_table))
        if unknown_effects:
            raise SystemExit(f"unknown --ad-hoc-effects node(s): {unknown_effects}")
        if len(effects) < 5:
            raise SystemExit("--ad-hoc-effects needs at least 5 known autonomous effects")
        ad_hoc = PermutationSet(args.ad_hoc_label, args.ad_hoc_seed, effects)
        available_sets.append(ad_hoc)
        reports.append(
            {
                "label": ad_hoc.label,
                "seed": ad_hoc.seed,
                "effects": list(ad_hoc.effects),
                "dimensions": sorted(dimensions_for(ad_hoc.effects, shader_table)),
                "ad_hoc": True,
            }
        )

    selected_labels = set(args.only_set)
    if args.ad_hoc_effects and not selected_labels:
        selected_labels.add(args.ad_hoc_label)
    known_labels = {spec.label for spec in available_sets}
    unknown_labels = sorted(selected_labels - known_labels)
    if unknown_labels:
        raise SystemExit(f"unknown --only-set label(s): {unknown_labels}")
    selected_sets = tuple(
        spec for spec in available_sets if not selected_labels or spec.label in selected_labels
    )
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary_dir = SUMMARY_ROOT / started
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {
        "started_at_utc": started,
        "repo": str(REPO_ROOT),
        "dropin": str(DROPIN),
        "sets": reports,
        "selected_sets": [spec.label for spec in selected_sets],
        "runs": [],
    }
    incomplete_sets: list[dict[str, object]] = []

    print(json.dumps({"sets": reports}, indent=2))
    if args.dry_run:
        (summary_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"dry-run summary: {summary_dir / 'summary.json'}")
        return 0
    if not args.confirm_live_service_control:
        raise SystemExit("refusing live service control without --confirm-live-service-control")

    acquire_singleton_lock()
    if not args.leave_constrained:
        atexit.register(release_full_inventory)
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, handle_termination)

    try:
        for spec in selected_sets:
            print(f"\n== {spec.label} ==")
            write_dropin(spec)
            restart_imagination()
            try:
                nodes = wait_for_plan_subset(spec)
            except RuntimeError:
                restart_imagination()
                nodes = wait_for_plan_subset(spec, timeout_s=35.0)
            print(f"plan: {' -> '.join(nodes)}")
            observed: set[str] = set()
            rounds: list[dict[str, object]] = []
            for round_index in range(1, args.max_rounds + 1):
                audit_stdout, audit_dir = run_paired_audit(
                    spec,
                    args.duration,
                    args.interval_ms,
                    round_index=round_index,
                )
                print(audit_stdout)
                round_observed = observed_nodes_from_audit_dir(audit_dir)
                plan_observed = plan_nodes() & set(spec.effects)
                followup_observed = sample_runtime_effect_state(args.state_followup_s) & set(
                    spec.effects
                )
                round_total_observed = round_observed | plan_observed | followup_observed
                observed |= round_total_observed
                missing = sorted(set(spec.effects) - observed)
                rounds.append(
                    {
                        "round": round_index,
                        "audit_dir": str(audit_dir),
                        "observed": sorted(round_observed),
                        "observed_in_current_plan": sorted(plan_observed),
                        "observed_in_followup_state": sorted(followup_observed),
                        "observed_round_total": sorted(round_total_observed),
                        "observed_cumulative": sorted(observed),
                        "missing_after_round": missing,
                    }
                )
                print(
                    "coverage: "
                    f"{len(set(spec.effects) - set(missing))}/{len(spec.effects)} "
                    f"observed; missing={missing}"
                )
                if not missing or args.no_require_set_coverage:
                    break
            missing_final = sorted(set(spec.effects) - observed)
            if missing_final and not args.no_require_set_coverage:
                incomplete_sets.append(
                    {
                        "label": spec.label,
                        "missing_effects": missing_final,
                        "max_rounds": args.max_rounds,
                    }
                )
                print(
                    "coverage incomplete: "
                    f"{spec.label} missing {missing_final} after {args.max_rounds} round(s); "
                    "continuing to the remaining sets"
                )
            summary["runs"].append(
                {
                    "label": spec.label,
                    "seed": spec.seed,
                    "plan_nodes": nodes,
                    "observed_effects": sorted(observed),
                    "missing_effects": missing_final,
                    "coverage_complete": not missing_final,
                    "rounds": rounds,
                }
            )
            summary["incomplete_sets"] = incomplete_sets
            (summary_dir / "summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
    finally:
        if not args.leave_constrained:
            release_full_inventory()
            summary["released_full_inventory_at_utc"] = datetime.now(UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            (summary_dir / "summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )

    if incomplete_sets and not args.no_require_set_coverage:
        print(f"coverage incomplete after all sets: {incomplete_sets}")
        return 1

    print(f"summary: {summary_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
