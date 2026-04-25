"""Tests for ``compose_publish_markdown`` (V5 wk1 follow-on).

Composes the publish-ready markdown form by interpolating the rendered
:class:`AttributionBlock` into the source body. The publish-ready form
is what publishers consume — it carries the operator-of-record byline,
the unsettled-contribution sentence, and the non-engagement clause as
canonical prose attached to the artifact body.

Per V5 weave Constitutional Brief outline §Approval queue: this closes
the source-to-publish substrate end-to-end. Source declares variant
references in frontmatter; render_publish_artifact assembles the
attribution; compose_publish_markdown produces the publish-shaped
artifact downstream renderers (Pandoc HTML / Pandoc PDF / mkdocs)
consume.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def synthetic_brief(tmp_path: Path) -> Path:
    p = tmp_path / "synthetic-brief.md"
    p.write_text(
        dedent(
            """\
            ---
            title: "Synthetic test brief"
            authors:
              byline_variant: V2
              unsettled_variant: V3
              surface_deviation_matrix_key: philarchive
            non_engagement_clause_form: LONG
            ---

            # Synthetic test brief

            Body content here.

            More body content.
            """
        )
    )
    return p


def test_compose_includes_byline_at_top(
    monkeypatch: pytest.MonkeyPatch, synthetic_brief: Path
) -> None:
    """Publish-ready markdown carries the rendered byline at the top."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import (
        compose_publish_markdown,
        render_publish_artifact,
    )

    artifact = render_publish_artifact(synthetic_brief)
    output = compose_publish_markdown(artifact, title="Synthetic test brief")

    # Byline appears in the header block, BEFORE the body prose.
    byline_pos = output.find("Test Operator, Hapax, Claude Code")
    body_prose_pos = output.find("Body content here")
    assert byline_pos >= 0
    assert body_prose_pos >= 0
    assert byline_pos < body_prose_pos
    # The output's title heading appears once (publish-output H1) — not twice
    # (composer should strip the duplicate H1 from the body to avoid two H1s).
    assert output.count("# Synthetic test brief") == 1


def test_compose_includes_unsettled_sentence(
    monkeypatch: pytest.MonkeyPatch, synthetic_brief: Path
) -> None:
    """Publish-ready markdown carries the unsettled-contribution sentence."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import (
        compose_publish_markdown,
        render_publish_artifact,
    )

    artifact = render_publish_artifact(synthetic_brief)
    output = compose_publish_markdown(artifact, title="Synthetic test brief")

    # V3 phenomenological register includes "voice" or "thinking".
    assert "voice" in output.lower() or "thinking" in output.lower()


def test_compose_includes_non_engagement_clause(
    monkeypatch: pytest.MonkeyPatch, synthetic_brief: Path
) -> None:
    """Publish-ready markdown carries the LONG non-engagement clause."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import (
        compose_publish_markdown,
        render_publish_artifact,
    )

    artifact = render_publish_artifact(synthetic_brief)
    output = compose_publish_markdown(artifact, title="Synthetic test brief")

    assert "Refusal Brief" in output
    assert "hapax.omg.lol/refusal" in output


def test_compose_preserves_body(monkeypatch: pytest.MonkeyPatch, synthetic_brief: Path) -> None:
    """Publish-ready markdown contains the artifact's full body."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import (
        compose_publish_markdown,
        render_publish_artifact,
    )

    artifact = render_publish_artifact(synthetic_brief)
    output = compose_publish_markdown(artifact, title="Synthetic test brief")

    assert "Body content here" in output
    assert "More body content" in output


def test_compose_strips_yaml_frontmatter(
    monkeypatch: pytest.MonkeyPatch, synthetic_brief: Path
) -> None:
    """Publish-ready markdown does NOT contain the source YAML frontmatter.

    Frontmatter declares variant references; the publish-ready form
    carries the rendered prose. Re-emitting frontmatter would expose
    the SURFACE_DEVIATION_MATRIX-key on a public surface, which is an
    operator-internal artifact, not publish-time content.
    """
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    from scripts.render_constitutional_brief import (
        compose_publish_markdown,
        render_publish_artifact,
    )

    artifact = render_publish_artifact(synthetic_brief)
    output = compose_publish_markdown(artifact, title="Synthetic test brief")

    # No YAML frontmatter delimiters
    assert not output.startswith("---")
    # No matrix-key leaks
    assert "surface_deviation_matrix_key" not in output
    assert "byline_variant" not in output


def test_compose_idempotent_on_no_clause(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When the matrix entry has no clause, output simply omits it (no None leak)."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
    p = tmp_path / "brief.md"
    p.write_text(
        dedent(
            """\
            ---
            authors:
              byline_variant: V0
              unsettled_variant: V3
              surface_deviation_matrix_key: nonexistent_surface
            ---
            # Untitled
            """
        )
    )
    from scripts.render_constitutional_brief import (
        compose_publish_markdown,
        render_publish_artifact,
    )

    artifact = render_publish_artifact(p)
    output = compose_publish_markdown(artifact, title="Untitled")

    # No None / null leaks even though no clause is bound.
    assert "None" not in output.split("\n")  # bare "None" line
    # V0 byline is solo-operator
    assert "Test Operator" in output
