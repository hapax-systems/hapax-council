"""Turn-timing queryable surface — the TIMING receipt ring.

CASE-VOICE-FOUNDATION-20260610, audit v2 gate (i) instrument
(audit-w2-latency-emitter): TurnBudget receipts land in the witness as
`last_turn_timing` — one record, overwritten every turn. Interview gate (i)
needs a *distribution* (≤2s p90 over a window), so every receipt is also
appended here: a bounded JSONL ring on /dev/shm, plus the reader that
computes p50/p90 over the last N turns. The fitness function that judges
the numbers is deliberately NOT here (audit: "emitter first; then a p90
fitness function") — this module only measures.

Like turn_budget.py this is a LEAF: it imports nothing from
agents.hapax_daimonion, so the witness can import it without cycles.

Operator probe:

    uv run python -m agents.hapax_daimonion.turn_timing_log --window 20
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict

TURN_TIMINGS_PATH = Path("/dev/shm/hapax-daimonion/turn-timings.jsonl")
# 10× the gate-(i) 20-turn window — enough history for a rehearsal
# post-mortem while keeping the ring a single tmpfs page-set.
MAX_ENTRIES = 200
DEFAULT_WINDOW = 20


class LegStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    p50_ms: float
    p90_ms: float


class TurnLatencyStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = 1
    window: int
    kind: str  # "all" or the TurnBudget kind the stats were scoped to
    count: int
    p50_ms: float | None
    p90_ms: float | None
    max_ms: float | None
    overrun_count: int
    legs: dict[str, LegStats]


def append_turn_timing(
    entry: dict,
    *,
    path: Path = TURN_TIMINGS_PATH,
    max_entries: int = MAX_ENTRIES,
) -> None:
    """Append one TurnBudget receipt to the ring, trimming to ``max_entries``.

    The whole ring is rewritten atomically (tmp + replace) so readers never
    see a torn line; at ≤200 entries on tmpfs the rewrite is negligible.
    """
    lines = _read_lines(path)
    lines.append(json.dumps(entry, sort_keys=True))
    lines = lines[-max_entries:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_turn_timings(
    *,
    window: int = DEFAULT_WINDOW,
    kind: str | None = None,
    path: Path = TURN_TIMINGS_PATH,
) -> list[dict]:
    """Last ``window`` receipts (newest last), optionally scoped to one kind.

    The kind filter applies BEFORE windowing, so ``kind="interactive"``
    means "the last N interactive turns", not "interactive turns among the
    last N". Malformed lines are skipped — a torn ring degrades the sample,
    never the reader.
    """
    entries: list[dict] = []
    for line in _read_lines(path):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        if kind is not None and parsed.get("kind") != kind:
            continue
        entries.append(parsed)
    return entries[-window:]


def turn_latency_stats(
    *,
    window: int = DEFAULT_WINDOW,
    kind: str | None = None,
    path: Path = TURN_TIMINGS_PATH,
) -> TurnLatencyStats:
    """p50/p90 (nearest-rank) of total and per-leg ms over the window."""
    entries = read_turn_timings(window=window, kind=kind, path=path)
    totals = [float(e["total_ms"]) for e in entries if isinstance(e.get("total_ms"), (int, float))]
    leg_values: dict[str, list[float]] = {}
    for e in entries:
        legs = e.get("legs")
        if not isinstance(legs, dict):
            continue
        for leg, ms in legs.items():
            if isinstance(ms, (int, float)):
                leg_values.setdefault(str(leg), []).append(float(ms))
    return TurnLatencyStats(
        window=window,
        kind=kind or "all",
        count=len(entries),
        p50_ms=_percentile(totals, 0.5),
        p90_ms=_percentile(totals, 0.9),
        max_ms=max(totals) if totals else None,
        overrun_count=sum(1 for e in entries if e.get("overrun") is True),
        legs={
            leg: LegStats(p50_ms=_percentile(vals, 0.5), p90_ms=_percentile(vals, 0.9))
            for leg, vals in sorted(leg_values.items())
            if vals
        },
    )


def _percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile: smallest value with ≥ q of the sample at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def _read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    return [line for line in text.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    """Print window stats as JSON — the audit recheck probe for gate (i)."""
    parser = argparse.ArgumentParser(description=turn_latency_stats.__doc__)
    parser.add_argument("--path", type=Path, default=TURN_TIMINGS_PATH)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument(
        "--kind", default=None, help='scope to one TurnBudget kind, e.g. "interactive"'
    )
    args = parser.parse_args(argv)
    stats = turn_latency_stats(window=args.window, kind=args.kind, path=args.path)
    print(json.dumps(stats.model_dump(mode="json"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_WINDOW",
    "MAX_ENTRIES",
    "TURN_TIMINGS_PATH",
    "LegStats",
    "TurnLatencyStats",
    "append_turn_timing",
    "main",
    "read_turn_timings",
    "turn_latency_stats",
]
