"""Hypothesis property tests for L6: ResourceArbiter, ScheduleQueue."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.arbiter import ResourceArbiter, ResourceClaim
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.executor import ScheduleQueue

# ── Strategy helpers (L6-specific, not general enough for shared library) ──


@st.composite
def st_schedule_list(draw, min_size=1, max_size=10):
    """Generate a list of Schedules with distinct wall_times and wide tolerance."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    schedules = []
    for i in range(n):
        wt = draw(st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6))
        cmd = Command(action=f"action_{i}")
        schedules.append(Schedule(command=cmd, wall_time=wt, tolerance_ms=1000.0))
    return schedules


class TestResourceArbiterProperties:
    @given(
        priorities=st.lists(st.integers(min_value=0, max_value=100), min_size=2, max_size=5),
        created_times=st.lists(
            st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
            min_size=2,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_highest_priority_wins(self, priorities, created_times):
        """resolve() returns the claim with the highest priority."""
        n = min(len(priorities), len(created_times))
        if n < 2:
            return

        # Configure all (resource, chain) pairs
        config = {}
        for i in range(n):
            config[("res", f"chain_{i}")] = priorities[i]

        arbiter = ResourceArbiter(config)
        for i in range(n):
            rc = ResourceClaim(
                resource="res",
                chain=f"chain_{i}",
                priority=priorities[i],
                command="test",
                created_at=created_times[i],
            )
            arbiter.claim(rc)

        winner = arbiter.resolve("res")
        assert winner is not None
        assert winner.priority == max(priorities[:n])

    @given(
        created_times=st.lists(
            st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
            min_size=2,
            max_size=5,
            unique=True,
        ),
    )
    @settings(max_examples=100)
    def test_fifo_tiebreak(self, created_times):
        """Equal-priority claims resolved by earliest created_at."""
        priority = 50
        config = {}
        for i in range(len(created_times)):
            config[("res", f"chain_{i}")] = priority

        arbiter = ResourceArbiter(config)
        for i, ct in enumerate(created_times):
            rc = ResourceClaim(
                resource="res",
                chain=f"chain_{i}",
                priority=priority,
                command="test",
                created_at=ct,
            )
            arbiter.claim(rc)

        winner = arbiter.resolve("res")
        assert winner is not None
        assert winner.created_at == min(created_times)

    @given(
        created_at=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=100)
    def test_release_removes(self, created_at):
        """After release, claim no longer wins."""
        config = {("res", "c1"): 50}
        arbiter = ResourceArbiter(config)
        rc = ResourceClaim(
            resource="res", chain="c1", priority=50, command="test", created_at=created_at
        )
        arbiter.claim(rc)
        assert arbiter.resolve("res") is not None
        arbiter.release("res", "c1")
        assert arbiter.resolve("res") is None


class TestScheduleQueueProperties:
    @given(schedules=st_schedule_list(min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_drain_ready_items(self, schedules):
        """drain(now) returns items with wall_time <= now within tolerance."""
        q = ScheduleQueue()
        for s in schedules:
            q.enqueue(s)

        # Drain at max wall_time
        max_wt = max(s.wall_time for s in schedules)
        drained = q.drain(max_wt)

        for s in drained:
            assert s.wall_time <= max_wt
            deadline = s.wall_time + s.tolerance_ms / 1000.0
            assert max_wt <= deadline

    @given(
        wall_time=st.floats(allow_nan=False, allow_infinity=False, min_value=100.0, max_value=1e6),
    )
    @settings(max_examples=100)
    def test_preserves_future_items(self, wall_time):
        """Items with wall_time > now remain after drain."""
        q = ScheduleQueue()
        future = Schedule(command=Command(action="future"), wall_time=wall_time, tolerance_ms=50.0)
        q.enqueue(future)

        # Drain at a time before wall_time
        drained = q.drain(wall_time - 1.0)
        assert len(drained) == 0
        assert q.pending_count == 1

    @given(schedules=st_schedule_list(min_size=2, max_size=10))
    @settings(max_examples=100)
    def test_monotonic_drain_order(self, schedules):
        """Drained items are in non-decreasing wall_time order."""
        q = ScheduleQueue()
        for s in schedules:
            q.enqueue(s)

        max_wt = max(s.wall_time for s in schedules)
        drained = q.drain(max_wt)

        for i in range(len(drained) - 1):
            assert drained[i].wall_time <= drained[i + 1].wall_time

    @given(schedules=st_schedule_list(min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_no_item_loss(self, schedules):
        """drained + expired + remaining == enqueued."""
        q = ScheduleQueue()
        for s in schedules:
            q.enqueue(s)

        total = len(schedules)
        max_wt = max(s.wall_time for s in schedules)
        drained = q.drain(max_wt)
        remaining = q.pending_count

        # Count expired: wall_time <= now but past tolerance window
        expired = sum(
            1
            for s in schedules
            if s.wall_time <= max_wt and max_wt > s.wall_time + s.tolerance_ms / 1000.0
        )
        assert len(drained) + expired + remaining == total
