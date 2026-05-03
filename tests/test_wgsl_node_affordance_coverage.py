"""Tests for cc-task wgsl-node-recruitment-investigation (audit U7).

Pins the WGSL-node → affordance-registry coverage relationship. The
investigation found that the live system actively recruited only 8 nodes
(the always-on permanent vocabulary) of the 60 ``.wgsl`` files on disk,
because only 13 had ``CapabilityRecord`` entries in
``shared.affordance_registry.SHADER_NODE_AFFORDANCES`` — the
AffordancePipeline's cosine-similarity stage had no Qdrant entries to
find for the other 47.

This test:

1. Pins the lower bound (≥25 entries currently registered) so a future
   commit that drops registrations is caught at CI time.
2. Reports the gap between WGSL files on disk and registered affordances
   so each PR sees the remaining work (printed via ``capsys``-friendly
   warning, not an assertion failure — Phase 0 picks low-hanging fruit;
   the long tail of 35 remaining nodes is operator-paced cataloguing).
3. Validates the naming contract (every ``node.<x>`` registered points
   at an actual ``<x>.wgsl`` on disk; no orphans).

The lower-bound is intentionally a floor, not parity. Each PR that adds
nodes bumps ``MIN_REGISTERED_NODES`` to lock the new floor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.affordance_registry import SHADER_NODE_AFFORDANCES

REPO_ROOT = Path(__file__).resolve().parent.parent
WGSL_NODE_DIR = REPO_ROOT / "agents" / "shaders" / "nodes"

# Floor pinned 2026-05-03 by cc-task wgsl-node-recruitment-investigation,
# raised by cc-task wgsl-node-affordance-coverage-batch-2 (PR #2281 follow-up).
# Bump this number in the same PR that adds new shader-node affordance
# registrations; the bump is the contract that the new entries are real.
MIN_REGISTERED_NODES = 60


def _wgsl_stems() -> set[str]:
    return {p.stem for p in WGSL_NODE_DIR.glob("*.wgsl")}


def _registered_node_names() -> set[str]:
    """Strip the ``node.`` prefix to get bare WGSL stems."""
    return {r.name.removeprefix("node.") for r in SHADER_NODE_AFFORDANCES}


class TestRegisteredCountFloor:
    """A drop in registered count reveals a regression — never decrease."""

    def test_min_registered_nodes_floor_holds(self) -> None:
        actual = len(SHADER_NODE_AFFORDANCES)
        assert actual >= MIN_REGISTERED_NODES, (
            f"SHADER_NODE_AFFORDANCES dropped from floor "
            f"({MIN_REGISTERED_NODES}) to {actual}; do not unregister "
            f"shader-node affordances without a corresponding floor bump"
        )


class TestNoOrphanedRegistrations:
    """Every registered ``node.<x>`` must point at an actual ``<x>.wgsl``."""

    def test_every_registered_node_has_wgsl_on_disk(self) -> None:
        registered = _registered_node_names()
        on_disk = _wgsl_stems()
        orphans = registered - on_disk
        assert not orphans, (
            f"Registered shader-node affordances point at WGSL files "
            f"that don't exist on disk: {sorted(orphans)}. Either remove "
            f"the registration or restore the .wgsl file at "
            f"agents/shaders/nodes/<name>.wgsl"
        )


class TestUniqueRegistrationNames:
    """The Qdrant point-id is derived from capability_name (uuid5); a
    duplicate name silently overwrites the prior point. Catch dupes at
    CI time, not in production."""

    def test_no_duplicate_node_names(self) -> None:
        names = [r.name for r in SHADER_NODE_AFFORDANCES]
        seen: set[str] = set()
        dupes: list[str] = []
        for n in names:
            if n in seen:
                dupes.append(n)
            seen.add(n)
        assert not dupes, (
            f"Duplicate shader-node affordance names: {dupes}. "
            f"Qdrant uuid5 keying on capability_name means dupes "
            f"silently overwrite prior point payloads."
        )


class TestCoverageVisibility:
    """Surfaces the remaining gap as a soft signal so each PR sees how
    many WGSL files are still missing affordance entries. Not an
    assertion failure — the long tail is operator-paced."""

    def test_print_remaining_unregistered_wgsl_files(self, capsys) -> None:
        registered = _registered_node_names()
        on_disk = _wgsl_stems()
        unregistered = on_disk - registered
        # Always print so the test output (under -v / failure log) carries
        # the gap report. xfail-free — the gap IS the work-in-progress.
        print(
            f"\nWGSL coverage: {len(registered)}/{len(on_disk)} "
            f"({len(registered) * 100 // max(len(on_disk), 1)}%); "
            f"{len(unregistered)} shader files lack affordance entries"
        )
        if unregistered:
            print(f"unregistered: {sorted(unregistered)}")
        assert True  # informational only


@pytest.mark.parametrize(
    "name",
    [
        # Batch 1 — cc-task wgsl-node-recruitment-investigation (PR #2281).
        "node.bloom",
        "node.vhs",
        "node.halftone",
        "node.kaleidoscope",
        "node.scanlines",
        "node.ascii",
        "node.glitch_block",
        "node.pixsort",
        "node.kuwahara",
        "node.dither",
        "node.palette_remap",
        "node.edge_detect",
        # Batch 2 — cc-task wgsl-node-affordance-coverage-batch-2 (PR #2295).
        "node.chroma_key",
        "node.chromatic_aberration",
        "node.circular_mask",
        "node.color_map",
        "node.crossfade",
        "node.displacement_map",
        "node.droste",
        "node.emboss",
        "node.fisheye",
        "node.mirror",
        # Batch 3 — cc-task wgsl-node-affordance-coverage-batch-3 (PR #2297).
        "node.blend",
        "node.diff",
        "node.thermal",
        "node.tunnel",
        "node.posterize",
        "node.slitscan",
        "node.waveform_render",
        "node.particle_system",
        "node.invert",
        "node.strobe",
        # Batch 4 — cc-task wgsl-node-affordance-coverage-batch-4 (this PR;
        # closes the gap to 60 of 60 = 100% coverage).
        "node.grain_bump",
        "node.luma_key",
        "node.noise_overlay",
        "node.palette_extract",
        "node.rutt_etra",
        "node.sharpen",
        "node.sierpinski_lines",
        "node.solid",
        "node.stutter",
        "node.syrup",
        "node.threshold",
        "node.tile",
        "node.transform",
        "node.vignette",
        "node.warp",
    ],
)
def test_phase0_added_node_is_registered(name: str) -> None:
    registered = {r.name for r in SHADER_NODE_AFFORDANCES}
    assert name in registered, (
        f"{name} was added by a wgsl-node-affordance-coverage cc-task "
        f"and must remain registered; if it is intentionally removed, "
        f"drop the corresponding entry in this test's parametrize list "
        f"AND lower MIN_REGISTERED_NODES in the same commit."
    )
