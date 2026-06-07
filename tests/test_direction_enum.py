"""Tests for the unified canonical Direction + new PhysicalDirection axis."""

from __future__ import annotations

from shared.direction import Direction, PhysicalDirection
from shared.semantic_recruitment import Direction as RecruitDirection
from shared.world_capability_surface import Direction as WCSDirection


class TestCanonicalDirection:
    def test_seven_members_values_and_order_stable(self):
        assert [d.value for d in Direction] == [
            "observe",
            "express",
            "act",
            "route",
            "recall",
            "communicate",
            "regulate",
        ]

    def test_both_modules_reexport_the_same_class(self):
        # Unification: the two formerly-duplicated definitions are now ONE object.
        assert WCSDirection is Direction
        assert RecruitDirection is Direction


class TestPhysicalDirection:
    def test_three_polarity_members(self):
        assert [d.value for d in PhysicalDirection] == [
            "afferent",
            "efferent",
            "stigmergic",
        ]

    def test_orthogonal_to_capability_direction(self):
        assert PhysicalDirection is not Direction
        # no value collision between the two axes
        assert {d.value for d in PhysicalDirection} & {d.value for d in Direction} == set()


class TestPhysicalDirectionOnRecords:
    """Phase 3: capability records carry the orthogonal physical axis, optional."""

    def test_world_capability_record_optional_physical_direction(self):
        from shared.world_capability_surface import WorldCapabilityRecord

        field = WorldCapabilityRecord.model_fields["physical_direction"]
        assert field.default is None  # optional → seed rows omit it, non-breaking

    def test_recruitment_row_optional_physical_direction(self):
        from shared.semantic_recruitment import SemanticRecruitmentRow

        field = SemanticRecruitmentRow.model_fields["physical_direction"]
        assert field.default is None

    def test_record_carries_both_axes_independently(self):
        # direction (capability) and physical_direction (transport) are orthogonal:
        # a record can set the physical axis without it being implied by direction.
        from shared.world_capability_surface import WorldCapabilityRecord

        fields = WorldCapabilityRecord.model_fields
        assert "direction" in fields and "physical_direction" in fields
        assert PhysicalDirection.AFFERENT in set(PhysicalDirection)
