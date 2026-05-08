"""Ward contrast floor tests (ARI L7/L3).

Verifies the tiered contrast floor system:
- Governance/legibility wards get a higher alpha floor for readability
- Standard wards get the base floor
- Skip-list sources get no floor at all
"""

from __future__ import annotations

from agents.studio_compositor.fx_chain import (
    _CONTRAST_FLOOR_SKIP,
    _GOVERNANCE_CONTRAST_SOURCES,
    CONTRAST_FLOOR_ALPHA,
    GOVERNANCE_CONTRAST_FLOOR_ALPHA,
)


def test_governance_floor_higher_than_standard() -> None:
    assert GOVERNANCE_CONTRAST_FLOOR_ALPHA > CONTRAST_FLOOR_ALPHA


def test_governance_floor_at_least_wcag_aa_viable() -> None:
    """0.65+ floor makes white-on-dark text viable for WCAG AA contrast."""
    assert GOVERNANCE_CONTRAST_FLOOR_ALPHA >= 0.65


def test_standard_floor_nonzero() -> None:
    assert CONTRAST_FLOOR_ALPHA > 0.0


def test_governance_sources_not_in_skip_list() -> None:
    overlap = _GOVERNANCE_CONTRAST_SOURCES & _CONTRAST_FLOOR_SKIP
    assert not overlap, f"Governance sources must not be skipped: {overlap}"


def test_skip_list_contains_fullframe_sources() -> None:
    for src in ("reverie", "sierpinski", "durf", "gem"):
        assert src in _CONTRAST_FLOOR_SKIP


def test_governance_sources_include_key_wards() -> None:
    for src in ("egress_footer", "precedent_ticker", "activity_header", "stance_indicator"):
        assert src in _GOVERNANCE_CONTRAST_SOURCES
