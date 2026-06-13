"""Integration tests: Coordinator.tick() ↔ refusal ledger ↔ escalation.

These tests exercise the REAL Coordinator.tick() path with mocked I/O
(task scanning, lane checking, subprocess dispatch, ntfy), verifying
that the no-spin law behaves correctly through the actual coordinator
dispatch loop — not just the standalone ledger.

Addresses review-dossier criticals:
  - gemini-1: "Regression test is coverage theater that bypasses Coordinator.tick()"
  - codex-1: "Storm coverage bypasses the coordinator path that regressed"
  - claude-1: "No integration test for Coordinator.tick() ↔ ledger path"
  - gemini-1: "_ntfy_escalate likely swallows NameError for send_notification"
  - codex-1: "Empty dispatcher stderr bypasses the refusal ledger"
"""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.coordinator.core import (
    SCHEDULER_LEGACY_ENV,
    Coordinator,
    LaneState,
    Task,
    _ntfy_escalate,
)
from agents.coordinator.refusal_ledger import DEFAULT_K
from shared.dispatch_service_time import QueueLane, QueueTask, plan_dispatches

# ── fixtures ──────────────────────────────────────────────────────────────────

TASK_A = Task(
    task_id="task-a",
    title="Task A",
    status="offered",
    assigned_to="unassigned",
    wsjf=10.0,
    effort_class="standard",
    platform_suitability=("any",),
    quality_floor="deterministic_ok",
    path=Path("/fake/task-a.md"),
    created_at=0.0,
)

TASK_B = Task(
    task_id="task-b",
    title="Task B",
    status="offered",
    assigned_to="unassigned",
    wsjf=1.0,
    effort_class="standard",
    platform_suitability=("any",),
    quality_floor="deterministic_ok",
    path=Path("/fake/task-b.md"),
    created_at=0.0,
)

LANE_ALPHA = LaneState(
    role="alpha",
    session="hapax-claude-alpha",
    platform="claude",
    alive=True,
    idle=True,
    claimed_task=None,
)

# Offered but NOT routable to a claude lane — used to construct a genuinely
# starving task that the refusal ledger is NOT holding (no cooldown of its own).
TASK_C = Task(
    task_id="task-c",
    title="Task C",
    status="offered",
    assigned_to="unassigned",
    wsjf=5.0,
    effort_class="standard",
    platform_suitability=("codex",),
    quality_floor="deterministic_ok",
    path=Path("/fake/task-c.md"),
    created_at=0.0,
)

DETERMINISTIC_REASON = "BLOCKED: route policy refuse: runtime_actuation_receipt_absent"


def _make_lanes(lane: LaneState) -> dict[str, LaneState]:
    return {lane.role: lane}


def _failing_dispatch_result(reason: str, returncode: int = 10) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=reason)


def _success_dispatch_result() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


# ── _ntfy_escalate tests (critical: import + exception handling) ──────────────


class TestNtfyEscalate:
    """Verify _ntfy_escalate calls send_notification correctly and handles errors."""

    @patch("agents.coordinator.core.send_notification")
    def test_calls_send_notification(self, mock_send: MagicMock) -> None:
        """_ntfy_escalate wires through to send_notification with correct args."""
        _ntfy_escalate("title-x", "body-y")
        mock_send.assert_called_once_with(
            "title-x", "body-y", priority="high", tags=["sdlc", "no-spin"]
        )

    @patch("agents.coordinator.core.send_notification", side_effect=ConnectionError("ntfy down"))
    def test_swallows_exception(self, mock_send: MagicMock) -> None:
        """_ntfy_escalate must not raise even when send_notification fails."""
        _ntfy_escalate("title", "body")  # must not raise
        mock_send.assert_called_once()

    @patch("agents.coordinator.core.send_notification", side_effect=RuntimeError("boom"))
    def test_swallows_runtime_error(self, mock_send: MagicMock) -> None:
        """Even RuntimeError is caught — the tick must never abort on ntfy failure."""
        _ntfy_escalate("title", "body")
        mock_send.assert_called_once()


# ── Coordinator.tick() integration tests ──────────────────────────────────────


class TestTickIntegration:
    """Exercise Coordinator.tick() with mocked I/O to verify the full
    tick → _dispatch → refusal_ledger path."""

    @pytest.fixture(autouse=True)
    def _hermetic_dispatcher(self, tmp_path: Path):
        """Point the methodology dispatcher at a hermetic fixture so these tick
        tests don't depend on the operator's ~/projects/hapax-council clone
        existing — without this, _dispatch returns dispatcher_not_found before the
        mocked subprocess result is reached on any clean checkout (review-dossier:
        codex-1 / claude-1, non-hermetic dispatcher path)."""
        fixture = tmp_path / "hapax-methodology-dispatch"
        fixture.write_text("#!/bin/sh\nexit 0\n")
        with patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", fixture):
            yield

    def _make_coordinator(self) -> Coordinator:
        coord = Coordinator()
        # Replace the ntfy escalation with a recorder.
        coord._refusal_ledger._escalate_fn = MagicMock()
        return coord

    def _run_tick(
        self,
        coord: Coordinator,
        tasks: list[Task],
        lanes: dict[str, LaneState],
        dispatch_result: subprocess.CompletedProcess | Exception,
        tmp_path: Path,
        *,
        now: float | None = None,
    ) -> int:
        """Run one Coordinator.tick() with mocked internals."""
        with ExitStack() as stack:
            stack.enter_context(patch.object(coord, "_scan_tasks", return_value=tasks))
            stack.enter_context(patch.object(coord, "_check_lanes", return_value=lanes))
            mock_admission = stack.enter_context(patch("agents.coordinator.core.admission_state"))
            stack.enter_context(patch("agents.coordinator.core.SHM_DIR", tmp_path / "shm"))
            stack.enter_context(
                patch("agents.coordinator.core.SHM_FILE", tmp_path / "shm" / "state.json")
            )
            mock_run = stack.enter_context(patch("subprocess.run"))
            if now is not None:
                stack.enter_context(
                    patch("agents.coordinator.core.time.monotonic", return_value=now)
                )
                stack.enter_context(patch("agents.coordinator.core.time.time", return_value=now))
            mock_admission.return_value = MagicMock(state="open")
            if isinstance(dispatch_result, Exception):
                mock_run.side_effect = dispatch_result
            else:
                mock_run.return_value = dispatch_result
            coord.tick()
            return mock_run.call_count

    def test_deterministic_refusal_enters_cooldown_after_k(self, tmp_path: Path) -> None:
        """After K identical deterministic dispatch failures through tick(),
        the refusal ledger enters cooldown and the escalation fires."""
        coord = self._make_coordinator()
        tasks = [TASK_A]
        lanes = _make_lanes(LANE_ALPHA)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)

        for _i in range(DEFAULT_K):
            self._run_tick(coord, tasks, lanes, fail, tmp_path)

        # After K ticks, the pair should be in cooldown.
        ledger = coord._refusal_ledger
        assert ledger.any_cooldown_for_pair("task-a", "alpha")
        # Exactly 1 escalation should have fired.
        assert ledger._escalate_fn.call_count == 1

    def test_cooldown_skips_dispatch(self, tmp_path: Path) -> None:
        """Once in cooldown, subsequent ticks skip the dispatch call entirely."""
        coord = self._make_coordinator()
        tasks = [TASK_A]
        lanes = _make_lanes(LANE_ALPHA)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)

        # Drive K refusals to enter cooldown.
        for _i in range(DEFAULT_K):
            self._run_tick(coord, tasks, lanes, fail, tmp_path)

        # Now run additional ticks — dispatch should NOT be called.
        with (
            patch.object(coord, "_scan_tasks", return_value=tasks),
            patch.object(coord, "_check_lanes", return_value=lanes),
            patch("agents.coordinator.core.admission_state") as mock_admission,
            patch("agents.coordinator.core.SHM_DIR", tmp_path / "shm"),
            patch("agents.coordinator.core.SHM_FILE", tmp_path / "shm" / "state.json"),
            patch("subprocess.run") as mock_run,
        ):
            mock_admission.return_value = MagicMock(state="open")
            mock_run.return_value = fail
            coord.tick()
            # The dispatch should have been skipped because of cooldown.
            mock_run.assert_not_called()

    def test_cooled_pair_does_not_block_other_dispatchable_task(self, tmp_path: Path) -> None:
        """A cooled high-WSJF pair must not consume the lane for other work."""
        coord = self._make_coordinator()
        lanes = _make_lanes(LANE_ALPHA)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)
        now = 10_000.0

        for _i in range(DEFAULT_K):
            now += 30.0
            self._run_tick(coord, [TASK_A], lanes, fail, tmp_path, now=now)

        now += 30.0
        with (
            patch.object(coord, "_scan_tasks", return_value=[TASK_A, TASK_B]),
            patch.object(coord, "_check_lanes", return_value=lanes),
            patch("agents.coordinator.core.admission_state") as mock_admission,
            patch("agents.coordinator.core.SHM_DIR", tmp_path / "shm"),
            patch("agents.coordinator.core.SHM_FILE", tmp_path / "shm" / "state.json"),
            patch("agents.coordinator.core.time.monotonic", return_value=now),
            patch("agents.coordinator.core.time.time", return_value=now),
            patch("subprocess.run", return_value=_success_dispatch_result()) as mock_run,
        ):
            mock_admission.return_value = MagicMock(state="open")
            coord.tick()

        args = mock_run.call_args.args[0]
        assert "task-b" in args

    def test_success_clears_refusal_state(self, tmp_path: Path) -> None:
        """A successful dispatch clears all refusal state for that task."""
        coord = self._make_coordinator()
        tasks = [TASK_A]
        lanes = _make_lanes(LANE_ALPHA)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)

        # Accumulate refusals (but not enough for cooldown).
        for _i in range(DEFAULT_K - 1):
            self._run_tick(coord, tasks, lanes, fail, tmp_path)

        # Now dispatch succeeds.
        success = _success_dispatch_result()
        self._run_tick(coord, tasks, lanes, success, tmp_path)

        # Refusal state should be cleared.
        ledger = coord._refusal_ledger
        assert not ledger.any_cooldown_for_pair("task-a", "alpha")
        assert len(ledger._entries) == 0

    def test_empty_stderr_nonzero_exit_is_tracked(self, tmp_path: Path) -> None:
        """A nonzero exit with empty stderr must still be tracked by the
        refusal ledger (the 'dispatch_exit_N' fallback reason)."""
        coord = self._make_coordinator()
        tasks = [TASK_A]
        lanes = _make_lanes(LANE_ALPHA)
        # Empty stderr, nonzero exit.
        fail = _failing_dispatch_result("", returncode=2)

        self._run_tick(coord, tasks, lanes, fail, tmp_path)

        ledger = coord._refusal_ledger
        # Must have exactly one entry with the fallback reason.
        assert len(ledger._entries) == 1
        key = next(iter(ledger._entries))
        assert key[2] == "dispatch_exit_2"

    def test_shm_state_includes_refusal_stats(self, tmp_path: Path) -> None:
        """The SHM state.json must include the refusal_ledger section after a
        tick with refusals."""
        coord = self._make_coordinator()
        tasks = [TASK_A]
        lanes = _make_lanes(LANE_ALPHA)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)

        shm = tmp_path / "shm"
        state_file = shm / "state.json"

        with (
            patch.object(coord, "_scan_tasks", return_value=tasks),
            patch.object(coord, "_check_lanes", return_value=lanes),
            patch("agents.coordinator.core.admission_state") as mock_admission,
            patch("agents.coordinator.core.SHM_DIR", shm),
            patch("agents.coordinator.core.SHM_FILE", state_file),
            patch("subprocess.run", return_value=fail),
        ):
            mock_admission.return_value = MagicMock(state="open")
            coord.tick()

        state = json.loads(state_file.read_text())
        assert "refusal_ledger" in state
        assert state["refusal_ledger"]["refusal_triples"] == 1

    def test_timeout_exception_tracked_as_transient(self, tmp_path: Path) -> None:
        """A TimeoutExpired exception from subprocess.run is tracked as a
        transient refusal."""
        coord = self._make_coordinator()
        tasks = [TASK_A]
        lanes = _make_lanes(LANE_ALPHA)
        timeout = subprocess.TimeoutExpired(cmd=["dispatch"], timeout=10)

        self._run_tick(coord, tasks, lanes, timeout, tmp_path)

        ledger = coord._refusal_ledger
        assert len(ledger._entries) == 1
        entry = next(iter(ledger._entries.values()))
        assert entry.transient is True

    def test_starvation_detected_through_tick(self, tmp_path: Path) -> None:
        """If offered>0 and dispatched=0 for long enough, starvation escalation fires."""
        coord = self._make_coordinator()
        # Use a very short horizon for testing.
        coord._refusal_ledger.starvation_horizon_s = 0.0
        tasks = [TASK_A]
        lanes = _make_lanes(LANE_ALPHA)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)

        # First tick starts starvation tracking; second should fire (horizon=0).
        self._run_tick(coord, tasks, lanes, fail, tmp_path)
        self._run_tick(coord, tasks, lanes, fail, tmp_path)

        assert coord._refusal_ledger._starvation.escalated

    def test_storm_replay_through_tick(self, tmp_path: Path) -> None:
        """Replay the 2026-06-12 storm shape through Coordinator.tick().
        After K ticks all subsequent attempts should be skipped, giving
        dramatically fewer subprocess.run calls than the 1028 original."""
        coord = self._make_coordinator()
        tasks = [TASK_A]
        lanes = _make_lanes(LANE_ALPHA)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)

        subprocess_calls = 0
        storm_ticks = 1028
        now = 10_000.0
        tick_s = 30.0

        for _i in range(storm_ticks):
            now += tick_s
            subprocess_calls += self._run_tick(coord, tasks, lanes, fail, tmp_path, now=now)

        # The no-spin law should have limited dispatch attempts to K (before
        # cooldown) plus bounded re-probes over the full 1,028-tick / 30s storm.
        assert subprocess_calls <= 25
        assert subprocess_calls >= DEFAULT_K
        # Exactly 1 refusal escalation and no duplicate starvation escalation.
        assert coord._refusal_ledger._escalate_fn.call_count == 1
        assert coord._refusal_ledger.stats(now=now)["starvation_escalated"] is False

    def test_cooled_pair_does_not_mask_genuine_fleet_starvation(self, tmp_path: Path) -> None:
        """A single cooled pair must NOT suppress the fleet-starvation escalation
        for OTHER offered work that is genuinely starving.

        Regression for the review-dossier critical (codex-1 / claude-1): the prior
        ``starvation_offered = 0 if skipped_cooldown > 0`` zeroed the starvation
        input whenever ANY pair was cooled, so a queue with one cooled pair could
        run for hours with offered, undispatched, NON-cooled work and never fire
        the required starvation escalation. With the fix, only offered tasks the
        ledger is actually holding are discounted."""
        coord = self._make_coordinator()
        lanes = _make_lanes(LANE_ALPHA)  # claude lane only
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)
        now = 50_000.0

        # Phase 1: cool (task-a, alpha) on its own — drives the circuit breaker.
        for _i in range(DEFAULT_K):
            now += 30.0
            self._run_tick(coord, [TASK_A], lanes, fail, tmp_path, now=now)
        assert coord._refusal_ledger.any_cooldown_for_task("task-a", now=now)
        assert coord._refusal_ledger._escalate_fn.call_count == 1  # the refusal escalation

        # Phase 2: now task-c is offered alongside the cooled task-a. task-c is
        # codex-only, so it can never route to the claude lane: offered>0,
        # dispatched=0, and NOT in cooldown — genuine fleet starvation.
        coord._refusal_ledger.starvation_horizon_s = 0.0
        coord._refusal_ledger._starvation.starved_since = 0.0
        coord._refusal_ledger._starvation.escalated = False

        now += 30.0
        self._run_tick(coord, [TASK_A, TASK_C], lanes, fail, tmp_path, now=now)  # start horizon
        now += 1.0
        self._run_tick(coord, [TASK_A, TASK_C], lanes, fail, tmp_path, now=now)  # crosses horizon

        # The starvation escalation MUST have fired despite task-a being cooled.
        assert coord._refusal_ledger._starvation.escalated is True
        assert coord._refusal_ledger.stats(now=now)["starvation_escalated"] is True

    def test_all_offered_cooled_does_not_double_escalate_starvation(self, tmp_path: Path) -> None:
        """The complement: when EVERY offered task is cooled, the starvation
        detector stays silent — the circuit breaker already escalated, so we must
        not double-escalate the same root cause."""
        coord = self._make_coordinator()
        # Horizon above the K-tick pre-cooldown window (3 ticks * 30s) so the
        # uncooled ticks before the circuit breaker engages cannot themselves fire
        # a starvation page — otherwise the later cooldown would reset
        # starvation_escalated and hide that an extra operator page went out.
        coord._refusal_ledger.starvation_horizon_s = 120.0
        lanes = _make_lanes(LANE_ALPHA)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)
        now = 70_000.0

        for _i in range(DEFAULT_K + 5):
            now += 30.0
            self._run_tick(coord, [TASK_A], lanes, fail, tmp_path, now=now)

        assert coord._refusal_ledger.any_cooldown_for_task("task-a", now=now)
        assert coord._refusal_ledger.stats(now=now)["starvation_escalated"] is False
        # Exactly ONE escalation total — the circuit breaker — and no starvation
        # page slipped out (call_count would be 2 if it had).
        assert coord._refusal_ledger._escalate_fn.call_count == 1

    def test_transient_cooldown_still_drives_starvation(self, tmp_path: Path) -> None:
        """A task stuck in a TRANSIENT cooldown (timeouts → K=10, no escalation)
        must still drive the starvation horizon. The circuit breaker never paged
        for it, so discounting it from starvation would drop it silently — neither
        escalated nor surfaced (review-dossier critical, codex-1)."""
        coord = self._make_coordinator()
        coord._refusal_ledger.transient_k = 2  # cool transiently fast for the test
        coord._refusal_ledger.starvation_horizon_s = 60.0
        lanes = _make_lanes(LANE_ALPHA)  # idle lane present → capacity exists
        timeout = subprocess.TimeoutExpired(cmd=["dispatch"], timeout=10)
        now = 130_000.0

        # Drive the task into a transient cooldown, then keep ticking past horizon.
        for _i in range(5):
            now += 30.0
            self._run_tick(coord, [TASK_A], lanes, timeout, tmp_path, now=now)

        # The task IS cooled, but transiently (no circuit-breaker escalation)...
        assert coord._refusal_ledger.any_cooldown_for_task("task-a", now=now)
        assert not coord._refusal_ledger.any_cooldown_for_task(
            "task-a", escalated_only=True, now=now
        )
        # ...so starvation MUST have fired (it would not under the old discount).
        assert coord._refusal_ledger.stats(now=now)["starvation_escalated"] is True
        title = coord._refusal_ledger._escalate_fn.call_args.args[0]
        assert "starvation" in title.lower()

    def test_legacy_scheduler_cooled_pair_does_not_block_other_work(self, tmp_path: Path) -> None:
        """Regression for the review-dossier critical (codex-1): under the legacy
        scheduler (HAPAX_DISPATCH_SCHEDULER_LEGACY=1), a cooled high-WSJF pair must
        not head-of-line-block a lane that other dispatchable work could use."""
        with patch.dict(os.environ, {SCHEDULER_LEGACY_ENV: "1"}):
            coord = self._make_coordinator()
            lanes = _make_lanes(LANE_ALPHA)
            fail = _failing_dispatch_result(DETERMINISTIC_REASON)
            now = 90_000.0

            # Cool the high-WSJF task-a on the only lane.
            for _i in range(DEFAULT_K):
                now += 30.0
                self._run_tick(coord, [TASK_A], lanes, fail, tmp_path, now=now)
            assert coord._refusal_ledger.any_cooldown_for_pair("task-a", "alpha", now=now)

            # task-a (wsjf 10, cooled) + task-b (wsjf 1, dispatchable). Legacy WSJF
            # order would pick task-a first and freeze the lane; the no-spin repair
            # must replan the lane to task-b instead.
            now += 30.0
            with (
                patch.object(coord, "_scan_tasks", return_value=[TASK_A, TASK_B]),
                patch.object(coord, "_check_lanes", return_value=lanes),
                patch("agents.coordinator.core.admission_state") as mock_admission,
                patch("agents.coordinator.core.SHM_DIR", tmp_path / "shm"),
                patch("agents.coordinator.core.SHM_FILE", tmp_path / "shm" / "state.json"),
                patch("agents.coordinator.core.time.monotonic", return_value=now),
                patch("agents.coordinator.core.time.time", return_value=now),
                patch("subprocess.run", return_value=_success_dispatch_result()) as mock_run,
            ):
                mock_admission.return_value = MagicMock(state="open")
                coord.tick()

            assert mock_run.call_args is not None, "legacy path dispatched nothing"
            args = mock_run.call_args.args[0]
            assert "task-b" in args
            assert "task-a" not in args

    def test_repair_is_noop_without_cooldowns(self) -> None:
        """The no-spin repair pass must not perturb normal dispatch when nothing is
        cooled — pins that the routine dispatch path provably delegates to the
        tested plan_dispatches (review-dossier major, claude-1)."""
        coord = self._make_coordinator()
        tasks = [
            QueueTask(task_id="a", wsjf=5.0, platform_suitability=("any",), age_s=0.0),
            QueueTask(task_id="b", wsjf=9.0, platform_suitability=("any",), age_s=0.0),
            QueueTask(task_id="c", wsjf=1.0, platform_suitability=("claude",), age_s=0.0),
        ]
        lanes = [
            QueueLane(role="alpha", platform="claude", cooldown_remaining_s=0.0),
            QueueLane(role="beta", platform="claude", cooldown_remaining_s=0.0),
        ]
        for legacy in (False, True):
            base = plan_dispatches(tasks, lanes, max_dispatches=2, age_norm_s=0.0, legacy=legacy)
            repaired, skipped = coord._repair_cooled_plan(
                base, tasks, lanes, age_norm_s=0.0, now_mono=1000.0
            )
            assert repaired == base, f"repair perturbed plan (legacy={legacy})"
            assert skipped == 0

    def test_dispatcher_not_found_reason(self, tmp_path: Path) -> None:
        """When the methodology dispatcher is missing, _dispatch reports the
        dispatcher_not_found refusal reason (not a silent success)."""
        coord = Coordinator()
        missing = tmp_path / "no-such-dispatcher"
        with patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", missing):
            success, reason = coord._dispatch(TASK_A, LANE_ALPHA)
        assert success is False
        assert reason == "dispatcher_not_found"

    def test_saturated_fleet_does_not_page_as_starvation(self, tmp_path: Path) -> None:
        """A fleet with NO idle lanes (all busy working) must not fire a starvation
        escalation even with offered work — that is saturation, not starvation
        (review-dossier minor, claude-1: spurious-page risk on busy fleets)."""
        coord = self._make_coordinator()
        coord._refusal_ledger.starvation_horizon_s = 0.0
        # Lane is alive but BUSY (claimed a task) → excluded from idle_lanes.
        busy_lane = LaneState(
            role="alpha",
            session="hapax-claude-alpha",
            platform="claude",
            alive=True,
            idle=False,
            claimed_task="something-else",
        )
        lanes = _make_lanes(busy_lane)
        fail = _failing_dispatch_result(DETERMINISTIC_REASON)
        now = 110_000.0

        # Offered work, zero idle capacity, well past the horizon.
        for _i in range(4):
            now += 30.0
            self._run_tick(coord, [TASK_A], lanes, fail, tmp_path, now=now)

        assert coord._refusal_ledger.stats(now=now)["starvation_escalated"] is False
        assert coord._refusal_ledger._starvation.starved_since == 0.0

    def test_oserror_dispatch_tracked_as_transient(self, tmp_path: Path) -> None:
        """An OSError from subprocess.run is recorded as a transient refusal."""
        coord = self._make_coordinator()
        self._run_tick(coord, [TASK_A], _make_lanes(LANE_ALPHA), OSError("boom"), tmp_path)
        ledger = coord._refusal_ledger
        assert len(ledger._entries) == 1
        entry = next(iter(ledger._entries.values()))
        assert entry.reason.startswith("OSError")
        assert entry.transient is True


# ── hapax-methodology-dispatch retry surface investigation ────────────────────


class TestMethodologyDispatchRetrySurface:
    """Exit predicate clause: 'the same guard rides hapax-methodology-dispatch's
    retry surface if one exists'.

    Investigation: hapax-methodology-dispatch has NO internal retry surface.
    It is a single-shot script (dispatch once, exit).  Retries come exclusively
    from the coordinator daemon tick loop, which the no-spin law now guards.

    This test documents and asserts the finding so future changes that add a
    retry surface will be caught."""

    def test_no_retry_surface_in_dispatcher(self) -> None:
        """The hapax-methodology-dispatch script contains no retry/loop logic."""
        dispatcher = Path(__file__).resolve().parents[1] / "scripts/hapax-methodology-dispatch"
        assert dispatcher.exists(), f"dispatcher not found at {dispatcher}"
        text = dispatcher.read_text(encoding="utf-8")
        # The script should not contain retry-loop patterns.
        import re

        retry_patterns = [
            r"\bretry\b.*\bloop\b",
            r"\bwhile\b.*\bretry\b",
            r"\bmax_retries\b",
            r"\bretry_count\b",
        ]
        for pattern in retry_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            assert match is None, (
                f"Unexpected retry surface found in hapax-methodology-dispatch: "
                f"{match.group()} at offset {match.start()}"
            )
