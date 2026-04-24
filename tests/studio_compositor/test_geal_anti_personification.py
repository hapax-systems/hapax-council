"""GEAL-scoped anti-personification rules (spec §11 #1).

GEAL files must not reference facial iconography — the 10-invariant
governance gate that carries HARDM's anti-anthropomorphization mandate
forward. Checked only against ``geal*.py`` / ``geal*.yaml`` paths so
the broader codebase can keep using words like "eye" when they mean
"hurricane eye" or "private eye".
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "text",
    [
        "# halo position near the eye",
        "# centred over the mouth",
        "# smile-shaped gradient",
        "# wink / blink envelope",
        "# brow region",
        "# nose",
    ],
)
def test_geal_file_with_face_reference_is_rejected(text: str) -> None:
    from shared.anti_personification_linter import lint_text

    findings = lint_text(text, path="agents/studio_compositor/geal_source.py")
    assert any(f.rule_id.startswith("geal_geometry::") for f in findings), (
        f"expected geal_geometry violation for text={text!r}, got {findings!r}"
    )


def test_non_geal_file_is_unaffected() -> None:
    """The geal_geometry family only fires on geal*.py paths."""
    from shared.anti_personification_linter import lint_text

    # Same text, different path — broader codebase shouldn't flag "eye".
    findings = lint_text(
        "# halo position near the eye",
        path="agents/studio_compositor/sierpinski_renderer.py",
    )
    assert not any(f.rule_id.startswith("geal_geometry::") for f in findings), (
        "geal_geometry must not flag non-GEAL files"
    )


def test_actual_geal_source_passes_linter() -> None:
    """The shipped GEAL source must itself satisfy the linter."""
    from shared.anti_personification_linter import lint_path

    findings = lint_path("agents/studio_compositor/geal_source.py")
    geal_findings = [f for f in findings if f.rule_id.startswith("geal_geometry::")]
    assert geal_findings == [], f"GEAL source has face references: {geal_findings}"


def test_shipped_geal_tests_pass_linter() -> None:
    """Tests for the GEAL source must also satisfy the linter."""
    from shared.anti_personification_linter import lint_path

    findings = lint_path("tests/studio_compositor/test_geal_source.py")
    geal_findings = [f for f in findings if f.rule_id.startswith("geal_geometry::")]
    assert geal_findings == [], f"GEAL tests have face references: {geal_findings}"
