"""Gate-event log — the measurement spine for capability-aware routing.

Appends one JSON line per routing-gate decision to a PERSISTENT path
(``~/.cache/hapax/sdlc-routing/gate-events.jsonl`` — NOT tmpfs, so it survives a
reboot). This is the substrate the cost-offload program lacked: it derives the
dev-story A/B harness, the shadow->promote counter, and the capability-coverage
scorecard. Additive and standalone — importing it has no side effects and no
caller is required to use it yet (Phase 0.2; callers wire in Phase 2+).

Design: ``~/projects/cost-offload-program/CAPABILITY-ROUTING-DESIGN-2026-06-16.md`` §4.
Capability-routing Tier-1 (ISAP ``S5-CAPABILITY-ROUTING-TIER1``).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# Persistent (NOT tmpfs): gate history must survive a reboot to be a measurement
# substrate. ``~/.cache/hapax`` is on the NVMe; ``/tmp`` / ``/dev/shm`` are tmpfs
# on this host and would be lost (the tmpfs-swap-trap). Overridable for tests.
DEFAULT_GATE_LOG = Path(
    os.environ.get(
        "HAPAX_GATE_LOG",
        str(Path.home() / ".cache" / "hapax" / "sdlc-routing" / "gate-events.jsonl"),
    )
)

GateResult = Literal["accept", "reject", "abstain", "escalate", "error"]
GateType = Literal["deterministic", "gold_verifier", "llm_acceptor", "frontier_review", "none"]


class GateEvent(BaseModel):
    """One routing-gate decision — the measured unit behind every offload route."""

    route: str  # the LiteLLM alias / model the work was routed to
    routing_class: str  # the SDLC routing-class (cross-product activity x component)
    ts: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    requirement_vector: dict[str, Any] = Field(default_factory=dict)  # the 8-dim req vector
    model_resolved: str = ""  # the concrete model LiteLLM resolved (post-fallback)
    task_hash: str = ""  # stable hash of the work unit (dedup / join key)
    gate_result: GateResult = "abstain"
    gate_type: GateType = "none"
    p_correct: float | None = None  # judge confidence when gate_type implies one
    latency_ms: float | None = None
    cost_usd: float | None = None


def append_gate_event(event: GateEvent, *, path: Path | str | None = None) -> Path:
    """Append one gate event as a JSON line to the persistent gate log.

    Creates the parent directory if needed; returns the path written to. A
    serialization-clean event is always written; an unwritable path raises the
    OSError to the caller — a lost measurement must surface, never silently pass.
    """
    target = Path(path) if path is not None else DEFAULT_GATE_LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(event.model_dump_json() + "\n")
    return target


def read_gate_events(*, path: Path | str | None = None) -> Iterator[GateEvent]:
    """Yield gate events from the log; skip blank/corrupt lines, never raise."""
    target = Path(path) if path is not None else DEFAULT_GATE_LOG
    if not target.exists():
        return
    with target.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                yield GateEvent.model_validate_json(line)
            except Exception:  # noqa: BLE001 — a corrupt line must not abort the read
                continue


def is_persistent(path: Path | str | None = None) -> bool:
    """True if the log path is on persistent storage (NOT tmpfs/ramfs).

    The measurement substrate is worthless if a reboot eats it (tmpfs-swap-trap).
    Best-effort: walk to the nearest existing ancestor and reject the host's tmpfs
    mounts (``/tmp``, ``/dev/shm``); default True when the path can't be resolved.
    """
    target = Path(path) if path is not None else DEFAULT_GATE_LOG
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        resolved = str(probe.resolve())
    except OSError:
        return True
    return not (
        resolved == "/tmp" or resolved.startswith("/tmp/") or resolved.startswith("/dev/shm")
    )
