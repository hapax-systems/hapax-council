"""Auto-discovering render smoke for every audience artifact.

Walks ``docs/audience/*.md`` at collection-time and parametrizes a
render smoke test for each discovered artifact. New audience
artifacts are auto-pinned without test-file changes; existing
artifacts that lose their frontmatter are caught at PR-time.

Companion to the per-artifact regression pins
(``test_actual_<artifact>_renders``); those make explicit assertions
about each artifact's surface key + byline + clause shape, while
this smoke validates the auto-discovery contract: every audience
artifact's frontmatter is valid + renderable.

Outline-style artifacts (``*-outline.md``) are intentionally
included — they share the same frontmatter contract as the prose
artifacts and should render cleanly even though their bodies are
shorter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIENCE_DIR = REPO_ROOT / "docs" / "audience"


def _audience_artifacts() -> list[Path]:
    """Discover all markdown files under docs/audience/.

    Returns an empty list when the directory is absent (pre-V5-weave
    bootstrap), which makes the parametrize collection cleanly empty
    rather than raising at import time.
    """
    if not AUDIENCE_DIR.is_dir():
        return []
    return sorted(AUDIENCE_DIR.glob("*.md"))


@pytest.mark.parametrize("artifact_path", _audience_artifacts(), ids=lambda p: p.name)
def test_audience_artifact_renders(
    artifact_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every docs/audience/*.md renders cleanly via render_publish_artifact.

    Pins the frontmatter contract: each artifact must declare
    ``authors.byline_variant`` and ``authors.unsettled_variant`` (or
    fall back to defaults), and the render must produce a non-empty
    AttributionBlock.

    The test uses a placeholder ``HAPAX_OPERATOR_NAME`` so it does not
    depend on operator-side env config; this validates the render
    contract in CI without leaking the operator's legal name.
    """
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import render_publish_artifact

    result = render_publish_artifact(artifact_path)

    # The artifact must declare a surface that maps to a usable
    # render output.
    assert result.surface_key  # non-empty string
    # The byline must be non-empty and contain the placeholder
    # operator name (proves the render path read the env).
    assert result.attribution.byline_text
    assert "Test Operator" in result.attribution.byline_text
    # The unsettled-contribution sentence is always non-empty
    # (one of the V1-V5 templates).
    assert result.attribution.unsettled_sentence


def test_audience_dir_has_artifacts() -> None:
    """Sanity check: the audience directory is not empty.

    If the audience directory becomes empty (artifacts deleted
    accidentally, directory renamed), this test fails the smoke
    suite even if the parametrize pass produces zero items.
    """
    artifacts = _audience_artifacts()
    assert len(artifacts) > 0, (
        "docs/audience/ contains zero artifacts; did the V5 weave "
        "audience tree get moved? Expected at least the Constitutional "
        "Brief, Aesthetic Library Manifesto, and Self-Censorship "
        "essays plus their outlines."
    )
