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
if str(DEFAULT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_REPO_ROOT))

from shared.live_surface_effect_policy import (
    live_surface_policy_kind,
    live_surface_unclassified_node_types,
)
from shared.reverie_uniform_policy import reverie_uniform_bound_violations

HOME_PRESET_ROOT = Path.home() / ".config" / "hapax" / "effect-presets"
NON_GRAPH_PRESET_FILES = frozenset({"shader_intensity_bounds.json"})
IGNORED_SURFACE_DIR_NAMES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache"})
IGNORED_SURFACE_SUFFIXES = frozenset({".pyc", ".pyo"})
RUNTIME_FILES = (
    "/dev/shm/hapax-compositor/fx-current.txt",
    "/dev/shm/hapax-compositor/fx-request.txt",
    "/dev/shm/hapax-compositor/fx-source.txt",
    "/dev/shm/hapax-compositor/graph-mutation.json",
    "/dev/shm/hapax-compositor/layout-mode.txt",
    "/dev/shm/hapax-compositor/current-layout-state.json",
    "/dev/shm/hapax-compositor/active_wards.json",
    "/dev/shm/hapax-compositor/ward-properties.json",
    "/dev/shm/hapax-compositor/ward-fx-events.jsonl",
    "/dev/shm/hapax-compositor/overlay-alpha-overrides.json",
    "/dev/shm/hapax-compositor/recent-recruitment.json",
    "/dev/shm/hapax-compositor/segment-layout-receipt.json",
    "/dev/shm/hapax-compositor/hero-effect-current.txt",
    "/dev/shm/hapax-compositor/hero-camera.txt",
    "/dev/shm/hapax-compositor/hero-camera-override.json",
    "/dev/shm/hapax-compositor/visual-layer-enabled.txt",
    "/dev/shm/hapax-compositor/layer-live-enabled.txt",
    "/dev/shm/hapax-compositor/layer-smooth-enabled.txt",
    "/dev/shm/hapax-compositor/layer-hls-enabled.txt",
    "/dev/shm/hapax-compositor/smooth-delay.txt",
    "/dev/shm/hapax-compositor/snapshot.jpg",
    "/dev/shm/hapax-compositor/frame_for_llm.jpg",
    "/dev/shm/hapax-compositor/fx-snapshot.jpg",
    "/dev/shm/hapax-compositor/smooth-snapshot.jpg",
    "/dev/shm/hapax-compositor/mobile-overlay.rgba",
    "/dev/shm/hapax-compositor/mobile-roi.json",
    "/dev/shm/hapax-compositor/v4l2-bridge.sock",
    "/dev/shm/hapax-compositor/homage-active.json",
    "/dev/shm/hapax-compositor/homage-active-artefact.json",
    "/dev/shm/hapax-compositor/homage-pending-transitions.json",
    "/dev/shm/hapax-compositor/homage-substrate-package.json",
    "/dev/shm/hapax-compositor/homage-voice-register.json",
    "/dev/shm/hapax-compositor/homage-shader-reading.json",
    "/dev/shm/hapax-compositor/gem-frames.json",
    "/dev/shm/hapax-gem/gem-frames.json",
    "/dev/shm/hapax-sources/reverie.rgba",
    "/dev/shm/hapax-sources/m8-display.rgba",
    "/dev/shm/hapax-sources/steamdeck-display.rgba",
    "/dev/shm/hapax-sources/m8-osc.bin",
    "/dev/shm/hapax-conversation/visual-signal.json",
    "/dev/shm/hapax-dmn/visual-salience.json",
    "/dev/shm/hapax-reverie",
    "/dev/shm/hapax-visual/frame.rgba",
    "/dev/shm/hapax-visual/frame.jpg",
    "/dev/shm/hapax-visual/state.json",
    "/dev/shm/hapax-visual/control.json",
    "/dev/shm/hapax-visual/visual-chain-state.json",
    "/dev/shm/hapax-exploration/visual_chain.json",
    "/dev/shm/hapax-imagination/current.json",
    "/dev/shm/hapax-imagination/stream.jsonl",
    "/dev/shm/hapax-imagination/sources",
    "/dev/shm/hapax-imagination/content",
    "/dev/shm/hapax-imagination/pool_metrics.json",
    "/dev/shm/hapax-imagination/uniforms.json",
    "/dev/shm/hapax-imagination/shader_health.json",
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


def _extract_cairo_source_registry(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "agents" / "studio_compositor" / "cairo_sources" / "__init__.py"
    payload: dict[str, Any] = {
        "path": _rel(path, repo_root),
        "exists": path.is_file(),
        "file_count": 1 if path.is_file() else 0,
        "files": [_rel(path, repo_root)] if path.is_file() else [],
        "registered_class_count": 0,
        "registered_classes": [],
        "registered_bindings": [],
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

    bindings: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "register":
            continue
        if len(node.args) < 2:
            continue
        registry_name = _string_constant(node.args[0])
        class_name = getattr(node.args[1], "id", None)
        if registry_name is None or class_name is None:
            continue
        bindings.append({"registry_name": registry_name, "class_name": class_name})
    payload["registered_bindings"] = sorted(bindings, key=lambda row: row["registry_name"])
    payload["registered_classes"] = sorted({row["registry_name"] for row in bindings})
    payload["registered_class_count"] = len(payload["registered_classes"])
    return payload


def _class_attr_string(tree: ast.Module, class_name: str, attr_name: str) -> str | None:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            value: ast.AST | None = None
            targets: list[ast.AST] = []
            if isinstance(item, ast.Assign):
                value = item.value
                targets = list(item.targets)
            elif isinstance(item, ast.AnnAssign):
                value = item.value
                targets = [item.target]
            if value is None:
                continue
            if any(isinstance(target, ast.Name) and target.id == attr_name for target in targets):
                return _string_constant(value)
    return None


def _extract_legacy_studio_fx_registry(repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    effects_dir = repo_root / "agents" / "studio_fx" / "effects"
    path = effects_dir / "__init__.py"
    payload: dict[str, Any] = {
        "path": _rel(path, repo_root),
        "exists": path.is_file(),
        "registered_effect_count": 0,
        "registered_effect_classes": [],
        "registered_effect_names": [],
        "registered_effects": [],
        "imported_modules": [],
        "effect_module_files": sorted(_rel(file, repo_root) for file in effects_dir.glob("*.py"))
        if effects_dir.is_dir()
        else [],
        "orphan_effect_modules": [],
        "missing_effect_modules": [],
        "classes_missing_name": [],
        "parse_error": None,
    }
    failures: list[str] = []
    if not effects_dir.exists():
        return payload, failures
    if not path.is_file():
        payload["parse_error"] = "missing_registry"
        failures.append("legacy_studio_fx_registry_missing")
        return payload, failures
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        payload["parse_error"] = f"{type(exc).__name__}:{exc}"
        failures.append(f"legacy_studio_fx_registry_parse_error:{type(exc).__name__}")
        return payload, failures

    class_to_module: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        prefix = "agents.studio_fx.effects."
        if not node.module.startswith(prefix):
            continue
        module_name = node.module.removeprefix(prefix)
        for alias in node.names:
            class_to_module[alias.asname or alias.name] = module_name
    payload["imported_modules"] = sorted(set(class_to_module.values()))

    registered_classes: list[str] = []
    for value in _iter_assignments(tree, "ALL_EFFECTS"):
        if not isinstance(value, ast.List | ast.Tuple):
            continue
        for item in value.elts:
            if isinstance(item, ast.Name):
                registered_classes.append(item.id)
    payload["registered_effect_classes"] = registered_classes

    module_files = {
        path.stem: path
        for path in effects_dir.glob("*.py")
        if path.name != "__init__.py" and path.is_file()
    }
    imported_modules = set(class_to_module.values())
    payload["orphan_effect_modules"] = sorted(set(module_files) - imported_modules)
    if payload["orphan_effect_modules"]:
        failures.extend(
            f"legacy_studio_fx_module_unregistered:{module}"
            for module in payload["orphan_effect_modules"]
        )

    effects: list[dict[str, Any]] = []
    for class_name in registered_classes:
        module_name = class_to_module.get(class_name)
        if module_name is None:
            payload["missing_effect_modules"].append({"class_name": class_name, "module": None})
            failures.append(f"legacy_studio_fx_class_not_imported:{class_name}")
            continue
        module_path = module_files.get(module_name)
        if module_path is None:
            payload["missing_effect_modules"].append(
                {"class_name": class_name, "module": module_name}
            )
            failures.append(f"legacy_studio_fx_module_missing:{class_name}:{module_name}")
            continue
        try:
            module_tree = ast.parse(module_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            failures.append(
                f"legacy_studio_fx_module_parse_error:{class_name}:{type(exc).__name__}"
            )
            effects.append(
                {
                    "class_name": class_name,
                    "module": module_name,
                    "path": _rel(module_path, repo_root),
                    "name": None,
                    "parse_error": f"{type(exc).__name__}:{exc}",
                }
            )
            continue
        effect_name = _class_attr_string(module_tree, class_name, "name")
        if effect_name is None:
            payload["classes_missing_name"].append(class_name)
            failures.append(f"legacy_studio_fx_class_missing_name:{class_name}")
        effects.append(
            {
                "class_name": class_name,
                "module": module_name,
                "path": _rel(module_path, repo_root),
                "name": effect_name,
                "parse_error": None,
            }
        )
    payload["registered_effects"] = effects
    payload["registered_effect_names"] = sorted(
        effect["name"] for effect in effects if isinstance(effect.get("name"), str)
    )
    payload["registered_effect_count"] = len(effects)
    return payload, failures


def _scan_palette_chains(repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    path = repo_root / "presets" / "scrim_palettes" / "registry.yaml"
    support = _scan_file_surface(
        repo_root,
        "palette_chain_support",
        (
            "presets/scrim_palettes/registry.yaml",
            "shared/palette_family.py",
            "shared/palette_registry.py",
            "shared/palette_response.py",
            "shared/palette_curve_evaluator.py",
            "shared/geal_palette_bridge.py",
            "shared/geal_stance_palette_map.yaml",
        ),
    )
    payload: dict[str, Any] = {
        "path": _rel(path, repo_root),
        "exists": path.is_file(),
        "palette_count": 0,
        "chain_count": 0,
        "palettes": [],
        "chains": [],
        "missing_palette_refs": [],
        "duplicate_palette_ids": [],
        "duplicate_chain_ids": [],
        "parse_error": None,
        "support_files": support["files"],
        "file_count": support["file_count"],
        "files": support["files"],
    }
    failures: list[str] = []
    if not path.is_file():
        payload["parse_error"] = "missing"
        failures.append("palette_registry_missing")
        return payload, failures
    try:
        import yaml
    except ImportError as exc:
        payload["parse_error"] = f"{type(exc).__name__}:{exc}"
        failures.append(f"palette_registry_read_failed:{type(exc).__name__}")
        return payload, failures
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        payload["parse_error"] = f"{type(exc).__name__}:{exc}"
        failures.append(f"palette_registry_read_failed:{type(exc).__name__}")
        return payload, failures
    except yaml.YAMLError as exc:
        payload["parse_error"] = f"{type(exc).__name__}:{exc}"
        failures.append(f"palette_registry_yaml_invalid:{type(exc).__name__}")
        return payload, failures
    if not isinstance(raw, dict):
        payload["parse_error"] = f"root_not_mapping:{type(raw).__name__}"
        failures.append("palette_registry_root_not_mapping")
        return payload, failures

    palette_ids: list[str] = []
    seen_palettes: set[str] = set()
    for entry in raw.get("palettes") or []:
        if not isinstance(entry, dict):
            continue
        palette_id = entry.get("id")
        if not isinstance(palette_id, str) or not palette_id:
            continue
        if palette_id in seen_palettes:
            payload["duplicate_palette_ids"].append(palette_id)
            failures.append(f"palette_registry_duplicate_palette:{palette_id}")
        seen_palettes.add(palette_id)
        palette_ids.append(palette_id)
        payload["palettes"].append(
            {
                "id": palette_id,
                "temporal_profile": entry.get("temporal_profile", "steady"),
                "semantic_tags": entry.get("semantic_tags") or [],
                "curve_mode": (entry.get("curve") or {}).get("mode")
                if isinstance(entry.get("curve"), dict)
                else None,
            }
        )

    seen_chains: set[str] = set()
    for entry in raw.get("chains") or []:
        if not isinstance(entry, dict):
            continue
        chain_id = entry.get("id")
        if not isinstance(chain_id, str) or not chain_id:
            continue
        if chain_id in seen_chains:
            payload["duplicate_chain_ids"].append(chain_id)
            failures.append(f"palette_registry_duplicate_chain:{chain_id}")
        seen_chains.add(chain_id)
        steps = entry.get("steps") if isinstance(entry.get("steps"), list) else []
        step_ids: list[str] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            palette_ref = step.get("palette_id")
            if not isinstance(palette_ref, str) or not palette_ref:
                continue
            step_ids.append(palette_ref)
            if palette_ref not in seen_palettes:
                payload["missing_palette_refs"].append(
                    {"chain_id": chain_id, "palette_id": palette_ref}
                )
                failures.append(f"palette_chain_missing_palette:{chain_id}:{palette_ref}")
        payload["chains"].append(
            {
                "id": chain_id,
                "step_count": len(step_ids),
                "palette_ids": step_ids,
                "loop": bool(entry.get("loop", True)),
                "semantic_tags": entry.get("semantic_tags") or [],
            }
        )
    payload["palette_count"] = len(palette_ids)
    payload["chain_count"] = len(payload["chains"])
    return payload, failures


def _scan_shader_nodes(repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    nodes_dir = repo_root / "agents" / "shaders" / "nodes"
    payload: dict[str, Any] = {
        "path": _rel(nodes_dir, repo_root),
        "exists": nodes_dir.is_dir(),
        "count": 0,
        "node_types": [],
        "files": [],
        "manifests": [],
        "missing_glsl_fragments": [],
        "missing_wgsl_files": [],
        "standalone_wgsl_files": [],
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
                "live_surface_policy": live_surface_policy_kind(node_type),
            }
        )
    manifest_wgsl = {f"{node}.wgsl" for node in node_types if node != "output"}
    payload["standalone_wgsl_files"] = sorted(
        path.name for path in nodes_dir.glob("*.wgsl") if path.name not in manifest_wgsl
    )
    payload["files"] = sorted(
        _rel(path, repo_root)
        for path in nodes_dir.glob("*")
        if path.is_file() and path.suffix in {".json", ".frag", ".wgsl"}
    )
    payload["node_types"] = sorted(node_types)
    payload["count"] = len(node_types)
    return payload, failures


def _scan_live_surface_policy(shader_node_types: set[str]) -> tuple[dict[str, Any], list[str]]:
    by_kind: dict[str, list[str]] = {}
    for node_type in sorted(shader_node_types):
        by_kind.setdefault(live_surface_policy_kind(node_type), []).append(node_type)
    unclassified = sorted(live_surface_unclassified_node_types(shader_node_types))
    failures = [f"live_surface_policy_unclassified_node:{node}" for node in unclassified]
    return (
        {
            "by_kind": dict(sorted(by_kind.items())),
            "unclassified_node_types": unclassified,
            "unclassified_count": len(unclassified),
            "bounded_count": len(by_kind.get("bounded", [])),
            "blocked_pending_repair_count": len(by_kind.get("blocked_pending_repair", [])),
            "content_slot_guarded_count": len(by_kind.get("content_slot_guarded", [])),
            "structural_count": len(by_kind.get("structural", [])),
        },
        failures,
    )


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
        Path.home() / ".config" / "hapax-compositor" / "layouts",
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
            surfaces = raw.get("surfaces") if isinstance(raw.get("surfaces"), list) else []
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
            surface_effect_chains: list[dict[str, Any]] = []
            for idx, surface in enumerate(surfaces):
                if not isinstance(surface, dict) or "effect_chain" not in surface:
                    continue
                chain = surface.get("effect_chain")
                chain_items = chain if isinstance(chain, list) else []
                surface_effect_chains.append(
                    {
                        "surface": surface.get("id", idx),
                        "path": f"surfaces.{idx}.effect_chain",
                        "length": len(chain_items),
                        "chain": chain_items,
                        "parse_error": None
                        if isinstance(chain, list)
                        else f"not_list:{type(chain).__name__}",
                    }
                )
            assignment_effect_chains: list[dict[str, Any]] = []
            for idx, assignment in enumerate(assignments):
                if not isinstance(assignment, dict):
                    continue
                if "effect_chain" in assignment:
                    chain = assignment.get("effect_chain")
                    chain_items = chain if isinstance(chain, list) else []
                    assignment_effect_chains.append(
                        {
                            "assignment": assignment.get("id", idx),
                            "path": f"assignments.{idx}.effect_chain",
                            "length": len(chain_items),
                            "chain": chain_items,
                            "parse_error": None
                            if isinstance(chain, list)
                            else f"not_list:{type(chain).__name__}",
                        }
                    )
                if "per_assignment_effects" in assignment:
                    effects = assignment.get("per_assignment_effects")
                    effect_items = effects if isinstance(effects, list) else []
                    assignment_effect_chains.append(
                        {
                            "assignment": assignment.get("id", idx),
                            "path": f"assignments.{idx}.per_assignment_effects",
                            "length": len(effect_items),
                            "chain": effect_items,
                            "parse_error": None
                            if isinstance(effects, list)
                            else f"not_list:{type(effects).__name__}",
                        }
                    )
            payload["layouts"].append(
                {
                    "name": raw.get("name", path.stem),
                    "path": _rel(path, repo_root),
                    "source_count": len(source_rows),
                    "surface_count": len(surfaces),
                    "assignment_count": len(assignments),
                    "surface_effect_chain_slot_count": len(surface_effect_chains),
                    "surface_effect_chain_nonempty_count": sum(
                        1 for row in surface_effect_chains if row["length"] > 0
                    ),
                    "assignment_effect_slot_count": len(assignment_effect_chains),
                    "assignment_effect_nonempty_count": sum(
                        1 for row in assignment_effect_chains if row["length"] > 0
                    ),
                    "assignment_effect_count": sum(
                        1
                        for row in (*surface_effect_chains, *assignment_effect_chains)
                        if row["length"] > 0
                    ),
                    "sources": source_rows,
                    "surface_effect_chains": surface_effect_chains,
                    "assignment_effect_chains": assignment_effect_chains,
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
        "reverie_uniforms": None,
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

    uniforms_path = Path("/dev/shm/hapax-imagination/uniforms.json")
    if uniforms_path.is_file():
        raw, error = _read_json(uniforms_path)
        payload["reverie_uniforms"] = {"path": str(uniforms_path), "parse_error": error}
        if isinstance(raw, dict):
            violations = reverie_uniform_bound_violations(raw)
            payload["reverie_uniforms"].update(
                {
                    "key_count": len(raw),
                    "live_bound_violations": violations,
                }
            )
            for key in sorted(violations):
                failures.append(f"runtime_reverie_uniform_out_of_bounds:{key}")

    plan_path = Path("/dev/shm/hapax-imagination/pipeline/plan.json")
    if plan_path.is_file():
        raw, error = _read_json(plan_path)
        payload["imagination_plan"] = {"path": str(plan_path), "parse_error": error}
        if isinstance(raw, dict):
            shaders: set[str] = set()
            for step in _iter_plan_passes(raw):
                if isinstance(step, dict) and isinstance(step.get("shader"), str):
                    shaders.add(step["shader"])
            shader_files = sorted(
                path.name for path in plan_path.parent.glob("*.wgsl") if path.is_file()
            )
            policy_by_shader: dict[str, str] = {}
            inactive_policy_by_shader: dict[str, str] = {}
            blocked: list[str] = []
            bounded_generators: list[str] = []
            unclassified: list[str] = []
            inactive_blocked: list[str] = []
            inactive_files = sorted(set(shader_files) - shaders)
            for step in _iter_plan_passes(raw):
                shader = step.get("shader")
                if not isinstance(shader, str):
                    continue
                node_type = Path(shader).stem
                policy = live_surface_policy_kind(node_type)
                policy_by_shader[shader] = policy
                if node_type != "output" and node_type not in shader_node_types:
                    failures.append(f"runtime_imagination_plan_unknown_shader:{shader}")
                if policy == "blocked_pending_repair":
                    node_id = str(step.get("node_id", ""))
                    uniforms = (
                        step.get("uniforms") if isinstance(step.get("uniforms"), dict) else {}
                    )
                    plan_uniforms = {
                        f"{node_id}.{key}": value
                        for key, value in uniforms.items()
                        if node_id and isinstance(key, str)
                    }
                    violations = reverie_uniform_bound_violations(plan_uniforms)
                    if node_type == "noise_gen" and not violations:
                        bounded_generators.append(shader)
                    else:
                        blocked.append(shader)
                        failures.append(f"runtime_imagination_plan_blocked_shader:{shader}")
                if policy == "unclassified":
                    unclassified.append(shader)
                    failures.append(f"runtime_imagination_plan_unclassified_shader:{shader}")
            for shader in inactive_files:
                policy = live_surface_policy_kind(Path(shader).stem)
                inactive_policy_by_shader[shader] = policy
                if policy == "blocked_pending_repair":
                    inactive_blocked.append(shader)
            payload["imagination_plan"].update(
                {
                    "shaders": sorted(shaders),
                    "shader_files": shader_files,
                    "inactive_shader_files": inactive_files,
                    "policy_by_shader": policy_by_shader,
                    "inactive_policy_by_shader": inactive_policy_by_shader,
                    "blocked_pending_repair_shaders": blocked,
                    "bounded_generator_shaders": sorted(bounded_generators),
                    "inactive_blocked_pending_repair_shader_files": inactive_blocked,
                    "unclassified_shaders": unclassified,
                }
            )
    del repo_root
    return payload, failures


def _scan_file_surface(repo_root: Path, label: str, roots: tuple[str, ...]) -> dict[str, Any]:
    files: list[str] = []
    root_rows: list[dict[str, Any]] = []
    for raw_root in roots:
        root = repo_root / raw_root
        if root.is_file():
            root_files = [root] if _surface_file_included(root) else []
        elif root.is_dir():
            root_files = sorted(
                path for path in root.rglob("*") if path.is_file() and _surface_file_included(path)
            )
        else:
            root_files = []
        root_rows.append({"path": raw_root, "exists": root.exists(), "file_count": len(root_files)})
        files.extend(_rel(path, repo_root) for path in root_files)
    suffix_counts: dict[str, int] = {}
    for file_name in files:
        suffix = Path(file_name).suffix or "<none>"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
    return {
        "label": label,
        "roots": root_rows,
        "files": files,
        "file_count": len(files),
        "suffix_counts": dict(sorted(suffix_counts.items())),
    }


def _surface_file_included(path: Path) -> bool:
    if path.suffix in IGNORED_SURFACE_SUFFIXES:
        return False
    return not any(part in IGNORED_SURFACE_DIR_NAMES for part in path.parts)


def _iter_plan_passes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return pass rows from all known imagination plan schemas."""

    rows: list[dict[str, Any]] = []
    steps = plan.get("steps")
    if isinstance(steps, list):
        rows.extend(step for step in steps if isinstance(step, dict))
    passes = plan.get("passes")
    if isinstance(passes, list):
        rows.extend(step for step in passes if isinstance(step, dict))
    targets = plan.get("targets")
    if isinstance(targets, dict):
        for target in targets.values():
            if not isinstance(target, dict):
                continue
            target_passes = target.get("passes")
            if isinstance(target_passes, list):
                rows.extend(step for step in target_passes if isinstance(step, dict))
    return rows


def _coverage_gaps(payload: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if payload["surfaces"]["presets"]["home_override_names"]:
        gaps.append("home_effect_preset_overrides_can_shadow_repo_presets")
    if payload["surfaces"]["runtime"]["included"]:
        gaps.append("direct_graph_mutation_runtime_path_requires_live_snapshot_proof")
        plan = payload["surfaces"]["runtime"].get("imagination_plan") or {}
        if plan.get("blocked_pending_repair_shaders"):
            gaps.append("runtime_imagination_plan_contains_blocked_effect_shaders")
    gaps.extend(
        [
            "transition_primitives_need_live_exercise_proof_per_primitive",
            "hero_effect_fragments_are_separate_from_graph_presets",
            "palette_scrim_chains_are_preset_like_visual_chains_and_need_live_policy_mapping",
            "layout_surface_effect_chains_need_live_exercise_proof_when_nonempty",
            "cairo_source_registry_is_a_layout-addressable_visual_effect_surface",
            "standalone_wgsl_files_need_manifest_or_helper_classification",
            "ward_fx_and_cairo_sources_are_visual_effects_even_when_not_shader_presets",
            "reverie_imagination_outputs_are_external_visual_sources_not_preset_graphs",
            "legacy_studio_fx_must_be_classified_live_dormant_or_retired",
            "glfeedback_and_visual_output_bridges_need_live_exercise_proof",
            "visual_command_surfaces_can_mutate_layout_or_effect_state",
            "visual_output_branches_need_viewer_truth_exercise_proof",
            "visual_systemd_units_are_runtime_activation_surfaces",
            "visual_maintenance_scripts_can_mutate_or_restore_effect_state",
            "shared_visual_policy_models_need_same_coverage_as_effect_code",
            "external_rgba_sources_need_freshness_and_alpha_policy_mapping",
            "homage_visual_substrates_need_policy_mapping_separate_from_graph_presets",
            "config_layouts_garage_door_is_a_layout_root_outside_config_compositor_layouts",
        ]
    )
    return gaps


def _surface_file_count(payload: dict[str, Any], surface: str) -> int:
    row = payload["surfaces"].get(surface, {})
    count = row.get("file_count")
    return count if isinstance(count, int) else 0


def build_audit(
    repo_root: Path, *, include_home_presets: bool, include_runtime: bool
) -> dict[str, Any]:
    failures: list[str] = []
    shader_nodes, shader_failures = _scan_shader_nodes(repo_root)
    failures.extend(shader_failures)
    shader_node_types = set(shader_nodes["node_types"])
    live_surface_policy, live_surface_policy_failures = _scan_live_surface_policy(shader_node_types)
    failures.extend(live_surface_policy_failures)

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

    layouts = _scan_layouts(repo_root)

    cairo_source_registry = _extract_cairo_source_registry(repo_root)
    if cairo_source_registry["parse_error"] is not None:
        failures.append(f"cairo_source_registry_parse_error:{cairo_source_registry['parse_error']}")
    registered_cairo_classes = set(cairo_source_registry["registered_classes"])
    layout_cairo_classes = sorted(
        {
            source["class_name"]
            for layout in layouts["layouts"]
            for source in layout["sources"]
            if isinstance(source.get("class_name"), str)
        }
    )
    cairo_source_registry["layout_class_names"] = layout_cairo_classes
    cairo_source_registry["layout_class_names_missing_registry"] = sorted(
        set(layout_cairo_classes) - registered_cairo_classes
    )
    failures.extend(
        f"layout_cairo_source_class_unregistered:{name}"
        for name in cairo_source_registry["layout_class_names_missing_registry"]
    )

    palette_chains, palette_chain_failures = _scan_palette_chains(repo_root)
    failures.extend(palette_chain_failures)

    legacy_studio_fx_registry, legacy_studio_fx_failures = _extract_legacy_studio_fx_registry(
        repo_root
    )
    failures.extend(legacy_studio_fx_failures)

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
        "files": sorted(_rel(path, repo_root) for path in hero_dir.glob("*.frag"))
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
            "layout surface effect_chain fields: per-surface visual chains outside graph presets",
            "palette/scrim chains: colour-response chains parallel to effect-preset chains",
            "Reverie/imagination SHM sources: external generated visual layers",
            "legacy agents/studio_fx: separate legacy FX service path",
            "legacy agents/studio_fx/effects.ALL_EFFECTS: Python/OpenCV effect registry",
            "gst-plugin-glfeedback and hapax-logos/src-imagination: visual bridge/effect runtime",
            "visual manifests/configs: non-code visual routing and substrate descriptors",
            "Logos/API + compositor command socket: layout/effect control surface",
            "home layout overrides: operator-local layout root that can shadow repo assumptions",
            "visual output branches: snapshots, v4l2, smooth delay, RTMP, SHM sidecars",
            "visual systemd units and drop-ins: activation source, env policy, restart scope",
            "visual maintenance scripts: preflight, audits, source checks, archive/recovery tools",
            "shared visual policy/model files: schemas and gates outside compositor package",
            "external RGBA sources: M8, Steam Deck, GEM, Reverie, HOMAGE runtime packages",
            "studio_compositor package: whole live image assembly and routing system",
            "visual sidecar agents: visual layer, pool, overlay, and standalone producer paths",
            "Logos visual UI: operator-facing graph/preset/control surface",
        ],
        "surfaces": {
            "shader_nodes": shader_nodes,
            "live_surface_policy": live_surface_policy,
            "presets": presets,
            "default_modulations": default_modulations,
            "visual_governance": visual_governance,
            "preset_family_selector": preset_family_selector,
            "palette_chains": palette_chains,
            "transition_primitives": transitions,
            "hero_effects": hero_effects,
            "layouts": layouts,
            "effect_orchestrators": _scan_file_surface(
                repo_root,
                "effect_orchestrators",
                (
                    "agents/effect_graph",
                    "agents/studio_compositor/effects.py",
                    "agents/studio_compositor/fx_chain.py",
                    "agents/studio_compositor/fx_tick.py",
                    "agents/studio_compositor/state.py",
                    "agents/studio_compositor/graph_patch_consumer.py",
                    "agents/studio_compositor/graph_mutation_bus.py",
                    "agents/studio_compositor/random_mode.py",
                    "agents/studio_compositor/preset_mutator.py",
                    "agents/studio_compositor/preset_recruitment_consumer.py",
                    "agents/studio_compositor/preset_policy.py",
                    "agents/studio_compositor/preset_family_selector.py",
                    "agents/studio_compositor/chat_reactor.py",
                    "agents/studio_compositor/compositional_consumer.py",
                    "agents/studio_compositor/compile.py",
                    "agents/studio_compositor/compositor.py",
                    "agents/studio_compositor/lifecycle.py",
                    "agents/studio_compositor/overlay.py",
                    "agents/studio_compositor/pipeline.py",
                    "agents/studio_compositor/sierpinski_renderer.py",
                    "shared/compositional_affordances.py",
                    "shared/director_intent.py",
                    "shared/director_semantic_verbs.py",
                    "shared/director_vocabulary.py",
                    "shared/live_surface_effect_policy.py",
                    "shared/logos_control_dispatch.py",
                    "shared/shader_bounds.py",
                    "shared/visual_mode_bias.py",
                ),
            ),
            "studio_compositor_package": _scan_file_surface(
                repo_root,
                "studio_compositor_package",
                ("agents/studio_compositor",),
            ),
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
            "cairo_source_registry": cairo_source_registry,
            "cairo_ward_implementations": _scan_file_surface(
                repo_root,
                "cairo_ward_implementations",
                (
                    "agents/studio_compositor/album_overlay.py",
                    "agents/studio_compositor/captions_source.py",
                    "agents/studio_compositor/cbip_signal_density.py",
                    "agents/studio_compositor/chat_ambient_ward.py",
                    "agents/studio_compositor/chronicle_ticker.py",
                    "agents/studio_compositor/coding_activity_reveal.py",
                    "agents/studio_compositor/coding_session_reveal.py",
                    "agents/studio_compositor/durf_source.py",
                    "agents/studio_compositor/egress_footer_source.py",
                    "agents/studio_compositor/geal_source.py",
                    "agents/studio_compositor/gem_source.py",
                    "agents/studio_compositor/hero_small_overlay.py",
                    "agents/studio_compositor/hothouse_sources.py",
                    "agents/studio_compositor/legibility_sources.py",
                    "agents/studio_compositor/mobile_cairo_sources.py",
                    "agents/studio_compositor/programme_banner_ward.py",
                    "agents/studio_compositor/programme_history_ward.py",
                    "agents/studio_compositor/programme_state_ward.py",
                    "agents/studio_compositor/research_instrument_dashboard_ward.py",
                    "agents/studio_compositor/research_marker_overlay.py",
                    "agents/studio_compositor/scribble_strip_source.py",
                    "agents/studio_compositor/segment_content_ward.py",
                    "agents/studio_compositor/sierpinski_renderer.py",
                    "agents/studio_compositor/stream_overlay.py",
                    "agents/studio_compositor/token_pole.py",
                    "agents/studio_compositor/tufte_density_ward.py",
                    "agents/studio_compositor/ascii_schematic_ward.py",
                    "agents/studio_compositor/assertion_receipt_ward.py",
                    "agents/studio_compositor/constructivist_research_poster_ward.py",
                    "agents/studio_compositor/interactive_lore_query_ward.py",
                    "agents/studio_compositor/m8_oscilloscope_source.py",
                    "agents/studio_compositor/objectives_overlay.py",
                    "agents/studio_compositor/packed_cameras_source.py",
                    "agents/studio_compositor/polyend_instrument_reveal.py",
                    "agents/studio_compositor/precedent_ticker_ward.py",
                    "agents/scribble_strip_ward",
                ),
            ),
            "homage_visuals": _scan_file_surface(
                repo_root,
                "homage_visuals",
                (
                    "agents/studio_compositor/homage",
                    "assets/homage",
                    "shared/homage_coupling.py",
                    "shared/homage_package.py",
                ),
            ),
            "reverie_imagination": _scan_file_surface(
                repo_root,
                "reverie_imagination",
                (
                    "agents/reverie",
                    "agents/imagination.py",
                    "agents/imagination/METADATA.yaml",
                    "agents/imagination_daemon",
                    "agents/imagination_context.py",
                    "agents/imagination_context/METADATA.yaml",
                    "agents/imagination_loop.py",
                    "agents/imagination_resolver.py",
                    "agents/imagination_resolver/METADATA.yaml",
                    "agents/imagination_source_protocol.py",
                    "agents/reverie_prediction_monitor.py",
                    "agents/visual_chain.py",
                    "agents/visual_chain",
                    "shared/reverie_uniform_policy.py",
                    "hapax-logos/crates/hapax-visual",
                ),
            ),
            "visual_sidecar_agents": _scan_file_surface(
                repo_root,
                "visual_sidecar_agents",
                (
                    "agents/visual_layer_aggregator",
                    "agents/visual_layer_state.py",
                    "agents/visual_layer_state",
                    "agents/visual_pool",
                    "agents/overlay_producer",
                    "agents/art_50_provenance/reverie_overlay.py",
                    "agents/studio_effects",
                ),
            ),
            "visual_output_bridges": _scan_file_surface(
                repo_root,
                "visual_output_bridges",
                (
                    "gst-plugin-glfeedback",
                    "hapax-logos/src-imagination",
                    "hapax-logos/crates/hapax-visual",
                    "hapax-logos/src-tauri/src/visual",
                ),
            ),
            "visual_output_branches": _scan_file_surface(
                repo_root,
                "visual_output_branches",
                (
                    "agents/studio_compositor/snapshots.py",
                    "agents/studio_compositor/v4l2_output_pipeline.py",
                    "agents/studio_compositor/shmsink_output_pipeline.py",
                    "agents/studio_compositor/smooth_delay.py",
                    "agents/studio_compositor/rtmp_output.py",
                    "agents/studio_compositor/output_router.py",
                ),
            ),
            "visual_command_surfaces": _scan_file_surface(
                repo_root,
                "visual_command_surfaces",
                (
                    "logos/api/routes/studio.py",
                    "logos/api/routes/studio_effects.py",
                    "logos/api/routes/studio_compositor.py",
                    "agents/studio_compositor/command_client.py",
                    "agents/studio_compositor/command_server.py",
                    "config/stream-deck/manifest.yaml",
                ),
            ),
            "visual_systemd_units": _scan_file_surface(
                repo_root,
                "visual_systemd_units",
                (
                    "systemd/hapax-imagination.service",
                    "systemd/hapax-reverie-monitor.service",
                    "systemd/hapax-reverie-monitor.timer",
                    "systemd/units/hapax-imagination.service",
                    "systemd/units/hapax-imagination-loop.service",
                    "systemd/units/hapax-imagination-watchdog.service",
                    "systemd/units/hapax-imagination-watchdog.timer",
                    "systemd/units/hapax-reverie.service",
                    "systemd/units/hapax-reverie-monitor.service",
                    "systemd/units/hapax-reverie-monitor.timer",
                    "systemd/units/hapax-visual-pool-snapshot-harvester.service",
                    "systemd/units/hapax-visual-pool-snapshot-harvester.timer",
                    "systemd/units/hapax-visual-stack.target",
                    "systemd/units/studio-compositor.service",
                    "systemd/units/studio-compositor.service.d",
                    "systemd/units/studio-fx-output.service",
                    "systemd/units/studio-fx-output.sh",
                    "systemd/units/visual-layer-aggregator.service",
                    "systemd/overrides/audio-stability/studio-compositor-cpu-affinity.conf",
                    "systemd/overrides/studio-compositor.service.d",
                    "systemd/overrides/studio-fx-output.service.d",
                    "systemd/user-preset.d/hapax.preset",
                ),
            ),
            "visual_plugins": _scan_file_surface(
                repo_root,
                "visual_plugins",
                (
                    "plugins/clock",
                    "plugins/gst-crossfade",
                    "plugins/gst-smooth-delay",
                    "plugins/gst-temporalfx",
                    "gst-plugin-glfeedback",
                ),
            ),
            "shared_visual_policy_models": _scan_file_surface(
                repo_root,
                "shared_visual_policy_models",
                (
                    "shared/compositor_model.py",
                    "shared/director_scrim_gesture_adapter.py",
                    "shared/live_surface_effect_policy.py",
                    "shared/programme_scrim_profile_policy.py",
                    "shared/reverie_uniform_policy.py",
                    "shared/scrim_health_fixtures.py",
                    "shared/scrim_refusal_correction_boundary_gestures.py",
                    "shared/scrim_wcs_claim_posture.py",
                    "shared/segment_quality_layout_eval.py",
                    "shared/shader_bounds.py",
                    "shared/stream_transition_gate.py",
                    "shared/visual_mode_bias.py",
                    "shared/ward_enhancement_profile.py",
                    "shared/ward_fx_bus.py",
                    "shared/ward_pair.py",
                    "shared/ward_publisher_schemas.py",
                    "shared/governance/scrim_invariants",
                ),
            ),
            "visual_manifests_configs": _scan_file_surface(
                repo_root,
                "visual_manifests_configs",
                (
                    "agents/manifests/visual_surface.yaml",
                    "agents/manifests/studio_compositor.yaml",
                    "agents/manifests/imagination_resolver.yaml",
                    "agents/visual_chain/METADATA.yaml",
                    "agents/studio_fx/METADATA.yaml",
                    "config/sister-epic/visual-signature.yaml",
                    "config/compositor-zones.yaml",
                    "config/livestream-render-architecture-shadow-plan.yaml",
                ),
            ),
            "logos_visual_ui": _scan_file_surface(
                repo_root,
                "logos_visual_ui",
                (
                    "hapax-logos/src/components/graph",
                    "hapax-logos/src/components/visual",
                    "hapax-logos/src/components/studio",
                    "hapax-logos/src/components/perception",
                    "hapax-logos/src/hooks/useVisualLayer.ts",
                    "hapax-logos/src/lib/commands/overlay.ts",
                ),
            ),
            "visual_scripts": _scan_file_surface(
                repo_root,
                "visual_scripts",
                (
                    "scripts/demo-transitions.py",
                    "scripts/audit-live-effect-surface.py",
                    "scripts/audit-preset-affordances.py",
                    "scripts/audit-ward-visibility.py",
                    "scripts/compare-preset-variety.py",
                    "scripts/measure-preset-variety-baseline.py",
                    "scripts/generate_preset_edges.py",
                    "scripts/effect_album_cover.py",
                    "scripts/compositor-inspect",
                    "scripts/compositor-inspect-audio",
                    "scripts/compositor-inspect-runtime",
                    "scripts/compositor-inspect-wards",
                    "scripts/compositor-frame-capture.sh",
                    "scripts/hapax-compositor-runtime-source-check",
                    "scripts/install-compositor-layout.sh",
                    "scripts/install-compositor-layouts.sh",
                    "scripts/compositor-vram-snapshot.sh",
                    "scripts/hapax-imagination-watchdog.sh",
                    "scripts/hapax-live-surface-preflight",
                    "scripts/migrate-shader-params.py",
                    "scripts/regenerate-homage-goldens.sh",
                    "scripts/retire-studio-compositor-reload-path.sh",
                    "scripts/smoke_test_reverie.py",
                    "scripts/smoke_test_reverie_checklist.md",
                    "scripts/studio-compositor-archive-precheck.sh",
                    "scripts/studio-compositor-persist-mode.sh",
                    "scripts/studio-compositor-post-start.sh",
                    "scripts/studio-compositor-postmortem.sh",
                    "scripts/visual-audit.sh",
                    "scripts/visual-pool-snapshot-harvester.py",
                ),
            ),
            "legacy_studio_fx": _scan_file_surface(
                repo_root, "legacy_studio_fx", ("agents/studio_fx",)
            ),
            "legacy_studio_fx_registry": legacy_studio_fx_registry,
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
        "palette_count": palette_chains["palette_count"],
        "palette_chain_count": palette_chains["chain_count"],
        "hero_effect_count": len(hero_effects["fragments"]),
        "transition_primitive_count": len(transitions["transition_names"]),
        "layout_count": len(payload["surfaces"]["layouts"]["layouts"]),
        "layout_surface_effect_chain_slot_count": sum(
            layout["surface_effect_chain_slot_count"]
            for layout in payload["surfaces"]["layouts"]["layouts"]
        ),
        "layout_surface_effect_chain_nonempty_count": sum(
            layout["surface_effect_chain_nonempty_count"]
            for layout in payload["surfaces"]["layouts"]["layouts"]
        ),
        "layout_assignment_effect_slot_count": sum(
            layout["assignment_effect_slot_count"]
            for layout in payload["surfaces"]["layouts"]["layouts"]
        ),
        "layout_assignment_effect_nonempty_count": sum(
            layout["assignment_effect_nonempty_count"]
            for layout in payload["surfaces"]["layouts"]["layouts"]
        ),
        "cairo_source_registry_class_count": cairo_source_registry["registered_class_count"],
        "effect_orchestrator_file_count": _surface_file_count(payload, "effect_orchestrators"),
        "studio_compositor_package_file_count": _surface_file_count(
            payload, "studio_compositor_package"
        ),
        "ward_fx_file_count": _surface_file_count(payload, "ward_fx"),
        "cairo_source_file_count": _surface_file_count(payload, "cairo_sources"),
        "cairo_source_registry_file_count": _surface_file_count(payload, "cairo_source_registry"),
        "cairo_ward_implementation_file_count": _surface_file_count(
            payload, "cairo_ward_implementations"
        ),
        "homage_visual_file_count": _surface_file_count(payload, "homage_visuals"),
        "reverie_imagination_file_count": _surface_file_count(payload, "reverie_imagination"),
        "visual_sidecar_agent_file_count": _surface_file_count(payload, "visual_sidecar_agents"),
        "visual_output_bridge_file_count": _surface_file_count(payload, "visual_output_bridges"),
        "visual_output_branch_file_count": _surface_file_count(payload, "visual_output_branches"),
        "visual_command_surface_file_count": _surface_file_count(
            payload, "visual_command_surfaces"
        ),
        "visual_systemd_unit_file_count": _surface_file_count(payload, "visual_systemd_units"),
        "visual_plugin_file_count": _surface_file_count(payload, "visual_plugins"),
        "shared_visual_policy_model_file_count": _surface_file_count(
            payload, "shared_visual_policy_models"
        ),
        "visual_manifest_config_file_count": _surface_file_count(
            payload, "visual_manifests_configs"
        ),
        "logos_visual_ui_file_count": _surface_file_count(payload, "logos_visual_ui"),
        "visual_script_file_count": _surface_file_count(payload, "visual_scripts"),
        "legacy_studio_fx_file_count": _surface_file_count(payload, "legacy_studio_fx"),
        "legacy_studio_fx_effect_count": legacy_studio_fx_registry["registered_effect_count"],
        "high_risk_node_type_count": len(presets["high_risk_node_usage"]),
        "live_surface_bounded_node_type_count": live_surface_policy["bounded_count"],
        "live_surface_blocked_pending_repair_node_type_count": live_surface_policy[
            "blocked_pending_repair_count"
        ],
        "live_surface_unclassified_node_type_count": live_surface_policy["unclassified_count"],
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
