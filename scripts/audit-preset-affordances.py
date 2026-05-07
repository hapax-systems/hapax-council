#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Audit preset-family affordance closure across Qdrant, FAMILY_PRESETS, and disk.

Phase 5 of preset-variety-plan (task #166). Variety scoring (Phases 3, 4)
prices over whatever candidate set retrieval produces. If families are
narrowly represented in Qdrant, recency buys variation within a narrow pool.

Cross-checks three sources:

1. ``shared/affordance_pipeline.py`` Qdrant ``affordances`` collection —
   every ``fx.family.*`` capability registered for retrieval. The
   ``preset.bias`` impingement intent_family routes to capability names
   in the ``fx.family.*`` namespace via ``dispatch_preset_bias``.
2. ``agents/studio_compositor/preset_family_selector.py::FAMILY_PRESETS``
   — the canonical family→preset mapping the dispatcher consults.
3. ``presets/*.json`` — the actual on-disk preset files.

Reports four gap categories:

- **A. Families with <3 members** in ``FAMILY_PRESETS`` (variety floor)
- **B. FAMILY_PRESETS entries missing on disk** (broken dispatch path)
- **C. Disk presets not in any FAMILY_PRESETS** (orphaned content)
- **D. Qdrant ``fx.family.*`` entries divergent from FAMILY_PRESETS**
  (catalog drift; only when Qdrant is reachable)

Output: JSON to stdout (or ``--output``) + optional markdown report
suitable for committing under ``docs/research/``.

Usage:
    scripts/audit-preset-affordances.py [--output PATH] [--markdown PATH]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = REPO_ROOT / "presets"
SELECTOR_PATH = REPO_ROOT / "agents" / "studio_compositor" / "preset_family_selector.py"

# Qdrant queries are best-effort — when unreachable, set D-category to
# "skipped" and continue. The script must work in CI / dev / locked-down
# environments without Qdrant access.


def _string_constant(node: ast.AST) -> str | None:
    """Return the str payload of an ast.Constant, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _string_tuple(node: ast.AST) -> tuple[str, ...] | None:
    """Return a tuple of strings extracted from an ast.Tuple/List of Constants."""
    if not isinstance(node, ast.Tuple | ast.List):
        return None
    items: list[str] = []
    for elt in node.elts:
        s = _string_constant(elt)
        if s is None:
            return None
        items.append(s)
    return tuple(items)


def _extract_family_presets_dict(dict_node: ast.Dict) -> dict[str, tuple[str, ...]] | None:
    """Walk an ast.Dict whose keys are str-Constants and values are tuples-of-str.

    Returns None when the literal contains anything else (ensures the
    auditor never silently misreads non-trivial expressions).
    """
    out: dict[str, tuple[str, ...]] = {}
    for key, value in zip(dict_node.keys, dict_node.values, strict=True):
        if key is None:
            return None
        family = _string_constant(key)
        presets = _string_tuple(value)
        if family is None or presets is None:
            return None
        out[family] = presets
    return out


def load_family_presets() -> dict[str, tuple[str, ...]]:
    """Extract ``FAMILY_PRESETS`` from preset_family_selector.py via AST walk.

    Cannot ``import`` the dispatcher module here because the script's
    PEP 723 header (``dependencies = []``) deliberately runs in an
    isolated environment without project deps, but importing
    ``agents.studio_compositor.preset_family_selector`` transitively
    triggers ``agents.studio_compositor.__init__`` → ``compositor.py``
    → ``shared.compositor_model`` → ``pydantic`` (not in script env).

    Walk the module-level AST instead, find the ``FAMILY_PRESETS``
    annotated assignment, and extract its dict literal. Family names
    are str-Constants; preset lists are tuples of str-Constants. Any
    departure from this shape (operator-defined helpers, computed
    keys, splat expansion) → fall back to the importing path so the
    audit doesn't silently misread.
    """
    try:
        tree = ast.parse(SELECTOR_PATH.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return _import_fallback_family_presets()

    for node in tree.body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "FAMILY_PRESETS"
                and isinstance(node.value, ast.Dict)
            ):
                extracted = _extract_family_presets_dict(node.value)
                if extracted is not None:
                    return extracted
                return _import_fallback_family_presets()
    return _import_fallback_family_presets()


def _import_fallback_family_presets() -> dict[str, tuple[str, ...]]:
    """Last-resort import — only works when run inside the project venv."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from agents.studio_compositor.preset_family_selector import FAMILY_PRESETS

        return dict(FAMILY_PRESETS)
    finally:
        if str(REPO_ROOT) in sys.path:
            sys.path.remove(str(REPO_ROOT))


def disk_preset_names() -> set[str]:
    """``presets/*.json`` filename stems, excluding underscore-prefixed
    metadata files (e.g. ``shader_intensity_bounds.json``)."""
    return {p.stem for p in PRESETS_DIR.glob("*.json") if not p.name.startswith("_")}


def query_qdrant_preset_affordances() -> tuple[set[str] | None, str | None]:
    """Return Qdrant-registered ``preset.bias.*`` capability names.

    Returns ``(None, error_msg)`` when Qdrant is unreachable so callers
    can mark category D as 'skipped' rather than failing the audit.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from shared.affordance_pipeline import COLLECTION_NAME
        from shared.config import get_qdrant
    except Exception as exc:  # noqa: BLE001
        return None, f"import failed: {exc}"
    finally:
        if str(REPO_ROOT) in sys.path:
            sys.path.remove(str(REPO_ROOT))

    try:
        client = get_qdrant()
        # Scroll the collection; cap at a generous batch since the catalog
        # is small (~100 capabilities total).
        offset = None
        names: set[str] = set()
        for _ in range(20):  # safety bound on scroll iterations
            result, offset = client.scroll(
                collection_name=COLLECTION_NAME,
                limit=200,
                offset=offset,
                with_payload=["capability_name"],
                with_vectors=False,
            )
            for point in result:
                payload = getattr(point, "payload", None) or {}
                # Qdrant payload uses ``capability_name`` (the canonical
                # field on ``CapabilityRecord``); fall back to ``name``
                # for any legacy entries that pre-date that rename.
                name = payload.get("capability_name") or payload.get("name", "")
                # The ``preset.bias`` intent_family routes to capability
                # names in the ``fx.family.*`` namespace via
                # ``dispatch_preset_bias`` (compositional_consumer.py).
                if isinstance(name, str) and name.startswith("fx.family."):
                    names.add(name)
            if offset is None:
                break
        return names, None
    except Exception as exc:  # noqa: BLE001
        return None, f"qdrant query failed: {exc}"


def compute_findings(
    family_presets: dict[str, tuple[str, ...]],
    disk_presets: set[str],
    qdrant_preset_bias: set[str] | None,
    qdrant_error: str | None,
) -> dict:
    """Build the structured findings dict."""
    # A: families with <3 members
    thin_families = {
        family: list(members) for family, members in family_presets.items() if len(members) < 3
    }

    # B: FAMILY_PRESETS entries missing on disk
    family_set: set[str] = set()
    for members in family_presets.values():
        family_set.update(members)
    missing_on_disk = sorted(family_set - disk_presets)

    # C: disk presets not in any FAMILY_PRESETS
    orphaned_on_disk = sorted(disk_presets - family_set)

    # D: Qdrant entries with no FAMILY_PRESETS family
    qdrant_drift: dict | str
    if qdrant_preset_bias is None:
        qdrant_drift = {"status": "skipped", "reason": qdrant_error or "unknown"}
    else:
        expected = {f"fx.family.{name}" for name in family_presets}
        unexpected = sorted(qdrant_preset_bias - expected)
        missing_in_qdrant = sorted(expected - qdrant_preset_bias)
        qdrant_drift = {
            "status": "ok",
            "qdrant_count": len(qdrant_preset_bias),
            "in_qdrant_not_in_family_map": unexpected,
            "in_family_map_not_in_qdrant": missing_in_qdrant,
        }

    return {
        "summary": {
            "family_count": len(family_presets),
            "disk_preset_count": len(disk_presets),
            "thin_family_count": len(thin_families),
            "missing_on_disk_count": len(missing_on_disk),
            "orphaned_on_disk_count": len(orphaned_on_disk),
        },
        "A_thin_families": thin_families,
        "B_family_entries_missing_on_disk": missing_on_disk,
        "C_disk_presets_orphaned": orphaned_on_disk,
        "D_qdrant_drift": qdrant_drift,
    }


def render_markdown(findings: dict) -> str:
    """Render the findings into a markdown report body."""
    s = findings["summary"]
    lines = [
        "# Preset affordance audit",
        "",
        f"- families: {s['family_count']}",
        f"- disk presets: {s['disk_preset_count']}",
        f"- thin families (<3 members): {s['thin_family_count']}",
        f"- family entries missing on disk: {s['missing_on_disk_count']}",
        f"- disk presets orphaned: {s['orphaned_on_disk_count']}",
        "",
        "## A. Thin families (<3 members)",
        "",
    ]
    if findings["A_thin_families"]:
        for family, members in findings["A_thin_families"].items():
            lines.append(f"- `{family}` ({len(members)}): {', '.join(members) or '∅'}")
    else:
        lines.append("(none — every family meets the variety floor)")
    lines.extend(
        [
            "",
            "## B. FAMILY_PRESETS entries missing on disk",
            "",
        ]
    )
    if findings["B_family_entries_missing_on_disk"]:
        for name in findings["B_family_entries_missing_on_disk"]:
            lines.append(f"- `{name}`")
    else:
        lines.append("(none)")
    lines.extend(
        [
            "",
            "## C. Disk presets not in any FAMILY_PRESETS",
            "",
        ]
    )
    if findings["C_disk_presets_orphaned"]:
        for name in findings["C_disk_presets_orphaned"]:
            lines.append(f"- `{name}.json`")
    else:
        lines.append("(none)")
    lines.extend(
        [
            "",
            "## D. Qdrant `fx.family.*` drift",
            "",
        ]
    )
    drift = findings["D_qdrant_drift"]
    if drift.get("status") == "skipped":
        lines.append(f"_skipped: {drift.get('reason', 'unknown')}_")
    else:
        lines.append(f"- qdrant entries: {drift['qdrant_count']}")
        if drift["in_qdrant_not_in_family_map"]:
            lines.append("- in Qdrant but not in `FAMILY_PRESETS`:")
            for name in drift["in_qdrant_not_in_family_map"]:
                lines.append(f"  - `{name}`")
        if drift["in_family_map_not_in_qdrant"]:
            lines.append("- in `FAMILY_PRESETS` but not in Qdrant:")
            for name in drift["in_family_map_not_in_qdrant"]:
                lines.append(f"  - `{name}`")
        if not drift["in_qdrant_not_in_family_map"] and not drift["in_family_map_not_in_qdrant"]:
            lines.append("(no drift)")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON findings to this path (default: stdout).",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        help="Also render a markdown report to this path.",
    )
    parser.add_argument(
        "--no-qdrant",
        action="store_true",
        help="Skip the Qdrant drift check entirely (offline / CI mode).",
    )
    args = parser.parse_args()

    family_presets = load_family_presets()
    disk_presets = disk_preset_names()
    if args.no_qdrant:
        qdrant_names, qdrant_error = None, "skipped via --no-qdrant"
    else:
        qdrant_names, qdrant_error = query_qdrant_preset_affordances()

    findings = compute_findings(family_presets, disk_presets, qdrant_names, qdrant_error)

    payload = json.dumps(findings, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(findings), encoding="utf-8")

    # Non-zero exit when any A/B finding lands so CI / pre-commit can
    # gate on closure. C and D are advisory; orphaned disk presets are
    # legitimate (unused experiments) and Qdrant drift may be stale.
    has_critical = bool(findings["A_thin_families"]) or bool(
        findings["B_family_entries_missing_on_disk"]
    )
    return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())
