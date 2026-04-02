"""Fragility tests for unified semantic recruitment.

These tests verify correct behavior under edge conditions identified
during code review of the recruitment pipeline, content routing,
imagination model, and expression capability registrations.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

# ---------- 1. Pipeline returns empty (no recruitment match) ----------


def test_tool_recruitment_empty_returns_no_tools():
    """When pipeline returns no candidates, recruit() returns empty list."""
    from agents.hapax_daimonion.tool_recruitment import ToolRecruitmentGate

    gate = ToolRecruitmentGate.__new__(ToolRecruitmentGate)
    gate._pipeline = MagicMock()
    gate._pipeline.select.return_value = []
    gate._tool_names = {"get_weather"}

    result = gate.recruit("something completely unrelated to any tool")
    assert result == []


def test_content_router_no_match_returns_false():
    """Camera activation with unknown affordance returns False."""
    from agents.reverie._content_capabilities import ContentCapabilityRouter

    router = ContentCapabilityRouter()
    assert router.activate_camera("content.nonexistent", 0.5) is False


# ---------- 2. Stale imagination fragment handling ----------


def test_slot_opacities_none_imagination():
    """No imagination -> zero opacities."""
    from agents.reverie._uniforms import build_slot_opacities

    assert build_slot_opacities(None, 0.0) == [0.0, 0.0, 0.0, 0.0]


def test_slot_opacities_zero_salience():
    """Zero salience imagination -> zero opacities."""
    from agents.reverie._uniforms import build_slot_opacities

    assert build_slot_opacities({"salience": 0.0}, 0.0) == [0.0, 0.0, 0.0, 0.0]


# ---------- 3. FRAGMENT_TO_SHADER params match actual shader param_order ----------


def test_fragment_to_shader_uses_valid_params():
    """FRAGMENT_TO_SHADER params must exist in visual chain VISUAL_DIMENSIONS mappings."""
    from agents.visual_chain import VISUAL_DIMENSIONS
    from shared.expression import FRAGMENT_TO_SHADER

    # Collect all param names that visual chain actually maps to
    valid_params = set()
    for dim in VISUAL_DIMENSIONS.values():
        for mapping in dim.parameter_mappings:
            valid_params.add(f"{mapping.technique}.{mapping.param}")

    for dim_name, shader_param in FRAGMENT_TO_SHADER.items():
        assert shader_param in valid_params, (
            f"FRAGMENT_TO_SHADER['{dim_name}'] = '{shader_param}' "
            f"is not in visual chain's valid params: {sorted(valid_params)}"
        )


# ---------- 4. can_resolve() not called outside pipeline in dispatch ----------


def test_mixer_visual_chain_uses_pipeline_score():
    """Visual chain activation should use pipeline combined score, not can_resolve()."""
    source = Path("agents/reverie/mixer.py").read_text()
    tree = ast.parse(source)

    # Find dispatch_impingement method
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "dispatch_impingement":
            source_lines = source.split("\n")
            method_source = "\n".join(source_lines[node.lineno - 1 : node.end_lineno])
            assert "can_resolve" not in method_source, (
                "dispatch_impingement still calls can_resolve() — should use c.combined"
            )
            break


# ---------- 5. Medium field present on key registrations ----------


def test_all_expression_capabilities_have_medium():
    """All expression capabilities must declare their output medium."""
    from agents.hapax_daimonion.vocal_chain import VOCAL_CHAIN_RECORDS
    from agents.visual_chain import VISUAL_CHAIN_RECORDS

    for rec in VISUAL_CHAIN_RECORDS:
        assert rec.operational.medium is not None, f"{rec.name} missing medium"

    for rec in VOCAL_CHAIN_RECORDS:
        assert rec.operational.medium is not None, f"{rec.name} missing medium"


# ---------- 6. No content_references anywhere in imagination model ----------


def test_imagination_fragment_has_no_content_references():
    """ImaginationFragment must not have content_references field."""
    from agents.imagination import ImaginationFragment

    fields = set(ImaginationFragment.model_fields.keys())
    assert "content_references" not in fields


def test_imagination_system_prompt_clean():
    """System prompt must not mention content sources or content_references."""
    from agents.imagination_loop import IMAGINATION_SYSTEM_PROMPT

    assert "content_references" not in IMAGINATION_SYSTEM_PROMPT
    assert "camera_frame" not in IMAGINATION_SYSTEM_PROMPT
    assert "qdrant_query" not in IMAGINATION_SYSTEM_PROMPT
