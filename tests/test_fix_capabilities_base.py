"""Tests for shared.fix_capabilities.base — base types for fix capabilities."""

import unittest

from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)


class TestSafetyEnum(unittest.TestCase):
    """Safety enum values and string behavior."""

    def test_safe_value(self):
        assert Safety.SAFE == "safe"

    def test_destructive_value(self):
        assert Safety.DESTRUCTIVE == "destructive"

    def test_is_string(self):
        assert isinstance(Safety.SAFE, str)
        assert isinstance(Safety.DESTRUCTIVE, str)

    def test_from_string(self):
        assert Safety("safe") is Safety.SAFE
        assert Safety("destructive") is Safety.DESTRUCTIVE


class TestAction(unittest.TestCase):
    """Action model creation and defaults."""

    def test_creation_minimal(self):
        action = Action(name="restart", safety=Safety.SAFE)
        assert action.name == "restart"
        assert action.safety == Safety.SAFE
        assert action.params == {}
        assert action.description == ""

    def test_creation_full(self):
        action = Action(
            name="purge",
            safety=Safety.DESTRUCTIVE,
            params={"force": True},
            description="Purge stale data",
        )
        assert action.name == "purge"
        assert action.safety == Safety.DESTRUCTIVE
        assert action.params == {"force": True}
        assert action.description == "Purge stale data"

    def test_params_default_is_independent(self):
        a1 = Action(name="a", safety=Safety.SAFE)
        a2 = Action(name="b", safety=Safety.SAFE)
        a1.params["x"] = 1
        assert "x" not in a2.params


class TestProbeResult(unittest.TestCase):
    """ProbeResult creation and summary."""

    def test_creation_minimal(self):
        result = ProbeResult(capability="docker")
        assert result.capability == "docker"
        assert result.raw == {}

    def test_creation_with_raw(self):
        result = ProbeResult(capability="systemd", raw={"status": "active"})
        assert result.raw == {"status": "active"}

    def test_summary_returns_string(self):
        result = ProbeResult(capability="docker", raw={"containers": 3})
        s = result.summary()
        assert isinstance(s, str)
        assert len(s) > 0

    def test_summary_contains_capability(self):
        result = ProbeResult(capability="qdrant", raw={"collections": 4})
        assert "qdrant" in result.summary()


class TestFixProposal(unittest.TestCase):
    """FixProposal creation, is_safe, safety classification."""

    def test_creation_minimal(self):
        proposal = FixProposal(capability="docker", action_name="restart")
        assert proposal.capability == "docker"
        assert proposal.action_name == "restart"
        assert proposal.params == {}
        assert proposal.rationale == ""
        assert proposal.safety == Safety.SAFE

    def test_creation_full(self):
        proposal = FixProposal(
            capability="systemd",
            action_name="reset-failed",
            params={"unit": "foo.service"},
            rationale="Unit is in failed state",
            safety=Safety.DESTRUCTIVE,
        )
        assert proposal.action_name == "reset-failed"
        assert proposal.params == {"unit": "foo.service"}
        assert proposal.rationale == "Unit is in failed state"

    def test_is_safe_true(self):
        proposal = FixProposal(capability="docker", action_name="restart", safety=Safety.SAFE)
        assert proposal.is_safe() is True

    def test_is_safe_false_for_destructive(self):
        proposal = FixProposal(capability="docker", action_name="prune", safety=Safety.DESTRUCTIVE)
        assert proposal.is_safe() is False


class TestExecutionResult(unittest.TestCase):
    """ExecutionResult success and failure."""

    def test_success(self):
        result = ExecutionResult(success=True, message="Done")
        assert result.success is True
        assert result.message == "Done"
        assert result.output == ""

    def test_failure_with_output(self):
        result = ExecutionResult(success=False, message="Failed", output="Error: timeout")
        assert result.success is False
        assert result.output == "Error: timeout"


class TestCapabilityABC(unittest.TestCase):
    """Capability ABC enforcement and concrete subclass."""

    def test_cannot_instantiate_abc(self):
        with self.assertRaises(TypeError):
            Capability()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        class DummyCapability(Capability):
            name = "dummy"
            check_groups = {"test_group"}

            async def gather_context(self, check):
                return ProbeResult(capability=self.name, raw={"check": str(check)})

            def available_actions(self):
                return [Action(name="fix", safety=Safety.SAFE)]

            def validate(self, proposal):
                return proposal.action_name in ("fix",)

            async def execute(self, proposal):
                return ExecutionResult(success=True, message="Fixed")

        cap = DummyCapability()
        assert cap.name == "dummy"
        assert "test_group" in cap.check_groups

    def test_concrete_subclass_available_actions(self):
        class SimpleCapability(Capability):
            name = "simple"
            check_groups = set()

            async def gather_context(self, check):
                return ProbeResult(capability=self.name)

            def available_actions(self):
                return [
                    Action(name="a", safety=Safety.SAFE),
                    Action(name="b", safety=Safety.DESTRUCTIVE),
                ]

            def validate(self, proposal):
                return True

            async def execute(self, proposal):
                return ExecutionResult(success=True, message="ok")

        cap = SimpleCapability()
        actions = cap.available_actions()
        assert len(actions) == 2
        assert actions[0].name == "a"

    def test_concrete_subclass_validate(self):
        class ValidatingCapability(Capability):
            name = "val"
            check_groups = set()

            async def gather_context(self, check):
                return ProbeResult(capability=self.name)

            def available_actions(self):
                return [Action(name="restart", safety=Safety.SAFE)]

            def validate(self, proposal):
                return proposal.action_name == "restart"

            async def execute(self, proposal):
                return ExecutionResult(success=True, message="ok")

        cap = ValidatingCapability()
        good = FixProposal(capability="val", action_name="restart")
        bad = FixProposal(capability="val", action_name="delete")
        assert cap.validate(good) is True
        assert cap.validate(bad) is False

    def test_concrete_subclass_execute(self):
        import asyncio

        class ExecCapability(Capability):
            name = "exec"
            check_groups = set()

            async def gather_context(self, check):
                return ProbeResult(capability=self.name)

            def available_actions(self):
                return []

            def validate(self, proposal):
                return True

            async def execute(self, proposal):
                return ExecutionResult(success=True, message="executed", output="details")

        cap = ExecCapability()
        proposal = FixProposal(capability="exec", action_name="run")
        result = asyncio.run(cap.execute(proposal))
        assert result.success is True
        assert result.output == "details"

    def test_concrete_subclass_gather_context(self):
        import asyncio

        class ProbeCapability(Capability):
            name = "probe"
            check_groups = {"grp"}

            async def gather_context(self, check):
                return ProbeResult(capability=self.name, raw={"check_id": check})

            def available_actions(self):
                return []

            def validate(self, proposal):
                return True

            async def execute(self, proposal):
                return ExecutionResult(success=True, message="ok")

        cap = ProbeCapability()
        result = asyncio.run(cap.gather_context("chk_001"))
        assert result.capability == "probe"
        assert result.raw["check_id"] == "chk_001"


if __name__ == "__main__":
    unittest.main()
