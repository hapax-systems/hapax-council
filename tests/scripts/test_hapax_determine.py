"""The determination spine must make "ran and declined" distinguishable from "never ran".

That ambiguity is the defect it exists to close. Measured 2026-08-19: agy's quota admission
is fully mechanical and mints a 15-minute receipt, nothing renewed it, its receipts had been
expired since 2026-08-17, the gemini review family silently left the review floor, and a PR
could not be reviewed. No artifact anywhere reported a problem, because a producer that never
runs and a producer that runs and correctly declines looked identical.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "hapax-determine"
_spec = importlib.util.spec_from_file_location(
    "hapax_determine",
    _SCRIPT,
    loader=importlib.machinery.SourceFileLoader("hapax_determine", str(_SCRIPT)),
)
assert _spec and _spec.loader
det = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(det)

NOW = datetime(2026, 8, 19, 18, 0, 0, tzinfo=UTC)


def _registry(tmp_path: Path, **over) -> Path:
    producer = {
        "id": "p1",
        "property": "account_live_quota",
        "subjects": ["some.route"],
        "command": ["/bin/true"],
        "cadence_seconds": 600,
        "evidence_ttl_seconds": 1800,
        "provenance": "mechanical",
        "success_exit_codes": [0],
        "declined_exit_codes": [3, 4],
    }
    producer.update(over)
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"schema": "x", "producers": [producer]}))
    return p


class TestRegistryRefusesGuaranteedLapse:
    def test_cadence_at_or_above_ttl_is_an_error(self, tmp_path: Path) -> None:
        """This is exactly how agy lapsed: evidence lived 900s, nothing ran inside it."""
        reg = _registry(tmp_path, cadence_seconds=900, evidence_ttl_seconds=900)
        with pytest.raises(ValueError, match="guaranteed to lapse"):
            det.load_registry(reg)

    def test_cadence_below_ttl_is_accepted(self, tmp_path: Path) -> None:
        assert det.load_registry(_registry(tmp_path, cadence_seconds=300))

    def test_duplicate_ids_are_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "r.json"
        one = {"id": "dup", "command": ["/bin/true"], "cadence_seconds": 60}
        p.write_text(json.dumps({"producers": [one, dict(one)]}))
        with pytest.raises(ValueError, match="duplicate"):
            det.load_registry(p)


class TestDeclinedIsNotSilence:
    """The central distinction. A declined run is a healthy producer reporting bad news."""

    def test_declined_exit_is_recorded_as_declined_not_failed(self, tmp_path: Path) -> None:
        rec = det.run_producer(
            {
                "id": "p1",
                "command": ["/bin/sh", "-c", "exit 4"],
                "cadence_seconds": 60,
                "success_exit_codes": [0],
                "declined_exit_codes": [3, 4],
            },
            now=NOW,
            repo_root=tmp_path,
            timeout=30,
        )
        assert rec["outcome"] == "declined"
        assert rec["returncode"] == 4

    def test_unlisted_nonzero_exit_is_a_failure(self, tmp_path: Path) -> None:
        rec = det.run_producer(
            {
                "id": "p1",
                "command": ["/bin/sh", "-c", "exit 9"],
                "cadence_seconds": 60,
                "success_exit_codes": [0],
                "declined_exit_codes": [3, 4],
            },
            now=NOW,
            repo_root=tmp_path,
            timeout=30,
        )
        assert rec["outcome"] == "failed"

    def test_missing_binary_is_unlaunchable_not_declined(self, tmp_path: Path) -> None:
        rec = det.run_producer(
            {"id": "p1", "command": [str(tmp_path / "nope")], "cadence_seconds": 60},
            now=NOW,
            repo_root=tmp_path,
            timeout=30,
        )
        assert rec["outcome"] == "unlaunchable"

    def test_a_run_is_witnessed_even_when_it_produces_nothing(self, tmp_path: Path) -> None:
        """Without this, declining and never running are the same observable."""
        ledger = tmp_path / "runs.jsonl"
        det.append_run(
            ledger, {"ran_at": det._iso(NOW), "producer_id": "p1", "outcome": "declined"}
        )
        assert det.last_runs(ledger)["p1"]["outcome"] == "declined"


class TestLivenessReconciler:
    def test_never_ran_is_a_deficit(self, tmp_path: Path) -> None:
        producers = det.load_registry(_registry(tmp_path))
        out = det.liveness(producers, {}, NOW)
        assert out and out[0]["deficit"] == "never_ran"

    def test_declined_recently_is_NOT_a_deficit(self, tmp_path: Path) -> None:
        """A producer honestly reporting 'no evidence' is healthy and must not alarm."""
        producers = det.load_registry(_registry(tmp_path))
        runs = {"p1": {"ran_at": det._iso(NOW - timedelta(seconds=60)), "outcome": "declined"}}
        assert det.liveness(producers, runs, NOW) == []

    def test_silence_past_two_cadences_is_a_deficit(self, tmp_path: Path) -> None:
        producers = det.load_registry(_registry(tmp_path))  # cadence 600
        runs = {"p1": {"ran_at": det._iso(NOW - timedelta(seconds=1500)), "outcome": "produced"}}
        out = det.liveness(producers, runs, NOW)
        assert out and out[0]["deficit"] == "producer_silent"
        assert out[0]["age_seconds"] == 1500

    def test_one_slipped_fire_is_tolerated(self, tmp_path: Path) -> None:
        producers = det.load_registry(_registry(tmp_path))
        runs = {"p1": {"ran_at": det._iso(NOW - timedelta(seconds=900)), "outcome": "produced"}}
        assert det.liveness(producers, runs, NOW) == []

    def test_last_run_failure_surfaces(self, tmp_path: Path) -> None:
        producers = det.load_registry(_registry(tmp_path))
        runs = {"p1": {"ran_at": det._iso(NOW), "outcome": "failed", "returncode": 9}}
        out = det.liveness(producers, runs, NOW)
        assert out and out[0]["deficit"] == "last_run_failed"


class TestCadence:
    def test_not_due_is_skipped(self, tmp_path: Path) -> None:
        p = det.load_registry(_registry(tmp_path))[0]
        assert not det.is_due(p, {"ran_at": det._iso(NOW - timedelta(seconds=10))}, NOW)

    def test_due_after_cadence(self, tmp_path: Path) -> None:
        p = det.load_registry(_registry(tmp_path))[0]
        assert det.is_due(p, {"ran_at": det._iso(NOW - timedelta(seconds=601))}, NOW)

    def test_unparseable_last_run_is_treated_as_due(self, tmp_path: Path) -> None:
        """Fail toward running. A corrupt ledger line must not silently stop a producer."""
        p = det.load_registry(_registry(tmp_path))[0]
        assert det.is_due(p, {"ran_at": "not-a-timestamp"}, NOW)


class TestDueWithin:
    """--due-within closes the measured failure phase: a pull at :X8:24 against
    a :X-1:42 mint is 582s old on a 600s cadence — not_due to a due-check-only
    gate, a NO-OP pull, and the flap survives the repair (critical finding on
    #4665)."""

    def _main(self, tmp_path: Path, ledger_age_s: int, *extra: str) -> dict:
        marker = tmp_path / "producer-ran"
        producer_sh = tmp_path / "producer.sh"
        producer_sh.write_text(f"#!/bin/sh\ntouch {marker}\n")
        producer_sh.chmod(0o755)
        reg = _registry(tmp_path, command=[str(producer_sh)])
        ledger = tmp_path / "runs.jsonl"
        det.append_run(
            ledger,
            {
                "ran_at": det._iso(NOW - timedelta(seconds=ledger_age_s)),
                "producer_id": "p1",
                "outcome": "produced",
            },
        )
        rc = det.main(
            [
                "--registry",
                str(reg),
                "--run-ledger",
                str(ledger),
                "--repo-root",
                str(tmp_path),
                "--now",
                det._iso(NOW),
                "--json",
                *extra,
            ]
        )
        assert rc == 0
        return {"marker": marker, "ledger": ledger}

    def test_waits_into_the_due_window_and_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The measured phase exactly: 582s of age on a 600s cadence, pulled 18s
        before the boundary. The harness must sleep those 18s and mint at the
        boundary, not skip."""
        slept: list[float] = []
        monkeypatch.setattr(det.time, "sleep", lambda s: slept.append(s))
        ctx = self._main(tmp_path, 582, "--due-within", "30")
        # subprocess.communicate polls in ~1ms sleeps (git identity probes,
        # producer waits); the due-window sleep is the only cadence-scale one.
        assert [s for s in slept if s > 0.1] == [18.0]
        assert ctx["marker"].exists()
        payload = json.loads(capsys.readouterr().out)
        assert [r["producer_id"] for r in payload["ran"]] == ["p1"]
        # The receipt is stamped at the post-sleep boundary, and the reported
        # now agrees with the stamp (--now advanced by the slept seconds).
        assert payload["ran"][0]["ran_at"] == det._iso(NOW + timedelta(seconds=18))
        assert payload["now"] == det._iso(NOW + timedelta(seconds=18))
        assert payload["skipped"] == []

    def test_out_of_horizon_does_not_wait(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """300s from due is outside a 30s horizon: no sleep, an honest not_due
        skip — waiting here would make every tick unboundedly slow."""
        slept: list[float] = []
        monkeypatch.setattr(det.time, "sleep", lambda s: slept.append(s))
        ctx = self._main(tmp_path, 300, "--due-within", "30")
        assert not any(s > 0.1 for s in slept)
        assert not ctx["marker"].exists()
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert payload["skipped"] == [{"producer_id": "p1", "reason": "not_due"}]

    def test_concurrent_winner_during_the_sleep_short_circuits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The determine timer fires while the pull sleeps into the boundary and
        mints first: the sleeper wakes, re-reads under the lock, and skips —
        still one provider round trip per cadence window."""
        marker = tmp_path / "producer-ran"
        producer_sh = tmp_path / "producer.sh"
        producer_sh.write_text(f"#!/bin/sh\ntouch {marker}\n")
        producer_sh.chmod(0o755)
        reg = _registry(tmp_path, command=[str(producer_sh)])
        ledger = tmp_path / "runs.jsonl"
        det.append_run(
            ledger,
            {
                "ran_at": det._iso(NOW - timedelta(seconds=582)),
                "producer_id": "p1",
                "outcome": "produced",
            },
        )

        def _winner_mints_during_sleep(seconds: float) -> None:
            if seconds <= 0.1:
                return  # subprocess poll noise, not the due-window sleep
            assert seconds == 18.0
            det.append_run(
                ledger,
                {
                    "ran_at": det._iso(NOW + timedelta(seconds=18)),
                    "producer_id": "p1",
                    "outcome": "produced",
                },
            )

        monkeypatch.setattr(det.time, "sleep", _winner_mints_during_sleep)
        rc = det.main(
            [
                "--registry",
                str(reg),
                "--run-ledger",
                str(ledger),
                "--repo-root",
                str(tmp_path),
                "--now",
                det._iso(NOW),
                "--due-within",
                "30",
                "--json",
            ]
        )
        assert rc == 0
        assert not marker.exists()
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert payload["skipped"] == [{"producer_id": "p1", "reason": "not_due"}]
        assert payload["liveness"] == []


class TestInvokerContractPins:
    def test_determine_unit_runs_the_default_run_ledger(self) -> None:
        """The pull-forward's lock + in-lock re-read dedup contract holds only
        while BOTH invokers gate the SAME default run ledger. If the unit ever
        grows a --run-ledger override, the writer's pull and the timer run
        different ledgers and both fire the provider round trip (review
        finding on #4665)."""
        unit = (REPO_ROOT / "systemd" / "units" / "hapax-determine.service").read_text(
            encoding="utf-8"
        )
        joined = "\n".join(
            line for line in unit.splitlines() if not line.lstrip().startswith("#")
        ).replace("\\\n", " ")
        exec_lines = [line for line in joined.splitlines() if line.strip().startswith("ExecStart=")]
        assert len(exec_lines) == 1, exec_lines
        exec_start = exec_lines[0]
        assert "scripts/hapax-determine" in exec_start
        assert "--json" in exec_start
        assert "--run-ledger" not in exec_start
        assert "--registry" not in exec_start


class TestPerProducerLock:
    """Two invokers share one cadence (timer + telemetry pull-forward); the lock
    plus in-lock re-check keeps one provider round trip per cadence window
    regardless of who fires first."""

    def test_lock_path_lives_beside_the_ledger(self, tmp_path: Path) -> None:
        ledger = tmp_path / "determine" / "runs.jsonl"
        assert det.producer_lock_path(ledger, "p1") == (
            tmp_path / "determine" / "locks" / "p1.lock"
        )

    def test_a_run_that_lands_while_waiting_for_the_lock_is_not_duplicated(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The quota telemetry writer pulls the agy producer forward ~18s before
        the determine timer fires. The late invoker must re-read the ledger
        inside the lock and skip, not run the provider round trip twice.

        Synchronization (review finding on #4665): the winner's append is
        published only AFTER the invoker is observed waiting in the lock-retry
        loop — which proves it already completed its pre-lock ledger read — so
        an implementation using only that stale pre-lock read cannot pass: it
        would see no run, deem the producer due, and mint (marker present).
        """
        marker = tmp_path / "producer-ran"
        producer_sh = tmp_path / "producer.sh"
        producer_sh.write_text(f"#!/bin/sh\ntouch {marker}\n")
        producer_sh.chmod(0o755)
        reg = _registry(tmp_path, command=[str(producer_sh)])
        ledger = tmp_path / "runs.jsonl"
        result: dict[str, int] = {}
        waiting_in_lock = threading.Event()
        real_sleep = det.time.sleep

        def _invoker() -> None:
            result["rc"] = det.main(
                [
                    "--registry",
                    str(reg),
                    "--run-ledger",
                    str(ledger),
                    "--repo-root",
                    str(tmp_path),
                    "--now",
                    det._iso(NOW),
                    "--json",
                ]
            )

        def _sleep_recording_waiter(seconds: float) -> None:
            # First retry-sleep == the invoker finished its pre-lock read and
            # failed a LOCK_NB attempt: it is provably waiting on the lock.
            waiting_in_lock.set()
            real_sleep(0.02)

        monkeypatch.setattr(det.time, "sleep", _sleep_recording_waiter)

        with det.producer_lock(ledger, "p1"):
            late = threading.Thread(target=_invoker)
            late.start()
            assert waiting_in_lock.wait(timeout=10), "invoker never reached the lock wait"
            # The concurrent winner's run lands while the late invoker is
            # blocked on the lock, exactly as an overlapping timer fire sees.
            det.append_run(
                ledger,
                {"ran_at": det._iso(NOW), "producer_id": "p1", "outcome": "produced"},
            )
        late.join(timeout=10)
        assert result["rc"] == 0
        assert not marker.exists()
        payload = json.loads(capsys.readouterr().out)
        # The skip is recorded, not inferred from the absent marker — and the
        # liveness view carries the WINNER's run (no false never_ran deficit),
        # which is the branch that silently re-opens the flap if it regresses
        # (review finding on #4665).
        assert payload["ran"] == []
        assert payload["skipped"] == [{"producer_id": "p1", "reason": "not_due"}]
        assert payload["liveness"] == []
        assert det.last_runs(ledger)["p1"]["ran_at"] == det._iso(NOW)

    def test_lock_wait_expiry_is_a_recorded_skip_not_a_hang(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A holder that outlives the bounded wait produces a lock_timeout skip
        and a clean exit — the previous unbounded flock left this invoker to be
        killed by the unit timeout instead (major finding on #4665)."""
        reg = _registry(tmp_path, command=["/bin/true"])
        ledger = tmp_path / "runs.jsonl"
        det.append_run(
            ledger,
            {
                "ran_at": det._iso(NOW - timedelta(seconds=60)),
                "producer_id": "p1",
                "outcome": "produced",
            },
        )
        result: dict[str, int] = {}
        monkeypatch.setattr(det, "LOCK_RETRY_INTERVAL_S", 0.01)

        def _invoker() -> None:
            result["rc"] = det.main(
                [
                    "--registry",
                    str(reg),
                    "--run-ledger",
                    str(ledger),
                    "--repo-root",
                    str(tmp_path),
                    "--now",
                    det._iso(NOW),
                    "--lock-wait",
                    "0.2",
                    "--json",
                ]
            )

        with det.producer_lock(ledger, "p1"):
            late = threading.Thread(target=_invoker)
            late.start()
            late.join(timeout=10)
        assert not late.is_alive()
        assert result["rc"] == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert [s["reason"] for s in payload["skipped"]] == ["lock_timeout"]
        assert payload["skipped"][0]["waited_s"] == 0.2
        assert payload["liveness"] == []

    def test_producer_lock_raises_when_the_wait_expires(self, tmp_path: Path) -> None:
        ledger = tmp_path / "runs.jsonl"
        with det.producer_lock(ledger, "p1"):
            with pytest.raises(det.ProducerLockTimeout, match="p1"):
                with det.producer_lock(ledger, "p1", wait_s=0):
                    pass


class TestExitCodes:
    def _main(self, tmp_path: Path, *extra, **over) -> int:
        reg = _registry(tmp_path, **over)
        return det.main(
            [
                "--registry",
                str(reg),
                "--run-ledger",
                str(tmp_path / "runs.jsonl"),
                "--repo-root",
                str(tmp_path),
                "--now",
                det._iso(NOW),
                "--json",
                *extra,
            ]
        )

    def test_produced_and_live_exits_zero(self, tmp_path: Path, capsys) -> None:
        assert self._main(tmp_path, command=["/bin/true"]) == 0

    def test_declined_still_exits_zero(self, tmp_path: Path, capsys) -> None:
        """Healthy bad news is not a harness failure."""
        assert self._main(tmp_path, command=["/bin/sh", "-c", "exit 3"]) == 0

    def test_producer_failure_exits_5(self, tmp_path: Path, capsys) -> None:
        assert self._main(tmp_path, command=["/bin/sh", "-c", "exit 9"]) == 5

    def test_liveness_deficit_exits_6(self, tmp_path: Path, capsys) -> None:
        assert self._main(tmp_path, "--check") == 6
