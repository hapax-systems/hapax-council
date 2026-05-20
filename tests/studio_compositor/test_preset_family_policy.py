from __future__ import annotations

from pathlib import Path

from agents.effect_graph.registry import ShaderRegistry
from agents.studio_compositor.preset_family_policy import (
    family_policy_reason_counts,
    inspect_family_policy,
    policy_eligible_presets_for_family,
)

NODES_DIR = Path(__file__).parent.parent.parent / "agents" / "shaders" / "nodes"


def _registry() -> ShaderRegistry:
    return ShaderRegistry(NODES_DIR)


def test_glitch_dense_regains_source_bound_policy_eligible_candidates() -> None:
    eligible = set(policy_eligible_presets_for_family("glitch-dense", registry=_registry(), env={}))

    assert eligible == {"pixsort_preset"}


def test_audio_reactive_temporal_pixsort_variants_remain_blocked_without_visual_evidence() -> None:
    eligible = set(policy_eligible_presets_for_family("audio-reactive", registry=_registry(), env={}))

    assert eligible == set()


def test_family_inventory_reports_exact_remaining_block_reasons() -> None:
    rows = inspect_family_policy("glitch-dense", registry=_registry(), env={})
    by_preset = {row.preset: row for row in rows}

    assert by_preset["pixsort_preset"].allowed is True
    assert by_preset["datamosh"].allowed is False
    assert by_preset["datamosh"].reason == "camera_legible_glsl_pending_source_bound_repair"
    assert by_preset["datamosh"].matched == ("stutter", "stutter")
    assert by_preset["xerox_photocopy_decay"].allowed is False
    assert by_preset["xerox_photocopy_decay"].reason == (
        "camera_legible_glsl_pending_source_bound_repair"
    )
    assert by_preset["xerox_photocopy_decay"].matched == ("threshold_xerox", "threshold")

    counts = family_policy_reason_counts("glitch-dense", registry=_registry(), env={})
    assert counts == {"camera_legible_glsl_pending_source_bound_repair": 14}


def test_remaining_blocked_family_presets_stay_mapped_to_policy_reasons() -> None:
    for family in ("calm-textural", "warm-minimal"):
        rows = inspect_family_policy(family, registry=_registry(), env={})
        blocked = [row for row in rows if not row.allowed]
        assert blocked
        assert all(row.reason for row in blocked)
