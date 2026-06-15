"""Turn-timing queryable surface — audit-w2-latency-emitter-20260611.

CASE-VOICE-FOUNDATION-20260610, audit v2 gate (i): TurnBudget TIMING
receipts extend past `last_turn_timing` (one record) into a bounded JSONL
ring so p50/p90 are computable over a 20-turn window.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion import turn_timing_log as ttl
from agents.hapax_daimonion.voice_output_witness import (
    read_voice_output_witness,
    record_turn_timing,
)

NOW = 1_800_000_000.0


def _entry(
    *,
    turn: int,
    total_ms: float,
    kind: str = "interactive",
    overrun: bool = False,
    legs: dict[str, float] | None = None,
) -> dict:
    return {
        "ts": "2027-01-15T08:00:00Z",
        "kind": kind,
        "turn": turn,
        "legs": legs if legs is not None else {"stt": 80.0, "llm_ttft": 400.0},
        "notes": {"outcome": "spoken"},
        "total_ms": total_ms,
        "budget_ms": 90_000.0,
        "overrun": overrun,
    }


class TestAppendAndRead:
    def test_append_then_read_round_trips_one_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        ttl.append_turn_timing(_entry(turn=1, total_ms=1200.0), path=path)

        entries = ttl.read_turn_timings(path=path)

        assert len(entries) == 1
        assert entries[0]["turn"] == 1
        assert entries[0]["total_ms"] == 1200.0

    def test_ring_is_bounded_keeping_newest(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        for turn in range(1, 8):
            ttl.append_turn_timing(
                _entry(turn=turn, total_ms=float(turn)), path=path, max_entries=5
            )

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        turns = [json.loads(line)["turn"] for line in lines]
        assert turns == [3, 4, 5, 6, 7]

    def test_read_returns_last_window_newest_last(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        for turn in range(1, 31):
            ttl.append_turn_timing(_entry(turn=turn, total_ms=float(turn)), path=path)

        entries = ttl.read_turn_timings(window=20, path=path)

        assert [e["turn"] for e in entries] == list(range(11, 31))

    def test_read_skips_malformed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        ttl.append_turn_timing(_entry(turn=1, total_ms=100.0), path=path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("not json\n")
            fh.write('["not", "a", "dict"]\n')
        ttl.append_turn_timing(_entry(turn=2, total_ms=200.0), path=path)

        entries = ttl.read_turn_timings(path=path)

        assert [e["turn"] for e in entries] == [1, 2]

    def test_read_filters_by_kind_before_windowing(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        ttl.append_turn_timing(_entry(turn=1, total_ms=100.0, kind="interactive"), path=path)
        ttl.append_turn_timing(_entry(turn=2, total_ms=200.0, kind="spontaneous"), path=path)
        ttl.append_turn_timing(_entry(turn=3, total_ms=300.0, kind="interactive"), path=path)

        entries = ttl.read_turn_timings(kind="interactive", path=path)

        assert [e["turn"] for e in entries] == [1, 3]

    def test_read_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert ttl.read_turn_timings(path=tmp_path / "absent.jsonl") == []


class TestLatencyStats:
    def test_p50_p90_over_twenty_turn_window(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        # totals 100..2000 in steps of 100 — nearest-rank: p50=1000, p90=1800
        for turn in range(1, 21):
            ttl.append_turn_timing(_entry(turn=turn, total_ms=turn * 100.0), path=path)

        stats = ttl.turn_latency_stats(window=20, path=path)

        assert stats.count == 20
        assert stats.window == 20
        assert stats.p50_ms == 1000.0
        assert stats.p90_ms == 1800.0
        assert stats.max_ms == 2000.0

    def test_window_excludes_older_turns(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        ttl.append_turn_timing(_entry(turn=0, total_ms=999_999.0), path=path)
        for turn in range(1, 21):
            ttl.append_turn_timing(_entry(turn=turn, total_ms=turn * 100.0), path=path)

        stats = ttl.turn_latency_stats(window=20, path=path)

        assert stats.count == 20
        assert stats.max_ms == 2000.0  # the 999s outlier fell outside the window

    def test_empty_surface_yields_count_zero_and_none_percentiles(self, tmp_path: Path) -> None:
        stats = ttl.turn_latency_stats(path=tmp_path / "absent.jsonl")

        assert stats.count == 0
        assert stats.p50_ms is None
        assert stats.p90_ms is None
        assert stats.max_ms is None
        assert stats.overrun_count == 0

    def test_overruns_are_counted(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        ttl.append_turn_timing(_entry(turn=1, total_ms=100.0), path=path)
        ttl.append_turn_timing(_entry(turn=2, total_ms=95_000.0, overrun=True), path=path)

        stats = ttl.turn_latency_stats(path=path)

        assert stats.overrun_count == 1

    def test_per_leg_percentiles(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        ttl.append_turn_timing(
            _entry(turn=1, total_ms=500.0, legs={"stt": 100.0, "synth": 300.0}), path=path
        )
        ttl.append_turn_timing(
            _entry(turn=2, total_ms=700.0, legs={"stt": 200.0, "synth": 400.0}), path=path
        )

        stats = ttl.turn_latency_stats(path=path)

        assert stats.legs["stt"].p50_ms == 100.0
        assert stats.legs["stt"].p90_ms == 200.0
        assert stats.legs["synth"].p90_ms == 400.0

    def test_kind_filter_scopes_stats(self, tmp_path: Path) -> None:
        path = tmp_path / "turn-timings.jsonl"
        ttl.append_turn_timing(_entry(turn=1, total_ms=100.0, kind="interactive"), path=path)
        ttl.append_turn_timing(_entry(turn=2, total_ms=9_000.0, kind="spontaneous"), path=path)

        stats = ttl.turn_latency_stats(kind="interactive", path=path)

        assert stats.count == 1
        assert stats.p90_ms == 100.0
        assert stats.kind == "interactive"


class TestWitnessSeam:
    def test_record_turn_timing_appends_to_sibling_ring(self, tmp_path: Path) -> None:
        witness_path = tmp_path / "voice-output-witness.json"

        for turn in (1, 2):
            record_turn_timing(
                kind="interactive",
                turn=turn,
                legs={"stt": 80.0},
                notes={"outcome": "spoken"},
                total_ms=turn * 1000.0,
                budget_ms=90_000.0,
                overrun=False,
                path=witness_path,
                now=NOW,
            )

        ring = tmp_path / "turn-timings.jsonl"
        entries = ttl.read_turn_timings(path=ring)
        assert [e["turn"] for e in entries] == [1, 2]
        assert entries[0]["total_ms"] == 1000.0

        witness = read_voice_output_witness(witness_path, now=NOW)
        assert witness.last_turn_timing is not None
        assert witness.last_turn_timing["turn"] == 2

    def test_ring_failure_does_not_break_witness_write(self, tmp_path: Path, monkeypatch) -> None:
        witness_path = tmp_path / "voice-output-witness.json"

        def _boom(*args, **kwargs):
            raise OSError("ring write failed")

        monkeypatch.setattr("agents.hapax_daimonion.turn_timing_log.append_turn_timing", _boom)

        witness = record_turn_timing(
            kind="interactive",
            turn=7,
            legs={},
            notes={},
            total_ms=1234.0,
            budget_ms=90_000.0,
            overrun=False,
            path=witness_path,
            now=NOW,
        )

        assert witness.last_turn_timing is not None
        assert witness.last_turn_timing["turn"] == 7

    def test_stats_computable_from_witness_emissions(self, tmp_path: Path) -> None:
        """Exit predicate: p50/p90 over a 20-turn window from emitted receipts."""
        witness_path = tmp_path / "voice-output-witness.json"
        for turn in range(1, 21):
            record_turn_timing(
                kind="interactive",
                turn=turn,
                legs={"stt": 50.0 + turn},
                notes={},
                total_ms=turn * 100.0,
                budget_ms=90_000.0,
                overrun=False,
                path=witness_path,
                now=NOW,
            )

        stats = ttl.turn_latency_stats(window=20, path=tmp_path / "turn-timings.jsonl")

        assert stats.count == 20
        assert stats.p50_ms == 1000.0
        assert stats.p90_ms == 1800.0


class TestProbeMain:
    def test_main_prints_stats_json(self, tmp_path: Path, capsys) -> None:
        path = tmp_path / "turn-timings.jsonl"
        ttl.append_turn_timing(_entry(turn=1, total_ms=100.0), path=path)

        rc = ttl.main(["--path", str(path), "--window", "20"])

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["count"] == 1
        assert payload["p50_ms"] == 100.0
