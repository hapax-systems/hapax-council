#!/usr/bin/env python3
"""Inventory every known live visual effect surface and fail on static drift.

This is not a visual-quality classifier. It is the coverage gate that answers:
"what can reach the livestream image?" The compositor has grown several
activation paths outside the obvious ``presets/*.json`` corpus: home preset
overrides, direct graph-mutation files, hero fragments, transition primitives,
ward/Cairo overlays, Reverie/imagination SHM outputs, and a legacy ``studio_fx``
service path. The audit keeps those surfaces visible so incident restoration
cannot accidentally fix one path while leaving another outside review.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
HOME_PRESET_ROOT = Path.home() / ".config" / "hapax" / "effect-presets"
NON_GRAPH_PRESET_FILES = frozenset({"shader_intensity_bounds.json"})
RUNTIME_FILES = (
    "/dev/shm/hapax-compositor/fx-current.txt",
    "/dev/shm/hapax-compositor/fx-request.txt",
    "/dev/shm/hapax-compositor/graph-mutation.json",
    "/dev/shm/hapax-compositor/current-layout-state.json",
    "/dev/shm/hapax-compositor/active_wards.json",
    "/dev/shm/hapax-compositor/ward-properties.json",
    "/dev/shm/hapax-compositor/recent-recruitment.json",
    "/dev/shm/hapax-compositor/hero-effect-current.txt",
    "/dev/shm/hapax-sources/reverie.rgba",
    "/dev/shm/hapax-imagination/pipeline/plan.json",
)

BANNED_GLOBAL_LUMA_PARAMS = frozenset(
    {
        "brightness",
        "intensity",
        "opacity",
        "alpha",
        "master_opacity",
        "strength",
        "flash",
        "dim",
        "pulse",
    }
)
AUDIO_SOURCE_PREFIXES = ("audio_", "music.", "audio.", "broadcast.")

RISK_NODE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "noise_gen": ("full_frame_replacement", "static_entropy"),
    "noise_overlay": ("full_frame_noise", "static_entropy"),
    "voronoi_overlay": ("full_frame_texture",),
    "particle_system": ("full_frame_texture",),
    "glitch_block": ("geometry_fragmentation", "temporal_jitter"),
    "pixsort": ("geometry_reordering",),
    "slitscan": ("geometry_reordering", "temporal_accumulator"),
    "stutter": ("temporal_accumulator", "temporal_jitter"),
    "feedback": ("temporal_accumulator",),
    "trail": ("temporal_accumulator",),
    "echo": ("temporal_accumulator",),
    "drift": ("geometry_distortion",),
    "displacement_map": ("geometry_distortion", "multi_input_binding"),
    "warp": ("geometry_distortion",),
    "fisheye": ("geometry_distortion",),
    "rutt_etra": ("geometry_distortion",),
    "fluid_sim": ("geometry_distortion", "temporal_accumulator"),
    "reaction_diffusion": ("geometry_distortion", "temporal_accumulator"),
    "circular_mask": ("large_mask", "alpha_cutout"),
    "chroma_key": ("alpha_cutout",),
    "luma_key": ("alpha_cutout",),
    "threshold": ("detail_loss", "large_mask"),
    "strobe": ("full_frame_luma",),
    "vignette": ("global_luma_multiply",),
    "postprocess": ("global_postprocess",),
    "posterize": ("detail_loss",),
    "thermal": ("detail_loss", "false_color"),
    "ascii": ("detail_loss",),
    "halftone": ("detail_loss",),
    "dither": ("detail_loss",),
    "kuwahara": ("detail_loss",),
    "vhs": ("line_jitter", "static_entropy"),
    "scanlines": ("line_jitter",),
    "transform": ("geometry_transform",),
    "tile": ("geometry_repetition",),
    "kaleidoscope": ("geometry_repetition",),
    "mirror": ("geometry_repetition",),
    "tunnel": ("geometry_repetition",),
    "droste": ("geometry_repetition",),
    "breathing": ("global_motion",),
}


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as exc:
        return None, f"{type(exc).__name__}:{exc}"
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError:{exc}"


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _string_constant(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _strings_from_sequence(node: ast.AST | None) -> list[str]:
    if not isinstance(node, ast.Tuple | ast.List):
        return []
    out: list[str] = []
    for item in node.elts:
        value = _string_constant(item)
        if value is None:
            return []
        out.append(value)
    return out


def _preset_family_strings(node: ast.AST | None) -> list[str]:
    if not isinstance(node, ast.Call):
        return []
    for keyword in node.keywords:
        if keyword.arg == "presets":
            return _strings_from_sequence(keyword.value)
    return []


def _iter_assignments(tree: ast.Module, name: str) -> list[ast.AST]:
    values: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            continue
        if value is None:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            values.append(value)
    return values


def _extract_visual_governance(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "agents" / "effect_graph" / "visual_governance.py"
    payload: dict[str, Any] = {
        "path": _rel(path, repo_root),
        "exists": path.is_file(),
        "state_matrix": {},
        "default_family": [],
        "genre_bias": {},
        "referenced_presets": [],
        "missing_presets": [],
        "parse_error": None,
    }
    if not path.is_file():
        payload["parse_error"] = "missing"
        return payload
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        payload["parse_error"] = f"{type(exc).__name__}:{exc}"
        return payload

    referenced: set[str] = set()
    for value in _iter_assignments(tree, "_STATE_MATRIX"):
        if not isinstance(value, ast.Dict):
            continue
        for key_node, family_node in zip(value.keys, value.values, strict=True):
            try:
                key = ast.unparse(key_node) if key_node is not None else "<none>"
            except Exception:
                key = "<unparseable>"
            presets = _preset_family_strings(family_node)
            if presets:
                payload["state_matrix"][key] = presets
                referenced.update(presets)

    for value in _iter_assignments(tree, "_DEFAULT_FAMILY"):
        presets = _preset_family_strings(value)
        if presets:
            payload["default_family"] = presets
            referenced.update(presets)

    for value in _iter_assignments(tree, "_GENRE_BIAS"):
        if not isinstance(value, ast.Dict):
            continue
        for key_node, presets_node in zip(value.keys, value.values, strict=True):
            key = _string_constant(key_node)
            presets = _strings_from_sequence(presets_node)
            if key is not None and presets:
                payload["genre_bias"][key] = presets
                referenced.update(presets)

    payload["referenced_presets"] = sorted(referenced)
    return payload


def _extract_transition_primitives(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "agents" / "studio_compositor" / "transition_primitives.py"
    payload: dict[str, Any] = {
        "path": _rel(path, repo_root),
        "exists": path.is_file(),
        "transition_names": [],
        "primitive_keys": [],
        "missing_primitives": [],
        "extra_primitives": [],
        "parse_error": None,
    }
    if not path.is_file():
        payload["parse_error"] = "missing"
        return payload
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        payload["parse_error"] = f"{type(exc).__name__}:{exc}"
        return payload

    for value in _iter_assignments(tree, "TRANSITION_NAMES"):
        names = _strings_from_sequence(value)
        if names:
            payload["transition_names"] = names
    for value in _iter_assignments(tree, "PRIMITIVES"):
        if not isinstance(value, ast.Dict):
            continue
        keys = [_string_constant(key) for key in value.keys]
        payload["primitive_keys"] = sorted(key for key in keys if key is not None)

    names = set(payload["transition_names"])
    keys = set(payload["primitive_keys"])
    payload["missing_primitives"] = sorted(names - keys)
    payload["extra_primitives"] = sorted(keys - names)
    return payload


def _extract_preset_family_selector(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "agents" / "studio_compositor" / "preset_family_selector.py"
    payload: dict[str, Any] = {
        "path": _rel(path, repo_root),
        "exists": path.is_file(),
        "families": {},
        "referenced_presets": [],
        "missing_presets": [],
        "orphaned_presets": [],
        "duplicate_memberships": {},
        "parse_error": None,
    }
    if not path.is_file():
        payload["parse_error"] = "missing"
        return payload
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        payload["parse_error"] = f"{type(exc).__name__}:{exc}"
        return payload

    families: dict[str, list[str]] = {}
    for value in _iter_assignments(tree, "FAMILY_PRESETS"):
        if not isinstance(value, ast.Dict):
            continue
        for key_node, presets_node in zip(value.keys, value.values, strict=True):
            family = _string_constant(key_node)
            presets = _strings_from_sequence(presets_node)
            if family is not None and presets:
                families[family] = presets

    reverse: dict[str, list[str]] = {}
    for family, presets in families.items():
        for preset in presets:
            reverse.setdefault(preset, []).append(family)
    payload["families"] = families
    payload["referenced_presets"] = sorted(reverse)
    payload["duplicate_memberships"] = {
        preset: sorted(families_for_preset)
        for preset, families_for_preset in sorted(reverse.items())
        if len(families_for_preset) > 1
    }
    return payload


def _scan_shader_nodes(repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    nodes_dir = repo_root / "agents" / "shaders" / "nodes"
    payload: dict[str, Any] = {
        "path": _rel(nodes_dir, repo_root),
        "exists": nodes_dir.is_dir(),
        "count": 0,
        "node_types": [],
        "manifests": [],
        "missing_glsl_fragments": [],
        "missing_wgsl_files": [],
        "parse_errors": [],
    }
    failures: list[str] = []
    node_types: set[str] = set()
    if not nodes_dir.is_dir():
        failures.append("shader_node_root_missing")
        return payload, failures

    for path in sorted(nodes_dir.glob("*.json")):
        raw, error = _read_json(path)
        if error is not None or not isinstance(raw, dict):
            payload["parse_errors"].append({"path": _rel(path, repo_root), "error": error})
            failures.append(f"shader_manifest_json_invalid:{_rel(path, repo_root)}")
            continue
        node_type = raw.get("node_type")
        if not isinstance(node_type, str) or not node_type:
            payload["parse_errors"].append(
                {"path": _rel(path, repo_root), "error": "missing_node_type"}
            )
            failures.append(f"shader_manifest_missing_node_type:{_rel(path, repo_root)}")
            continue
        node_types.add(node_type)
        glsl_fragment = raw.get("glsl_fragment")
        if isinstance(glsl_fragment, str) and glsl_fragment:
            glsl_path = nodes_dir / glsl_fragment
            if not glsl_path.is_file():
                payload["missing_glsl_fragments"].append(
                    {"node_type": node_type, "fragment": glsl_fragment}
                )
                failures.append(
                    f"shader_manifest_missing_glsl_fragment:{node_type}:{glsl_fragment}"
                )
        wgsl_path = nodes_dir / f"{node_type}.wgsl"
        if node_type != "output" and not wgsl_path.is_file():
            payload["missing_wgsl_files"].append(node_type)
        payload["manifests"].append(
            {
                "node_type": node_type,
                "path": _rel(path, repo_root),
                "backend": raw.get("backend", "wgsl_render"),
                "temporal": bool(raw.get("temporal", False)),
                "compute": bool(raw.get("compute", False)),
                "requires_content_slots": bool(raw.get("requires_content_slots", False)),
                "has_glsl_fragment": isinstance(glsl_fragment, str) and bool(glsl_fragment),
                "has_wgsl_file": wgsl_path.is_file(),
                "risk_categories": list(RISK_NODE_CATEGORIES.get(node_type, ())),
            }
        )
    payload["node_types"] = sorted(node_types)
    payload["count"] = len(node_types)
    return payload, failures


def _preset_roots(repo_root: Path, include_home: bool) -> list[Path]:
    roots: list[Path] = []
    if include_home:
        roots.append(HOME_PRESET_ROOT)
    roots.append(repo_root / "presets")
    return roots


def _scan_presets(
    repo_root: Path,
    *,
    shader_node_types: set[str],
    include_home: bool,
) -> tuple[dict[str, Any], list[str]]:
    roots = _preset_roots(repo_root, include_home)
    payload: dict[str, Any] = {
        "roots": [],
        "count": 0,
        "graph_count": 0,
        "home_override_names": [],
        "repo_shadowed_names": [],
        "presets": [],
        "node_type_usage": {},
        "high_risk_node_usage": {},
        "unknown_node_types": [],
        "parse_errors": [],
    }
    failures: list[str] = []
    seen_by_name: dict[str, str] = {}
    node_type_usage: dict[str, set[str]] = {}
    high_risk_usage: dict[str, set[str]] = {}
    repo_root_seen = False

    for root in roots:
        role = "home_override" if root == HOME_PRESET_ROOT else "repo"
        exists = root.is_dir()
        if role == "repo":
            repo_root_seen = exists
        files = sorted(root.glob("*.json")) if exists else []
        graph_files = [
            path
            for path in files
            if not path.name.startswith("_") and path.name not in NON_GRAPH_PRESET_FILES
        ]
        payload["roots"].append(
            {
                "role": role,
                "path": str(root),
                "exists": exists,
                "json_count": len(files),
                "preset_count": len(graph_files),
            }
        )
        for path in graph_files:
            name = path.stem
            raw, error = _read_json(path)
            if error is not None or not isinstance(raw, dict):
                rel = _rel(path, repo_root)
                payload["parse_errors"].append({"path": rel, "error": error})
                failures.append(f"preset_json_invalid:{rel}")
                continue
            nodes = raw.get("nodes")
            is_graph = isinstance(nodes, dict)
            node_types: list[str] = []
            unknown: list[dict[str, str]] = []
            if is_graph:
                for node_id, node_value in nodes.items():
                    if not isinstance(node_value, dict):
                        continue
                    node_type = node_value.get("type")
                    if not isinstance(node_type, str) or not node_type:
                        continue
                    node_types.append(node_type)
                    node_type_usage.setdefault(node_type, set()).add(name)
                    if node_type in RISK_NODE_CATEGORIES:
                        high_risk_usage.setdefault(node_type, set()).add(name)
                    if node_type != "output" and node_type not in shader_node_types:
                        unknown.append({"node_id": str(node_id), "node_type": node_type})
                        failures.append(f"preset_node_type_unknown:{name}:{node_id}:{node_type}")
            if role == "home_override":
                payload["home_override_names"].append(name)
            if name in seen_by_name and role == "repo":
                payload["repo_shadowed_names"].append(name)
            seen_by_name.setdefault(name, role)
            payload["presets"].append(
                {
                    "name": name,
                    "path": _rel(path, repo_root),
                    "root_role": role,
                    "graph": is_graph,
                    "node_types": sorted(set(node_types)),
                    "risk_categories": sorted(
                        {
                            category
                            for node_type in node_types
                            for category in RISK_NODE_CATEGORIES.get(node_type, ())
                        }
                    ),
                    "modulation_count": len(raw.get("modulations") or []),
                    "unknown_node_types": unknown,
                }
            )

    if not repo_root_seen:
        failures.append("preset_repo_root_missing")
    payload["count"] = len(payload["presets"])
    payload["graph_count"] = sum(1 for item in payload["presets"] if item["graph"])
    payload["home_override_names"] = sorted(payload["home_override_names"])
    payload["repo_shadowed_names"] = sorted(payload["repo_shadowed_names"])
    payload["node_type_usage"] = {
        node_type: sorted(names) for node_type, names in sorted(node_type_usage.items())
    }
    payload["high_risk_node_usage"] = {
        node_type: {
            "presets": sorted(names),
            "risk_categories": list(RISK_NODE_CATEGORIES.get(node_type, ())),
        }
        for node_type, names in sorted(high_risk_usage.items())
    }
    payload["unknown_node_types"] = sorted(
        {
            item["node_type"]
            for preset in payload["presets"]
            for item in preset["unknown_node_types"]
        }
    )
    if payload["graph_count"] <= 0:
        failures.append("preset_graph_corpus_empty")
    return payload, failures


def _scan_default_modulations(
    repo_root: Path,
    *,
    shader_node_types: set[str],
) -> tuple[dict[str, Any], list[str]]:
    path = repo_root / "presets" / "_default_modulations.json"
    payload: dict[str, Any] = {
        "path": _rel(path, repo_root),
        "exists": path.is_file(),
        "count": 0,
        "node_types": [],
        "bindings": [],
        "unknown_node_types": [],
        "banned_global_luma_bindings": [],
    }
    failures: list[str] = []
    raw, error = _read_json(path)
    if error is not None or not isinstance(raw, dict):
        failures.append(f"default_modulations_json_invalid:{error}")
        return payload, failures
    node_types: set[str] = set()
    for row in raw.get("default_modulations", []) or []:
        if not isinstance(row, dict) or "node" not in row or "param" not in row:
            continue
        node = str(row.get("node", ""))
        param = str(row.get("param", ""))
        source = str(row.get("source", ""))
        node_types.add(node)
        binding = {"node": node, "param": param, "source": source}
        payload["bindings"].append(binding)
        if node not in shader_node_types:
            payload["unknown_node_types"].append(node)
            failures.append(f"default_modulation_unknown_node_type:{node}")
        if source.startswith(AUDIO_SOURCE_PREFIXES) and param in BANNED_GLOBAL_LUMA_PARAMS:
            payload["banned_global_luma_bindings"].append(binding)
            failures.append(f"default_modulation_banned_global_luma:{source}:{node}.{param}")
    payload["count"] = len(payload["bindings"])
    payload["node_types"] = sorted(node_types)
    payload["unknown_node_types"] = sorted(set(payload["unknown_node_types"]))
    return payload, failures


def _scan_layouts(repo_root: Path) -> dict[str, Any]:
    layout_roots = (
        repo_root / "config" / "compositor-layouts",
        repo_root / "config" / "compositor-layouts" / "examples",
        repo_root / "config" / "layouts",
    )
    payload: dict[str, Any] = {"roots": [], "layouts": [], "source_kind_counts": {}}
    kind_counts: dict[str, int] = {}
    for root in layout_roots:
        files = sorted(root.glob("*.json")) if root.is_dir() else []
        payload["roots"].append(
            {"path": _rel(root, repo_root), "exists": root.is_dir(), "count": len(files)}
        )
        for path in files:
            raw, error = _read_json(path)
            if error is not None or not isinstance(raw, dict):
                payload["layouts"].append({"path": _rel(path, repo_root), "parse_error": error})
                continue
            sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
            assignments = raw.get("assignments") if isinstance(raw.get("assignments"), list) else []
            source_rows: list[dict[str, Any]] = []
            for source in sources:
                if not isinstance(source, dict):
                    continue
                kind = str(source.get("kind", "unknown"))
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
                params = source.get("params") if isinstance(source.get("params"), dict) else {}
                source_rows.append(
                    {
                        "id": source.get("id"),
                        "kind": kind,
                        "backend": source.get("backend"),
                        "ward_id": source.get("ward_id"),
                        "class_name": params.get("class_name"),
                    }
                )
            assignment_effects = 0
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    continue
                if assignment.get("effect_chain"):
                    assignment_effects += 1
                if assignment.get("per_assignment_effects"):
                    assignment_effects += 1
            payload["layouts"].append(
                {
                    "name": raw.get("name", path.stem),
                    "path": _rel(path, repo_root),
                    "source_count": len(source_rows),
                    "assignment_count": len(assignments),
                    "assignment_effect_count": assignment_effects,
                    "sources": source_rows,
                }
            )
    payload["source_kind_counts"] = dict(sorted(kind_counts.items()))
    return payload


def _scan_runtime(
    repo_root: Path, *, include_runtime: bool, shader_node_types: set[str]
) -> tuple[dict[str, Any], list[str]]:
    payload: dict[str, Any] = {
        "included": include_runtime,
        "files": [],
        "graph_mutation": None,
        "imagination_plan": None,
    }
    failures: list[str] = []
    if not include_runtime:
        return payload, failures
    now = time.time()
    for raw_path in RUNTIME_FILES:
        path = Path(raw_path)
        try:
            stat = path.stat()
        except OSError:
            payload["files"].append({"path": raw_path, "exists": False})
            continue
        payload["files"].append(
            {
                "path": raw_path,
                "exists": True,
                "size": stat.st_size,
                "age_seconds": max(0.0, now - stat.st_mtime),
            }
        )

    graph_path = Path("/dev/shm/hapax-compositor/graph-mutation.json")
    if graph_path.is_file():
        raw, error = _read_json(graph_path)
        payload["graph_mutation"] = {"path": str(graph_path), "parse_error": error}
        if isinstance(raw, dict):
            nodes = raw.get("nodes") if isinstance(raw.get("nodes"), dict) else {}
            node_types = sorted(
                {
                    str(node.get("type"))
                    for node in nodes.values()
                    if isinstance(node, dict) and isinstance(node.get("type"), str)
                }
            )
            unknown = [
                node for node in node_types if node != "output" and node not in shader_node_types
            ]
            payload["graph_mutation"].update(
                {"node_types": node_types, "unknown_node_types": unknown}
            )
            for node in unknown:
                failures.append(f"runtime_graph_mutation_unknown_node_type:{node}")

    plan_path = Path("/dev/shm/hapax-imagination/pipeline/plan.json")
    if plan_path.is_file():
        raw, error = _read_json(plan_path)
        payload["imagination_plan"] = {"path": str(plan_path), "parse_error": error}
        if isinstance(raw, dict):
            shaders: set[str] = set()
            for step in raw.get("steps", []) or []:
                if isinstance(step, dict) and isinstance(step.get("shader"), str):
                    shaders.add(step["shader"])
            payload["imagination_plan"]["shaders"] = sorted(shaders)
    del repo_root
    return payload, failures


def _scan_file_surface(repo_root: Path, label: str, roots: tuple[str, ...]) -> dict[str, Any]:
    files: list[str] = []
    root_rows: list[dict[str, Any]] = []
    for raw_root in roots:
        root = repo_root / raw_root
        if root.is_file():
            root_files = [root]
        elif root.is_dir():
            root_files = sorted(path for path in root.rglob("*") if path.is_file())
        else:
            root_files = []
        root_rows.append({"path": raw_root, "exists": root.exists(), "file_count": len(root_files)})
        files.extend(_rel(path, repo_root) for path in root_files)
    return {"label": label, "roots": root_rows, "files": files}


def _coverage_gaps(payload: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if payload["surfaces"]["presets"]["home_override_names"]:
        gaps.append("home_effect_preset_overrides_can_shadow_repo_presets")
    if payload["surfaces"]["runtime"]["included"]:
        gaps.append("direct_graph_mutation_runtime_path_requires_live_snapshot_proof")
    gaps.extend(
        [
            "transition_primitives_need_live_exercise_proof_per_primitive",
            "hero_effect_fragments_are_separate_from_graph_presets",
            "ward_fx_and_cairo_sources_are_visual_effects_even_when_not_shader_presets",
            "reverie_imagination_outputs_are_external_visual_sources_not_preset_graphs",
            "legacy_studio_fx_must_be_classified_live_dormant_or_retired",
            "config_layouts_garage_door_is_a_layout_root_outside_config_compositor_layouts",
        ]
    )
    return gaps


def build_audit(
    repo_root: Path, *, include_home_presets: bool, include_runtime: bool
) -> dict[str, Any]:
    failures: list[str] = []
    shader_nodes, shader_failures = _scan_shader_nodes(repo_root)
    failures.extend(shader_failures)
    shader_node_types = set(shader_nodes["node_types"])

    presets, preset_failures = _scan_presets(
        repo_root,
        shader_node_types=shader_node_types,
        include_home=include_home_presets,
    )
    failures.extend(preset_failures)
    available_presets = {preset["name"] for preset in presets["presets"]}

    default_modulations, modulation_failures = _scan_default_modulations(
        repo_root,
        shader_node_types=shader_node_types,
    )
    failures.extend(modulation_failures)

    visual_governance = _extract_visual_governance(repo_root)
    visual_governance["missing_presets"] = sorted(
        set(visual_governance["referenced_presets"]) - available_presets
    )
    failures.extend(
        f"visual_governance_missing_preset:{name}" for name in visual_governance["missing_presets"]
    )
    if visual_governance["parse_error"] is not None:
        failures.append(f"visual_governance_parse_error:{visual_governance['parse_error']}")

    transitions = _extract_transition_primitives(repo_root)
    if transitions["parse_error"] is not None:
        failures.append(f"transition_primitives_parse_error:{transitions['parse_error']}")
    for name in transitions["missing_primitives"]:
        failures.append(f"transition_primitive_missing_registry:{name}")
    for name in transitions["extra_primitives"]:
        failures.append(f"transition_primitive_extra_registry:{name}")

    preset_family_selector = _extract_preset_family_selector(repo_root)
    preset_family_selector["missing_presets"] = sorted(
        set(preset_family_selector["referenced_presets"]) - available_presets
    )
    preset_family_selector["orphaned_presets"] = sorted(
        available_presets - set(preset_family_selector["referenced_presets"])
    )
    if preset_family_selector["parse_error"] is not None:
        failures.append(
            f"preset_family_selector_parse_error:{preset_family_selector['parse_error']}"
        )
    failures.extend(
        f"preset_family_selector_missing_preset:{name}"
        for name in preset_family_selector["missing_presets"]
    )

    hero_dir = repo_root / "agents" / "shaders" / "hero_effects"
    hero_effects = {
        "path": _rel(hero_dir, repo_root),
        "exists": hero_dir.is_dir(),
        "fragments": sorted(path.name for path in hero_dir.glob("*.frag"))
        if hero_dir.is_dir()
        else [],
    }

    runtime, runtime_failures = _scan_runtime(
        repo_root,
        include_runtime=include_runtime,
        shader_node_types=shader_node_types,
    )
    failures.extend(runtime_failures)

    payload: dict[str, Any] = {
        "ok": False,
        "reasons": [],
        "summary": {},
        "entrypoints": [
            "effects.try_graph_preset: home overrides then repo presets",
            "state.py: direct /dev/shm/hapax-compositor/graph-mutation.json loads",
            "preset_recruitment_consumer.py and random_mode.py: transition graph writers",
            "fx_tick.py and visual_governance.py: atmospheric preset selection",
            "hero_effect_rotator.py: standalone hero fragment slot",
            "transition_primitives.py: graph handoff primitives",
            "ward_fx_bus / ward_properties / Cairo source registry: overlay effects",
            "layout JSON assignments: per-source visual placement and assignment effects",
            "Reverie/imagination SHM sources: external generated visual layers",
            "legacy agents/studio_fx: separate legacy FX service path",
        ],
        "surfaces": {
            "shader_nodes": shader_nodes,
            "presets": presets,
            "default_modulations": default_modulations,
            "visual_governance": visual_governance,
            "preset_family_selector": preset_family_selector,
            "transition_primitives": transitions,
            "hero_effects": hero_effects,
            "layouts": _scan_layouts(repo_root),
            "ward_fx": _scan_file_surface(
                repo_root,
                "ward_fx",
                (
                    "shared/ward_fx_bus.py",
                    "agents/studio_compositor/ward_fx_mapping.py",
                    "agents/studio_compositor/fx_chain_ward_reactor.py",
                    "agents/studio_compositor/ward_properties.py",
                    "agents/studio_compositor/ward_stimmung_modulator.py",
                    "config/ward_enhancement_profiles.yaml",
                ),
            ),
            "cairo_sources": _scan_file_surface(
                repo_root,
                "cairo_sources",
                (
                    "agents/studio_compositor/cairo_sources",
                    "agents/studio_compositor/cairo_source.py",
                    "agents/studio_compositor/cairo_source_registry.py",
                ),
            ),
            "reverie_imagination": _scan_file_surface(
                repo_root,
                "reverie_imagination",
                (
                    "agents/reverie",
                    "agents/imagination.py",
                    "agents/imagination_loop.py",
                    "agents/imagination_source_protocol.py",
                    "agents/visual_chain.py",
                    "hapax-logos/crates/hapax-visual/src",
                ),
            ),
            "legacy_studio_fx": _scan_file_surface(
                repo_root, "legacy_studio_fx", ("agents/studio_fx",)
            ),
            "runtime": runtime,
        },
    }
    payload["coverage_gaps"] = _coverage_gaps(payload)
    payload["reasons"] = sorted(dict.fromkeys(failures))
    payload["ok"] = not payload["reasons"]
    payload["summary"] = {
        "preset_count": presets["count"],
        "graph_preset_count": presets["graph_count"],
        "shader_node_count": shader_nodes["count"],
        "preset_family_count": len(preset_family_selector["families"]),
        "hero_effect_count": len(hero_effects["fragments"]),
        "transition_primitive_count": len(transitions["transition_names"]),
        "layout_count": len(payload["surfaces"]["layouts"]["layouts"]),
        "high_risk_node_type_count": len(presets["high_risk_node_usage"]),
        "reason_count": len(payload["reasons"]),
        "coverage_gap_count": len(payload["coverage_gaps"]),
    }
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--no-home-presets", action="store_true")
    parser.add_argument("--no-runtime", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 10 when static failures exist")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    payload = build_audit(
        repo_root,
        include_home_presets=not args.no_home_presets,
        include_runtime=not args.no_runtime,
    )
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    if args.strict and not payload["ok"]:
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
