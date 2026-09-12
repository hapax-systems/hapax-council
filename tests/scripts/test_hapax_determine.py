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
import os
import threading
import time
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


def _two_producer_registry(tmp_path: Path) -> Path:
    """The live registry's ordering: claude-account-live runs BEFORE
    agy-review-quota, so agy's terminal event is preceded by real pre-execution
    work its own subprocess duration does not include."""

    def _producer(pid: str) -> dict:
        return {
            "id": pid,
            "property": "account_live_quota",
            "subjects": ["some.route"],
            "command": ["/bin/true"],
            "cadence_seconds": 600,
            "evidence_ttl_seconds": 1800,
            "provenance": "mechanical",
            "success_exit_codes": [0],
            "declined_exit_codes": [3, 4],
        }

    p = tmp_path / "two-producer-registry.json"
    p.write_text(
        json.dumps(
            {
                "schema": "x",
                "producers": [
                    _producer("claude-account-live"),
                    _producer("agy-review-quota"),
                ],
            }
        )
    )
    return p


class SequenceClock:
    """Monotonic fake returning scripted values in order, holding the last.

    Lets a test script the exact elapsed profile of an invocation — lock
    waits, per-producer start/end — with no sleeping and no wall clock."""

    def __init__(self, values: list[float]) -> None:
        self._values = values
        self.calls = 0

    def __call__(self) -> float:
        value = self._values[min(self.calls, len(self._values) - 1)]
        self.calls += 1
        return value


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

    def test_unlaunchable_record_shape_is_witnessed_without_duration(self, tmp_path: Path) -> None:
        """claude-1 minor (#4665, round 8): the unlaunchable branch stamps
        completed_at but deliberately no duration_s — the producer never ran,
        so there is no producer duration to report. Pin the conservative
        asymmetry: completion reads the stamped witness directly, and the
        legacy ran_at+duration_s fallback never manufactures a later instant
        for a spawn that failed."""
        rec = det.run_producer(
            {"id": "p1", "command": [str(tmp_path / "nope")], "cadence_seconds": 60},
            now=NOW,
            repo_root=tmp_path,
            timeout=30,
        )
        assert rec["outcome"] == "unlaunchable"
        assert rec["returncode"] is None
        assert "duration_s" not in rec
        completed = det._completion_of(rec)
        assert completed is not None
        assert completed == det._parse_iso(str(rec["completed_at"]))
        # The witness lands at or after the invocation anchor it extends —
        # never before it.
        assert completed >= NOW

    def test_a_run_is_witnessed_even_when_it_produces_nothing(self, tmp_path: Path) -> None:
        """Without this, declining and never running are the same observable."""
        ledger = tmp_path / "runs.jsonl"
        det.append_run(
            ledger, {"ran_at": det._iso(NOW), "producer_id": "p1", "outcome": "declined"}
        )
        assert det.last_runs(ledger)["p1"]["outcome"] == "declined"


class TestProducerTimeoutKillsTheWholeTree:
    """codex-1 major (#4665, round 10, M1): subprocess.run's timeout killed only
    the direct child. Producers here spawn the real provider call as their own
    descendant, so the tree survived the kill, kept running after the timeout
    record released the producer lock, and a forced invocation overlapped a
    still-live provider call. The timeout path must kill the whole process
    group and reap before returning."""

    def test_timeout_kills_and_reaps_descendants_before_returning(self, tmp_path: Path) -> None:
        child_pid_file = tmp_path / "child.pid"
        rec = det.run_producer(
            {
                "id": "p1",
                "command": [
                    "/bin/sh",
                    "-c",
                    f"sleep 600 & echo $! > {child_pid_file}; sleep 600",
                ],
                "cadence_seconds": 60,
            },
            now=NOW,
            repo_root=tmp_path,
            timeout=2,
        )
        assert rec["outcome"] == "timeout"
        assert rec["returncode"] is None
        assert rec["duration_s"] >= 2.0
        assert rec["completed_at"]
        # The direct child is reaped by contract: run_producer returned, and it
        # only returns from this path after communicate() completed the wait.
        # The DESCENDANT is the regression: SIGKILL'd via the process group,
        # then reaped by init — poll for its death with a real deadline so a
        # survivor fails loudly instead of racing green.
        descendant = int(child_pid_file.read_text().strip())
        assert descendant > 1
        assert descendant != os.getpid()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                os.kill(descendant, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"descendant sleep(600) pid {descendant} survived the producer timeout")

    def test_fast_producer_completion_path_is_unchanged(self, tmp_path: Path) -> None:
        """The Popen restructure must not disturb the normal completion path:
        exit codes, stderr capture, and the stamped witnesses all keep their
        contracts."""
        rec = det.run_producer(
            {
                "id": "p1",
                "command": ["/bin/sh", "-c", "echo producer-note >&2; exit 0"],
                "cadence_seconds": 60,
                "success_exit_codes": [0],
            },
            now=NOW,
            repo_root=tmp_path,
            timeout=30,
        )
        assert rec["outcome"] == "produced"
        assert rec["returncode"] == 0
        assert rec["stderr"] == "producer-note"
        assert rec["duration_s"] is not None and rec["duration_s"] >= 0.0


class TestProducerCompletionSweepsTheGroup:
    """codex-1 major (#4665, round 11, M2): a producer that handles its OWN
    inner timeout — the agy admission producer's 240s smoke timeout inside
    this harness's 300s budget — kills its direct child, exits rc=2 through
    the ORDINARY completion path, and can leave provider descendants alive
    when the terminal record publishes and the lock releases. Normal
    completion must sweep the whole process group too, not just the timeout
    path."""

    def test_producer_handled_failure_leaves_no_descendant(self, tmp_path: Path) -> None:
        child_pid_file = tmp_path / "child.pid"
        rec = det.run_producer(
            {
                "id": "p1",
                # The producer-handled inner-timeout shape (codex's scaled
                # repro returned failed/rc=2 in 0.22s with the descendant
                # still running): the producer exits on its own, the
                # descendant holds NO pipe fds, and only the group sweep can
                # reach it.
                "command": [
                    "/bin/sh",
                    "-c",
                    (f"sleep 600 >/dev/null 2>&1 </dev/null & echo $! > {child_pid_file}; exit 2"),
                ],
                "cadence_seconds": 60,
            },
            now=NOW,
            repo_root=tmp_path,
            timeout=30,
        )
        assert rec["outcome"] == "failed"
        assert rec["returncode"] == 2
        descendant = int(child_pid_file.read_text().strip())
        assert descendant > 1
        assert descendant != os.getpid()
        # The sweep must have SIGKILL'd the surviving group member before the
        # record published: a live descendant here is a provider call that
        # outlived the producer lock.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                os.kill(descendant, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"descendant sleep(600) pid {descendant} survived the producer's own exit")

    def test_killpg_permission_error_on_normal_completion_is_a_named_bounded_leak(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """glm-1 minor (#4665, round 10) + claude-1 minor (round 10): when the
        group is not ours to signal, the sweep cannot close the leak — the
        record must NAME it instead of hiding it."""

        def denied_killpg(pgid, sig):
            raise PermissionError(f"not our group (test), pgid={pgid}")

        monkeypatch.setattr(os, "killpg", denied_killpg)
        rec = det.run_producer(
            {
                "id": "p1",
                "command": ["/bin/sh", "-c", "exit 0"],
                "cadence_seconds": 60,
                "success_exit_codes": [0],
            },
            now=NOW,
            repo_root=tmp_path,
            timeout=30,
        )
        assert rec["outcome"] == "produced"
        assert rec["returncode"] == 0
        assert rec["group_sweep"] == "permission-denied-bounded-leak"

    def test_killpg_permission_error_on_timeout_still_reaps_the_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The timeout path's PermissionError fallback (proc.kill) stays
        functional: untested branches run precisely when the system is
        misbehaving, and a crash there would strand the lock holder
        (claude-1 minor, #4665 round 10)."""

        def denied_killpg(pgid, sig):
            raise PermissionError("not our group (test)")

        monkeypatch.setattr(os, "killpg", denied_killpg)
        rec = det.run_producer(
            {
                "id": "p1",
                "command": ["/bin/sh", "-c", "sleep 600"],
                "cadence_seconds": 60,
            },
            now=NOW,
            repo_root=tmp_path,
            timeout=2,
        )
        assert rec["outcome"] == "timeout"
        assert rec["returncode"] is None
        # run_producer returned through the fallback kill + reap, so the
        # direct child was waited on; the fallback branch executed without
        # raising (the run completing IS the reap proof).


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


class TestForceFreshnessEscape:
    """``--force`` is the freshness-consumer escape hatch the telemetry writer's
    pull-forward uses (critical finding on #4665, round 2): a fixed due-window
    leaves a 560s-old admission unpulled at drifted timer phases, so the CALLER
    measures the freshness the next write needs and forces the mint NOW. The
    harness's job is to honor force immediately — no sleeping into a cadence
    boundary the receipt cannot wait for — while the run-ledger append keeps
    the later invokers honest."""

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

    def test_force_mints_now_despite_not_due(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The reviewer's exact repro age: 560s old on a 600s cadence — not_due to
        the cadence gate — yet the receipt expires before the consumer's next
        write. Force must run immediately and stamp the mint at now."""
        slept: list[float] = []
        monkeypatch.setattr(det.time, "sleep", lambda s: slept.append(s))
        ctx = self._main(tmp_path, 560, "--force")
        assert not any(s > 0.1 for s in slept)
        assert ctx["marker"].exists()
        payload = json.loads(capsys.readouterr().out)
        assert [r["producer_id"] for r in payload["ran"]] == ["p1"]
        assert payload["ran"][0]["ran_at"] == det._iso(NOW)
        assert payload["now"] == det._iso(NOW)
        assert payload["skipped"] == []

    def test_post_force_invoker_on_the_same_ledger_skips(self, tmp_path: Path, capsys) -> None:
        """One run per cadence window survives force: a later plain invoker
        re-reads the forced mint's fresh ran_at and skips as not_due."""
        ctx = self._main(tmp_path, 560, "--force")
        assert ctx["marker"].exists()
        capsys.readouterr()  # consume the forced run's JSON before the second invocation
        marker2 = tmp_path / "second-ran"
        producer2 = tmp_path / "producer2.sh"
        producer2.write_text(f"#!/bin/sh\ntouch {marker2}\n")
        producer2.chmod(0o755)
        reg = _registry(tmp_path, command=[str(producer2)])
        rc = det.main(
            [
                "--registry",
                str(reg),
                "--run-ledger",
                str(ctx["ledger"]),
                "--repo-root",
                str(tmp_path),
                "--now",
                det._iso(NOW + timedelta(seconds=30)),
                "--json",
            ]
        )
        assert rc == 0
        assert not marker2.exists()
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert payload["skipped"] == [{"producer_id": "p1", "reason": "not_due"}]


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

    def test_a_forced_waiter_defers_to_a_winner_that_minted_during_the_wait(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """M1 (#4665, round 3): the force decision is computed BEFORE the lock
        wait. A winner that completed while the forced invoker waited has
        already minted this window — the in-lock revalidation must supersede
        the force (skip, no append, no producer run) instead of letting
        `--force` bypass the due check and duplicate the run."""
        marker = tmp_path / "producer-ran"
        producer_sh = tmp_path / "producer.sh"
        producer_sh.write_text(f"#!/bin/sh\ntouch {marker}\n")
        producer_sh.chmod(0o755)
        reg = _registry(tmp_path, command=[str(producer_sh)])
        ledger = tmp_path / "runs.jsonl"
        justified_at = NOW - timedelta(seconds=30)
        winner_ran_at = NOW - timedelta(seconds=10)
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
                    "--force",
                    "--force-justified-at",
                    det._iso(justified_at),
                    "--lock-wait",
                    "5",
                    "--json",
                ]
            )

        def _sleep_recording_waiter(seconds: float) -> None:
            waiting_in_lock.set()
            real_sleep(0.02)

        monkeypatch.setattr(det.time, "sleep", _sleep_recording_waiter)

        with det.producer_lock(ledger, "p1"):
            late = threading.Thread(target=_invoker)
            late.start()
            assert waiting_in_lock.wait(timeout=10), "invoker never reached the lock wait"
            # The winner's run completed after the force decision — while this
            # forced invoker was still blocked on the lock.
            det.append_run(
                ledger,
                {
                    "ran_at": det._iso(winner_ran_at),
                    "producer_id": "p1",
                    "outcome": "produced",
                },
            )
        late.join(timeout=10)
        assert result["rc"] == 0
        assert not marker.exists()
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert len(payload["skipped"]) == 1
        skip = payload["skipped"][0]
        assert skip["producer_id"] == "p1"
        assert skip["reason"] == "force_superseded"
        assert det._iso(winner_ran_at) in skip["detail"]
        # The waiter must not append: the ledger still holds exactly the
        # winner's run — one run per window even when force crosses locks.
        assert det.last_runs(ledger)["p1"]["ran_at"] == det._iso(winner_ran_at)

    def test_a_forced_waiter_defers_to_a_winner_that_started_before_the_decision(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """C1 (#4665, round 4): `ran_at` is the invocation anchor, so a winner
        that STARTED before the forced waiter's decision and COMPLETED while
        it waited compares as older than the decision on `ran_at` alone — and
        the round-4 code duplicated it. The completion witness
        (`completed_at`) is what supersedes: the run finished after the
        justification, so this window is already minted."""
        marker = tmp_path / "producer-ran"
        producer_sh = tmp_path / "producer.sh"
        producer_sh.write_text(f"#!/bin/sh\ntouch {marker}\n")
        producer_sh.chmod(0o755)
        reg = _registry(tmp_path, command=[str(producer_sh)])
        ledger = tmp_path / "runs.jsonl"
        justified_at = NOW - timedelta(seconds=30)
        winner_ran_at = NOW - timedelta(seconds=40)  # started BEFORE the decision
        winner_completed_at = NOW - timedelta(seconds=10)  # finished during the wait
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
                    "--force",
                    "--force-justified-at",
                    det._iso(justified_at),
                    "--lock-wait",
                    "5",
                    "--json",
                ]
            )

        def _sleep_recording_waiter(seconds: float) -> None:
            waiting_in_lock.set()
            real_sleep(0.02)

        monkeypatch.setattr(det.time, "sleep", _sleep_recording_waiter)

        with det.producer_lock(ledger, "p1"):
            late = threading.Thread(target=_invoker)
            late.start()
            assert waiting_in_lock.wait(timeout=10), "invoker never reached the lock wait"
            det.append_run(
                ledger,
                {
                    "ran_at": det._iso(winner_ran_at),
                    "completed_at": det._iso(winner_completed_at),
                    "producer_id": "p1",
                    "outcome": "produced",
                },
            )
        late.join(timeout=10)
        assert result["rc"] == 0
        assert not marker.exists()
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert len(payload["skipped"]) == 1
        skip = payload["skipped"][0]
        assert skip["reason"] == "force_superseded"
        assert det._iso(winner_completed_at) in skip["detail"]
        # One run per window: the ledger still holds exactly the winner's row.
        rows = ledger.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 1
        assert det.last_runs(ledger)["p1"]["ran_at"] == det._iso(winner_ran_at)

    def test_legacy_winner_rows_supersede_via_ran_at_plus_duration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Rows predating the `completed_at` witness (rounds <= 4 of #4665)
        must still supersede correctly: completion = ran_at + duration_s. The
        negative leg proves the comparison is on COMPLETION, not ran_at alone
        in either direction: a legacy row whose derived completion precedes
        the decision does NOT supersede, and the force runs."""
        marker = tmp_path / "producer-ran"
        producer_sh = tmp_path / "producer.sh"
        producer_sh.write_text(f"#!/bin/sh\ntouch {marker}\n")
        producer_sh.chmod(0o755)
        reg = _registry(tmp_path, command=[str(producer_sh)])
        argv = [
            "--registry",
            str(reg),
            "--run-ledger",
            str(reg.parent / "runs.jsonl"),
            "--repo-root",
            str(tmp_path),
            "--now",
            det._iso(NOW),
            "--force",
            "--force-justified-at",
            det._iso(NOW - timedelta(seconds=30)),
            "--json",
        ]
        ledger = tmp_path / "runs.jsonl"

        # Legacy row completed BEFORE the decision: NOW-40 + 5s = NOW-35,
        # older than the NOW-30 justification → the window is not minted and
        # the force must run the producer.
        det.append_run(
            ledger,
            {
                "ran_at": det._iso(NOW - timedelta(seconds=40)),
                "duration_s": 5.0,
                "producer_id": "p1",
                "outcome": "produced",
            },
        )
        assert det.main(argv) == 0
        assert marker.exists()
        capsys.readouterr()

        # Legacy row completed AFTER the decision: NOW-40 + 35s = NOW-5,
        # newer than the NOW-30 justification → superseded; no producer run.
        ledger.unlink()
        marker.unlink()
        det.append_run(
            ledger,
            {
                "ran_at": det._iso(NOW - timedelta(seconds=40)),
                "duration_s": 35.0,
                "producer_id": "p1",
                "outcome": "produced",
            },
        )
        assert det.main(argv) == 0
        assert not marker.exists()
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert len(payload["skipped"]) == 1
        assert payload["skipped"][0]["reason"] == "force_superseded"
        rows = ledger.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 1  # the superseded waiter appended nothing

    def test_same_second_completion_supersedes_a_whole_second_decision(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """C1 (#4665, round 7): whole-second truncation made a winner that
        finished 0.8s AFTER the decision compare EQUAL to it, fail the strict
        comparison, and get duplicated by the forced waiter. The completion
        witness now carries sub-second precision, and a completion landing
        inside the decision's own second supersedes conservatively — a
        duplicate forced run is a provider round-trip nothing undoes, while a
        skipped-but-needed run self-heals at the next cadence window."""
        marker = tmp_path / "producer-ran"
        producer_sh = tmp_path / "producer.sh"
        producer_sh.write_text(f"#!/bin/sh\ntouch {marker}\n")
        producer_sh.chmod(0o755)
        reg = _registry(tmp_path, command=[str(producer_sh)])
        ledger = tmp_path / "runs.jsonl"
        argv = [
            "--registry",
            str(reg),
            "--run-ledger",
            str(ledger),
            "--repo-root",
            str(tmp_path),
            "--now",
            det._iso(NOW),
            "--force",
            "--force-justified-at",
            det._iso(NOW),
            "--json",
        ]

        # Sub-second leg: the winner completed 0.8s into the decision's
        # second — strictly after the decision stamp, invisible to a
        # whole-second comparison. It must supersede; the producer must not
        # run; the skip detail must carry the precise instant.
        winner_completed = NOW + timedelta(milliseconds=800)
        det.append_run(
            ledger,
            {
                "ran_at": det._iso(NOW - timedelta(seconds=30)),
                "completed_at": det._iso_precise(winner_completed),
                "producer_id": "p1",
                "outcome": "produced",
            },
        )
        assert det.main(argv) == 0
        assert not marker.exists()
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert payload["skipped"][0]["reason"] == "force_superseded"
        assert det._iso_precise(winner_completed) in payload["skipped"][0]["detail"]
        rows = ledger.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 1  # the superseded waiter appended nothing

        # Legacy tie leg: a whole-second row completing exactly ON the
        # decision second is ambiguous in both directions; it resolves toward
        # supersession for the same conservative reason.
        ledger.unlink()
        det.append_run(
            ledger,
            {
                "ran_at": det._iso(NOW - timedelta(seconds=30)),
                "completed_at": det._iso(NOW),
                "producer_id": "p1",
                "outcome": "produced",
            },
        )
        assert det.main(argv) == 0
        assert not marker.exists()
        assert json.loads(capsys.readouterr().out)["ran"] == []

        # Control leg: a completion in the second BEFORE the decision still
        # runs — the conservative tie rule must not swallow real deficits.
        ledger.unlink()
        det.append_run(
            ledger,
            {
                "ran_at": det._iso(NOW - timedelta(seconds=30)),
                "completed_at": det._iso(NOW - timedelta(seconds=1)),
                "producer_id": "p1",
                "outcome": "produced",
            },
        )
        assert det.main(argv) == 0
        assert marker.exists()

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


class TestInvocationWideCompletionWitness:
    """codex-1 round-5 C1: ``completed_at`` is the invocation anchor plus the
    invocation-wide monotonic elapsed at the terminal event — never the anchor
    plus the producer's OWN duration, which undercounts the real completion
    instant by every second of earlier producers and lock waits and breaks the
    forced waiter's supersession comparison exactly there."""

    def _run_two_producers(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys,
        clock_values: list[float],
    ) -> tuple[Path, Path, dict]:
        reg = _two_producer_registry(tmp_path)
        ledger = tmp_path / "runs.jsonl"
        monkeypatch.setattr(det, "monotonic_clock", SequenceClock(clock_values))
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
            ]
        )
        assert rc == 0
        return reg, ledger, json.loads(capsys.readouterr().out)

    def test_the_second_producers_completion_includes_the_first_ones_elapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The registry runs claude-account-live before agy-review-quota. With
        claude occupying 30→50 and agy 100→120 on the monotonic clock, agy's
        own subprocess ran 20s — but it COMPLETED 120s after the invocation
        anchor, and only the invocation-wide stamp records that. The ledger
        row must carry the same witness: it is what a later forced invoker's
        supersession comparison reads."""
        _, ledger, payload = self._run_two_producers(
            tmp_path, monkeypatch, capsys, [0, 0, 30, 50, 60, 100, 120]
        )
        assert [r["producer_id"] for r in payload["ran"]] == [
            "claude-account-live",
            "agy-review-quota",
        ]
        claude, agy = payload["ran"]
        assert claude["ran_at"] == det._iso(NOW)
        assert agy["ran_at"] == det._iso(NOW)
        assert claude["duration_s"] == 20.0
        assert agy["duration_s"] == 20.0
        assert claude["completed_at"] == det._iso(NOW + timedelta(seconds=50))
        # NOT now+20: the anchor-plus-own-duration stamp that round 5 removed.
        assert agy["completed_at"] == det._iso(NOW + timedelta(seconds=120))
        rows = [
            json.loads(line) for line in ledger.read_text(encoding="utf-8").strip().splitlines()
        ]
        assert [r["producer_id"] for r in rows] == ["claude-account-live", "agy-review-quota"]
        assert rows[0]["completed_at"] == det._iso(NOW + timedelta(seconds=50))
        assert rows[1]["completed_at"] == det._iso(NOW + timedelta(seconds=120))

    def test_the_completion_witness_preserves_sub_second_precision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The witness must survive truncation, not just include the elapsed:
        the supersession comparison runs against a whole-second force
        decision, so a completion 1.3s after the invocation anchor truncated
        back onto the anchor's second would tie the decision and duplicate
        (codex-1 round-7 C1). Fractional digits appear only when nonzero, so
        whole-second stamps keep their exact prior wire form."""
        reg = _registry(tmp_path)  # /bin/true, success exit 0
        ledger = tmp_path / "runs.jsonl"
        monkeypatch.setattr(det, "monotonic_clock", SequenceClock([0, 0, 0.5, 1.3]))
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
            ]
        )
        assert rc == 0
        (raw_row,) = ledger.read_text(encoding="utf-8").strip().splitlines()
        row = json.loads(raw_row)
        expected = det._iso_precise(NOW + timedelta(seconds=1.3))
        assert expected.endswith(".300Z")
        assert row["completed_at"] == expected
        assert det._parse_iso(row["completed_at"]) == NOW + timedelta(seconds=1.3)

    def test_a_forced_waiter_justified_mid_invocation_defers_to_the_second_producer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The C1 counterexample's consumer, generated through main(): a
        forced waiter justified at NOW+110 must defer to the agy run that
        COMPLETED at NOW+120 — a supersession that only holds because the
        completion witness includes the first producer's elapsed. Under the
        anchor-plus-own-duration stamp the agy row read NOW+20 and this waiter
        would have minted a duplicate window."""
        reg, ledger, _ = self._run_two_producers(
            tmp_path, monkeypatch, capsys, [0, 0, 30, 50, 60, 100, 120]
        )
        assert len(ledger.read_text(encoding="utf-8").strip().splitlines()) == 2
        monkeypatch.setattr(det, "monotonic_clock", SequenceClock([0, 0]))
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
                "--producer",
                "agy-review-quota",
                "--force",
                "--force-justified-at",
                det._iso(NOW + timedelta(seconds=110)),
                "--json",
            ]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ran"] == []
        assert [s["reason"] for s in payload["skipped"]] == ["force_superseded"]
        # The superseded waiter appended nothing: the ledger still holds
        # exactly the two runs the first invocation generated.
        rows_after = ledger.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows_after) == 2


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

    def test_invalid_force_justified_at_exits_2(self, tmp_path: Path) -> None:
        """A malformed force-decision instant must fail loudly before any
        producer runs, not fall back to an unvalidated force."""
        assert (
            self._main(
                tmp_path,
                "--force",
                "--force-justified-at",
                "not-a-timestamp",
            )
            == 2
        )
