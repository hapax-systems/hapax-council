"""Refusal-as-data registry: append-only JSONL log of refusal events.

Constitutional fit (Hapax provenance): refusals are first-class data,
not apologies. Every gate firing — every below-floor or unmatched
assertion the LLM was asked to retract — is a citable record. The
log is append-only; "clear log" affordances create human-in-the-loop
pressure, which is the very thing this substrate is meant to avoid.

Usage::

    from hapax_refusals import RefusalEvent, RefusalRegistry
    from datetime import UTC, datetime

    registry = RefusalRegistry()  # default: /dev/shm/hapax-refusals/log.jsonl
    registry.append(RefusalEvent(
        timestamp=datetime.now(UTC),
        axiom="claim_below_floor",
        surface="refusal_gate:director",
        reason="vinyl_is_playing posterior 0.42 < director floor 0.60",
    ))

The default log path is ``/dev/shm/hapax-refusals/log.jsonl`` so the
default behavior is RAM-only (volatile, fast, fail-cheap). Set
``HAPAX_REFUSALS_LOG_PATH`` to override (or pass ``log_path=`` to
``RefusalRegistry``).

Append is thread-safe and best-effort: filesystem errors are logged
and swallowed. Refusal-emission paths must NEVER break the calling
gate — observability that breaks the verifier is worse than no
observability.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


# Hard cap on the ``reason`` field. Anything longer almost certainly
# belongs in a long-form refusal-brief markdown file (linked via
# ``refusal_brief_link``) rather than the per-event log line. This
# keeps downstream consumers (waybar, sidebar, Grafana) from having
# to truncate.
REASON_MAX_CHARS = 160


def _default_log_path() -> Path:
    return Path(
        os.environ.get(
            "HAPAX_REFUSALS_LOG_PATH",
            "/dev/shm/hapax-refusals/log.jsonl",
        )
    )


class RefusalEvent(BaseModel):
    """One refusal-as-data record — structured, no narrative voice.

    Attributes:
        timestamp: When the refusal fired. Use a timezone-aware
            ``datetime`` (``datetime.now(UTC)`` is the canonical
            constructor); naive datetimes are accepted but downstream
            consumers may treat them as UTC.
        axiom: Why the refusal fired. Free-form short string (e.g.
            ``"claim_below_floor"``, ``"single_user"``,
            ``"interpersonal_transparency"``). The label is the
            grouping key on the Grafana panel.
        surface: Where the refusal fired. Convention is
            ``"<gate>:<surface>"`` (e.g. ``"refusal_gate:director"``)
            so the surface taxonomy is visible.
        reason: Short rationale (≤ 160 chars). Longer treatment goes
            in ``refusal_brief_link``.
        public: Sub-block style flag. When ``True``, the event is
            eligible for public surfacing (e.g. omg.lol fanout in
            the upstream Hapax stack). Default ``False`` is the safe
            choice; some axiom violations might leak operator-internal
            context.
        refusal_brief_link: Optional pointer to a long-form refusal
            brief (e.g. a markdown file under
            ``hapax-cc-tasks/closed/refusals/``) that explains the
            decision in narrative form. The event itself stays
            short.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    axiom: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    reason: str = Field(max_length=REASON_MAX_CHARS, min_length=1)
    public: bool = False
    refusal_brief_link: str | None = None


class RefusalRegistry:
    """Append-only JSONL writer.

    The class is a thin shell around a path + a module-level lock so
    multiple producer threads inside one process do not interleave
    bytes mid-line. Cross-process append uses POSIX semantics
    (``open(path, "a")`` with ``write`` smaller than ``PIPE_BUF`` on
    Linux ext4/xfs) so concurrent processes work too at the cost of
    per-event line ordering.

    The registry has no aggregation, no rotation, no rollover. It is
    a substrate; consumers (Hapax aggregator, omg.lol publisher,
    Grafana scraper) read from it.
    """

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path or _default_log_path()
        self._lock = threading.Lock()

    @property
    def log_path(self) -> Path:
        return self._log_path

    def append(self, event: RefusalEvent) -> bool:
        """Append one event to the JSONL log; return True iff written.

        Thread-safe: holds the instance lock during the parent-mkdir
        + open + write + flush path. Best-effort: ``OSError`` is
        logged and returns ``False`` rather than raising — refusal
        emission must never break the calling gate path.
        """
        line = event.model_dump_json() + "\n"
        with self._lock:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
            except OSError:
                log.warning(
                    "hapax-refusals: log append failed at %s",
                    self._log_path,
                    exc_info=True,
                )
                return False
        return True


__all__ = [
    "REASON_MAX_CHARS",
    "RefusalEvent",
    "RefusalRegistry",
]
