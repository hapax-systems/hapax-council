"""shared/chronicle.py — Unified observability event store.

Provides a frozen ChronicleEvent dataclass, record/query/trim functions,
and OTel span context extraction. Events are persisted as JSONL to /dev/shm.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

CHRONICLE_DIR = Path("/dev/shm/hapax-chronicle")
CHRONICLE_FILE = CHRONICLE_DIR / "events.jsonl"
RETENTION_S = 12 * 3600


# ── Model ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChronicleEvent:
    """Immutable observability event for the Hapax circulatory system.

    Fields
    ------
    ts            Unix timestamp (time.time()).
    trace_id      32-hex OTel trace ID.
    span_id       16-hex OTel span ID.
    parent_span_id  Parent OTel span ID, or None.
    source        Circulatory system name (e.g. "hapax_daimonion").
    event_type    Discriminator string (e.g. "voice.turn_start").
    payload       Arbitrary structured data.
    """

    ts: float
    trace_id: str
    span_id: str
    parent_span_id: str | None
    source: str
    event_type: str
    payload: dict = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialise to a single-line JSON string."""
        return json.dumps(
            {
                "ts": self.ts,
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "source": self.source,
                "event_type": self.event_type,
                "payload": self.payload,
            }
        )

    @classmethod
    def from_json(cls, line: str) -> ChronicleEvent:
        """Deserialise from a single-line JSON string."""
        d = json.loads(line)
        return cls(
            ts=float(d["ts"]),
            trace_id=d["trace_id"],
            span_id=d["span_id"],
            parent_span_id=d.get("parent_span_id"),
            source=d["source"],
            event_type=d["event_type"],
            payload=d.get("payload", {}),
        )


# ── OTel extraction ───────────────────────────────────────────────────────────


def current_otel_ids() -> tuple[str, str]:
    """Return (trace_id, span_id) from the active OTel span.

    Falls back to ("0" * 32, "0" * 16) when no span is active or the
    opentelemetry package is not installed.
    """
    _null = ("0" * 32, "0" * 16)
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
        return _null
    except Exception:  # noqa: BLE001
        return _null


# ── Writer ────────────────────────────────────────────────────────────────────


def record(event: ChronicleEvent, *, path: Path = CHRONICLE_FILE) -> None:
    """Append *event* to the JSONL file at *path*, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(event.to_json() + "\n")


# ── Reader ────────────────────────────────────────────────────────────────────


def query(
    *,
    since: float,
    until: float | None = None,
    source: str | None = None,
    event_type: str | None = None,
    trace_id: str | None = None,
    limit: int = 500,
    path: Path = CHRONICLE_FILE,
) -> list[ChronicleEvent]:
    """Return matching events, newest-first.

    Parameters
    ----------
    since       Inclusive lower bound (Unix timestamp).
    until       Inclusive upper bound; defaults to now.
    source      Exact source match; None = any.
    event_type  Exact event_type match; None = any.
    trace_id    Exact trace_id match; None = any.
    limit       Maximum number of results returned.
    path        JSONL file to read.
    """
    if not path.exists():
        return []

    effective_until = until if until is not None else time.time()

    results: list[ChronicleEvent] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = ChronicleEvent.from_json(raw)
                except (json.JSONDecodeError, KeyError):
                    continue

                if ev.ts < since or ev.ts > effective_until:
                    continue
                if source is not None and ev.source != source:
                    continue
                if event_type is not None and ev.event_type != event_type:
                    continue
                if trace_id is not None and ev.trace_id != trace_id:
                    continue

                results.append(ev)
    except OSError:
        return []

    # Newest-first, then enforce limit.
    results.sort(key=lambda e: e.ts, reverse=True)
    return results[:limit]


# ── Retention ─────────────────────────────────────────────────────────────────


def trim(*, retention_s: float = RETENTION_S, path: Path = CHRONICLE_FILE) -> None:
    """Drop events older than *retention_s* seconds, atomically rewriting the file.

    No-op when the file does not exist.
    """
    if not path.exists():
        return

    cutoff = time.time() - retention_s
    kept: list[str] = []

    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    ev = ChronicleEvent.from_json(stripped)
                    if ev.ts >= cutoff:
                        kept.append(stripped)
                except (json.JSONDecodeError, KeyError):
                    # Preserve malformed lines to avoid silent data loss.
                    kept.append(stripped)
    except OSError:
        return

    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            for line in kept:
                fh.write(line + "\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
