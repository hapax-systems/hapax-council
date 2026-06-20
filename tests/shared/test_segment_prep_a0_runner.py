"""Tests for the seg-prep A0 baseline collection runner (#29 driver).

The runner drives prep passes (an injected callable) and stops at the §5.1 condition the G3 phase
controller computes. The loop is exercised with a fake `run_pass` that appends synthetic ledger
rows — no live resident-model run.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.segment_prep_a0_runner import (
    A0Result,
    _main,
    run_a0_collection,
    run_prep_subprocess,
)
from shared.segment_prep_phase_controller import PhasePlan


def _append_rows(
    prep_base: Path,
    *,
    n: int,
    criterion: float,
    score: float,
    released: bool = True,
    start: int = 0,
    date: str = "2026-06-16",
) -> None:
    """Append n council-decisions ledger rows in the format the DV reader parses."""
    day = prep_base / date
    day.mkdir(parents=True, exist_ok=True)
    ledger = day / "council-decisions.ndjson"
    with ledger.open("a", encoding="utf-8") as handle:
        for i in range(n):
            seq = start + i
            row = {
                "programme_id": f"p{seq}",
                "ledgered_at": f"2026-06-16T00:{seq:02d}:00Z",
                "terminal_status": "released" if released else "refused",
                "council_decisions": {"coherence": {"mean_score": score, "criterion": criterion}},
            }
            handle.write(json.dumps(row) + "\n")


def _fake_pass(prep_base: Path, *, per_pass: int, criterion: float, score: float):
    """A run_pass that appends `per_pass` stable released rows each call (deterministic order)."""
    state = {"seq": 0}

    def _run(c: float, base: Path) -> None:
        _append_rows(prep_base, n=per_pass, criterion=criterion, score=score, start=state["seq"])
        state["seq"] += per_pass

    return _run


class TestRunA0Collection:
    A0 = PhasePlan(criteria=(3.0,))  # floor-only baseline; min_hosted=8, max_segments=15

    def test_stops_when_controller_reports_baseline_complete(self, tmp_path: Path):
        # 3 stable released rows per pass: pass 3 reaches 9 hosted (>=8) + stable -> baseline_complete
        run_pass = _fake_pass(tmp_path, per_pass=3, criterion=3.0, score=4.0)
        result = run_a0_collection(plan=self.A0, prep_base=tmp_path, run_pass=run_pass)
        assert isinstance(result, A0Result)
        assert result.stop_reason == "controller"
        assert result.final_decision.action == "baseline_complete"
        assert result.passes_run == 3
        assert result.phase_summary is not None and result.phase_summary.released == 9

    def test_stops_at_max_passes_when_never_terminal(self, tmp_path: Path):
        # a run_pass that produces nothing -> the controller holds forever -> the cap stops it
        def empty_pass(c: float, base: Path) -> None:
            return None

        result = run_a0_collection(
            plan=self.A0, prep_base=tmp_path, run_pass=empty_pass, max_passes=5
        )
        assert result.stop_reason == "max_passes"
        assert result.passes_run == 5
        assert result.final_decision.action == "hold"

    def test_rejects_nonpositive_max_passes(self, tmp_path: Path):
        with pytest.raises(ValueError):
            run_a0_collection(
                plan=self.A0, prep_base=tmp_path, run_pass=lambda c, b: None, max_passes=0
            )

    def test_each_pass_receives_the_floor_criterion(self, tmp_path: Path):
        seen: list[float] = []

        def recording_pass(c: float, base: Path) -> None:
            seen.append(c)
            _append_rows(tmp_path, n=8, criterion=3.0, score=4.0)

        run_a0_collection(plan=self.A0, prep_base=tmp_path, run_pass=recording_pass)
        assert seen and all(c == 3.0 for c in seen)

    def test_rejects_multi_criterion_plan(self, tmp_path: Path):
        # the A0 runner drives the floor-only baseline; a multi-step ladder is a different driver
        with pytest.raises(ValueError):
            run_a0_collection(
                plan=PhasePlan(criteria=(3.0, 3.5)),
                prep_base=tmp_path,
                run_pass=lambda c, b: None,
            )

    def test_off_plan_rows_stop_early_with_distinct_reason(self, tmp_path: Path):
        # prep stamping an off-plan C_k (env/plan drift) must NOT silently burn every heavyweight
        # pass to the cap; surface it loud and stop after the first drifted pass.
        run_pass = _fake_pass(
            tmp_path, per_pass=9, criterion=3.5, score=4.0
        )  # off-plan vs floor 3.0
        result = run_a0_collection(
            plan=self.A0, prep_base=tmp_path, run_pass=run_pass, max_passes=10
        )
        assert result.stop_reason == "off_plan_drift"
        assert result.passes_run == 1
        assert result.phase_summary is None


class TestRunPrepSubprocess:
    def test_sets_criterion_env_and_invokes_prep_cli(self, tmp_path: Path):
        with patch("shared.segment_prep_a0_runner.subprocess.run") as mock_run:
            run_prep_subprocess(3.0, tmp_path)
        assert mock_run.call_count == 1
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert "agents.hapax_daimonion.daily_segment_prep" in cmd
        assert "--prep-dir" in cmd and str(tmp_path) in cmd
        env = kwargs["env"]
        assert env["HAPAX_COHERENCE_CRITERION"] == repr(3.0)
        assert env["HAPAX_SEGMENT_PREP_DIR"] == str(tmp_path)


class TestMainCli:
    def test_main_drives_collection_and_returns_zero(self, tmp_path: Path):
        # the CLI wires --floor into an A0 plan and drives run_a0_collection with the real
        # subprocess run_pass — patched here so no live prep runs; stable rows -> baseline_complete.
        def fake_pass(criterion: float, base: Path) -> None:
            _append_rows(tmp_path, n=8, criterion=3.0, score=4.0)

        with patch("shared.segment_prep_a0_runner.run_prep_subprocess", side_effect=fake_pass):
            rc = _main(["--floor", "3.0", "--prep-base", str(tmp_path), "--max-passes", "3"])
        assert rc == 0

    def test_main_rejects_out_of_range_floor(self, tmp_path: Path):
        # an out-of-range floor must fail at plan-build (PhasePlan range check), not at first pass
        with pytest.raises(ValueError):
            _main(["--floor", "0.5", "--prep-base", str(tmp_path)])
