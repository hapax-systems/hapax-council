"""The service-time distribution must read the ledger that is actually written.

`DEFAULT_METHODOLOGY_PATH` pointed at `~/.cache/hapax/methodology-dispatch.jsonl`. Nothing in the
estate writes that path — grepping scripts/, shared/ and agents/ for it returns only the constant
itself. The real ledger is written by `hapax-methodology-dispatch` via
`orchestration_ledger_dir()` to `~/.cache/hapax/orchestration/methodology-dispatch.jsonl`,
968,573,691 bytes as of 2026-08-10.

The distribution was NOT empty, which is why this went unnoticed: the other source
(`cc-task-gate-decisions.jsonl`) exists and supplied 4,231 samples. Materially wrong is worse
than empty here, because empty fails visibly.

Measured effect of adding the real source, 14-day window:

    global p99   1,918s -> 15,363s
    epsilon      n=21   -> n=4,606   tau 1,800s -> 7,200s
    theta        n=4    -> n=1,012   tau 1,800s -> 7,200s
    beta         n=2,074 -> n=2,076  tau unchanged

The two lineages with the sparsest history were the ones defaulting to the tau FLOOR, so the
lanes least visible to the ledger were the most exposed to reaping. `tau_for_lineage` feeds
`should_reap`, which feeds the lane reaper and the idle watchdog.

Every movement is toward LESS reaping, and `TAU_CEIL_S` bounds it absolutely. That direction is
the invariant pinned below: correcting a data source must never make a killer more aggressive.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.dispatch_service_time import (
    DEFAULT_DECISIONS_PATH,
    DEFAULT_METHODOLOGY_PATH,
    TAU_CEIL_S,
    load_service_time_distribution,
    tau_for_lineage,
)


def _iso(epoch: float) -> str:
    """`parse_ts` deliberately rejects bare floats — the gate writes ISO strings, and treating a
    string as a float is the bug it guards against. Fixtures must honour that."""
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def _ledger(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = [{**r, "ts": _iso(r["ts"])} for r in rows]
    path.write_text("\n".join(json.dumps(r) for r in stamped) + "\n", encoding="utf-8")
    return path


def test_default_methodology_path_is_the_written_ledger() -> None:
    """The constant must name the directory the producer actually writes.

    `hapax-methodology-dispatch:1818` resolves `orchestration_ledger_dir()` to
    `~/.cache/hapax/orchestration`, honouring HAPAX_ORCHESTRATION_LEDGER_DIR. A consumer path
    that no producer writes is a distribution over a file that will never exist.
    """
    assert DEFAULT_METHODOLOGY_PATH.parent.name == "orchestration", (
        f"{DEFAULT_METHODOLOGY_PATH} is not under the orchestration ledger dir; nothing writes "
        f"the bare ~/.cache/hapax location"
    )
    assert DEFAULT_METHODOLOGY_PATH.name == "methodology-dispatch.jsonl"


def test_adding_the_methodology_source_never_lowers_tau(tmp_path: Path) -> None:
    """The safety invariant, pinned as a property rather than as numbers.

    Numbers move as the ledger grows; the direction must not. Correcting a data source feeds a
    killer (`should_reap` -> lane reaper), so the change must only ever make it more permissive.
    """
    now = 1_000_000.0
    decisions = _ledger(
        tmp_path / "decisions.jsonl",
        [
            {"task_id": "t1", "session_id": "s1", "role": "epsilon", "ts": now - 100},
            {"task_id": "t1", "session_id": "s1", "role": "epsilon", "ts": now - 90},
        ],
    )
    methodology = _ledger(
        tmp_path / "orchestration" / "methodology-dispatch.jsonl",
        [
            {"task_id": "t2", "session_id": "s2", "role": "epsilon", "ts": now - 9000},
            {"task_id": "t2", "session_id": "s2", "role": "epsilon", "ts": now - 500},
        ],
    )

    without = load_service_time_distribution(sources=[decisions], now=now)
    with_both = load_service_time_distribution(sources=[decisions, methodology], now=now)

    for lineage in ("epsilon", "__unknown__"):
        before = tau_for_lineage(without, lineage)
        after = tau_for_lineage(with_both, lineage)
        assert after >= before, (
            f"adding a data source LOWERED tau for {lineage} ({before} -> {after}); a correction "
            f"to the input of a reaper must never make it more aggressive"
        )
        assert after <= TAU_CEIL_S


def test_a_missing_source_is_skipped_not_fatal(tmp_path: Path) -> None:
    """Absent sources are skipped by design — which is exactly why this went unnoticed.

    Worth pinning so the behaviour stays deliberate: the loader must not crash on a path that
    does not exist, and must still fold whatever sources do.
    """
    now = 1_000_000.0
    present = _ledger(
        tmp_path / "present.jsonl",
        [
            {"task_id": "t", "session_id": "s", "role": "beta", "ts": now - 60},
            {"task_id": "t", "session_id": "s", "role": "beta", "ts": now - 30},
        ],
    )
    report = load_service_time_distribution(
        sources=[present, tmp_path / "does-not-exist.jsonl"], now=now
    )
    assert report.gaps.n > 0


def test_both_default_sources_are_distinct_and_named() -> None:
    """Guard against collapsing the two sources, which would silently drop one."""
    assert DEFAULT_DECISIONS_PATH != DEFAULT_METHODOLOGY_PATH
    assert DEFAULT_DECISIONS_PATH.name == "cc-task-gate-decisions.jsonl"
