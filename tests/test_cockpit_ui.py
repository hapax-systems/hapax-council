"""Tests for cockpit formatters: render_infra_detail, render_scout_detail.

No LLM calls; tests focus on render function output.
"""

from __future__ import annotations

from rich.text import Text

from cockpit.data.infrastructure import ContainerStatus
from cockpit.data.scout import ScoutData, ScoutRecommendation
from cockpit.formatters import render_infra_detail, render_scout_detail

# ── render_infra_detail tests ────────────────────────────────────────────────


def test_render_infra_detail_empty():
    """Empty container list returns 'No containers' text."""
    result = render_infra_detail([])
    assert "No containers" in result.plain


def test_render_infra_detail_with_data():
    """Container list renders names and status."""
    containers = [
        ContainerStatus(
            name="ollama",
            service="ollama",
            state="running",
            health="healthy",
        ),
        ContainerStatus(
            name="qdrant",
            service="qdrant",
            state="running",
            health="healthy",
        ),
        ContainerStatus(
            name="postgres",
            service="postgres",
            state="exited",
            health="",
        ),
    ]
    result = render_infra_detail(containers)
    plain = result.plain
    assert "ollama" in plain
    assert "qdrant" in plain
    assert "postgres" in plain
    assert "3 containers, 2 healthy" in plain


def test_render_infra_detail_returns_text():
    """render_infra_detail always returns a rich Text object."""
    assert isinstance(render_infra_detail([]), Text)
    containers = [
        ContainerStatus(name="x", service="x", state="running", health="healthy"),
    ]
    assert isinstance(render_infra_detail(containers), Text)


# ── render_scout_detail tests ────────────────────────────────────────────────


def test_render_scout_detail_none():
    """None scout data returns 'No scout report' text."""
    result = render_scout_detail(None)
    assert "No scout report" in result.plain


def test_render_scout_detail_with_data():
    """Scout data renders tier icons and recommendations."""
    scout = ScoutData(
        generated_at="2026-03-01T07:00:00+00:00",
        components_scanned=5,
        recommendations=[
            ScoutRecommendation(
                component="litellm",
                current="1.50.0",
                tier="evaluate",
                summary="New version available with breaking changes",
                confidence="medium",
            ),
            ScoutRecommendation(
                component="qdrant",
                current="1.12.0",
                tier="current-best",
                summary="No changes needed",
                confidence="high",
            ),
        ],
        adopt_count=0,
        evaluate_count=1,
    )
    result = render_scout_detail(scout)
    plain = result.plain
    assert "5 components" in plain
    assert "litellm" in plain
    assert "evaluate" in plain
    assert "1 current-best" in plain


def test_render_scout_detail_returns_text():
    """render_scout_detail always returns a rich Text object."""
    assert isinstance(render_scout_detail(None), Text)
    scout = ScoutData(components_scanned=0)
    assert isinstance(render_scout_detail(scout), Text)
