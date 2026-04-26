"""Surface-taxonomy tests — pin the calibrated floor values."""

from __future__ import annotations

from itertools import pairwise

import pytest

from hapax_refusals.surface import SURFACE_FLOORS, floor_for


class TestSurfaceFloors:
    def test_director_is_060(self) -> None:
        assert SURFACE_FLOORS["director"] == 0.60

    def test_spontaneous_speech_is_070(self) -> None:
        assert SURFACE_FLOORS["spontaneous_speech"] == 0.70

    def test_autonomous_narrative_is_075(self) -> None:
        assert SURFACE_FLOORS["autonomous_narrative"] == 0.75

    def test_voice_persona_is_080(self) -> None:
        assert SURFACE_FLOORS["voice_persona"] == 0.80

    def test_grounding_act_is_090(self) -> None:
        assert SURFACE_FLOORS["grounding_act"] == 0.90

    def test_floors_strictly_increasing(self) -> None:
        ordered = [
            "director",
            "spontaneous_speech",
            "autonomous_narrative",
            "voice_persona",
            "grounding_act",
        ]
        for a, b in pairwise(ordered):
            assert SURFACE_FLOORS[a] < SURFACE_FLOORS[b]

    def test_all_floors_in_range(self) -> None:
        for surface, floor in SURFACE_FLOORS.items():
            assert 0.0 <= floor <= 1.0, f"{surface} out of range: {floor}"


class TestFloorFor:
    def test_returns_calibrated_value(self) -> None:
        assert floor_for("director") == 0.60
        assert floor_for("grounding_act") == 0.90

    def test_unknown_surface_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="unknown surface"):
            floor_for("not_a_real_surface")  # type: ignore[arg-type]
