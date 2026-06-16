"""Ground-truth ``stalled`` projection + bounded, pressure-gated tick() reoffer.

A lane is ``stalled`` iff it owns a non-terminal task AND it has stopped: its
supervising launcher PID is gone, or its progress signal is stale past grace. The
projection is re-derived every tick (pure, no persisted edge). A stalled lane's
held task is reoffered back to ``offered``/``unassigned`` under the #3850 pressure
budget, and a ``ts``-keyed (ISO-8601 STRING, NOT an epoch float) ledger record is
emitted so the real stuck case is finally visible to INV-2.

All on-disk roots the reoffer path touches are patched onto a temp dir — no live
state (real ``cc-active-task`` signals, the real authority-case ledger) is ever
mutated by this suite.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agents.coordinator.core import (
    MAX_REOFFERS_PER_TASK,
    MAX_REOFFERS_PER_TICK,
    STALL_OUTPUT_GRACE_S,
    Coordinator,
    CoordinatorState,
    LaneState,
    Task,
    _lane_to_dict,
    project_stalled,
)
from shared.sdlc_pressure_gate import AdmissionDecision


@contextlib.contextmanager
def _isolated(tmp: Path) -> Iterator[None]:
    """Patch every on-disk root the projection/reoffer path reads or writes onto a
    temp dir, so the suite never touches live lane signals or the real ledger."""
    for sub in ("tasks", "cache", "pid"):
        (tmp / sub).mkdir(exist_ok=True)
    with (
        patch("agents.coordinator.core.TASKS_DIR", tmp / "tasks"),
        patch("agents.coordinator.core.CACHE_DIR", tmp / "cache"),
        patch("agents.coordinator.core.PID_DIR", tmp / "pid"),
        patch("agents.coordinator.core.REOFFER_LEDGER", tmp / "ledger.jsonl"),
    ):
        yield


def _lane(
    *, role: str = "ut_lane", claim: str | None = "ut-task-20260602", output_age_s: float = 0.0
) -> LaneState:
    return LaneState(
        role=role,
        session="",
        platform="claude",
        alive=True,
        claimed_task=claim,
        idle=False,
        output_age_s=output_age_s,
    )


def _write_note(
    tasks_dir: Path, task_id: str, *, status: str = "in_progress", assigned: str = "ut_lane"
) -> Path:
    path = tasks_dir / f"{task_id}.md"
    path.write_text(
        f"---\ntask_id: {task_id}\nstatus: {status}\nassigned_to: {assigned}\nwsjf: 5\n---\nbody\n",
        encoding="utf-8",
    )
    return path


def _set_launcher_alive(pid_dir: Path, role: str) -> None:
    # the test process itself is a live PID — os.kill(pid, 0) succeeds
    (pid_dir / f"{role}.launcher.pid").write_text(str(os.getpid()), encoding="utf-8")


def _offered_task(task_id: str, status: str = "claimed") -> Task:
    return Task(
        task_id=task_id,
        title="x",
        status=status,
        assigned_to="ut_lane",
        wsjf=5.0,
        effort_class="standard",
        platform_suitability=("claude",),
        quality_floor="deterministic_ok",
        path=Path(f"/tmp/{task_id}.md"),
    )


def _records(ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]


# ── pure projection (exercises the REAL _launcher_pid_present via PID_DIR) ─────


def test_project_stalled_dead_launcher() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            # no {role}.launcher.pid written → owner process gone; output is fresh
            lane = _lane(output_age_s=0.0)
            assert (
                project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is True
            )


def test_project_stalled_stale_output() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            _set_launcher_alive(tmp / "pid", "ut_lane")
            lane = _lane(output_age_s=STALL_OUTPUT_GRACE_S + 1.0)
            assert (
                project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is True
            )


def test_project_stalled_fresh_working() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            _set_launcher_alive(tmp / "pid", "ut_lane")
            lane = _lane(output_age_s=STALL_OUTPUT_GRACE_S - 1.0)
            assert (
                project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is False
            )


def test_project_stalled_pidfile_free_live_launcher_stays_busy() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with (
            _isolated(tmp),
            patch(
                "agents.coordinator.core._live_headless_launcher",
                return_value=(os.getpid(), "ut-task-20260602"),
            ),
        ):
            lane = _lane(output_age_s=float("inf"))
            lane.pid = os.getpid()
            lane.pid_source = "proc"

            assert (
                project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is False
            )


def test_project_stalled_live_tmux_session_stays_busy_without_launcher_pid() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            lane = _lane(role="cx-red", claim="ut-task-20260602", output_age_s=0.0)
            lane.session = "hapax-codex-cx-red"
            lane.platform = "codex"

            assert (
                project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is False
            )


def test_project_stalled_live_tmux_session_with_stale_output_stalls() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            lane = _lane(
                role="cx-red",
                claim="ut-task-20260602",
                output_age_s=STALL_OUTPUT_GRACE_S + 1.0,
            )
            lane.session = "hapax-codex-cx-red"
            lane.platform = "codex"

            assert (
                project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is True
            )


def test_project_stalled_no_claim_or_terminal_claim() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            # idle lane (no claim) is never stalled
            assert project_stalled(_lane(claim=None), non_terminal_task_ids=frozenset()) is False
            # claim already terminal (not in the non-terminal id set) → not stalled
            lane = _lane(claim="finished-task")
            assert project_stalled(lane, non_terminal_task_ids=frozenset({"other"})) is False


# ── bounded reoffer action + ledger record ────────────────────────────────────


def test_reoffer_rewrites_status_and_unassigns() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            note = _write_note(tmp / "tasks", "ut-task-20260602", status="in_progress")
            assert Coordinator()._reoffer_stalled(_lane(output_age_s=1234.0)) is True
            text = note.read_text(encoding="utf-8")
            assert "status: offered" in text
            assert "assigned_to: unassigned" in text
            recs = _records(tmp / "ledger.jsonl")
            assert len(recs) == 1
            rec = recs[0]
            assert rec["kind"] == "lane_stalled_reoffer"
            assert rec["task_id"] == "ut-task-20260602"
            assert rec["role"] == "ut_lane"
            assert rec["to_stage"] == "offered"
            assert "ts" in rec and "timestamp" not in rec


def test_ledger_ts_is_iso_string_not_epoch_float() -> None:
    """REGRESSION GUARD — the 56-year false-stuck.

    The reoffer record's ``ts`` MUST be an ISO-8601 STRING that the SAME parser INV-2
    uses (``datetime.fromisoformat``) round-trips, matching cc-stage-advance byte-for-byte
    — NOT a ``time.time()`` float. A float epoch hits ``fromisoformat`` → ``ValueError`` →
    ts=0.0 → ~56-year false stale → the record regenerates the exact INV-2 'stuck' finding
    it exists to cure.
    """
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            _write_note(tmp / "tasks", "ut-task-20260602", status="in_progress")
            Coordinator()._reoffer_stalled(_lane())
            ts = _records(tmp / "ledger.jsonl")[0]["ts"]
            assert isinstance(ts, str)
            assert not isinstance(ts, float)
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts), ts
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            # sane, present-day — NOT epoch-0 and NOT 1970+56yr
            assert parsed.year >= 2026
            assert abs((datetime.now(UTC) - parsed).total_seconds()) < 86400


def test_reoffer_idempotent() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            _write_note(tmp / "tasks", "ut-task-20260602", status="in_progress")
            coord = Coordinator()
            assert coord._reoffer_stalled(_lane()) is True
            assert coord._reoffer_stalled(_lane()) is False  # already offered → no-op
            assert len(_records(tmp / "ledger.jsonl")) == 1  # no duplicate record


def test_reoffer_clears_active_task_signal() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            _write_note(tmp / "tasks", "ut-task-20260602", status="in_progress")
            signal = tmp / "cache" / "cc-active-task-ut_lane"
            signal.write_text("ut-task-20260602", encoding="utf-8")
            assert Coordinator()._reoffer_stalled(_lane()) is True
            assert not signal.exists()  # stale claim signal removed → lane idle next tick


# ── glob prefix-collision (reviewer must-fix #2) ──────────────────────────────


def test_reoffer_aborts_on_ambiguous_prefix_collision() -> None:
    """A claim that prefix-matches MULTIPLE notes (``reform-clog`` vs ``reform-clog-g`` /
    ``reform-clog-d``) must NOT silently reoffer the wrong file — it aborts and emits a
    visible ambiguity record instead of taking ``matches[0]``."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            tasks = tmp / "tasks"
            _write_note(tasks, "reform-clog-g-20260602", status="in_progress")
            _write_note(tasks, "reform-clog-d-20260602", status="in_progress")
            assert Coordinator()._reoffer_stalled(_lane(claim="reform-clog")) is False
            # neither sibling was rewritten
            assert "status: in_progress" in (tasks / "reform-clog-g-20260602.md").read_text()
            assert "status: in_progress" in (tasks / "reform-clog-d-20260602.md").read_text()
            assert any(
                r["kind"] == "lane_stalled_reoffer_ambiguous"
                for r in _records(tmp / "ledger.jsonl")
            )


def test_reoffer_exact_match_wins_over_prefix() -> None:
    """Exact ``{id}.md`` is chosen even when ``{id}-*.md`` siblings exist (mirrors the
    cc-stage-advance ``_find_note`` resolution)."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            tasks = tmp / "tasks"
            exact = _write_note(tasks, "ut-task", status="in_progress")
            sibling = _write_note(tasks, "ut-task-suffix", status="in_progress")
            assert Coordinator()._reoffer_stalled(_lane(claim="ut-task")) is True
            assert "status: offered" in exact.read_text()
            assert "status: in_progress" in sibling.read_text()  # untouched


# ── per-task-lifetime cap (reviewer open-question, elevated by dispatch) ───────


def test_per_task_reoffer_cap_escalates_to_blocked() -> None:
    """After MAX_REOFFERS_PER_TASK reoffers of the SAME task, the next stall escalates to
    ``status: blocked`` (+ntfy) instead of looping offered→claim→stall→offered forever."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with (
            _isolated(tmp),
            patch("agents.coordinator.core.send_notification", return_value=True) as ntfy,
        ):
            note = _write_note(tmp / "tasks", "ut-loop-20260602", status="in_progress")
            coord = Coordinator()
            for _ in range(MAX_REOFFERS_PER_TASK):
                assert coord._reoffer_stalled(_lane(claim="ut-loop-20260602")) is True
                # simulate a fresh lane re-claiming the just-reoffered task
                note.write_text(
                    note.read_text()
                    .replace("status: offered", "status: in_progress")
                    .replace("assigned_to: unassigned", "assigned_to: ut_lane"),
                    encoding="utf-8",
                )
            # the (N+1)th stall escalates rather than reoffering again
            assert coord._reoffer_stalled(_lane(claim="ut-loop-20260602")) is True
            assert "status: blocked" in note.read_text()
            ntfy.assert_called()
            assert any(
                r["kind"] == "lane_stalled_escalated" for r in _records(tmp / "ledger.jsonl")
            )


# ── tick() wiring: projection + bounded, pressure-gated reoffer ────────────────


def _run_tick(
    lanes: dict[str, LaneState], tasks: list[Task], admission: str
) -> tuple[CoordinatorState, list]:
    coord = Coordinator()
    captured: list[CoordinatorState] = []
    with (
        patch.object(Coordinator, "_scan_tasks", return_value=tasks),
        patch.object(Coordinator, "_check_lanes", return_value=lanes),
        patch.object(Coordinator, "_dispatch", return_value=(True, "")),
        patch.object(
            Coordinator, "_write_state", side_effect=lambda state, **_: captured.append(state)
        ),
        patch(
            "agents.coordinator.core.admission_state",
            return_value=AdmissionDecision(state=admission),
        ),
    ):
        coord.tick()
    return captured[0], captured


def test_tick_reoffer_budget_closed_reoffers_nothing() -> None:
    """admission 'closed' → reoffer budget 0; a genuinely stalled lane is NOT reoffered
    (the held task stays on disk — queued, never dropped)."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):  # dead launcher → lane projects stalled
            lane = _lane(output_age_s=99999.0)
            with patch.object(Coordinator, "_reoffer_stalled") as spy:
                state, _ = _run_tick(
                    {"ut_lane": lane}, [_offered_task("ut-task-20260602")], "closed"
                )
            spy.assert_not_called()
            assert state.lanes_stalled == 1  # projected stalled, just not reoffered
            assert state.reoffers_this_tick == 0


def test_tick_reoffers_are_bounded_per_tick() -> None:
    """Two stalled lanes, MAX_REOFFERS_PER_TICK==1 → exactly one reoffer this tick."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            lanes = {
                "ut_a": _lane(role="ut_a", claim="ut-a-20260602", output_age_s=99999.0),
                "ut_b": _lane(role="ut_b", claim="ut-b-20260602", output_age_s=99999.0),
            }
            tasks = [_offered_task("ut-a-20260602"), _offered_task("ut-b-20260602")]
            with patch.object(Coordinator, "_reoffer_stalled", return_value=True) as spy:
                state, _ = _run_tick(lanes, tasks, "open")
            assert spy.call_count == MAX_REOFFERS_PER_TICK == 1
            assert state.lanes_stalled == 2
            assert state.reoffers_this_tick == 1


def test_tick_does_not_reoffer_blocked_or_pr_open_lane_claims() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with _isolated(tmp):
            lanes = {
                "ut_blocked": _lane(
                    role="ut_blocked", claim="ut-blocked-20260602", output_age_s=99999.0
                ),
                "ut_pr": _lane(role="ut_pr", claim="ut-pr-20260602", output_age_s=99999.0),
            }
            tasks = [
                _offered_task("ut-blocked-20260602", status="blocked"),
                _offered_task("ut-pr-20260602", status="pr_open"),
            ]
            with patch.object(Coordinator, "_reoffer_stalled") as spy:
                state, _ = _run_tick(lanes, tasks, "open")

            spy.assert_not_called()
            assert state.lanes_stalled == 0
            assert state.reoffers_this_tick == 0


# ── concrete safety acceptance + SHM surface ──────────────────────────────────


def test_reoffer_path_never_uses_killpg() -> None:
    """Concrete acceptance: the module never escalates to a process-group kill; every
    ``os.kill`` is a signal-0 liveness probe only."""
    import agents.coordinator.core as core

    src = Path(core.__file__).read_text(encoding="utf-8")
    assert "killpg(" not in src  # no process-group kill anywhere (prose may name it)
    for match in re.finditer(r"os\.kill\(([^)]*)\)", src):
        assert match.group(1).strip().endswith(", 0"), f"non-probe os.kill: {match.group(0)}"


def test_lane_to_dict_exposes_stalled_and_output_age() -> None:
    out = _lane_to_dict(LaneState(role="ut_lane", stalled=True, output_age_s=42.0))
    assert out["stalled"] is True
    assert out["output_age_s"] == 42.0
    # default inf age is JSON-safe (None), never a float('inf') in the SHM payload
    assert _lane_to_dict(LaneState(role="x"))["output_age_s"] is None
