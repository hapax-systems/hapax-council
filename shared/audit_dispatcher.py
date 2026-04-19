"""shared/audit_dispatcher.py — Cross-agent audit dispatcher (stub).

Enqueue-side: ``enqueue_audit`` is callable from any Gemini call-site. It
appends a JSONL record to ``/dev/shm/hapax-audit-queue.jsonl`` and increments
a Prometheus counter. Early-returns when the ``AuditPoint`` is disabled.

Cycle-side: ``run_audit_cycle`` drains the queue and (eventually) dispatches
to Claude via LiteLLM. The LLM invocation itself is NOT implemented here —
this is scaffolding. The dispatch boundary is marked with a TODO and the
function writes a placeholder finding record.

No live call-site currently invokes ``enqueue_audit``. Activation procedure:
``docs/governance/cross-agent-audit.md`` §12.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.audit_registry import AuditPoint

log = logging.getLogger(__name__)

# Queue + finding paths ------------------------------------------------------

AUDIT_QUEUE_PATH: Path = Path(
    os.environ.get("HAPAX_AUDIT_QUEUE", "/dev/shm/hapax-audit-queue.jsonl")
)

AUDIT_FINDINGS_DIR: Path = Path(os.environ.get("HAPAX_AUDIT_FINDINGS", "rag-sources/audits"))

# Backpressure --------------------------------------------------------------
# If the queue file exceeds this many lines, new enqueues become no-ops and
# increment the drop counter. Prevents unbounded memory use during scaffolding
# activation when a call-site is newly wired and producing more records than
# the (not-yet-real) dispatcher can drain.
AUDIT_QUEUE_MAX_DEPTH: int = int(os.environ.get("HAPAX_AUDIT_QUEUE_MAX_DEPTH", "1000"))


# Prometheus metrics (tolerate absence of prometheus_client) -----------------

_METRICS_AVAILABLE = False
try:
    from prometheus_client import Counter

    _enqueued_total = Counter(
        "hapax_audit_enqueued_total",
        "Audit jobs enqueued, labelled by audit_id.",
        ("audit_id",),
    )
    _completed_total = Counter(
        "hapax_audit_completed_total",
        "Audit jobs completed with a finding written, labelled by audit_id and severity.",
        ("audit_id", "severity"),
    )
    _dropped_total = Counter(
        "hapax_audit_dropped_total",
        "Audit jobs dropped, labelled by audit_id and reason.",
        ("audit_id", "reason"),
    )
    _METRICS_AVAILABLE = True
except ImportError:  # pragma: no cover — prod always has prometheus_client
    _enqueued_total = None  # type: ignore[assignment]
    _completed_total = None  # type: ignore[assignment]
    _dropped_total = None  # type: ignore[assignment]


def _inc(counter: Any, **labels: str) -> None:
    """Increment a Prometheus counter; no-op if the client is unavailable."""
    if counter is None:
        return
    try:
        counter.labels(**labels).inc()
    except Exception:  # pragma: no cover — never raise into the caller
        log.debug("Audit metric increment failed", exc_info=True)


# Enqueue side --------------------------------------------------------------


def _queue_depth() -> int:
    """Return current queue depth (line count). Zero if queue does not exist."""
    try:
        with AUDIT_QUEUE_PATH.open("rb") as fh:
            return sum(1 for _ in fh)
    except FileNotFoundError:
        return 0
    except OSError:
        return 0


def enqueue_audit(
    audit_point: AuditPoint,
    input_context: dict[str, Any],
    provider_output: str,
) -> None:
    """Enqueue a Gemini call for asynchronous Claude audit.

    Early-returns when the audit point is disabled (the default). Early-returns
    when queue depth is at or above ``AUDIT_QUEUE_MAX_DEPTH`` (drops increment
    ``hapax_audit_dropped_total{reason="backpressure"}``).

    Safe to call from any context. Never raises into the caller — enqueue
    failures are logged and increment a drop counter.
    """
    if not audit_point.enabled:
        return

    if _queue_depth() >= AUDIT_QUEUE_MAX_DEPTH:
        _inc(_dropped_total, audit_id=audit_point.audit_id, reason="backpressure")
        return

    record = {
        "audit_id": audit_point.audit_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "provider": audit_point.provider,
        "call_site": audit_point.call_site,
        "auditor": audit_point.auditor,
        "severity_floor": audit_point.severity_floor,
        "sampling_rate": audit_point.sampling_rate,
        "input_context": input_context,
        "provider_output": provider_output,
    }

    try:
        AUDIT_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_QUEUE_PATH.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        log.warning("Audit enqueue failed for %s: %s", audit_point.audit_id, exc)
        _inc(_dropped_total, audit_id=audit_point.audit_id, reason="enqueue-error")
        return

    _inc(_enqueued_total, audit_id=audit_point.audit_id)


# Cycle side ----------------------------------------------------------------


def _drain_queue() -> list[dict[str, Any]]:
    """Atomically drain the audit queue. Returns the list of records."""
    if not AUDIT_QUEUE_PATH.exists():
        return []
    # Atomic-enough for the scaffolding case: move the queue aside, read it.
    # Real dispatch will need coordinated rotation with a lockfile.
    tmp = AUDIT_QUEUE_PATH.with_suffix(".jsonl.draining")
    try:
        AUDIT_QUEUE_PATH.rename(tmp)
    except FileNotFoundError:
        return []

    records: list[dict[str, Any]] = []
    try:
        with tmp.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("Malformed audit record dropped: %s", line[:200])
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return records


def _write_finding(record: dict[str, Any], finding_text: str, severity: str) -> None:
    """Write a finding file to ``rag-sources/audits/``."""
    AUDIT_FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = record.get("timestamp", datetime.now(UTC).isoformat()).replace(":", "-")
    audit_id = record.get("audit_id", "unknown")
    target = AUDIT_FINDINGS_DIR / f"{ts}-{audit_id}.md"
    body = (
        f"# Audit finding — {audit_id}\n\n"
        f"- timestamp: {record.get('timestamp')}\n"
        f"- provider: {record.get('provider')}\n"
        f"- call_site: {record.get('call_site')}\n"
        f"- auditor: {record.get('auditor')}\n"
        f"- severity: {severity}\n\n"
        "## Finding\n\n"
        f"{finding_text}\n"
    )
    target.write_text(body)


async def run_audit_cycle() -> int:
    """Drain the queue and produce findings. Returns record count processed.

    Scaffolding behavior: drains the queue, writes a placeholder finding per
    record at the audit point's ``severity_floor``, and increments the
    completion counter. Does NOT actually call the auditor LLM.

    Activation work (separate PR):
    - Replace the placeholder-finding block below with a LiteLLM invocation
      against ``record["auditor"]`` using a grounded audit prompt that
      references ``docs/governance/cross-agent-audit.md`` §3.
    - Structured output schema covering the six audit dimensions.
    - Severity aggregation: each dimension's worst score → overall severity,
      bounded below by ``severity_floor``.
    - Escalation plumbing per §5 (ntfy on critical, weekly digest timer).
    """
    records = _drain_queue()
    for record in records:
        severity = record.get("severity_floor", "low")
        # TODO(audit-activation): dispatch to auditor LLM here.
        # LiteLLM call should use ``record["auditor"]`` (claude-opus or
        # claude-sonnet), a grounded audit prompt that references the
        # governance doc §3 dimensions, and structured output. For now we
        # emit a placeholder finding so the finding path is exercised end
        # to end.
        finding_text = (
            "Placeholder finding — audit dispatcher is scaffolding.\n"
            "No auditor LLM was invoked. This record documents that the\n"
            "queue → finding path is live; the LLM dispatch boundary is\n"
            "TODO(audit-activation)."
        )
        try:
            _write_finding(record, finding_text, severity)
        except OSError as exc:
            log.warning("Audit finding write failed: %s", exc)
            _inc(
                _dropped_total,
                audit_id=record.get("audit_id", "unknown"),
                reason="finding-write-error",
            )
            continue
        _inc(
            _completed_total,
            audit_id=record.get("audit_id", "unknown"),
            severity=severity,
        )
    return len(records)


__all__ = [
    "AUDIT_FINDINGS_DIR",
    "AUDIT_QUEUE_MAX_DEPTH",
    "AUDIT_QUEUE_PATH",
    "enqueue_audit",
    "run_audit_cycle",
]
