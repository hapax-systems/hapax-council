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


def _load_prev_state(state_path: Path) -> tuple[float | None, int]:
    """Return (prev_gqi, dispatched_count) from the state file. Defaults on miss."""
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, 0
    prev = data.get("prev_gqi")
    dispatched = data.get("dispatched_total", 0)
    try:
        prev_f = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev_f = None
    try:
        dispatched_i = int(dispatched)
    except (TypeError, ValueError):
        dispatched_i = 0
    return prev_f, dispatched_i


def _save_state(state_path: Path, gqi: float, dispatched_total: int) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"prev_gqi": gqi, "dispatched_total": dispatched_total}))
    tmp.replace(state_path)


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
    low: float = GQI_LOW_THRESHOLD
    high: float = GQI_HIGH_THRESHOLD

    def tick(self) -> dict:
        """Run one tick. Returns a structured report dict."""
        reading = read_gqi(self.gqi_path)
        if reading is None:
            return {"status": "skipped", "reason": "gqi file missing or unparseable"}

        prev_gqi, dispatched_total = _load_prev_state(self.state_path)
        absorbed_total = 0  # not yet wired to recruitment-outcome telemetry

        shifted = detect_rising_shift(prev_gqi, reading.gqi, low=self.low, high=self.high)
        outcome = "absorbed"
        if shifted:
            payload = build_impingement_payload(reading, prev_gqi)
            if append_impingement(payload, self.bus_path):
                dispatched_total += 1
                outcome = "dispatched"
            else:
                outcome = "write_failed"

        write_textfile(self.textfile, dispatched_total, absorbed_total)
        _save_state(self.state_path, reading.gqi, dispatched_total)

        return {
            "status": outcome,
            "gqi": round(reading.gqi, 3),
            "prev_gqi": round(prev_gqi, 3) if prev_gqi is not None else None,
            "shifted": shifted,
            "dispatched_total": dispatched_total,
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
