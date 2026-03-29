"""Tests for Executor Protocol, ScheduleQueue, and ExecutorRegistry."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.hapax_daimonion.commands import Command, Schedule
from agents.hapax_daimonion.executor import Executor, ExecutorRegistry, ScheduleQueue
from agents.hapax_daimonion.governance import VetoResult


class FakeExecutor:
    """Minimal Executor for testing."""

    def __init__(self, name: str, handles: frozenset[str], avail: bool = True) -> None:
        self._name = name
        self._handles = handles
        self._available = avail
        self.executed: list[Command] = []
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def handles(self) -> frozenset[str]:
        return self._handles

    def execute(self, command: Command) -> None:
        self.executed.append(command)

    def available(self) -> bool:
        return self._available

    def close(self) -> None:
        self.closed = True


def _cmd(action: str = "test", **kwargs) -> Command:
    return Command(action=action, **kwargs)


def _schedule(
    action: str = "test", wall_time: float = 100.0, tolerance_ms: float = 10000.0
) -> Schedule:
    return Schedule(command=_cmd(action), wall_time=wall_time, tolerance_ms=tolerance_ms)


class TestExecutorProtocol(unittest.TestCase):
    def test_fake_executor_satisfies_protocol(self):
        ex = FakeExecutor("test", frozenset({"a"}))
        self.assertIsInstance(ex, Executor)

    def test_non_executor_fails_protocol(self):
        self.assertNotIsInstance("not an executor", Executor)


class TestScheduleQueue(unittest.TestCase):
    def test_drain_returns_ready_items_sorted(self):
        q = ScheduleQueue()
        q.enqueue(_schedule("c", wall_time=103.0))
        q.enqueue(_schedule("a", wall_time=101.0))
        q.enqueue(_schedule("b", wall_time=102.0))
        result = q.drain(105.0)
        self.assertEqual([s.command.action for s in result], ["a", "b", "c"])

    def test_drain_leaves_future_items(self):
        q = ScheduleQueue()
        q.enqueue(_schedule("now", wall_time=100.0))
        q.enqueue(_schedule("later", wall_time=200.0))
        result = q.drain(105.0)  # within tolerance of "now" but before "later"
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].command.action, "now")
        self.assertEqual(q.pending_count, 1)

    def test_expired_items_discarded(self):
        q = ScheduleQueue()
        # tolerance_ms=50 → deadline at 100.05
        q.enqueue(_schedule("old", wall_time=100.0, tolerance_ms=50.0))
        result = q.drain(100.1)  # past deadline
        self.assertEqual(len(result), 0)
        self.assertEqual(q.pending_count, 0)  # removed, not kept

    def test_within_tolerance_returned(self):
        q = ScheduleQueue()
        q.enqueue(_schedule("ok", wall_time=100.0, tolerance_ms=100.0))
        result = q.drain(100.05)  # within tolerance window
        self.assertEqual(len(result), 1)

    def test_drain_idempotent(self):
        q = ScheduleQueue()
        q.enqueue(_schedule("a", wall_time=100.0))
        first = q.drain(105.0)
        second = q.drain(105.0)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)

    def test_drain_never_returns_future(self):
        """drain(now) never returns items with wall_time > now."""
        q = ScheduleQueue()
        for i in range(20):
            q.enqueue(_schedule(f"s{i}", wall_time=100.0 + i * 0.5))
        now = 105.0
        result = q.drain(now)
        for s in result:
            self.assertLessEqual(s.wall_time, now)

    def test_drain_monotonic_order(self):
        """Returned items are in monotonic wall_time order."""
        q = ScheduleQueue()
        q.enqueue(_schedule("c", wall_time=103.0, tolerance_ms=5000.0))
        q.enqueue(_schedule("a", wall_time=101.0, tolerance_ms=5000.0))
        q.enqueue(_schedule("b", wall_time=102.0, tolerance_ms=5000.0))
        result = q.drain(110.0)
        times = [s.wall_time for s in result]
        self.assertEqual(times, sorted(times))

    def test_empty_drain(self):
        q = ScheduleQueue()
        self.assertEqual(q.drain(100.0), [])


class TestExecutorRegistry(unittest.TestCase):
    def test_dispatch_routes_correctly(self):
        reg = ExecutorRegistry()
        ex = FakeExecutor("audio", frozenset({"vocal_throw", "ad_lib"}))
        reg.register(ex)
        cmd = _cmd("vocal_throw")
        self.assertTrue(reg.dispatch(cmd))
        self.assertEqual(len(ex.executed), 1)
        self.assertEqual(ex.executed[0].action, "vocal_throw")

    def test_unknown_action_returns_false(self):
        reg = ExecutorRegistry()
        self.assertFalse(reg.dispatch(_cmd("unknown")))

    def test_duplicate_name_rejected(self):
        reg = ExecutorRegistry()
        reg.register(FakeExecutor("audio", frozenset({"a"})))
        with self.assertRaises(ValueError, msg="already registered"):
            reg.register(FakeExecutor("audio", frozenset({"b"})))

    def test_handle_conflict_rejected(self):
        reg = ExecutorRegistry()
        reg.register(FakeExecutor("ex1", frozenset({"shared_action"})))
        with self.assertRaises(ValueError, msg="conflicts"):
            reg.register(FakeExecutor("ex2", frozenset({"shared_action"})))

    def test_unavailable_executor_skipped(self):
        reg = ExecutorRegistry()
        ex = FakeExecutor("unavail", frozenset({"a"}), avail=False)
        reg.register(ex)
        self.assertFalse(reg.dispatch(_cmd("a")))

    def test_close_all(self):
        reg = ExecutorRegistry()
        ex1 = FakeExecutor("a", frozenset({"x"}))
        ex2 = FakeExecutor("b", frozenset({"y"}))
        reg.register(ex1)
        reg.register(ex2)
        reg.close_all()
        self.assertTrue(ex1.closed)
        self.assertTrue(ex2.closed)
        self.assertEqual(reg.registered_actions, frozenset())

    def test_executor_exception_handled(self):
        reg = ExecutorRegistry()
        ex = FakeExecutor("bad", frozenset({"boom"}))
        ex.execute = MagicMock(side_effect=RuntimeError("kaboom"))
        reg.register(ex)
        self.assertFalse(reg.dispatch(_cmd("boom")))

    def test_governance_blocked_command_not_dispatched(self):
        """dispatch returns False and executor.execute() never called when governance blocks."""
        reg = ExecutorRegistry()
        ex = FakeExecutor("audio", frozenset({"vocal_throw"}))
        reg.register(ex)
        blocked_cmd = Command(
            action="vocal_throw",
            governance_result=VetoResult(
                allowed=False,
                denied_by=("axiom_compliance",),
                axiom_ids=("mg-boundary-001",),
            ),
        )
        self.assertFalse(reg.dispatch(blocked_cmd))
        self.assertEqual(len(ex.executed), 0)

    def test_governance_allowed_command_dispatched(self):
        """dispatch succeeds when governance_result.allowed=True."""
        reg = ExecutorRegistry()
        ex = FakeExecutor("audio", frozenset({"vocal_throw"}))
        reg.register(ex)
        allowed_cmd = Command(
            action="vocal_throw",
            governance_result=VetoResult(allowed=True),
        )
        self.assertTrue(reg.dispatch(allowed_cmd))
        self.assertEqual(len(ex.executed), 1)

    def test_registered_actions(self):
        reg = ExecutorRegistry()
        reg.register(FakeExecutor("a", frozenset({"x", "y"})))
        reg.register(FakeExecutor("b", frozenset({"z"})))
        self.assertEqual(reg.registered_actions, frozenset({"x", "y", "z"}))


if __name__ == "__main__":
    unittest.main()
