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
