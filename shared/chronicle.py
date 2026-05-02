"""shared/chronicle.py — Unified observability event store.

Provides a frozen ChronicleEvent dataclass, record/query/trim functions,
and OTel span context extraction. Events are persisted as JSONL to /dev/shm.

Per cc-task ``chronicle-event-evidence-envelope-migration`` (WSJF 9.4),
events now carry an optional **evidence envelope** — durable event_id,
valid/transaction-time, aperture/speech/impulse/triad refs, public scope,
evidence class, evidence refs, and a temporal-span ref. Every new field is
optional with a backward-compatible default so callers built against the
pre-migration schema continue to work unchanged. Pre-migration JSONL lines
deserialize cleanly (the new fields fall back to their defaults).

Authority downgrade logic (zero trace/span or missing refs → diagnostic
ceiling) lives in the consumer layer (director snapshot, autonomous
narration, public-claim gate); this module ships the schema + query
filters those consumers need to enforce the policy.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

CHRONICLE_DIR = Path("/dev/shm/hapax-chronicle")
CHRONICLE_FILE = CHRONICLE_DIR / "events.jsonl"
RETENTION_S = 12 * 3600


# ── Model ─────────────────────────────────────────────────────────────────────


#: Allowed values for ``ChronicleEvent.public_scope``. The value drives
#: downstream consumer routing — public-event adapters honor only
#: ``"public"`` rows; the autonomous-narration WCS gate refuses to
#: render anything outside this set.
PUBLIC_SCOPES: tuple[str, ...] = ("public", "private", "diagnostic")

#: Allowed values for ``ChronicleEvent.evidence_class``. Mirrors the
#: PerceptualField witness-map taxonomy so downstream consumers can
#: filter chronicle events through the same evidence classification
#: surface they already use for percept fields.
EVIDENCE_CLASSES: tuple[str, ...] = (
    "sensor",
    "public_event",
    "route",
    "archive",
    "classifier",
    "derived_state",
    "operator_command",
    "diagnostic",
)


def _new_event_id() -> str:
    """Generate a durable event ID. UUID4 is fast and collision-safe at
    chronicle's expected event volume (a few k/s peak)."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class ChronicleEvent:
    """Immutable observability event for the Hapax circulatory system.

    Pre-migration fields
    --------------------
    ts              Unix timestamp (time.time()) — back-compat alias for
                    ``transaction_time``.
    trace_id        32-hex OTel trace ID.
    span_id         16-hex OTel span ID.
    parent_span_id  Parent OTel span ID, or None.
    source          Circulatory system name (e.g. "hapax_daimonion").
    event_type      Discriminator string (e.g. "voice.turn_start").
    payload         Arbitrary structured data.

    Evidence-envelope fields (per cc-task chronicle-event-evidence-
    envelope-migration; all optional with backward-compatible defaults)
    --------------------
    event_id            Durable per-event identifier; auto-assigned via
                        UUID4 if not supplied.
    valid_time          When the event is true in the world. Defaults
                        to ``ts``; consumer-supplied for events whose
                        valid time differs from the recording moment
                        (e.g., a back-filled archive entry).
    transaction_time    When the event was recorded. Defaults to ``ts``.
    aperture_ref        Aperture registry reference (canonical aperture
                        ID), or empty string if none.
    public_scope        ``"public"`` | ``"private"`` | ``"diagnostic"``;
                        defaults to ``"private"`` (legacy events were
                        all private-scope by construction).
    speech_event_ref    Optional reference to a speech event row.
    impulse_ref         Optional reference to an impulse row.
    triad_ref           Optional reference to a narration triad row.
    evidence_class      One of EVIDENCE_CLASSES; empty string if none.
    evidence_refs       Tuple of free-form evidence references (commit
                        SHAs, frame URIs, claim IDs, etc.).
    temporal_span_ref   Optional reference to a TemporalSpan registry row.
    """

    ts: float
    trace_id: str
    span_id: str
    parent_span_id: str | None
    source: str
    event_type: str
    payload: dict = field(default_factory=dict)

    # Evidence-envelope fields (all optional, backward-compatible).
    event_id: str = field(default_factory=_new_event_id)
    valid_time: float | None = None
    transaction_time: float | None = None
    aperture_ref: str = ""
    public_scope: str = "private"
    speech_event_ref: str = ""
    impulse_ref: str = ""
    triad_ref: str = ""
    evidence_class: str = ""
    evidence_refs: tuple[str, ...] = ()
    temporal_span_ref: str = ""

    @property
    def effective_valid_time(self) -> float:
        """Valid time, defaulting to ``ts`` when not explicitly set."""
        return self.ts if self.valid_time is None else self.valid_time

    @property
    def effective_transaction_time(self) -> float:
        """Transaction time, defaulting to ``ts`` when not explicitly set."""
        return self.ts if self.transaction_time is None else self.transaction_time

    @property
    def has_full_provenance(self) -> bool:
        """Whether the event carries non-zero trace/span IDs.

        Consumers downgrade authority for events lacking trace/span;
        this property exposes the predicate without each consumer
        re-implementing the zero-fill check. Per the cc-task: 'Zero
        trace/span or missing refs downgrade claim authority unless
        explicitly diagnostic.'
        """
        return self.trace_id != "0" * 32 and self.span_id != "0" * 16

    def to_json(self) -> str:
        """Serialise to a single-line JSON string.

        Pre-migration fields are emitted unconditionally so legacy
        readers stay compatible. Evidence-envelope fields are emitted
        only when they carry non-default values, keeping JSONL files
        small and pre-migration consumers from tripping on unknown keys.
        """
        out: dict = {
            "ts": self.ts,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "source": self.source,
            "event_type": self.event_type,
            "payload": self.payload,
        }
        # Always include event_id — it's the durable handle consumers
        # will use to deduplicate / cross-reference; emitting it
        # universally costs ~36 bytes/line and lets readers index on
        # it without an existence check.
        out["event_id"] = self.event_id
        # Evidence-envelope fields: only emit when set so legacy lines
        # stay byte-equivalent and JSON diffs in tests remain stable.
        if self.valid_time is not None:
            out["valid_time"] = self.valid_time
        if self.transaction_time is not None:
            out["transaction_time"] = self.transaction_time
        if self.aperture_ref:
            out["aperture_ref"] = self.aperture_ref
        # public_scope is always present so consumers can filter
        # without a "default to private" hop on every read.
        out["public_scope"] = self.public_scope
        if self.speech_event_ref:
            out["speech_event_ref"] = self.speech_event_ref
        if self.impulse_ref:
            out["impulse_ref"] = self.impulse_ref
        if self.triad_ref:
            out["triad_ref"] = self.triad_ref
        if self.evidence_class:
            out["evidence_class"] = self.evidence_class
        if self.evidence_refs:
            out["evidence_refs"] = list(self.evidence_refs)
        if self.temporal_span_ref:
            out["temporal_span_ref"] = self.temporal_span_ref
        return json.dumps(out)

    @classmethod
    def from_json(cls, line: str) -> ChronicleEvent:
        """Deserialise from a single-line JSON string.

        Pre-migration JSONL lines (no evidence-envelope fields) round-
        trip cleanly: the new fields fall back to dataclass defaults.
        """
        d = json.loads(line)
        evidence_refs_raw = d.get("evidence_refs", ())
        evidence_refs = (
            tuple(str(r) for r in evidence_refs_raw)
            if isinstance(evidence_refs_raw, (list, tuple))
            else ()
        )
        # Pre-migration lines have no event_id; assign one at read time
        # so downstream consumers can rely on the field being populated.
        # The synthetic ID is deterministic so re-reads produce the same
        # value (using the trace_id/span_id/ts triple as the seed).
        legacy_event_id = d.get("event_id")
        if not legacy_event_id:
            legacy_event_id = uuid.uuid5(
                uuid.NAMESPACE_OID,
                f"{d.get('trace_id', '')}:{d.get('span_id', '')}:{d.get('ts', '')}",
            ).hex
        return cls(
            ts=float(d["ts"]),
            trace_id=d["trace_id"],
            span_id=d["span_id"],
            parent_span_id=d.get("parent_span_id"),
            source=d["source"],
            event_type=d["event_type"],
            payload=d.get("payload", {}),
            event_id=legacy_event_id,
            valid_time=(float(d["valid_time"]) if d.get("valid_time") is not None else None),
            transaction_time=(
                float(d["transaction_time"]) if d.get("transaction_time") is not None else None
            ),
            aperture_ref=str(d.get("aperture_ref", "")),
            public_scope=str(d.get("public_scope", "private")),
            speech_event_ref=str(d.get("speech_event_ref", "")),
            impulse_ref=str(d.get("impulse_ref", "")),
            triad_ref=str(d.get("triad_ref", "")),
            evidence_class=str(d.get("evidence_class", "")),
            evidence_refs=evidence_refs,
            temporal_span_ref=str(d.get("temporal_span_ref", "")),
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
    aperture_ref: str | None = None,
    public_scope: str | None = None,
    speech_event_ref: str | None = None,
    evidence_class: str | None = None,
    temporal_span_ref: str | None = None,
    limit: int = 500,
    path: Path = CHRONICLE_FILE,
) -> list[ChronicleEvent]:
    """Return matching events, newest-first.

    Parameters
    ----------
    since               Inclusive lower bound (Unix timestamp).
    until               Inclusive upper bound; defaults to now.
    source              Exact source match; None = any.
    event_type          Exact event_type match; None = any.
    trace_id            Exact trace_id match; None = any.
    aperture_ref        Exact aperture_ref match; None = any. Per
                        cc-task chronicle-event-evidence-envelope-
                        migration: lets aperture-scoped consumers
                        filter without re-implementing the predicate.
    public_scope        Exact public_scope match; None = any. Pass
                        ``"public"`` to surface only public-scope
                        events for the public-event adapter; pass
                        ``"private"`` for private-only audits.
    speech_event_ref    Exact speech_event_ref match; None = any.
    evidence_class      Exact evidence_class match; None = any.
    temporal_span_ref   Exact temporal_span_ref match; None = any.
    limit               Maximum number of results returned.
    path                JSONL file to read.

    Drop #23 Option A: walks the JSONL file in reverse (newest-first) so
    we can early-exit on `ts < since` and stop once we have `limit`
    results. Pre-fix this function read every line, parsed every event,
    then sorted at the end — `~85%` of CPU time was in `json.loads` for
    events that were filtered out by the `since` bound. For a 1-hour
    query on a 2.8-hour file the reverse walk parses `~36%` of lines;
    for a 15-minute query, `~9%`. Median latency drops from
    `~1500 ms → ~215 ms` per drop #23 §3.1 measurements. Tmpfs read
    of the whole file is cheap — chronicle is `RETENTION_S=12h` and the
    trim() helper keeps the file bounded; the doc estimates `~14 MB`
    typical, well within memory.
    """
    if not path.exists():
        return []

    effective_until = until if until is not None else time.time()

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    results: list[ChronicleEvent] = []
    for raw in reversed(lines):
        if not raw:
            continue
        try:
            ev = ChronicleEvent.from_json(raw)
        except (json.JSONDecodeError, KeyError):
            continue

        if ev.ts > effective_until:
            continue
        if ev.ts < since:
            break  # Reverse walk: every earlier line is also too old.

        if source is not None and ev.source != source:
            continue
        if event_type is not None and ev.event_type != event_type:
            continue
        if trace_id is not None and ev.trace_id != trace_id:
            continue
        if aperture_ref is not None and ev.aperture_ref != aperture_ref:
            continue
        if public_scope is not None and ev.public_scope != public_scope:
            continue
        if speech_event_ref is not None and ev.speech_event_ref != speech_event_ref:
            continue
        if evidence_class is not None and ev.evidence_class != evidence_class:
            continue
        if temporal_span_ref is not None and ev.temporal_span_ref != temporal_span_ref:
            continue

        results.append(ev)
        if len(results) >= limit:
            break  # Reverse walk produces newest-first; stop at limit.

    return results


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
