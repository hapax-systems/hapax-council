"""HOMAGE Phase 11c batch 3 — overlay-zone + research-marker ward migration.

Per the Phase 4 / 11a / 11b pattern, verifies that the final batch of
overlay-zone sources inherit :class:`HomageTransitionalSource` so their
text content is gated by the HOMAGE FSM under ``HAPAX_HOMAGE_ACTIVE=1``.

Each migrated source:

* exposes a ``transition_state`` FSM field (inherited from the base).
* starts in either ``ABSENT`` or ``HOLD`` — never in an intermediate
  ``ENTERING`` / ``EXITING`` state (that would mean the subclass is
  driving its own transitions, breaking the choreographer contract).
* has a ``source_id`` matching the ward registry expectation.
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.homage.transitional_source import (
    HomageTransitionalSource,
    TransitionState,
)


def _migrated_sources() -> list[tuple[str, type]]:
    """Return the (source_id, class) pairs this batch migrates.

    Kept small and explicit; adding a new migration is one line and
    forces the test matrix to cover it.
    """
    from agents.studio_compositor.overlay_zones import OverlayZonesCairoSource
    from agents.studio_compositor.research_marker_frame_source import (
        ResearchMarkerFrameSource,
    )

    return [
        ("overlay_zones", OverlayZonesCairoSource),
        ("research_marker_frame", ResearchMarkerFrameSource),
    ]


@pytest.mark.parametrize("expected_id,cls", _migrated_sources())
def test_migrated_source_inherits_homage_transitional(expected_id: str, cls: type) -> None:
    """Each migrated class is a HomageTransitionalSource subclass."""
    assert issubclass(cls, HomageTransitionalSource), (
        f"{cls.__name__} must inherit HomageTransitionalSource after Phase 11c"
    )


@pytest.mark.parametrize("expected_id,cls", _migrated_sources())
def test_migrated_source_reports_source_id(expected_id: str, cls: type) -> None:
    """Each migrated class reports the canonical source_id via the FSM base."""
    instance = cls()
    assert instance.source_id == expected_id


@pytest.mark.parametrize("expected_id,cls", _migrated_sources())
def test_migrated_source_initial_state_is_absent_or_hold(expected_id: str, cls: type) -> None:
    """Initial FSM state must be ABSENT (choreographer-driven) or HOLD
    (self-gating / always-on). An ``ENTERING`` / ``EXITING`` initial
    state would indicate a subclass is driving its own transitions
    and breaking the choreographer's single-arbiter invariant."""
    instance = cls()
    assert instance.transition_state in {
        TransitionState.ABSENT,
        TransitionState.HOLD,
    }


@pytest.mark.parametrize("expected_id,cls", _migrated_sources())
def test_migrated_source_exposes_render_content(expected_id: str, cls: type) -> None:
    """Each migrated class overrides ``render_content`` (not ``render``).

    ``HomageTransitionalSource.render()`` dispatches to
    ``render_content`` under the active FSM state. Subclasses that
    override ``render`` directly would bypass the FSM, which is what
    the phase 11c migration is explicitly eliminating.
    """
    # ``render_content`` is defined on the subclass (not inherited as the
    # NotImplementedError placeholder from the base).
    assert cls.render_content is not HomageTransitionalSource.render_content
    # ``render`` should NOT be overridden — the base FSM-dispatching
    # implementation is what we want.
    assert cls.render is HomageTransitionalSource.render
