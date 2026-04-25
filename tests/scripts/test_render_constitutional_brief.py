"""Tests for ``scripts/render_constitutional_brief.py`` (V5 wk1 follow-on).

The renderer takes a markdown source path + operator credentials,
parses the YAML frontmatter for byline-variant + unsettled-variant +
surface-deviation-matrix-key, renders the attribution block via the
registered modules, and returns the publish-shaped artifact metadata.

Per V5 weave Constitutional Brief outline §Approval queue: the
substrate-to-prose pass (#1436) ships the source; this renderer
closes the source-to-publish pipeline. The eventual Pandoc PDF
render consumes this metadata; today's scaffold validates the
attribution block can be assembled end-to-end with the registered
modules.
"""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def synthetic_brief_md(tmp_path: Path) -> Path:
    """A minimal brief-shaped markdown file with V5 frontmatter."""
    p = tmp_path / "synthetic-brief.md"
    p.write_text(
        dedent(
            """\
            ---
            title: "Synthetic test brief"
            authors:
              byline_variant: V2
              unsettled_variant: V3
              surface: philarchive
              surface_deviation_matrix_key: philarchive
            non_engagement_clause_form: LONG
            ---

            # Synthetic test brief

            Body content here.
            """
        )
    )
    return p


def test_renders_attribution_block_from_frontmatter(
    monkeypatch: pytest.MonkeyPatch, synthetic_brief_md: Path
) -> None:
    """Renderer reads frontmatter + env, returns AttributionBlock + meta."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import render_publish_artifact

    result = render_publish_artifact(synthetic_brief_md)

    assert result.attribution.byline_text  # non-empty
    assert result.attribution.unsettled_sentence  # non-empty
    assert result.attribution.non_engagement_clause is not None
    assert "Refusal Brief" in result.attribution.non_engagement_clause
    assert result.surface_key == "philarchive"
    assert "Test Operator" in result.attribution.byline_text


def test_v2_byline_includes_three_attributions(
    monkeypatch: pytest.MonkeyPatch, synthetic_brief_md: Path
) -> None:
    """V2 byline = operator + Hapax + Claude Code three-way."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import render_publish_artifact

    result = render_publish_artifact(synthetic_brief_md)

    assert "Test Operator" in result.attribution.byline_text
    assert "Hapax" in result.attribution.byline_text
    assert "Claude Code" in result.attribution.byline_text


def test_long_clause_is_long(monkeypatch: pytest.MonkeyPatch, synthetic_brief_md: Path) -> None:
    """philarchive matrix entry → LONG non-engagement clause."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import render_publish_artifact

    result = render_publish_artifact(synthetic_brief_md)

    assert result.attribution.non_engagement_clause is not None
    # LONG form is materially longer than SHORT (>= 400 chars vs ~100).
    assert len(result.attribution.non_engagement_clause) > 300


def test_missing_operator_name_falls_back(tmp_path: Path) -> None:
    """No HAPAX_OPERATOR_NAME → renderer uses placeholder, never crashes."""
    p = tmp_path / "brief.md"
    p.write_text(
        dedent(
            """\
            ---
            authors:
              byline_variant: V2
              unsettled_variant: V3
              surface_deviation_matrix_key: philarchive
            ---
            # Test
            """
        )
    )
    # Explicitly clear the env to validate fallback.
    env_backup = os.environ.pop("HAPAX_OPERATOR_NAME", None)
    try:
        from scripts.render_constitutional_brief import render_publish_artifact

        result = render_publish_artifact(p)
        # Falls back to a non-empty placeholder; never empty/None.
        assert result.attribution.byline_text
    finally:
        if env_backup is not None:
            os.environ["HAPAX_OPERATOR_NAME"] = env_backup


def test_actual_constitutional_brief_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped Constitutional Brief at docs/audience/constitutional-brief.md
    renders end-to-end per its declared frontmatter.

    Regression pin: if the brief's frontmatter loses the byline-variant
    field, this test catches it before publish-event time.
    """
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    brief_path = REPO_ROOT / "docs" / "audience" / "constitutional-brief.md"
    if not brief_path.exists():
        pytest.skip("Constitutional Brief not yet shipped")

    from scripts.render_constitutional_brief import render_publish_artifact

    result = render_publish_artifact(brief_path)

    # The brief declares philarchive surface + V2 byline + V3 unsettled.
    assert result.surface_key == "philarchive"
    assert "Test Operator" in result.attribution.byline_text
    assert "Hapax" in result.attribution.byline_text
    assert "Claude Code" in result.attribution.byline_text
    # V3 phenomenological register includes 'voice' or 'thinking'.
    assert any(
        marker in result.attribution.unsettled_sentence.lower() for marker in ("voice", "thinking")
    )


def test_actual_aesthetic_library_manifesto_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped Aesthetic Library Manifesto renders per its declared
    frontmatter.

    Regression pin: V4 byline (Hapax-canonical with operator-of-record)
    + V5 unsettled (manifesto register) + LONG non-engagement clause
    per ``SURFACE_DEVIATION_MATRIX["omg_lol_weblog"]``.
    """
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    artifact_path = REPO_ROOT / "docs" / "audience" / "aesthetic-library-manifesto.md"
    if not artifact_path.exists():
        pytest.skip("Aesthetic Library Manifesto not yet shipped")

    from scripts.render_constitutional_brief import render_publish_artifact

    result = render_publish_artifact(artifact_path)

    assert result.surface_key == "omg_lol_weblog"
    # V4 byline: ``Hapax · operator-of-record: <name>``
    assert "Hapax" in result.attribution.byline_text
    assert "operator-of-record" in result.attribution.byline_text
    assert "Test Operator" in result.attribution.byline_text
    # V5 unsettled: 'manifesto register' phrasing emphasizes
    # constitutive/indeterminate framing.
    sentence = result.attribution.unsettled_sentence.lower()
    assert any(marker in sentence for marker in ("constitutive", "indeterminacy", "co-publication"))
    # LONG non-engagement clause references the Refusal Brief.
    assert result.attribution.non_engagement_clause is not None
    assert "Refusal Brief" in result.attribution.non_engagement_clause


def test_actual_self_censorship_aesthetic_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped Self-Censorship as Aesthetic essay renders per its
    declared frontmatter.

    Regression pin: V2 byline (full three-way) + V1 unsettled
    (celebrated polysemy) per ``SURFACE_DEVIATION_MATRIX["lesswrong"]``
    fallback (Triple Canopy lacks matrix entry).
    """
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    artifact_path = REPO_ROOT / "docs" / "audience" / "self-censorship-aesthetic.md"
    if not artifact_path.exists():
        pytest.skip("Self-Censorship as Aesthetic not yet shipped")

    from scripts.render_constitutional_brief import render_publish_artifact

    result = render_publish_artifact(artifact_path)

    assert result.surface_key == "lesswrong"
    # V2 byline: three-way comma-separated.
    assert "Test Operator" in result.attribution.byline_text
    assert "Hapax" in result.attribution.byline_text
    assert "Claude Code" in result.attribution.byline_text
    # V1 unsettled: 'celebrated polysemy' includes the polysemic-surface
    # framing.
    assert "polysemic" in result.attribution.unsettled_sentence.lower()
    # LONG non-engagement clause references the Refusal Brief.
    assert result.attribution.non_engagement_clause is not None
    assert "Refusal Brief" in result.attribution.non_engagement_clause
