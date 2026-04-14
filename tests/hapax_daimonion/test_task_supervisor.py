"""Tests for the background-task supervisor (BETA-FINDING-L, queue 025/026).

The supervisor lives in ``agents.hapax_daimonion.run_inner`` and walks
``daemon._supervised_tasks`` every main-loop tick. It observes crashes that
``asyncio.create_task`` otherwise holds invisibly in the Task object and
applies per-task policy (CRITICAL → SystemExit, RECREATE → log+recreate
with exponential backoff, LOG_AND_CONTINUE → log+drop).

See ``docs/research/2026-04-13/round5-unblock-and-gaps/phase-1-task-supervisor-design.md``
for the design rationale.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import MagicMock

import pytest

from agents.hapax_daimonion import run_inner


def _make_stub_daemon() -> types.SimpleNamespace:
    """Minimal daemon stub carrying only the attributes the supervisor touches."""
    return types.SimpleNamespace(
        _running=True,
        _background_tasks=[],
        _supervised_tasks={},
        event_log=MagicMock(),
    )


async def _dead_task_with_exc(exc: BaseException) -> asyncio.Task:
    """Create a task that raises ``exc`` and wait for it to be done."""

    async def _body() -> None:
        raise exc

    task = asyncio.create_task(_body())
    # Drive it to completion without propagating the exception.
    try:
        await task
    except BaseException:  # noqa: BLE001 — we expect the crash
        pass
    assert task.done()
    assert not task.cancelled()
    return task


class TestRecreatePolicy:
    """A RECREATE task that crashes should log, schedule a relaunch, and
    carry the retry count forward on the new task."""

    @pytest.mark.asyncio
    async def test_crash_schedules_relaunch(self, monkeypatch):
        daemon = _make_stub_daemon()

        # Force "ambient_refresh_loop" into RECREATE for this test (it
        # already is in the day-1 roster, but this makes the test
        # self-contained).
        monkeypatch.setattr(
            run_inner,
            "RECREATE_TASKS",
            frozenset({"ambient_refresh_loop"}),
        )
        monkeypatch.setattr(run_inner, "CRITICAL_TASKS", frozenset())
        monkeypatch.setattr(run_inner, "LOG_AND_CONTINUE_TASKS", frozenset())

        # Factory counter — observable in the test.
        calls = {"n": 0}

        async def _factory_body() -> None:
            calls["n"] += 1
            raise RuntimeError("boom")

        def factory():
            return _factory_body()

        crashed = await _dead_task_with_exc(RuntimeError("boom"))
        daemon._supervised_tasks["ambient_refresh_loop"] = (crashed, factory)
        daemon._background_tasks.append(crashed)

        # Supervisor should NOT raise — RECREATE policy logs + schedules.
        run_inner._supervise_background_tasks(daemon)

        # The dead entry is gone from _supervised_tasks (relaunch task will
        # repopulate it once the delay elapses).
        assert "ambient_refresh_loop" not in daemon._supervised_tasks

        # A relaunch task was scheduled in _background_tasks.
        relaunches = [
            t for t in daemon._background_tasks if t.get_name() == "_relaunch_ambient_refresh_loop"
        ]
        assert len(relaunches) == 1

        # Structured crash event was emitted with policy=recreate and retry=1.
        daemon.event_log.emit.assert_called()
        args, kwargs = daemon.event_log.emit.call_args
        assert args[0] == "background_task_crash"
        assert kwargs["task_name"] == "ambient_refresh_loop"
        assert kwargs["policy"] == "recreate"
        assert kwargs["retry_count"] == 1

        # Clean up: cancel the sleeping relaunch task so pytest doesn't warn.
        for t in relaunches:
            t.cancel()
        await asyncio.gather(*relaunches, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_retry_budget_exhaustion_raises_systemexit(self, monkeypatch):
        daemon = _make_stub_daemon()

        monkeypatch.setattr(
            run_inner,
            "RECREATE_TASKS",
            frozenset({"ntfy_subscribe"}),
        )
        monkeypatch.setattr(run_inner, "CRITICAL_TASKS", frozenset())
        monkeypatch.setattr(run_inner, "_RECREATE_RETRY_BUDGET", 3)

        async def _body() -> None:
            raise RuntimeError("persistent bug")

        def factory():
            return _body()

        crashed = await _dead_task_with_exc(RuntimeError("persistent bug"))
        # Simulate three prior recreations already having happened — the
        # next crash puts us at retries=4 which exceeds the budget (3).
        crashed._hapax_retry_count = 3  # type: ignore[attr-defined]
        daemon._supervised_tasks["ntfy_subscribe"] = (crashed, factory)
        daemon._background_tasks.append(crashed)

        with pytest.raises(SystemExit) as excinfo:
            run_inner._supervise_background_tasks(daemon)
        assert excinfo.value.code == 1

        # Escalation event was emitted with the retry-exhausted policy.
        emits = [
            c for c in daemon.event_log.emit.call_args_list if c.args[0] == "background_task_crash"
        ]
        assert emits, "no crash event emitted"
        assert emits[-1].kwargs["policy"] == "retry_exhausted_systemexit"


class TestCriticalPolicy:
    """A CRITICAL task crash should raise SystemExit(1) so systemd restarts
    the whole daemon. This is the fail-hard path that protects against the
    'alive but silent' failure mode from queue 024."""

    @pytest.mark.asyncio
    async def test_critical_crash_raises_systemexit(self, monkeypatch):
        daemon = _make_stub_daemon()

        monkeypatch.setattr(
            run_inner,
            "CRITICAL_TASKS",
            frozenset({"cpal_runner"}),
        )
        monkeypatch.setattr(run_inner, "RECREATE_TASKS", frozenset())

        async def _body() -> None:
            raise ValueError("CPAL runner collapsed")

        def factory():
            return _body()

        crashed = await _dead_task_with_exc(ValueError("CPAL runner collapsed"))
        daemon._supervised_tasks["cpal_runner"] = (crashed, factory)
        daemon._background_tasks.append(crashed)

        with pytest.raises(SystemExit) as excinfo:
            run_inner._supervise_background_tasks(daemon)
        assert excinfo.value.code == 1

        # Structured crash event was emitted with policy=systemexit.
        args, kwargs = daemon.event_log.emit.call_args
        assert args[0] == "background_task_crash"
        assert kwargs["policy"] == "systemexit"
        assert kwargs["task_name"] == "cpal_runner"


class TestCancelledTasksIgnored:
    """Tasks that were cancelled (shutdown path) must not be recreated or
    trigger SystemExit — otherwise the supervisor would interfere with
    normal shutdown."""

    @pytest.mark.asyncio
    async def test_cancelled_task_is_skipped(self, monkeypatch):
        daemon = _make_stub_daemon()

        monkeypatch.setattr(
            run_inner,
            "RECREATE_TASKS",
            frozenset({"workspace_monitor"}),
        )
        monkeypatch.setattr(run_inner, "CRITICAL_TASKS", frozenset())

        async def _body() -> None:
            await asyncio.sleep(60)

        task = asyncio.create_task(_body(), name="workspace_monitor")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

        daemon._supervised_tasks["workspace_monitor"] = (task, lambda: _body())

        # Supervisor must NOT raise and must NOT recreate a cancelled task.
        run_inner._supervise_background_tasks(daemon)

        # Entry still present but not relaunched — we leave the cancelled
        # task in the map because shutdown will clear it wholesale.
        assert "workspace_monitor" in daemon._supervised_tasks
        daemon.event_log.emit.assert_not_called()


class TestUnknownTaskDefaultsToSystemExit:
    """A task that exists in _supervised_tasks but has no policy entry
    should default to SystemExit — silent drift of a new unsupervised
    subsystem would re-introduce BETA-FINDING-L."""

    @pytest.mark.asyncio
    async def test_unknown_task_crash_raises_systemexit(self, monkeypatch):
        daemon = _make_stub_daemon()

        monkeypatch.setattr(run_inner, "CRITICAL_TASKS", frozenset())
        monkeypatch.setattr(run_inner, "RECREATE_TASKS", frozenset())
        monkeypatch.setattr(run_inner, "LOG_AND_CONTINUE_TASKS", frozenset())

        async def _body() -> None:
            raise RuntimeError("orphan")

        crashed = await _dead_task_with_exc(RuntimeError("orphan"))
        daemon._supervised_tasks["mystery_task"] = (crashed, lambda: _body())
        daemon._background_tasks.append(crashed)

        with pytest.raises(SystemExit) as excinfo:
            run_inner._supervise_background_tasks(daemon)
        assert excinfo.value.code == 1

        args, kwargs = daemon.event_log.emit.call_args
        assert kwargs["policy"] == "unknown_task_systemexit"
