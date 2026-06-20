"""Tests for the seg-prep producer-DV reader (the SCED A0 baseline read side)."""

from __future__ import annotations

import json
from pathlib import Path

from shared import segment_prep_dv_reader as reader


def _row(
    programme_id: str,
    mean_score: float | None,
    criterion: float | None,
    terminal_status: str,
    ledgered_at: str,
    *,
    coherence: dict | None = None,
) -> dict:
    """A ledger row matching daily_segment_prep._append_council_decisions_ledger."""
    if coherence is None:
        coherence = {"check": "coherence"}
        if mean_score is not None:
            coherence["mean_score"] = mean_score
        if criterion is not None:
            coherence["criterion"] = criterion
    return {
        "schema_version": 1,
        "record_type": "council_decisions_ledger_entry",
        "ledgered_at": ledgered_at,
        "programme_id": programme_id,
        "terminal_status": terminal_status,
        "council_decisions": {"coherence": coherence},
    }


def _s2_row(
    programme_id: str,
    criterion: float | None,
    accepted: bool | str,
    ledgered_at: str,
    *,
    reason: str = "reason",
    role: str = "tier_list",
    topic: str = "topic",
) -> dict:
    return {
        "schema_version": 1,
        "record_type": reader.S2_COMPOSABILITY_LEDGER_RECORD_TYPE,
        "ledgered_at": ledgered_at,
        "programme_id": programme_id,
        "terminal": accepted is False,
        "terminal_status": "s2_composable" if accepted is True else "no_candidate",
        "terminal_reason": None if accepted is True else "uncomposable_topic_type",
        "producer_gate": {
            "accepted": accepted,
            "criterion": criterion,
            "gate": reader.S2_COMPOSABILITY_GATE_NAME,
            "reason": reason,
            "role": role,
            "segment_beats": ["a", "b"],
            "topic": topic,
        },
    }


def _write_ledger(base: Path, date: str, rows: list) -> Path:
    d = base / date
    d.mkdir(parents=True, exist_ok=True)
    path = d / reader.COUNCIL_DECISIONS_LEDGER_FILENAME
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            line = r if isinstance(r, str) else json.dumps(r, sort_keys=True)
            fh.write(line + "\n")
    return path


def test_reads_observations_and_reconstructs_released(tmp_path: Path) -> None:
    base = tmp_path / "segment-prep"
    _write_ledger(
        base,
        "2026-06-16",
        [
            _row("prog-a", 4.0, 3.0, "released", "2026-06-16T04:00:00Z"),
            _row("prog-b", 2.0, 3.0, "refused_no_release", "2026-06-16T04:01:00Z"),
            _row("prog-c", 2.8, 3.0, "low_coherence_no_release", "2026-06-16T04:02:00Z"),
        ],
    )

    obs = reader.read_producer_observations(base)
    assert [o.programme_id for o in obs] == ["prog-a", "prog-b", "prog-c"]
    assert [o.mean_score for o in obs] == [4.0, 2.0, 2.8]
    assert [o.criterion for o in obs] == [3.0, 3.0, 3.0]
    # released? is reconstructed solely from terminal_status == "released".
    assert [o.released for o in obs] == [True, False, False]


def test_summarize_phases_groups_by_criterion_and_orders_by_time(tmp_path: Path) -> None:
    base = tmp_path / "segment-prep"
    _write_ledger(
        base,
        "2026-06-16",
        [
            # phase C_k=3.5 written out of chronological order on purpose
            _row("p2", 4.2, 3.5, "released", "2026-06-16T05:00:00Z"),
            _row("p1", 3.8, 3.5, "released", "2026-06-16T04:00:00Z"),
            # phase C_k=3.0
            _row("p3", 3.0, 3.0, "low_coherence_no_release", "2026-06-16T04:30:00Z"),
            _row("p4", 4.0, 3.0, "released", "2026-06-16T04:31:00Z"),
        ],
    )

    phases = reader.summarize_phases(reader.read_producer_observations(base))
    # ascending C_k (the ratchet direction)
    assert [p.criterion for p in phases] == [3.0, 3.5]
    p30, p35 = phases
    assert p30.n == 2 and p30.released == 1 and p30.released_fraction == 0.5
    assert p30.mean_pre_gate == 3.5
    # within-phase scores ordered by ledgered_at, not file order
    assert p35.pre_gate_scores == [3.8, 4.2]
    assert p35.released_fraction == 1.0


def test_skips_rows_without_a_pre_gate_score(tmp_path: Path) -> None:
    base = tmp_path / "segment-prep"
    unavailable = _row(
        "u",
        None,
        3.0,
        "refused_no_release",
        "t",
        coherence={"check": "coherence", "convergence_status": "unavailable", "criterion": 3.0},
    )
    no_coherence = {
        "council_decisions": {"disconfirmation": {"x": 1}},
        "programme_id": "n",
        "terminal_status": "released",
    }
    bad_criterion = _row("bc", 4.0, None, "released", "t")
    _write_ledger(
        base,
        "2026-06-16",
        [
            "{ not valid json",  # malformed line
            json.dumps(["not", "a", "dict"]),  # non-dict row
            json.dumps(unavailable),  # criterion but no mean_score
            json.dumps(no_coherence),  # no coherence block
            json.dumps(bad_criterion),  # mean_score but no criterion
            _s2_row("s2", 3.0, False, "2026-06-16T03:59:00Z"),  # non-numeric S2 row
            _row("good", 3.6, 3.0, "released", "2026-06-16T04:00:00Z"),
        ],
    )

    obs = reader.read_producer_observations(base)
    assert [o.programme_id for o in obs] == ["good"]


def test_reads_and_summarizes_s2_composability_attempts(tmp_path: Path) -> None:
    base = tmp_path / "segment-prep"
    _write_ledger(
        base,
        "2026-06-16",
        [
            _row("scored", 4.0, 3.0, "released", "2026-06-16T04:00:00Z"),
            _s2_row(
                "reject-a",
                3.0,
                False,
                "2026-06-16T04:01:00Z",
                reason="un-composable parallel_list",
                role="tier_list",
                topic="ranked failures",
            ),
            _s2_row("accept-a", 3.0, True, "2026-06-16T04:02:00Z"),
            _s2_row("accept-b", 3.5, True, "2026-06-16T04:03:00Z"),
            _s2_row("bad-accepted", 3.5, "false", "2026-06-16T04:04:00Z"),
            _s2_row("bad-criterion", None, False, "2026-06-16T04:05:00Z"),
        ],
    )

    attempts = reader.read_s2_composability_attempts(base)

    assert [attempt.programme_id for attempt in attempts] == ["reject-a", "accept-a", "accept-b"]
    assert attempts[0].criterion == 3.0
    assert attempts[0].accepted is False
    assert attempts[0].terminal is True
    assert attempts[0].terminal_status == "no_candidate"
    assert attempts[0].terminal_reason == "uncomposable_topic_type"
    assert attempts[0].role == "tier_list"
    assert attempts[0].topic == "ranked failures"
    assert attempts[0].reason == "un-composable parallel_list"

    summaries = reader.summarize_s2_composability(attempts)
    assert [(s.criterion, s.attempts, s.accepted, s.rejected) for s in summaries] == [
        (3.0, 2, 1, 1),
        (3.5, 1, 1, 0),
    ]
    assert summaries[0].rejected_fraction == 0.5
    assert summaries[1].rejected_fraction == 0.0


def test_baseline_intervention_scores_feed_baseline_corrected_tau(tmp_path: Path) -> None:
    from agents.hapax_daimonion import stats

    base = tmp_path / "segment-prep"
    # baseline phase (C_k 3.0) low producer means; intervention phase (C_k 3.5) higher
    # → curriculum signal (producer distribution rises) → positive BCTau.
    baseline_rows = [
        _row(f"b{i}", v, 3.0, "released", f"2026-06-16T04:0{i}:00Z")
        for i, v in enumerate([2.8, 3.0, 2.9, 3.1])
    ]
    intervention_rows = [
        _row(f"i{i}", v, 3.5, "released", f"2026-06-16T05:0{i}:00Z")
        for i, v in enumerate([4.2, 4.0, 4.4, 4.1])
    ]
    _write_ledger(base, "2026-06-16", baseline_rows + intervention_rows)

    observations = reader.read_producer_observations(base)
    bl, iv = reader.baseline_intervention_scores(
        observations, baseline_criterion=3.0, intervention_criterion=3.5
    )
    assert bl == [2.8, 3.0, 2.9, 3.1]
    assert iv == [4.2, 4.0, 4.4, 4.1]

    result = stats.baseline_corrected_tau(bl, iv)
    assert result["n_baseline"] == 4
    assert result["n_intervention"] == 4
    # intervention strictly dominates baseline → non-overlap tau is strongly positive
    assert result["tau"] > 0.5


def test_globs_across_date_dirs_and_honors_prep_dir_override(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "custom-prep"
    _write_ledger(base, "2026-06-15", [_row("d1", 3.2, 3.0, "released", "2026-06-15T04:00:00Z")])
    _write_ledger(base, "2026-06-16", [_row("d2", 3.4, 3.0, "released", "2026-06-16T04:00:00Z")])

    # explicit base
    assert {o.programme_id for o in reader.read_producer_observations(base)} == {"d1", "d2"}

    # env override resolves the SAME base when no arg is passed
    monkeypatch.setenv("HAPAX_SEGMENT_PREP_DIR", str(base))
    assert reader.default_prep_base() == base
    assert {o.programme_id for o in reader.read_producer_observations()} == {"d1", "d2"}


def test_missing_base_is_empty_not_error(tmp_path: Path) -> None:
    assert reader.read_producer_observations(tmp_path / "does-not-exist") == []
    assert reader.summarize_phases([]) == []


def test_cli_reports_phase_summary_and_bctau(tmp_path: Path, capsys) -> None:
    base = tmp_path / "segment-prep"
    rows = [
        _row(f"b{i}", v, 3.0, "released", f"2026-06-16T04:0{i}:00Z")
        for i, v in enumerate([2.8, 3.0, 2.9, 3.1])
    ] + [
        _row(f"i{i}", v, 3.5, "released", f"2026-06-16T05:0{i}:00Z")
        for i, v in enumerate([4.2, 4.0, 4.4, 4.1])
    ]
    _write_ledger(base, "2026-06-16", rows)
    _write_ledger(
        base,
        "2026-06-16",
        [
            _s2_row("s2-a", 3.0, False, "2026-06-16T03:59:00Z"),
            _s2_row("s2-b", 3.5, True, "2026-06-16T04:59:00Z"),
        ],
    )

    rc = reader._main(
        ["--prep-base", str(base), "--baseline", "3.0", "--intervention", "3.5", "--json"]
    )
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["n_observations"] == 8
    assert report["n_s2_composability_attempts"] == 2
    assert [p["criterion"] for p in report["phases"]] == [3.0, 3.5]
    assert report["s2_composability"] == [
        {
            "accepted": 0,
            "attempts": 1,
            "criterion": 3.0,
            "rejected": 1,
            "rejected_fraction": 1.0,
        },
        {
            "accepted": 1,
            "attempts": 1,
            "criterion": 3.5,
            "rejected": 0,
            "rejected_fraction": 0.0,
        },
    ]
    assert report["baseline_corrected_tau"]["tau"] > 0.5


def test_constants_mirror_the_writer(monkeypatch) -> None:
    """Drift guard: the re-declared constants must track daily_segment_prep so the
    reader and writer never disagree about the ledger filename or base path."""
    from agents.hapax_daimonion import daily_segment_prep as prep

    assert reader.COUNCIL_DECISIONS_LEDGER_FILENAME == prep.COUNCIL_DECISIONS_LEDGER_FILENAME

    # default_prep_base resolves the env var the same way DEFAULT_PREP_DIR does.
    monkeypatch.delenv("HAPAX_SEGMENT_PREP_DIR", raising=False)
    assert reader.default_prep_base() == Path.home() / ".cache" / "hapax" / "segment-prep"
    monkeypatch.setenv("HAPAX_SEGMENT_PREP_DIR", "/tmp/xyz-prep")
    assert reader.default_prep_base() == Path("/tmp/xyz-prep")
