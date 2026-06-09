"""Pin the canonical ``is_compositional_capability`` predicate.

The segment materializer post-filters recruited candidates to *director*
capabilities using this predicate, so it must agree with what
``compositional_consumer.dispatch`` will actually route, and with the
canonical prefix set the live consumer (``run_loops_aux``) already uses.
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.compositional_consumer import is_compositional_capability


@pytest.mark.parametrize(
    "name",
    [
        "ward.highlight.tier-panel.glow",
        "overlay.foreground.coding-activity",
        "gem.spawn.fresh-mural",
        "cam.hero.overhead.vinyl-spinning",
        "youtube.cut-away",
        "composition.reframe.tighten",
        "pace.tempo_shift.slow",
        "mood.tone_pivot.warmer",
        "node.add.kaleidoscope",
        "transition.crossfade.soft",
    ],
)
def test_known_director_capabilities_are_compositional(name: str) -> None:
    assert is_compositional_capability(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "perception.gaze.read",
        "recall.episodic.surface",
        "regulation.duck.tts",
        "",
        "definitely-not-a-capability",
    ],
)
def test_non_director_names_are_not_compositional(name: str) -> None:
    assert is_compositional_capability(name) is False


def test_predicate_agrees_with_canonical_live_consumer_set() -> None:
    """Guard against drift from the live consumer's prefix set."""

    from agents.hapax_daimonion.run_loops_aux import _COMPOSITIONAL_PREFIXES
    from agents.studio_compositor.compositional_consumer import (
        COMPOSITIONAL_CAPABILITY_PREFIXES,
    )

    assert set(COMPOSITIONAL_CAPABILITY_PREFIXES) == set(_COMPOSITIONAL_PREFIXES)
