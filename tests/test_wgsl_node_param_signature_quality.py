"""u7-per-node-parametrize-signature-quality-audit — shader node JSON spec audit.

cc-task `u7-per-node-parametrize-signature-quality-audit`. Each WGSL shader
node carries a JSON spec at `agents/shaders/nodes/<name>.json` whose `params`
dict drives:
  * Python visual-chain `compute_param_deltas()` writes per-node modulation
    to `uniforms.json`
  * Rust `DynamicPipeline` positional parse against `param_order`
  * Operator/director recruitment writes named param overrides

If a param spec is malformed (missing `type`, missing `default`, `min >= max`,
default outside `[min, max]`), the visual chain or Rust side may crash silently
or apply the wrong value. This file pins the spec quality so future drift is
caught at CI time.

Audit rules (per param):
  * `type` is required.
  * For `type == "float"`: `default` is required.
  * If BOTH `min` and `max` are present: `min < max`, and `default` falls in
    `[min, max]`.
  * If only ONE of `min`/`max` is present: spec error (half-bound range).
  * If NEITHER is present: allowed (driver-set params like `time`, `width`,
    `height`).

Floor: every existing `.json` spec must pass. ``MIN_NODE_SPECS`` is the
lower bound on count so PRs that silently delete spec files are caught.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_DIR = REPO_ROOT / "agents" / "shaders" / "nodes"

# Floor pinned 2026-05-03 by cc-task u7-per-node-parametrize-signature-
# quality-audit (this PR). Bump in the same PR that adds new shader
# node spec files; the bump is the contract that the new specs are real.
MIN_NODE_SPECS = 63

# Some specs are intentionally not 1:1 WGSL shader nodes:
# - output is a graph-level pseudo node.
# Keep these exceptions explicit so future drift cannot hide inside the raw
# count floor.
JSON_SPECS_WITHOUT_WGSL = frozenset({"output"})
WGSL_NODES_WITHOUT_JSON_SPEC = frozenset()


def _spec_files() -> list[Path]:
    return sorted(NODE_DIR.glob("*.json"))


def _wgsl_files() -> list[Path]:
    return sorted(NODE_DIR.glob("*.wgsl"))


def _audit_one(spec: dict, source: str) -> Iterator[str]:
    """Yield one human-readable issue string per problem found in `spec`."""
    if not isinstance(spec, dict):
        yield f"{source}: spec is not a dict"
        return
    params = spec.get("params", {})
    if not isinstance(params, dict):
        yield f"{source}: params is not a dict"
        return
    for name, decl in params.items():
        if not isinstance(decl, dict):
            yield f"{source}::{name}: declaration is not a dict"
            continue
        if "type" not in decl:
            yield f"{source}::{name}: missing `type`"
            continue
        ptype = decl["type"]
        if ptype == "float":
            if "default" not in decl:
                yield f"{source}::{name}: float param missing `default`"
                continue
            has_min = "min" in decl
            has_max = "max" in decl
            if has_min ^ has_max:
                yield (
                    f"{source}::{name}: half-bound range "
                    f"(only one of `min`/`max` declared) — declare both or neither"
                )
                continue
            if has_min and has_max:
                lo, hi, default = decl["min"], decl["max"], decl["default"]
                if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
                    yield f"{source}::{name}: min/max not numeric"
                    continue
                if lo >= hi:
                    yield f"{source}::{name}: degenerate range min={lo} >= max={hi}"
                    continue
                if not isinstance(default, (int, float)):
                    yield f"{source}::{name}: default not numeric"
                    continue
                if not (lo <= default <= hi):
                    yield (f"{source}::{name}: default {default} outside [{lo}, {hi}]")


# ── Floor pin ───────────────────────────────────────────────────────


def test_minimum_spec_count() -> None:
    """A future PR that silently deletes spec files is caught here."""
    assert len(_spec_files()) >= MIN_NODE_SPECS, (
        f"Found {len(_spec_files())} node spec files; floor is {MIN_NODE_SPECS}. "
        "Did a PR remove specs without bumping the floor?"
    )


def test_wgsl_spec_inventory_matches_allowlisted_asymmetry() -> None:
    """Every live WGSL node should have a JSON spec unless explicitly
    allowlisted, and every JSON spec should point at a WGSL node unless it
    is an explicit graph-level or legacy exception."""
    json_stems = {path.stem for path in _spec_files()}
    wgsl_stems = {path.stem for path in _wgsl_files()}

    json_without_wgsl = json_stems - wgsl_stems
    wgsl_without_json = wgsl_stems - json_stems

    assert json_without_wgsl == JSON_SPECS_WITHOUT_WGSL
    assert wgsl_without_json == WGSL_NODES_WITHOUT_JSON_SPEC


# ── Per-spec audit ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "spec_path",
    _spec_files(),
    ids=lambda p: p.stem,
)
def test_spec_node_type_matches_filename(spec_path: Path) -> None:
    """The spec filename is the runtime node identifier. Keep
    ``node_type`` aligned so registry lookups and telemetry labels do not
    silently diverge."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec.get("node_type") == spec_path.stem


@pytest.mark.parametrize(
    "spec_path",
    _spec_files(),
    ids=lambda p: p.stem,
)
def test_spec_passes_audit(spec_path: Path) -> None:
    """Every shader node JSON must pass the param-signature audit."""
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        pytest.fail(f"{spec_path.name}: invalid JSON — {e}")
    issues = list(_audit_one(spec, spec_path.stem))
    assert not issues, f"{spec_path.name} spec audit failed:\n  " + "\n  ".join(issues)


# ── Whole-fleet sweep (informational) ───────────────────────────────


def test_audit_helpers_self_consistent() -> None:
    """Sanity pin on `_audit_one`: a clean synthetic spec passes; a
    seeded-bad one trips the right rules."""
    clean = {
        "node_type": "synthetic",
        "params": {
            "saturation": {"type": "float", "default": 1.0, "min": 0.0, "max": 2.0},
            "time": {"type": "float", "default": 0.0},  # driver-set, no range
        },
    }
    assert list(_audit_one(clean, "synthetic-clean")) == []

    bad_missing_type = {"params": {"saturation": {"default": 1.0}}}
    issues = list(_audit_one(bad_missing_type, "synthetic-1"))
    assert any("missing `type`" in i for i in issues)

    bad_half_bound = {"params": {"saturation": {"type": "float", "default": 1.0, "min": 0.0}}}
    issues = list(_audit_one(bad_half_bound, "synthetic-2"))
    assert any("half-bound range" in i for i in issues)

    bad_degenerate = {
        "params": {"saturation": {"type": "float", "default": 1.0, "min": 1.0, "max": 1.0}}
    }
    issues = list(_audit_one(bad_degenerate, "synthetic-3"))
    assert any("degenerate range" in i for i in issues)

    bad_default_out_of_range = {
        "params": {"saturation": {"type": "float", "default": 5.0, "min": 0.0, "max": 2.0}}
    }
    issues = list(_audit_one(bad_default_out_of_range, "synthetic-4"))
    assert any("outside" in i for i in issues)

    bad_missing_default = {"params": {"saturation": {"type": "float", "min": 0.0, "max": 2.0}}}
    issues = list(_audit_one(bad_missing_default, "synthetic-5"))
    assert any("missing `default`" in i for i in issues)


def test_audit_handles_empty_params() -> None:
    """Some content-only nodes legitimately have no params — empty
    params dict must pass the audit."""
    spec = {"node_type": "content_only", "params": {}}
    assert list(_audit_one(spec, "content-only")) == []


def test_audit_handles_int_type_params() -> None:
    """Non-float param types (int, etc.) bypass the float-specific
    range checks — only `type` is required for them."""
    spec = {
        "params": {
            "iteration_count": {"type": "int", "default": 4},
        }
    }
    # int param without min/max should not trip the half-bound rule.
    assert list(_audit_one(spec, "int-only")) == []
