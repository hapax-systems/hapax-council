"""Support-only fold of observed dispatch service times.

The JSONL inputs are ambient observations, not lifecycle facts, authority,
admission, or execution outcomes.  This module therefore preserves their source
provenance, frontier, freshness, and loss classes while refusing to turn them
into dispatch ordering or liveness effects.  No current Gate-0 admission/outcome
contract consumes this projection.

The compatibility planning and reap functions remain importable while callers
migrate. Planning emits deterministic candidates from governed task/lane inputs
without using this support data; reap decisions return ``hold``. A measured
value can be inspected; it cannot authorize, rank, reap, kill, release, clear,
revive, launch, mint, or notify.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

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

SUPPORT_PROJECTION_KIND = "dispatch_service_time"
SUPPORT_EFFECT_STATE = "held_not_admitted"
SUPPORT_HOLD_REASON = "dispatch_service_time_support_has_no_admission_or_execution_lease"
SUPPORT_MAY_AUTHORIZE = False

# Parsing bounds make hostile or corrupt ambient input visible and finite.
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_ID_LENGTH = 256
DEFAULT_FRESHNESS_WINDOW_S = 86_400.0
_ISO_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


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
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("service_time_distribution_value_invalid")
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
class SourceSupportReceipt:
    """Content-bound disposition for one ambient JSONL source."""

    source: str
    source_state: str
    sha256: str | None
    byte_length: int | None
    lines_total: int
    records_accepted: int
    rejected: dict[str, int]
    frontier_ts: float | None
    freshness_state: str


@dataclass(frozen=True)
class ServiceTimeReport:
    """Folded support projection across explicitly receipted sources."""

    gaps: Distribution
    spans: Distribution
    per_lineage: dict[str, Distribution]
    records_total: int
    records_no_task: int
    records_usable: int
    records_rejected: int
    rejected: dict[str, int]
    cross_session_breaks: int
    now: float
    window_s: float | None = None
    sources: tuple[str, ...] = field(default_factory=tuple)
    source_receipts: tuple[SourceSupportReceipt, ...] = field(default_factory=tuple)


# ── the fold ──────────────────────────────────────────────────────────────────


def parse_ts(value: object) -> float | None:
    """Parse a timezone-aware ISO-8601 timestamp into finite epoch seconds."""

    if not isinstance(value, str) or not _ISO_TS_RE.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        timestamp = parsed.timestamp()
    except (OverflowError, ValueError):
        return None
    return timestamp if math.isfinite(timestamp) and timestamp >= 0 else None


def _valid_identity(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_ID_LENGTH:
        return None
    if value != value.strip() or "\x00" in value:
        return None
    return value


def _increment(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def _source_freshness(
    *, frontier_ts: float | None, now: float, window_s: float | None, source_state: str
) -> str:
    if source_state != "observed":
        return source_state
    if frontier_ts is None:
        return "no_accepted_frontier"
    horizon = window_s if window_s is not None else DEFAULT_FRESHNESS_WINDOW_S
    return "fresh" if frontier_ts >= now - horizon else "stale"


def _read_source_bytes(source: Path) -> tuple[bytes | None, str, int | None, str | None]:
    """Read one bounded source and return bytes, state, size, and hash."""

    try:
        byte_length = source.stat().st_size
        if byte_length > MAX_SOURCE_BYTES:
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            return None, "source_too_large", byte_length, digest
        raw = source.read_bytes()
    except OSError:
        state = "missing" if not source.exists() else "unreadable"
        return None, state, None, None
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > MAX_SOURCE_BYTES:
        return None, "source_too_large", len(raw), digest
    return raw, "observed", len(raw), digest


def load_service_time_distribution(
    sources: Sequence[Path | str] | None = None,
    *,
    now: float | None = None,
    window_s: float | None = None,
) -> ServiceTimeReport:
    """Fold ambient ledgers into a non-authorizing support projection.

    Every nonempty line is either accepted or assigned an explicit rejection
    class.  Source hashes bind the projection to its input frontier without
    copying parent-encrypted or otherwise sensitive records into the cache.
    """
    if sources is None:
        sources = [DEFAULT_DECISIONS_PATH, DEFAULT_METHODOLOGY_PATH]
    resolved = [Path(s) for s in sources]
    now = time.time() if now is None else now
    if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
        raise ValueError("service_time_query_time_invalid")
    if now < 0:
        raise ValueError("service_time_query_time_invalid")
    if window_s is not None and (
        isinstance(window_s, bool)
        or not isinstance(window_s, (int, float))
        or not math.isfinite(window_s)
        or window_s <= 0
    ):
        raise ValueError("service_time_window_invalid")

    total = no_task = 0
    rejected: dict[str, int] = {}
    receipts: list[SourceSupportReceipt] = []
    rows: list[tuple[str, str, str, float]] = []  # (task_id, session_id, role, ts)
    for source in resolved:
        raw, source_state, byte_length, digest = _read_source_bytes(source)
        source_rejected: dict[str, int] = {}
        source_accepted = 0
        lines_total = 0
        frontier_ts: float | None = None
        if raw is None:
            _increment(rejected, source_state)
            receipts.append(
                SourceSupportReceipt(
                    source=str(source),
                    source_state=source_state,
                    sha256=digest,
                    byte_length=byte_length,
                    lines_total=0,
                    records_accepted=0,
                    rejected={source_state: 1},
                    frontier_ts=None,
                    freshness_state=source_state,
                )
            )
            continue

        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _increment(rejected, "source_invalid_utf8")
            receipts.append(
                SourceSupportReceipt(
                    source=str(source),
                    source_state="source_invalid_utf8",
                    sha256=digest,
                    byte_length=byte_length,
                    lines_total=0,
                    records_accepted=0,
                    rejected={"source_invalid_utf8": 1},
                    frontier_ts=None,
                    freshness_state="source_invalid_utf8",
                )
            )
            continue

        for raw_line in text.splitlines():
            lines_total += 1
            if not raw_line.strip():
                reason = "blank_line"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            total += 1
            if len(raw_line.encode("utf-8")) > MAX_LINE_BYTES:
                reason = "line_too_large"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                reason = "json_invalid"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            if not isinstance(record, dict):
                reason = "record_not_object"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue

            task_value = record.get("task_id")
            if task_value is None or task_value == "":
                no_task += 1
                reason = "task_id_missing"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            task_id = _valid_identity(task_value)
            if task_id is None:
                reason = "task_id_invalid"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue

            ts_value = record.get("ts")
            timestamp_value = record.get("timestamp")
            if ts_value is not None and timestamp_value is not None and ts_value != timestamp_value:
                reason = "timestamp_conflict"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            selected_ts = ts_value if ts_value is not None else timestamp_value
            if selected_ts is None:
                reason = "timestamp_missing"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            ts = parse_ts(selected_ts)
            if ts is None:
                reason = "timestamp_invalid"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            if ts > now:
                reason = "timestamp_future"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            frontier_ts = ts if frontier_ts is None else max(frontier_ts, ts)
            if window_s is not None and ts < now - window_s:
                reason = "timestamp_stale"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue

            session_value = record.get("session_id") or record.get("session")
            session_id = _valid_identity(session_value)
            if session_id is None:
                reason = "session_id_missing" if not session_value else "session_id_invalid"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue
            role_value = record.get("role") or record.get("lane")
            role = _valid_identity(role_value)
            if role is None:
                reason = "role_missing" if not role_value else "role_invalid"
                _increment(rejected, reason)
                _increment(source_rejected, reason)
                continue

            rows.append((task_id, session_id, role, ts))
            source_accepted += 1

        receipts.append(
            SourceSupportReceipt(
                source=str(source),
                source_state=source_state,
                sha256=digest,
                byte_length=byte_length,
                lines_total=lines_total,
                records_accepted=source_accepted,
                rejected=dict(sorted(source_rejected.items())),
                frontier_ts=frontier_ts,
                freshness_state=_source_freshness(
                    frontier_ts=frontier_ts,
                    now=float(now),
                    window_s=float(window_s) if window_s is not None else None,
                    source_state=source_state,
                ),
            )
        )

    gaps, spans, per_lineage, cross = _segment(rows)
    return ServiceTimeReport(
        gaps=Distribution.from_values(gaps),
        spans=Distribution.from_values(spans),
        per_lineage={role: Distribution.from_values(vals) for role, vals in per_lineage.items()},
        records_total=total,
        records_no_task=no_task,
        records_usable=len(rows),
        records_rejected=sum(rejected.values()),
        rejected=dict(sorted(rejected.items())),
        cross_session_breaks=cross,
        now=float(now),
        window_s=window_s,
        sources=tuple(str(s) for s in resolved),
        source_receipts=tuple(receipts),
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


# ── support metrics + fail-closed compatibility APIs ──────────────────────────


def _tau_from_p99(p99: float, k: float = TAU_K) -> float:
    """Derive a bounded, non-authorizing timeout candidate for inspection."""
    if not math.isfinite(p99) or not math.isfinite(k) or p99 <= 0 or k <= 0:
        return TAU_FLOOR_S
    return max(TAU_FLOOR_S, min(TAU_CEIL_S, k * p99))


def tau_for_lineage(report: ServiceTimeReport, lineage: str, k: float = TAU_K) -> float:
    """Return a bounded support metric; never an admission or execution lease."""
    dist = report.per_lineage.get(lineage)
    p99 = dist.p99 if dist is not None and dist.n > 0 else report.gaps.p99
    return _tau_from_p99(p99, k)


def should_reap(progress_age_s: float, tau_s: float) -> bool:
    """Fail closed: ambient service-time observations cannot authorize a reap."""

    del progress_age_s, tau_s
    return False


def reap_decision(
    progress_age_s: float,
    tau_s: float,
    tau_ceil_s: float,
    attempts: int,
    max_attempts: int = MAX_REAP_ATTEMPTS,
) -> str:
    """Fail closed until admission and an execution lease bind any recovery."""

    del progress_age_s, tau_s, tau_ceil_s, attempts, max_attempts
    return "hold"


def wsjf_effective(
    wsjf: float,
    age_in_queue_s: float,
    age_norm_s: float = AGE_NORM_S,
    aging_coeff: float = AGING_COEFF,
    aging_cap: float = AGING_CAP,
) -> float:
    """Return raw WSJF without allowing observed age/service time to modulate rank."""

    del age_in_queue_s, age_norm_s, aging_coeff, aging_cap
    value = float(wsjf)
    if not math.isfinite(value):
        raise ValueError("wsjf_support_value_invalid")
    return value


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
    """Select deterministic candidates without service-time or refusal influence.

    This is a pure candidate projection, not dispatch admission.  It uses only
    raw finite WSJF, stable task/lane identity, route compatibility, the lane's
    governed dispatchable flag, and the caller's candidate bound.  Queue age,
    observed cooldown, cache values, fit-blend dials, and the legacy environment
    cannot change the result.  Downstream methodology carriage must still emit a
    universal held carrier until a real admission/outcome contract exists.
    """

    del age_norm_s, legacy, fit_blend
    return _baseline_candidate_plan(tasks, lanes, max_dispatches)


def _baseline_candidate_plan(
    tasks: Sequence[QueueTask], lanes: Sequence[QueueLane], max_dispatches: int
) -> list[tuple[str, str]]:
    if (
        isinstance(max_dispatches, bool)
        or not isinstance(max_dispatches, int)
        or max_dispatches <= 0
    ):
        return []

    available = sorted(
        (lane for lane in lanes if is_dispatchable_lane(lane)),
        key=lambda lane: (lane.role, lane.platform),
    )
    remaining = [
        task
        for task in tasks
        if _valid_identity(task.task_id) is not None
        and not isinstance(task.wsjf, bool)
        and isinstance(task.wsjf, (int, float))
        and math.isfinite(task.wsjf)
    ]
    plan: list[tuple[str, str]] = []
    for lane in available:
        if len(plan) >= max_dispatches:
            break
        eligible = [task for task in remaining if _routable(task, lane)]
        if not eligible:
            continue
        best = min(eligible, key=lambda task: (-float(task.wsjf), task.task_id))
        plan.append((best.task_id, lane.role))
        remaining.remove(best)
    return plan


def _plan_legacy(
    tasks: Sequence[QueueTask],
    lanes: Sequence[QueueLane],
    max_dispatches: int,
) -> list[tuple[str, str]]:
    """Legacy compatibility delegates to the same Gate-0A candidate projection."""

    return _baseline_candidate_plan(tasks, lanes, max_dispatches)


# ── derived support cache ─────────────────────────────────────────────────────


def build_cache_payload(report: ServiceTimeReport, k: float = TAU_K) -> dict:
    """Build an inspectable projection that explicitly cannot authorize effects."""

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
        entry["observed_tau_candidate_s"] = _tau_from_p99(dist.p99, k)
        per_lineage[role] = entry

    global_entry = summarize(report.gaps)
    global_entry["observed_tau_candidate_s"] = _tau_from_p99(report.gaps.p99, k)

    receipts = [
        {
            "source": receipt.source,
            "source_state": receipt.source_state,
            "sha256": receipt.sha256,
            "byte_length": receipt.byte_length,
            "lines_total": receipt.lines_total,
            "records_accepted": receipt.records_accepted,
            "rejected": receipt.rejected,
            "frontier_ts": _format_ts(receipt.frontier_ts),
            "freshness_state": receipt.freshness_state,
        }
        for receipt in report.source_receipts
    ]

    return {
        "projection_kind": SUPPORT_PROJECTION_KIND,
        "effect_state": SUPPORT_EFFECT_STATE,
        "hold_reason": SUPPORT_HOLD_REASON,
        "may_authorize": SUPPORT_MAY_AUTHORIZE,
        "generated_at": _format_ts(report.now),
        "query_window_s": report.window_s,
        "tau_floor_s": TAU_FLOOR_S,
        "tau_ceil_s": TAU_CEIL_S,
        "tau_k": k,
        "records_total": report.records_total,
        "records_no_task": report.records_no_task,
        "records_usable": report.records_usable,
        "records_rejected": report.records_rejected,
        "rejected": report.rejected,
        "cross_session_breaks": report.cross_session_breaks,
        "source_frontier": receipts,
        "global": global_entry,
        "spans": summarize(report.spans),
        "per_lineage": per_lineage,
    }


def _round(value: float) -> float | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), 2)


def _format_ts(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def write_cache(report: ServiceTimeReport, path: Path, k: float = TAU_K) -> None:
    """Atomically materialize the non-authorizing projection with private mode."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_cache_payload(report, k)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.rename(path)


def tau_from_cache(
    path: Path,
    lineage: str,
    *,
    now: float | None = None,
    max_age_s: float = DEFAULT_FRESHNESS_WINDOW_S,
) -> float:
    """Read a fresh, bounded diagnostic candidate from a support-only cache."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TAU_CEIL_S
    if not isinstance(data, dict):
        return TAU_CEIL_S
    if (
        data.get("projection_kind") != SUPPORT_PROJECTION_KIND
        or data.get("effect_state") != SUPPORT_EFFECT_STATE
        or data.get("hold_reason") != SUPPORT_HOLD_REASON
        or data.get("may_authorize") is not False
    ):
        return TAU_CEIL_S
    queried_at = time.time() if now is None else now
    generated_at = parse_ts(data.get("generated_at"))
    if (
        isinstance(queried_at, bool)
        or not isinstance(queried_at, (int, float))
        or not math.isfinite(queried_at)
        or isinstance(max_age_s, bool)
        or not math.isfinite(max_age_s)
        or max_age_s <= 0
        or generated_at is None
        or generated_at > queried_at
        or queried_at - generated_at > max_age_s
    ):
        return TAU_CEIL_S
    per_lineage = data.get("per_lineage", {})
    entry = per_lineage.get(lineage) if isinstance(per_lineage, dict) else None
    if isinstance(entry, dict):
        candidate = _bounded_tau_candidate(entry.get("observed_tau_candidate_s"))
        if candidate is not None:
            return candidate
    global_entry = data.get("global", {})
    if isinstance(global_entry, dict):
        candidate = _bounded_tau_candidate(global_entry.get("observed_tau_candidate_s"))
        if candidate is not None:
            return candidate
    return TAU_CEIL_S


def _bounded_tau_candidate(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    candidate = float(value)
    if not math.isfinite(candidate) or not TAU_FLOOR_S <= candidate <= TAU_CEIL_S:
        return None
    return candidate


# ── CLI ───────────────────────────────────────────────────────────────────────


def _format_report(report: ServiceTimeReport) -> str:
    lines = [
        f"dispatch service-time support fold  (effect_state={SUPPORT_EFFECT_STATE} "
        f"records: total={report.records_total} "
        f"no_task_id={report.records_no_task} usable={report.records_usable} "
        f"rejected={report.records_rejected} "
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
    lines.append("per-lineage inter-tool gaps + non-authorizing tau candidate:")
    for role in sorted(report.per_lineage):
        dist = report.per_lineage[role]
        tau = tau_for_lineage(report, role)
        lines.append(f"  {row(role, dist)}   tau_candidate={tau:.0f}s")
    lines.append("")
    lines.append(f"HOLD: {SUPPORT_HOLD_REASON}")
    return "\n".join(lines)


def _sources(args: argparse.Namespace) -> list[Path]:
    if args.source:
        return [Path(args.source)]
    return [DEFAULT_DECISIONS_PATH, DEFAULT_METHODOLOGY_PATH]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dispatch service-time support fold")
    parser.add_argument("--report", action="store_true", help="print the distribution table")
    parser.add_argument(
        "--recompute", action="store_true", help="recompute the support-only cache"
    )
    parser.add_argument(
        "--tau", action="store_true", help="print diagnostic tau candidate for --lineage"
    )
    parser.add_argument(
        "--reap-decision",
        action="store_true",
        help="print the fail-closed Gate-0A recovery disposition (hold)",
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
