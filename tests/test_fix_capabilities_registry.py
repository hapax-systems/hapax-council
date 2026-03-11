"""Tests for fix capabilities registry."""

from typing import Any

from shared.fix_capabilities import (
    _REGISTRY,
    get_all_capabilities,
    get_capability_for_group,
    register_capability,
)
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
)


class _StubCapability(Capability):
    """Minimal concrete capability for testing."""

    def __init__(self, name: str, groups: set[str]) -> None:
        self.name = name
        self.check_groups = groups

    async def gather_context(self, check: Any) -> ProbeResult:
        return ProbeResult(capability=self.name)

    def available_actions(self) -> list[Action]:
        return []

    def validate(self, proposal: FixProposal) -> bool:
        return True

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        return ExecutionResult(success=True, message="ok")


class TestCapabilityRegistry:
    def setup_method(self) -> None:
        _REGISTRY.clear()

    def test_register_capability_adds_to_registry(self) -> None:
        cap = _StubCapability("gpu", {"gpu"})
        register_capability(cap)
        assert "gpu" in _REGISTRY
        assert _REGISTRY["gpu"] is cap

    def test_get_capability_for_group_returns_correct_cap(self) -> None:
        cap = _StubCapability("docker", {"docker", "containers"})
        register_capability(cap)
        assert get_capability_for_group("docker") is cap
        assert get_capability_for_group("containers") is cap

    def test_get_capability_for_group_returns_none_for_unknown(self) -> None:
        assert get_capability_for_group("nonexistent") is None

    def test_get_all_capabilities_returns_unique_list(self) -> None:
        cap1 = _StubCapability("gpu", {"gpu", "vram"})
        cap2 = _StubCapability("docker", {"docker"})
        register_capability(cap1)
        register_capability(cap2)
        result = get_all_capabilities()
        assert len(result) == 2
        names = {c.name for c in result}
        assert names == {"gpu", "docker"}

    def test_duplicate_registration_overwrites(self) -> None:
        cap1 = _StubCapability("gpu", {"gpu"})
        cap2 = _StubCapability("gpu_v2", {"gpu"})
        register_capability(cap1)
        register_capability(cap2)
        assert get_capability_for_group("gpu") is cap2
