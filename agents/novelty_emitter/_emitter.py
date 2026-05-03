"""Implementation of the novelty-shift emitter (cc-task u3)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

GQI_LOW_THRESHOLD: float = 0.4
GQI_HIGH_THRESHOLD: float = 0.7
DEFAULT_GQI_PATH = Path("/dev/shm/hapax-daimonion/grounding-quality.json")
DEFAULT_IMPINGEMENTS_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
DEFAULT_TEXTFILE = Path(
    "/var/lib/node_exporter/textfile_collector/hapax_novelty_shift_emitter.prom"
)
DEFAULT_STATE_PATH = Path("/dev/shm/hapax-dmn/novelty-emitter-state.json")
METRIC_PREFIX = "hapax_novelty_shift_impingement"

# u3-recruitment-outcome-telemetry-back-to-emitter
# `recent-recruitment.json` is the AffordancePipeline + downstream
# consumers' shared write-surface (one entry per family-key with
# `last_recruited_ts`). When we dispatch a novelty.shift impingement,
# the pipeline normally produces SOME family recruitment (e.g.
# preset.bias, ward.size, structural.placement) within a short window;
# absence of any new recruitment within ABSORPTION_WINDOW_S is the
# "absorbed" outcome — the impingement landed but no consumer picked
# it up.
DEFAULT_RECENT_RECRUITMENT_PATH = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
ABSORPTION_WINDOW_S: float = 5.0


@dataclass(frozen=True)
class NoveltyShiftReading:
    """Snapshot of the gqi signal at a single tick."""

    gqi: float
    timestamp: float
    source_age_s: float


def read_gqi(path: Path = DEFAULT_GQI_PATH) -> NoveltyShiftReading | None:
    """Load the latest gqi reading. Returns None on missing/unparseable file."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    gqi = data.get("gqi")
    ts = data.get("timestamp")
    if gqi is None or ts is None:
        return None
    try:
        gqi_f = float(gqi)
        ts_f = float(ts)
    except (TypeError, ValueError):
        return None
    return NoveltyShiftReading(gqi=gqi_f, timestamp=ts_f, source_age_s=time.time() - ts_f)


def _load_prev_state(
    state_path: Path,
) -> tuple[float | None, int, int, list[float]]:
    """Return (prev_gqi, dispatched_total, absorbed_total, pending_dispatches).

    Defaults on miss / parse failure. ``pending_dispatches`` is the list
    of timestamps of dispatched impingements awaiting outcome attribution
    (recruitment-window resolution at next tick).
    """
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, 0, 0, []
    prev = data.get("prev_gqi")
    dispatched = data.get("dispatched_total", 0)
    absorbed = data.get("absorbed_total", 0)
    pending = data.get("pending_dispatches", [])
    try:
        prev_f = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev_f = None
    try:
        dispatched_i = int(dispatched)
    except (TypeError, ValueError):
        dispatched_i = 0
    try:
        absorbed_i = int(absorbed)
    except (TypeError, ValueError):
        absorbed_i = 0
    pending_list: list[float] = []
    if isinstance(pending, list):
        for x in pending:
            try:
                pending_list.append(float(x))
            except (TypeError, ValueError):
                continue
    return prev_f, dispatched_i, absorbed_i, pending_list


def _save_state(
    state_path: Path,
    gqi: float,
    dispatched_total: int,
    absorbed_total: int = 0,
    pending_dispatches: list[float] | None = None,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".json.tmp")
    payload = {
        "prev_gqi": gqi,
        "dispatched_total": dispatched_total,
        "absorbed_total": absorbed_total,
        "pending_dispatches": list(pending_dispatches or []),
    }
    tmp.write_text(json.dumps(payload))
    tmp.replace(state_path)


def read_max_recruitment_ts(path: Path = DEFAULT_RECENT_RECRUITMENT_PATH) -> float | None:
    """Return the max ``last_recruited_ts`` across all families in
    ``recent-recruitment.json``. None on missing/malformed/empty file.

    The recent-recruitment.json schema is
    ``{"families": {<family-key>: {"last_recruited_ts": float, ...}, ...},
    "updated_at": float}``. Any family being recruited within the
    absorption window after our dispatch counts as "novelty.shift
    consumed" — we don't try to attribute per-family because the
    AffordancePipeline can recruit any subset of families in response.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    families = data.get("families")
    if not isinstance(families, dict) or not families:
        return None
    max_ts: float | None = None
    for entry in families.values():
        if not isinstance(entry, dict):
            continue
        ts = entry.get("last_recruited_ts")
        try:
            ts_f = float(ts) if ts is not None else None
        except (TypeError, ValueError):
            continue
        if ts_f is None:
            continue
        if max_ts is None or ts_f > max_ts:
            max_ts = ts_f
    return max_ts


def resolve_pending_dispatches(
    pending: list[float],
    *,
    max_recruitment_ts: float | None,
    now: float,
    window_s: float = ABSORPTION_WINDOW_S,
) -> tuple[list[float], int]:
    """Partition pending dispatches into (still-pending, newly-absorbed).

    A dispatch is RECRUITED iff there exists a recruitment with
    ``last_recruited_ts >= dispatch_ts`` (any family — the impingement
    landed and SOMETHING acted on it). RECRUITED dispatches are dropped
    from the pending list (no double-counting against the dispatched
    counter). A dispatch is ABSORBED iff ``now - dispatch_ts > window_s``
    AND no recruitment occurred since the dispatch — drop + count.
    Otherwise still pending.

    Returns ``(still_pending, newly_absorbed_count)``.
    """
    still_pending: list[float] = []
    newly_absorbed = 0
    for dispatch_ts in pending:
        recruited = max_recruitment_ts is not None and max_recruitment_ts >= dispatch_ts
        if recruited:
            continue  # consumed — drop, no absorbed increment
        if now - dispatch_ts > window_s:
            newly_absorbed += 1
            continue
        still_pending.append(dispatch_ts)
    return still_pending, newly_absorbed


def detect_rising_shift(
    prev_gqi: float | None,
    current_gqi: float,
    *,
    low: float = GQI_LOW_THRESHOLD,
    high: float = GQI_HIGH_THRESHOLD,
) -> bool:
    """True iff this tick crossed from below ``low`` to above ``high``."""
    if prev_gqi is None:
        return False
    return prev_gqi < low and current_gqi > high


def build_impingement_payload(
    reading: NoveltyShiftReading,
    prev_gqi: float | None,
    *,
    now: float | None = None,
) -> dict:
    """Build the JSONL-bus payload for a novelty.shift impingement.

    Mirrors the ``content.too-similar-recently`` payload shape that the
    AffordancePipeline already consumes (see
    ``shared.affordance_pipeline._maybe_emit_perceptual_distance_impingement``).
    """
    timestamp = now if now is not None else time.time()
    delta = reading.gqi - (prev_gqi if prev_gqi is not None else 0.0)
    narrative = (
        f"Grounding quality jumped from {prev_gqi:.2f} to {reading.gqi:.2f} "
        f"(delta {delta:+.2f}) — the surface has fresh ground; widen the "
        f"perceptual register and reach for a novel preset family."
        if prev_gqi is not None
        else (
            f"Grounding quality at {reading.gqi:.2f} — fresh ground; widen the perceptual register."
        )
    )
    return {
        "id": uuid.uuid4().hex[:12],
        "timestamp": timestamp,
        "source": "agents.novelty_emitter.gqi_shift",
        "type": "novelty",
        "strength": min(1.0, max(0.0, reading.gqi)),
        "content": {
            "metric": "gqi_rising_shift",
            "gqi": round(reading.gqi, 3),
            "prev_gqi": round(prev_gqi, 3) if prev_gqi is not None else None,
            "delta": round(delta, 3),
            "narrative": narrative,
        },
        "context": {},
        "intent_family": "novelty.shift",
        "embedding": None,
        "interrupt_token": None,
        "parent_id": None,
        "trace_id": None,
        "span_id": None,
    }


def append_impingement(payload: dict, bus_path: Path = DEFAULT_IMPINGEMENTS_PATH) -> bool:
    """Append a payload to the impingement bus. Returns False on write failure."""
    try:
        bus_path.parent.mkdir(parents=True, exist_ok=True)
        with bus_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except OSError:
        log.warning("novelty_shift impingement append failed", exc_info=True)
        return False
    return True


def write_textfile(textfile: Path, dispatched_total: int, absorbed_total: int) -> bool:
    """Render the Prometheus textfile via tmp+rename."""
    try:
        textfile.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    body = (
        f"# HELP {METRIC_PREFIX}_total Counter of novelty.shift impingements emitted by gqi_shift detector, by outcome\n"
        f"# TYPE {METRIC_PREFIX}_total counter\n"
        f'{METRIC_PREFIX}_total{{outcome="dispatched"}} {dispatched_total}\n'
        f'{METRIC_PREFIX}_total{{outcome="absorbed"}} {absorbed_total}\n'
    )
    tmp = textfile.with_name(f"{textfile.name}.tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(textfile)
    except OSError:
        return False
    return True


@dataclass
class NoveltyShiftEmitter:
    """One-shot emitter; intended to be called every ~1s by a systemd timer.

    The state file tracks ``prev_gqi`` so a single tick can decide whether
    we crossed a rising-edge threshold. Cumulative ``dispatched`` /
    ``absorbed`` counters live in the same state file so the Prometheus
    textfile is monotonic-counter-correct across timer firings.
    """

    gqi_path: Path = DEFAULT_GQI_PATH
    bus_path: Path = DEFAULT_IMPINGEMENTS_PATH
    textfile: Path = DEFAULT_TEXTFILE
    state_path: Path = DEFAULT_STATE_PATH
    recent_recruitment_path: Path = DEFAULT_RECENT_RECRUITMENT_PATH
    low: float = GQI_LOW_THRESHOLD
    high: float = GQI_HIGH_THRESHOLD
    absorption_window_s: float = ABSORPTION_WINDOW_S

    def tick(self) -> dict:
        """Run one tick. Returns a structured report dict.

        u3 absorbed-counter wiring: each dispatched impingement is held
        in ``pending_dispatches`` until either (a) a recruitment is
        observed in ``recent-recruitment.json`` after its timestamp
        (RECRUITED, dropped), or (b) ``absorption_window_s`` elapses
        without recruitment (ABSORBED, increment + drop).
        """
        reading = read_gqi(self.gqi_path)
        if reading is None:
            return {"status": "skipped", "reason": "gqi file missing or unparseable"}

        prev_gqi, dispatched_total, absorbed_total, pending_dispatches = _load_prev_state(
            self.state_path
        )

        # Resolve pending dispatches against current recruitment state.
        max_recruitment_ts = read_max_recruitment_ts(self.recent_recruitment_path)
        now = time.time()
        pending_dispatches, newly_absorbed = resolve_pending_dispatches(
            pending_dispatches,
            max_recruitment_ts=max_recruitment_ts,
            now=now,
            window_s=self.absorption_window_s,
        )
        absorbed_total += newly_absorbed

        shifted = detect_rising_shift(prev_gqi, reading.gqi, low=self.low, high=self.high)
        # outcome categorises THIS tick: "dispatched" if impingement
        # emitted, else "absorbed" (no-shift or write_failed). Backward-
        # compat with pre-u3 callers. The precise absorbed-counter
        # semantic (impingement was emitted but not recruited within
        # window) is on `absorbed_total` and `newly_absorbed`.
        outcome = "absorbed"
        if shifted:
            payload = build_impingement_payload(reading, prev_gqi)
            if append_impingement(payload, self.bus_path):
                dispatched_total += 1
                outcome = "dispatched"
                # Track this dispatch for outcome attribution at next tick.
                pending_dispatches.append(now)
            else:
                outcome = "write_failed"

        write_textfile(self.textfile, dispatched_total, absorbed_total)
        _save_state(
            self.state_path,
            reading.gqi,
            dispatched_total,
            absorbed_total=absorbed_total,
            pending_dispatches=pending_dispatches,
        )

        return {
            "status": outcome,
            "gqi": round(reading.gqi, 3),
            "prev_gqi": round(prev_gqi, 3) if prev_gqi is not None else None,
            "shifted": shifted,
            "dispatched_total": dispatched_total,
            "absorbed_total": absorbed_total,
            "newly_absorbed": newly_absorbed,
            "pending_dispatches": len(pending_dispatches),
        }


def emit_if_shifted(
    *,
    gqi_path: Path = DEFAULT_GQI_PATH,
    bus_path: Path = DEFAULT_IMPINGEMENTS_PATH,
    textfile: Path = DEFAULT_TEXTFILE,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict:
    """One-shot convenience wrapper — used by the systemd-timer-driven CLI."""
    emitter = NoveltyShiftEmitter(
        gqi_path=gqi_path,
        bus_path=bus_path,
        textfile=textfile,
        state_path=state_path,
    )
    return emitter.tick()
