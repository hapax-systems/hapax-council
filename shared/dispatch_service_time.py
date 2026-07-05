"""Event-sourced fold of the dispatch plane's service-time distribution.

The coordinator dispatch plane is an unmodeled M/G/k WSJF queue. To replace its
provably-wrong *fixed* stall timeout (lane-reaper 1800s / idle-watchdog 600s)
with a measured, age/SRPT-aware timeout, we first have to MEASURE the service
time. This module is the pure, idempotent, daemon-free fold that does so.

SSOT: ``~/.cache/hapax/cc-task-gate-decisions.jsonl`` (every gated tool call,
with an ISO-8601 ``ts``, ``task_id``, ``session_id`` and ``role``). The
``methodology-dispatch.jsonl`` dispatch->completion ledger is folded too *when
present* (it does not exist yet — graceful).

Three reviewer must-fixes are baked in (and pinned by tests):

* **ISO timestamps** — ``ts`` is an ISO-8601 *string* (``2026-05-31T20:40:17Z``),
  not a float epoch. A naive ``float()`` yields ``0.0`` and a silently-empty
  distribution (the same class of bug as the sdlc_invariants ts defect). We parse
  via :func:`datetime.fromisoformat`.
* **Null task_id exclusion** — a large fraction of gate records carry no
  ``task_id`` (system/orchestrator commands); they are excluded from the fold.
* **Session-continuity segmentation** — the "inter-tool gap" is only a valid
  service-time signal *within a single session*. A gap that spans a session
  boundary is an abandon/reclaim cycle (the task was dropped then re-offered by
  the very reaper this tunes), NOT a live non-preemptible turn. Folding those in
  inflates the tail and would set ``tau`` far too high, defeating never-stall.
  We segment each task's events into maximal same-session runs and only count
  gaps *inside* a run.

Re-derived baseline (the design's cited "CV=1.40" is unreproducible against this
source; see ``--report``): session-continuous inter-tool gaps run CV>>1 with a
heavy Pareto tail (Hill alpha ~1.3), which is exactly why a single fixed scalar
timeout cannot separate "slow-but-live" from "dead" — hence per-lineage ``tau``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from shared.intake_fit_scorer import composite_rank_key, fit_score

# ── tunables (all overridable; defaults grounded in the measured distribution) ─

#: Multiplier applied to the per-lineage p99 inter-tool gap to size ``tau``.
TAU_K = 2.0
#: Floor for ``tau`` — never reap a lane faster than this even for a quiet
#: lineage (matches the legacy reaper's 30-min intuition as a lower bound).
TAU_FLOOR_S = 1800.0
#: Hard ceiling for ``tau`` — a genuinely-wedged lane is ALWAYS recovered within
#: this bound (never-stall / bounded-recovery backstop).
TAU_CEIL_S = 7200.0
#: WSJF aging: effective priority = wsjf * (1 + COEFF * min(age/age_norm, CAP)).
AGING_COEFF = 1.0
AGING_CAP = 2.0
#: One "service epoch" for aging — the measured p90 per-segment service span.
AGE_NORM_S = 3453.0
#: Bounded recovery: escalate-then-STOP after this many reaps without recovery.
MAX_REAP_ATTEMPTS = 3

DEFAULT_DECISIONS_PATH = Path.home() / ".cache/hapax/cc-task-gate-decisions.jsonl"
DEFAULT_METHODOLOGY_PATH = Path.home() / ".cache/hapax/methodology-dispatch.jsonl"
DEFAULT_CACHE_PATH = Path.home() / ".cache/hapax/dispatch-service-time.json"


# ── statistics ────────────────────────────────────────────────────────────────


def percentile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (numpy "linear"/type-7). NaN if empty."""
    values = sorted(float(x) for x in xs)
    if not values:
        return math.nan
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * q
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return values[int(k)]
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def coefficient_of_variation(xs: Sequence[float]) -> float:
    """Population CV (std/mean). NaN if <2 points or zero mean."""
    if len(xs) < 2:
        return math.nan
    mean = statistics.fmean(xs)
    if mean == 0:
        return math.nan
    return statistics.pstdev(xs) / mean


def hill_alpha(xs: Sequence[float], frac: float = 0.1) -> float:
    """Hill tail-index estimator over the top ``frac`` order statistics.

    Lower alpha = heavier tail. NaN if there is too little data to estimate.
    """
    positive = sorted(x for x in (float(v) for v in xs) if x > 0)
    n = len(positive)
    if n < 3:
        return math.nan
    k = max(2, int(n * frac))
    if k >= n:
        return math.nan
    threshold = positive[n - k]
    if threshold <= 0:
        return math.nan
    s = sum(math.log(x / threshold) for x in positive[n - k :])
    return k / s if s > 0 else math.nan


# ── distribution + report ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Distribution:
    """Summary of one sample (inter-tool gaps or service spans)."""

    n: int
    mean: float
    median: float
    p50: float
    p90: float
    p95: float
    p99: float
    cv: float
    hill_alpha: float
    maximum: float
    values: tuple[float, ...] = ()

    @classmethod
    def from_values(cls, xs: Iterable[float]) -> Distribution:
        values = [float(x) for x in xs]
        if not values:
            nan = math.nan
            return cls(0, nan, nan, nan, nan, nan, nan, nan, nan, ())
        return cls(
            n=len(values),
            mean=statistics.fmean(values),
            median=statistics.median(values),
            p50=percentile(values, 0.5),
            p90=percentile(values, 0.9),
            p95=percentile(values, 0.95),
            p99=percentile(values, 0.99),
            cv=coefficient_of_variation(values),
            hill_alpha=hill_alpha(values),
            maximum=max(values),
            values=tuple(sorted(values)),
        )


@dataclass(frozen=True)
class ServiceTimeReport:
    """Folded service-time distribution across all sources."""

    gaps: Distribution
    spans: Distribution
    per_lineage: dict[str, Distribution]
    records_total: int
    records_no_task: int
    records_usable: int
    cross_session_breaks: int
    now: float
    window_s: float | None = None
    sources: tuple[str, ...] = field(default_factory=tuple)


# ── the fold ──────────────────────────────────────────────────────────────────


def parse_ts(value: object) -> float | None:
    """Parse an ISO-8601 ``ts`` string into epoch seconds. None on anything else.

    Accepts a trailing ``Z`` (UTC). Deliberately does NOT accept bare floats —
    the gate writes ISO strings, and treating a string as a float is the bug
    this guards against.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _read_records(source: Path) -> Iterable[dict]:
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


def load_service_time_distribution(
    sources: Sequence[Path | str] | None = None,
    *,
    now: float | None = None,
    window_s: float | None = None,
) -> ServiceTimeReport:
    """Fold the gate-decision (and methodology-dispatch, when present) ledgers."""
    if sources is None:
        sources = [DEFAULT_DECISIONS_PATH, DEFAULT_METHODOLOGY_PATH]
    resolved = [Path(s) for s in sources]
    now = time.time() if now is None else now

    total = no_task = 0
    rows: list[tuple[str, str, str, float]] = []  # (task_id, session_id, role, ts)
    for source in resolved:
        if not source.exists():
            continue
        for record in _read_records(source):
            total += 1
            task_id = record.get("task_id")
            if not task_id:
                no_task += 1
                continue
            ts = parse_ts(record.get("ts") or record.get("timestamp"))
            if ts is None:
                continue
            if window_s is not None and ts < now - window_s:
                continue
            session_id = str(record.get("session_id") or record.get("session") or "")
            role = str(record.get("role") or record.get("lane") or "")
            rows.append((str(task_id), session_id, role, ts))

    gaps, spans, per_lineage, cross = _segment(rows)
    return ServiceTimeReport(
        gaps=Distribution.from_values(gaps),
        spans=Distribution.from_values(spans),
        per_lineage={role: Distribution.from_values(vals) for role, vals in per_lineage.items()},
        records_total=total,
        records_no_task=no_task,
        records_usable=len(rows),
        cross_session_breaks=cross,
        now=now,
        window_s=window_s,
        sources=tuple(str(s) for s in resolved),
    )


def _segment(
    rows: Sequence[tuple[str, str, str, float]],
) -> tuple[list[float], list[float], dict[str, list[float]], int]:
    """Segment each task's events into same-session runs; gaps are intra-run only."""
    by_task: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    for task_id, session_id, role, ts in rows:
        by_task[task_id].append((ts, session_id, role))

    gaps: list[float] = []
    spans: list[float] = []
    per_lineage: dict[str, list[float]] = defaultdict(list)
    cross_session_breaks = 0

    for events in by_task.values():
        events.sort()
        seg_start = 0
        current_session = events[0][1]
        for i in range(1, len(events) + 1):
            same_session = i < len(events) and events[i][1] == current_session
            if same_session:
                delta = events[i][0] - events[i - 1][0]
                if delta > 0:
                    gaps.append(delta)
                    per_lineage[events[i][2]].append(delta)
            else:
                segment = events[seg_start:i]
                if len(segment) >= 2:
                    spans.append(segment[-1][0] - segment[0][0])
                if i < len(events):
                    cross_session_breaks += 1
                    seg_start = i
                    current_session = events[i][1]
    return gaps, spans, per_lineage, cross_session_breaks


# ── scheduler primitives (consumed by the reaper and tick()) ──────────────────


def _tau_from_p99(p99: float, k: float = TAU_K) -> float:
    """Size tau from a p99 inter-tool gap, clamped into [floor, ceil]."""
    if not math.isfinite(p99) or p99 <= 0:
        return TAU_FLOOR_S
    return max(TAU_FLOOR_S, min(TAU_CEIL_S, k * p99))


def tau_for_lineage(report: ServiceTimeReport, lineage: str, k: float = TAU_K) -> float:
    """Progress-timeout for a lineage: k * its measured p99 gap, clamped.

    Unknown/empty lineages fall back to the global gap p99 (then the floor).
    This is the Gittins move: rank by elapsed *silence* against the measured
    hazard, so a long-but-progressing turn is never reaped.
    """
    dist = report.per_lineage.get(lineage)
    p99 = dist.p99 if dist is not None and dist.n > 0 else report.gaps.p99
    return _tau_from_p99(p99, k)


def should_reap(progress_age_s: float, tau_s: float) -> bool:
    """A lane is a reap candidate iff it has been silent longer than tau."""
    return progress_age_s > tau_s


def reap_decision(
    progress_age_s: float,
    tau_s: float,
    tau_ceil_s: float,
    attempts: int,
    max_attempts: int = MAX_REAP_ATTEMPTS,
) -> str:
    """Bounded-recovery reap decision: ``skip`` | ``reap`` | ``escalate``.

    ``skip``     — progressing (silence within tau): never reap a live turn.
    ``reap``     — silent past tau and attempts remain: kill + re-offer.
    ``escalate`` — silent past tau but attempts exhausted: ntfy and STOP, so the
                   coordinator never spins an infinite reap loop on a wedged lane.
    """
    if not should_reap(progress_age_s, min(tau_s, tau_ceil_s)):
        return "skip"
    if attempts >= max_attempts:
        return "escalate"
    return "reap"


def wsjf_effective(
    wsjf: float,
    age_in_queue_s: float,
    age_norm_s: float = AGE_NORM_S,
    aging_coeff: float = AGING_COEFF,
    aging_cap: float = AGING_CAP,
) -> float:
    """WSJF with bounded aging — breaks SJF starvation without an expert rule.

    A low-WSJF task that has waited a full service epoch climbs above fresh
    high-WSJF arrivals; the multiplier is capped so it never inverts by more
    than the aging cap (pure parametric modulation, no thresholds).
    """
    if age_norm_s <= 0:
        return wsjf
    factor = 1.0 + aging_coeff * min(age_in_queue_s / age_norm_s, aging_cap)
    return wsjf * factor


# ── per-lineage virtual queues (the tick() inner loop, made pure & testable) ──


@dataclass(frozen=True)
class QueueTask:
    """An offered task as the scheduler sees it (lightweight, no fs coupling)."""

    task_id: str
    wsjf: float
    platform_suitability: tuple[str, ...]
    age_s: float = 0.0
    # Demand-shape for the SdlcRouter shadow scorer (None = honest-DARK).
    requirement_vector: dict[str, int] | None = None
    routing_class: str | None = None


@dataclass(frozen=True)
class QueueLane:
    """An idle lane as the scheduler sees it. ``cooldown_remaining_s`` > 0 ==
    the lane was dispatched-to recently and is rate-limited this tick."""

    role: str
    platform: str
    cooldown_remaining_s: float = 0.0
    dispatchable: bool = True


def is_claude_operator_pool_role(role: str) -> bool:
    """True for visible Claude dev-pool sessions that are not governed lanes."""

    return re.fullmatch(r"dev[0-9]*", role.strip().lower()) is not None


def _routable(task: QueueTask, lane: QueueLane) -> bool:
    if not is_dispatchable_lane(lane):
        return False
    platforms = {p.lower() for p in task.platform_suitability}
    return "any" in platforms or lane.platform.lower() in platforms


def is_dispatchable_lane(lane: QueueLane) -> bool:
    """False for live operator-pool sessions that must never receive queue work."""

    if not lane.dispatchable:
        return False
    if lane.platform.lower() != "claude":
        return True
    return not is_claude_operator_pool_role(lane.role)


def plan_dispatches(
    tasks: Sequence[QueueTask],
    lanes: Sequence[QueueLane],
    *,
    max_dispatches: int,
    age_norm_s: float = AGE_NORM_S,
    legacy: bool = False,
    fit_blend: float = 0.0,
) -> list[tuple[str, str]]:
    """Decide ``(task_id, lane_role)`` dispatches for one tick.

    Default (new) policy — **per-lineage virtual queues + WSJF aging**:
    iterate *idle* lanes (lane-outer), and let each free lane pull its
    best-eligible task by aged WSJF. Because the loop is lane-outer over
    cooled-*out* lanes only, a busy/cooled lane can never head-of-line-block a
    routable task from reaching a different free lane (the VOQ fix), and aging
    lets a starved low-WSJF task overtake fresh high-WSJF arrivals (bounded).

    ``legacy=True`` restores the prior behavior exactly: task-outer over raw
    WSJF-desc, first-matching lane, and a cooled first-match lane *skips the
    task* (the head-of-line bug this change fixes) — for the revert env and the
    golden diff.

    ``fit_blend`` (default ``0.0``) blends the intake ``fit_score`` (demand-shape
    magnitude) into the rank-key: the per-task key becomes ``composite_rank_key``
    over aged WSJF + ``fit_blend * fit_score``. ``0.0`` short-circuits to pure
    WSJF (byte-identical to the pre-blend plan — the golden guarantee); a non-zero
    blend is the operator's dial. ``_repair_cooled_plan`` MUST receive the same
    ``fit_blend`` so the no-spin repair never reorders relative to the plan.
    """
    if legacy:
        return _plan_legacy(tasks, lanes, max_dispatches)

    available = [lane for lane in lanes if lane.cooldown_remaining_s <= 0]
    remaining = list(tasks)
    plan: list[tuple[str, str]] = []
    for lane in available:
        if len(plan) >= max_dispatches:
            break
        eligible = [t for t in remaining if _routable(t, lane)]
        if not eligible:
            continue
        best = max(
            eligible,
            key=lambda t: composite_rank_key(
                wsjf_effective(t.wsjf, t.age_s, age_norm_s),
                fit_score(t.requirement_vector),
                blend=fit_blend,
            ),
        )
        plan.append((best.task_id, lane.role))
        remaining.remove(best)
    return plan


def _plan_legacy(
    tasks: Sequence[QueueTask],
    lanes: Sequence[QueueLane],
    max_dispatches: int,
) -> list[tuple[str, str]]:
    idle = list(lanes)
    plan: list[tuple[str, str]] = []
    for task in sorted(tasks, key=lambda t: t.wsjf, reverse=True):
        if not idle or len(plan) >= max_dispatches:
            break
        lane = next((ln for ln in idle if _routable(task, ln)), None)
        if lane is None:
            continue
        if lane.cooldown_remaining_s > 0:
            # prior behavior: the task gives up on its first-match lane without
            # trying any other free lane — the head-of-line block.
            continue
        plan.append((task.task_id, lane.role))
        idle.remove(lane)
    return plan


# ── cache (the SSOT the bash watchdogs read) ──────────────────────────────────


def build_cache_payload(report: ServiceTimeReport, k: float = TAU_K) -> dict:
    """Compact, value-free summary + per-lineage tau for the watchdogs to read."""

    def summarize(dist: Distribution) -> dict:
        return {
            "n": dist.n,
            "p50": _round(dist.p50),
            "p90": _round(dist.p90),
            "p95": _round(dist.p95),
            "p99": _round(dist.p99),
            "cv": _round(dist.cv),
            "hill_alpha": _round(dist.hill_alpha),
            "max": _round(dist.maximum),
        }

    per_lineage = {}
    for role, dist in report.per_lineage.items():
        entry = summarize(dist)
        entry["tau_s"] = _tau_from_p99(dist.p99, k)
        per_lineage[role] = entry

    global_entry = summarize(report.gaps)
    global_entry["tau_s"] = _tau_from_p99(report.gaps.p99, k)

    return {
        "generated_at": report.now,
        "tau_floor_s": TAU_FLOOR_S,
        "tau_ceil_s": TAU_CEIL_S,
        "tau_k": k,
        "max_reap_attempts": MAX_REAP_ATTEMPTS,
        "age_norm_s": _round(report.spans.p90) if report.spans.n else AGE_NORM_S,
        "records_total": report.records_total,
        "records_no_task": report.records_no_task,
        "records_usable": report.records_usable,
        "cross_session_breaks": report.cross_session_breaks,
        "global": global_entry,
        "spans": summarize(report.spans),
        "per_lineage": per_lineage,
    }


def _round(value: float) -> float | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), 2)


def write_cache(report: ServiceTimeReport, path: Path, k: float = TAU_K) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_cache_payload(report, k)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.rename(path)


def tau_from_cache(path: Path, lineage: str) -> float:
    """Read tau for a lineage from the cache. Missing cache -> safe ceiling.

    A blind reaper (no cache) must not reap aggressively, so the fallback is the
    ceiling, not the floor: when uncertain, wait the maximum bounded time.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TAU_CEIL_S
    per_lineage = data.get("per_lineage", {})
    entry = per_lineage.get(lineage)
    if isinstance(entry, dict) and "tau_s" in entry:
        return float(entry["tau_s"])
    global_entry = data.get("global", {})
    if isinstance(global_entry, dict) and "tau_s" in global_entry:
        return float(global_entry["tau_s"])
    return TAU_CEIL_S


# ── CLI ───────────────────────────────────────────────────────────────────────


def _format_report(report: ServiceTimeReport) -> str:
    lines = [
        f"dispatch service-time fold  (records: total={report.records_total} "
        f"no_task_id={report.records_no_task} usable={report.records_usable} "
        f"cross_session_breaks={report.cross_session_breaks})",
        "",
        f"{'sample':<26} {'n':>6} {'p50':>8} {'p90':>8} {'p95':>8} "
        f"{'p99':>9} {'max':>9} {'CV':>7} {'hill':>6}",
    ]

    def row(name: str, dist: Distribution) -> str:
        return (
            f"{name:<26} {dist.n:>6} {dist.p50:>8.0f} {dist.p90:>8.0f} {dist.p95:>8.0f} "
            f"{dist.p99:>9.0f} {dist.maximum:>9.0f} {dist.cv:>7.2f} {dist.hill_alpha:>6.2f}"
        )

    lines.append(row("inter-tool gaps", report.gaps))
    lines.append(row("service spans", report.spans))
    lines.append("")
    lines.append("per-lineage inter-tool gaps + tau:")
    for role in sorted(report.per_lineage):
        dist = report.per_lineage[role]
        tau = tau_for_lineage(report, role)
        lines.append(f"  {row(role, dist)}   tau={tau:.0f}s")
    return "\n".join(lines)


def _sources(args: argparse.Namespace) -> list[Path]:
    if args.source:
        return [Path(args.source)]
    return [DEFAULT_DECISIONS_PATH, DEFAULT_METHODOLOGY_PATH]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dispatch service-time fold")
    parser.add_argument("--report", action="store_true", help="print the distribution table")
    parser.add_argument("--recompute", action="store_true", help="recompute and write the cache")
    parser.add_argument("--tau", action="store_true", help="print tau for --lineage from --cache")
    parser.add_argument(
        "--reap-decision",
        action="store_true",
        help="print skip|reap|escalate for the reaper",
    )
    parser.add_argument(
        "--lineage", default="", help="lineage (lane role) for --tau/--reap-decision"
    )
    parser.add_argument("--progress-age", type=float, default=0.0, help="lane silence seconds")
    parser.add_argument("--attempts", type=int, default=0, help="prior reap attempts this lane")
    parser.add_argument("--max-attempts", type=int, default=MAX_REAP_ATTEMPTS, help="reap cap")
    parser.add_argument(
        "--tau-override", type=float, default=None, help="force tau (legacy/fixed); else from cache"
    )
    parser.add_argument("--source", default="", help="override source jsonl (default: gate ledger)")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH), help="cache json path")
    parser.add_argument("--window", type=float, default=None, help="recency window in seconds")
    args = parser.parse_args(argv)

    if args.tau:
        print(int(tau_from_cache(Path(args.cache), args.lineage)))
        return 0

    if args.reap_decision:
        tau = args.tau_override
        if tau is None:
            tau = tau_from_cache(Path(args.cache), args.lineage)
        print(reap_decision(args.progress_age, tau, TAU_CEIL_S, args.attempts, args.max_attempts))
        return 0

    if args.recompute:
        report = load_service_time_distribution(_sources(args), window_s=args.window)
        write_cache(report, Path(args.cache))
        return 0

    # default action is --report
    report = load_service_time_distribution(_sources(args), window_s=args.window)
    print(_format_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
