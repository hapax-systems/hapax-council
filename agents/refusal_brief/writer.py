"""Thread-safe refusal-event log writer.

Each refusal source calls ``append(event)`` inline; the writer
serialises behind a module-level lock and atomically appends one
JSON line per event. Operator never edits the log — append-only
is constitutional (any "clear log" affordance creates HITL pressure
per the spec).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path(
    os.environ.get(
        "HAPAX_REFUSALS_LOG_PATH",
        "/dev/shm/hapax-refusals/log.jsonl",
    )
)

# Refusal-event reason field hard cap. Spec: ≤160 chars; anything
# longer almost certainly belongs in a refusal-brief markdown file
# (linked via refusal_brief_link). This is a model-level constraint
# so a misuse fails at construction rather than producing oversized
# log lines that downstream consumers (waybar, sidebar) have to truncate.
REASON_MAX_CHARS = 160


class RefusalEvent(BaseModel):
    """One refusal event — structured record with no narrative voice.

    Constitutional fit: refusals are first-class data, not apologies.
    The reason field is a short rationale (≤160 chars); longer
    treatment belongs in a refusal-brief markdown file linked via
    ``refusal_brief_link``.

    Sub-block style ``public: bool`` flag is consulted by the
    public-filter pass on the awareness state spine — refusals
    flagged ``public=True`` surface in omg.lol fanout. The default
    is False because a per-event public decision is safer than a
    blanket "all refusals are public" policy (some axiom violations
    might leak operator-internal context).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    axiom: str  # e.g. "single_user", "full_auto_or_nothing"
    surface: str  # e.g. "publication-bus:bandcamp-upload"
    reason: str = Field(max_length=REASON_MAX_CHARS)
    public: bool = False
    refusal_brief_link: str | None = None
    # Refused-lifecycle extension (additive; defaults preserve existing
    # subscribers' behaviour). `transition` discriminates the five state-
    # machine transitions; `evidence_url` carries the upstream lift-evidence
    # for accepted/regressed; `cc_task_slug` ties the event back to its
    # vault note for sidebar/dashboard cross-linking.
    transition: Literal["created", "re-affirmed", "accepted", "removed", "regressed"] = "created"
    evidence_url: str | None = None
    cc_task_slug: str | None = None


# Module-level lock + counter. The lock serialises concurrent appends
# from different daemon threads (axiom guard + content resolver may
# fire simultaneously). The counter records both the axiom + surface
# so a Grafana panel can show "which axiom is being enforced most"
# alongside "which surface is refusing most".
_lock = threading.Lock()

refusal_appends_total = Counter(
    "hapax_refusal_appends_total",
    "Refusal events appended to the canonical refusal log.",
    ["axiom", "surface"],
)


def append(event: RefusalEvent, *, log_path: Path = DEFAULT_LOG_PATH) -> bool:
    """Append one event to the JSONL log; return True iff written.

    Thread-safe: holds the module lock during the parent-mkdir +
    open + write + flush path so concurrent appends never interleave
    bytes mid-line. Best-effort: file system errors log and return
    False rather than raise — refusal emission must never break the
    calling refusal-gate path.

    The ``log_path`` parameter is for tests; production uses the
    module default reading from ``HAPAX_REFUSALS_LOG_PATH``.
    """
    line = event.model_dump_json() + "\n"
    with _lock:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        except OSError:
            log.warning("refusal log append failed at %s", log_path, exc_info=True)
            return False
    refusal_appends_total.labels(axiom=event.axiom, surface=event.surface).inc()
    return True


__all__ = [
    "DEFAULT_LOG_PATH",
    "REASON_MAX_CHARS",
    "RefusalEvent",
    "append",
    "refusal_appends_total",
]
