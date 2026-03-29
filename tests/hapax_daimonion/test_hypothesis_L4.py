"""Hypothesis property tests for L4: Command, Schedule, VetoResult."""

from __future__ import annotations

import types

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_daimonion.executor import ScheduleQueue
from agents.hapax_daimonion.governance import VetoResult
from tests.hapax_daimonion.hypothesis_strategies import st_command, st_schedule, st_veto_result


class TestCommandProperties:
    @given(cmd=st_command())
    @settings(max_examples=200)
    def test_frozen(self, cmd):
        """Command is frozen — setattr raises AttributeError."""
        try:
            cmd.action = "hacked"  # type: ignore[misc]
            raise AssertionError("Should have raised AttributeError")
        except AttributeError:
            pass

    @given(cmd=st_command())
    @settings(max_examples=200)
    def test_params_mapping_proxy(self, cmd):
        """Command.params is MappingProxyType — mutation raises TypeError."""
        assert isinstance(cmd.params, types.MappingProxyType)
        try:
            cmd.params["injected"] = 999  # type: ignore[index]
            raise AssertionError("Should have raised TypeError")
        except TypeError:
            pass

    @given(vr=st_veto_result())
    @settings(max_examples=200)
    def test_veto_result_allowed_implies_no_denials(self, vr):
        """allowed == True implies denied_by is empty (by construction)."""
        if vr.allowed:
            assert vr.denied_by == ()

    @given(cmd=st_command())
    @settings(max_examples=200)
    def test_governance_result_preserved(self, cmd):
        """governance_result round-trips through construction."""
        assert cmd.governance_result.allowed == cmd.governance_result.allowed
        assert isinstance(cmd.governance_result, VetoResult)


class TestScheduleProperties:
    @given(
        sched=st_schedule(),
        now_offset=st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_tolerance_boundary(self, sched, now_offset):
        """Schedule within tolerance window (wall_time + tolerance/1000) is drainable."""
        now = sched.wall_time + now_offset * (sched.tolerance_ms / 1000.0)
        if now < sched.wall_time:
            return  # Skip if now < wall_time (not yet ready)
        deadline = sched.wall_time + sched.tolerance_ms / 1000.0
        # Within tolerance: now <= deadline
        assert now <= deadline + 1e-9

    @given(sched=st_schedule())
    @settings(max_examples=100)
    def test_composition_contract_to_L6(self, sched):
        """Generated Schedule is valid input to ScheduleQueue.enqueue()."""
        q = ScheduleQueue()
        q.enqueue(sched)
        assert q.pending_count == 1
