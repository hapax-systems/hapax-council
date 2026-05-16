from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.resource_model import (
    DEFAULT_CONTENTION_GROUPS,
    DEFAULT_SERVICE_PROFILES,
    DEFAULT_THRESHOLDS,
    ContentionGroup,
    Enforcement,
    ResourceAllocation,
    ResourceConstraint,
    ResourcePressure,
    ResourceState,
    ResourceThreshold,
    ResourceType,
    ServiceResourceProfile,
    YieldTier,
    classify_state,
)


class TestResourceTypeCompleteness:
    def test_all_five_types_are_distinct(self):
        values = [rt.value for rt in ResourceType]
        assert len(values) == 5
        assert len(set(values)) == 5

    def test_serializable(self):
        for rt in ResourceType:
            assert json.loads(json.dumps(rt.value)) == rt.value


class TestYieldTierOrdering:
    def test_yield_order(self):
        assert YieldTier.AGENT_SESSION < YieldTier.BACKGROUND_BATCH
        assert YieldTier.BACKGROUND_BATCH < YieldTier.DISCRETIONARY_GPU
        assert YieldTier.DISCRETIONARY_GPU < YieldTier.ANALYTICS
        assert YieldTier.ANALYTICS < YieldTier.INFRASTRUCTURE
        assert YieldTier.INFRASTRUCTURE < YieldTier.CRITICAL_PATH

    def test_values_contiguous(self):
        values = sorted(t.value for t in YieldTier)
        assert values == [1, 2, 3, 4, 5, 6]


class TestServiceTierVsYieldTierIndependence:
    def test_distinct_types_in_distinct_modules(self):
        from shared.service_tiers import ServiceTier

        assert ServiceTier is not YieldTier
        assert ServiceTier.__module__ != YieldTier.__module__

    def test_service_tier_zero_not_valid_yield_tier(self):
        with pytest.raises(ValueError):
            YieldTier(0)

    def test_pydantic_rejects_invalid_yield_tier_value(self):
        with pytest.raises(ValidationError):
            ServiceResourceProfile(
                service_name="test",
                yield_tier=0,
                allocations={
                    ResourceType.RAM: ResourceAllocation(
                        resource_type=ResourceType.RAM,
                        steady_state=1.0,
                        unit="GB",
                    )
                },
                contention_groups=["test"],
            )


class TestContentionGroupValidation:
    def test_zero_capacity_rejected(self):
        with pytest.raises(ValidationError):
            ContentionGroup(
                name="bad",
                resource_type=ResourceType.CPU,
                total_capacity=0,
                unit="cores",
                members=["a"],
                headroom_min=0,
            )

    def test_negative_capacity_rejected(self):
        with pytest.raises(ValidationError):
            ContentionGroup(
                name="bad",
                resource_type=ResourceType.CPU,
                total_capacity=-1,
                unit="cores",
                members=["a"],
                headroom_min=0,
            )

    def test_empty_members_rejected(self):
        with pytest.raises(ValidationError):
            ContentionGroup(
                name="bad",
                resource_type=ResourceType.CPU,
                total_capacity=4.0,
                unit="cores",
                members=[],
                headroom_min=0,
            )

    def test_valid_group_passes(self):
        cg = ContentionGroup(
            name="test",
            resource_type=ResourceType.CPU,
            total_capacity=4.0,
            unit="cores",
            members=["a", "b"],
            headroom_min=1.0,
        )
        assert cg.name == "test"
        assert len(cg.members) == 2


class TestClassifyStateDirection:
    @pytest.fixture()
    def higher_threshold(self):
        return ResourceThreshold(
            resource_type=ResourceType.RAM,
            signal="mem_available_gb",
            unit="GB",
            green_above=30.0,
            yellow_above=15.0,
            direction="higher_is_better",
        )

    @pytest.fixture()
    def lower_threshold(self):
        return ResourceThreshold(
            resource_type=ResourceType.RAM,
            signal="swap_used_gb",
            unit="GB",
            green_above=4.0,
            yellow_above=16.0,
            direction="lower_is_better",
        )

    def test_higher_is_better_green(self, higher_threshold):
        assert classify_state(50.0, higher_threshold) == ResourceState.GREEN
        assert classify_state(30.1, higher_threshold) == ResourceState.GREEN

    def test_higher_is_better_yellow(self, higher_threshold):
        assert classify_state(30.0, higher_threshold) == ResourceState.YELLOW
        assert classify_state(20.0, higher_threshold) == ResourceState.YELLOW
        assert classify_state(15.1, higher_threshold) == ResourceState.YELLOW

    def test_higher_is_better_red(self, higher_threshold):
        assert classify_state(15.0, higher_threshold) == ResourceState.RED
        assert classify_state(10.0, higher_threshold) == ResourceState.RED
        assert classify_state(0.0, higher_threshold) == ResourceState.RED

    def test_lower_is_better_green(self, lower_threshold):
        assert classify_state(0.0, lower_threshold) == ResourceState.GREEN
        assert classify_state(3.9, lower_threshold) == ResourceState.GREEN

    def test_lower_is_better_yellow(self, lower_threshold):
        assert classify_state(4.0, lower_threshold) == ResourceState.YELLOW
        assert classify_state(10.0, lower_threshold) == ResourceState.YELLOW
        assert classify_state(15.9, lower_threshold) == ResourceState.YELLOW

    def test_lower_is_better_red(self, lower_threshold):
        assert classify_state(16.0, lower_threshold) == ResourceState.RED
        assert classify_state(20.0, lower_threshold) == ResourceState.RED


class TestResourceThresholdBoundaryValues:
    def test_value_exactly_at_green_boundary_is_yellow(self):
        t = ResourceThreshold(
            resource_type=ResourceType.RAM,
            signal="test",
            unit="GB",
            green_above=30.0,
            yellow_above=15.0,
            direction="higher_is_better",
        )
        assert classify_state(30.0, t) == ResourceState.YELLOW

    def test_value_exactly_at_yellow_boundary_is_red(self):
        t = ResourceThreshold(
            resource_type=ResourceType.RAM,
            signal="test",
            unit="GB",
            green_above=30.0,
            yellow_above=15.0,
            direction="higher_is_better",
        )
        assert classify_state(15.0, t) == ResourceState.RED

    def test_zero_value_lower_is_better(self):
        t = ResourceThreshold(
            resource_type=ResourceType.CPU,
            signal="load",
            unit="load",
            green_above=10.0,
            yellow_above=14.0,
            direction="lower_is_better",
        )
        assert classify_state(0.0, t) == ResourceState.GREEN

    def test_negative_value_does_not_crash(self):
        t = ResourceThreshold(
            resource_type=ResourceType.RAM,
            signal="test",
            unit="GB",
            green_above=30.0,
            yellow_above=15.0,
            direction="higher_is_better",
        )
        assert classify_state(-5.0, t) == ResourceState.RED

    def test_lower_is_better_exact_boundaries(self):
        t = ResourceThreshold(
            resource_type=ResourceType.CPU,
            signal="test",
            unit="load",
            green_above=10.0,
            yellow_above=14.0,
            direction="lower_is_better",
        )
        assert classify_state(10.0, t) == ResourceState.YELLOW
        assert classify_state(14.0, t) == ResourceState.RED


class TestServiceProfileCompleteness:
    def test_every_profile_has_at_least_one_allocation(self):
        for name, profile in DEFAULT_SERVICE_PROFILES.items():
            assert len(profile.allocations) >= 1, f"{name} has no allocations"

    def test_every_profile_has_at_least_one_contention_group(self):
        for name, profile in DEFAULT_SERVICE_PROFILES.items():
            assert len(profile.contention_groups) >= 1, f"{name} has no contention groups"

    def test_logos_api_profile_reflects_128gb_host_headroom(self):
        profile = DEFAULT_SERVICE_PROFILES["logos-api"]
        allocation = profile.allocations[ResourceType.RAM]

        assert profile.yield_tier == YieldTier.CRITICAL_PATH
        assert allocation.limit == 8.0
        assert allocation.enforcement == Enforcement.HARD
        assert "MemoryMax=8G" in allocation.notes


class TestContentionGroupConsistency:
    def test_all_contention_group_members_exist_in_profiles(self):
        profile_names = set(DEFAULT_SERVICE_PROFILES.keys())
        for cg_name, cg in DEFAULT_CONTENTION_GROUPS.items():
            for member in cg.members:
                assert member in profile_names, (
                    f"CG '{cg_name}' member '{member}' not in DEFAULT_SERVICE_PROFILES"
                )

    def test_all_profile_contention_groups_exist(self):
        cg_names = set(DEFAULT_CONTENTION_GROUPS.keys())
        for name, profile in DEFAULT_SERVICE_PROFILES.items():
            for cg_ref in profile.contention_groups:
                assert cg_ref in cg_names, f"Profile '{name}' references unknown CG '{cg_ref}'"


class TestResourcePressureConstruction:
    def test_construction_and_json_serialization(self):
        t = DEFAULT_THRESHOLDS[0]
        p = ResourcePressure(
            resource_type=ResourceType.RAM,
            state=ResourceState.GREEN,
            current_value=50.0,
            threshold=t,
            measured_at=datetime(2026, 5, 9, tzinfo=UTC),
        )
        data = json.loads(p.model_dump_json())
        assert data["resource_type"] == "ram"
        assert data["state"] == "green"
        assert data["current_value"] == 50.0
        assert "threshold" in data

    def test_with_contention_group(self):
        t = DEFAULT_THRESHOLDS[0]
        p = ResourcePressure(
            resource_type=ResourceType.RAM,
            state=ResourceState.YELLOW,
            current_value=20.0,
            threshold=t,
            measured_at=datetime(2026, 5, 9, tzinfo=UTC),
            contention_group="CG-RAM",
        )
        assert p.contention_group == "CG-RAM"

    def test_without_contention_group(self):
        t = DEFAULT_THRESHOLDS[0]
        p = ResourcePressure(
            resource_type=ResourceType.RAM,
            state=ResourceState.GREEN,
            current_value=50.0,
            threshold=t,
            measured_at=datetime(2026, 5, 9, tzinfo=UTC),
        )
        assert p.contention_group is None


class TestResourceConstraintSerialization:
    def test_json_roundtrip(self):
        rc = ResourceConstraint(
            constraint_id="rc-ram-available-min",
            resource_type=ResourceType.RAM,
            signal="mem_available_gb",
            green_threshold=30.0,
            yellow_threshold=15.0,
            red_threshold=15.0,
            enforcement=Enforcement.SOFT,
            source="CASE-INFRA-GOV-001",
            created_at=datetime(2026, 5, 9, tzinfo=UTC),
        )
        json_str = rc.model_dump_json()
        rc2 = ResourceConstraint.model_validate_json(json_str)
        assert rc2.constraint_id == rc.constraint_id
        assert rc2.resource_type == rc.resource_type
        assert rc2.active is True
        assert rc2.reason == ""

    def test_expires_at_none_is_valid(self):
        rc = ResourceConstraint(
            constraint_id="test",
            resource_type=ResourceType.CPU,
            signal="load_avg_5m",
            green_threshold=10.0,
            yellow_threshold=14.0,
            red_threshold=14.0,
            enforcement=Enforcement.HARD,
            source="test",
            created_at=datetime(2026, 5, 9, tzinfo=UTC),
            expires_at=None,
        )
        assert rc.expires_at is None
        data = json.loads(rc.model_dump_json())
        assert data["expires_at"] is None

    def test_inactive_constraint_representable(self):
        rc = ResourceConstraint(
            constraint_id="test-inactive",
            resource_type=ResourceType.GPU_VRAM,
            signal="vram_free_gb",
            green_threshold=2.0,
            yellow_threshold=1.0,
            red_threshold=1.0,
            enforcement=Enforcement.HYBRID,
            source="test",
            created_at=datetime(2026, 5, 9, tzinfo=UTC),
            active=False,
        )
        assert rc.active is False
        rc2 = ResourceConstraint.model_validate_json(rc.model_dump_json())
        assert rc2.active is False


class TestDefaultThresholdsCoverage:
    def test_at_least_one_threshold_per_resource_type(self):
        covered = {t.resource_type for t in DEFAULT_THRESHOLDS}
        for rt in ResourceType:
            assert rt in covered, f"No threshold for {rt}"


class TestClassifyStateDeterminism:
    def test_same_inputs_same_output(self):
        t = ResourceThreshold(
            resource_type=ResourceType.RAM,
            signal="test",
            unit="GB",
            green_above=30.0,
            yellow_above=15.0,
            direction="higher_is_better",
        )
        results = [classify_state(25.0, t) for _ in range(100)]
        assert all(r == ResourceState.YELLOW for r in results)

    def test_no_external_state_dependency(self):
        t = ResourceThreshold(
            resource_type=ResourceType.CPU,
            signal="test",
            unit="load",
            green_above=10.0,
            yellow_above=14.0,
            direction="lower_is_better",
        )
        r1 = classify_state(5.0, t)
        r2 = classify_state(12.0, t)
        r3 = classify_state(5.0, t)
        assert r1 == ResourceState.GREEN
        assert r2 == ResourceState.YELLOW
        assert r3 == ResourceState.GREEN
