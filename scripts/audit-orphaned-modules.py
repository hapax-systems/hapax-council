#!/usr/bin/env python3
"""Audit all shared/ and agents/ modules with zero non-test importers.

Produces a JSON inventory at docs/audits/orphaned-modules-YYYY-MM-DD.json.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}
SOURCE_DIRS = ["shared", "agents"]

NAMED_ORPHANS = {
    "ward_spatial_affordance": "WardSpatialAffordance",
    "hardm_signal_map": "HARDM signal map",
    "audio_visual_modulation": "anti-visualizer oracle",
    "monetization": "monetization agent",
    "eigenform": "eigenform module",
    "density_field": "density-field module",
}

SPEC_ALIGNED_PATTERNS = {
    "shared/config.py",
    "shared/working_mode.py",
    "shared/notify.py",
    "shared/frontmatter.py",
    "shared/dimensions.py",
    "shared/governance/consent.py",
    "shared/agent_registry.py",
    "shared/telemetry.py",
    "shared/audio_routing_policy.py",
    "shared/audio_topology_inspector.py",
    "shared/claim.py",
    "shared/affordance.py",
}


def _excluded(path: Path) -> bool:
    return any(ex in path.parts for ex in EXCLUDE_DIRS)


def _build_import_map(root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    importers: dict[str, set[str]] = defaultdict(set)
    test_importers: dict[str, set[str]] = defaultdict(set)

    for py_file in root.rglob("*.py"):
        if _excluded(py_file):
            continue
        is_test = "tests" in py_file.parts or py_file.name.startswith("test_")
        try:
            source = py_file.read_text(errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except Exception:
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            target = importers if not is_test else test_importers
            rel = str(py_file.relative_to(root))
            for mod in mods:
                target[mod].add(rel)

    return importers, test_importers


def _path_to_module(root: Path, p: Path) -> str:
    rel = p.relative_to(root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].replace(".py", "")
    return ".".join(parts)


def _has_importer(
    mod_name: str,
    file_rel: str,
    importers: dict[str, set[str]],
) -> bool:
    for imported_mod, imp_files in importers.items():
        if imported_mod == mod_name or imported_mod.startswith(mod_name + "."):
            non_self = {f for f in imp_files if f != file_rel}
            if non_self:
                return True
    return False


def _count_test_importers(mod_name: str, test_importers: dict[str, set[str]]) -> int:
    count = 0
    for imported_mod, imp_files in test_importers.items():
        if imported_mod == mod_name or imported_mod.startswith(mod_name + "."):
            count += len(imp_files)
    return count


def _last_commit_author(root: Path, rel_path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%an", "--", rel_path],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _named_orphan_label(rel_path: str) -> str | None:
    for pattern, label in NAMED_ORPHANS.items():
        if pattern in rel_path:
            return label
    return None


def _recommend_action(rel_path: str, loc: int, test_count: int) -> str:
    if loc < 50 and test_count == 0:
        return "retire"
    if any(p in rel_path for p in ("takeout/", "legacy_", "cycle_mode")):
        return "retire"
    if rel_path in SPEC_ALIGNED_PATTERNS:
        return "wire"
    if test_count >= 3 and loc > 100:
        return "defer"
    if loc > 500:
        return "defer"
    return "retire"


def main() -> int:
    importers, test_importers = _build_import_map(ROOT)

    orphans: list[dict[str, object]] = []
    for source_dir in SOURCE_DIRS:
        for py_file in (ROOT / source_dir).rglob("*.py"):
            if _excluded(py_file) or py_file.name == "__init__.py":
                continue
            rel = str(py_file.relative_to(ROOT))
            mod_name = _path_to_module(ROOT, py_file)
            if _has_importer(mod_name, rel, importers):
                continue
            loc = len(py_file.read_text(errors="replace").splitlines())
            test_count = _count_test_importers(mod_name, test_importers)
            author = _last_commit_author(ROOT, rel)
            named = _named_orphan_label(rel)

            orphans.append(
                {
                    "path": rel,
                    "module": mod_name,
                    "loc": loc,
                    "last_author": author,
                    "test_importers": test_count,
                    "named_orphan": named,
                    "spec_aligned": rel in SPEC_ALIGNED_PATTERNS,
                    "recommended_action": _recommend_action(rel, loc, test_count),
                }
            )

    orphans.sort(key=lambda x: (-x["loc"],))

    output = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_root": str(ROOT),
        "total_orphaned_modules": len(orphans),
        "total_orphaned_loc": sum(o["loc"] for o in orphans),
        "named_orphans_found": [o["path"] for o in orphans if o["named_orphan"]],
        "action_summary": {
            "wire": len([o for o in orphans if o["recommended_action"] == "wire"]),
            "retire": len([o for o in orphans if o["recommended_action"] == "retire"]),
            "defer": len([o for o in orphans if o["recommended_action"] == "defer"]),
        },
        "modules": orphans,
    }

    out_dir = ROOT / "docs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = out_dir / f"orphaned-modules-{date_str}.json"
    out_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"wrote {out_path} ({len(orphans)} modules, {output['total_orphaned_loc']} LOC)")
    print(f"actions: {output['action_summary']}")
    print(f"named orphans: {output['named_orphans_found']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
