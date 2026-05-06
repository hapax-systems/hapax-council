"""Canonical publication-bus witness producer.

Closes cc-task ``witness-rail-publication-log-producer`` (WSJF 9.0).
Writes one JSONL row to ``~/hapax-state/publication/publication-log.jsonl``
per successful publication-bus :meth:`Publisher.publish` outcome so the
``publication-tree-effect`` braid rail recovers from
``braid_recomputed=0``.

Why this module exists:

* The braided-value snapshot runner
  (:mod:`scripts.braided_value_snapshot_runner`) declares a
  :class:`WitnessSpec("publication_log", ..., ~/hapax-state/publication/
  publication-log.jsonl, "publication_tree_effect")` and reads the last
  row to classify the witness state.
* :func:`shared.github_publication_log.classify_publication_log_payload`
  treats any non-``publication.github.*`` event_type as
  ``status="ok", reason="publication_witness_present"`` — meaning the
  runner accepts publication-bus rows as live witnesses with a
  ``publication.bus.<surface>`` event_type prefix.
* The github-side writer at
  :func:`shared.github_publication_log.write_publication_log_events`
  handles GitHub-typed rows only. The publication-bus has 17+ surfaces
  (Bridgy, Bluesky, omg.lol, OSF, PhilArchive, Internet Archive,
  refusal-brief Zenodo, Stripe Payment Link, Open Collective, Liberapay,
  GitHub Sponsors, omg.lol Pay, x402 USDC) — none of which were
  appending to the canonical log. This module fills that gap.

Hook point: :meth:`Publisher.publish` calls
:func:`append_publication_witness` from a single point in the ABC
after ``_emit()`` returns. Every current and future Publisher
subclass participates without per-subclass touch.

Schema (one JSONL row per witness event):

    {
      "event_type": "publication.bus.<surface_name>",
      "ts": "2026-05-05T03:30:00+00:00",
      "surface": "<surface_name>",
      "target": "<payload.target>",
      "target_sha256": "<sha256(target)[:16]>",
      "result": "ok" | "refused" | "error"
    }

The witness intentionally carries no payload body — only the
existence-of-publish event. Anti-overclaim: the row evidences that
the bus dispatched a publish call to a registered surface and the
subclass returned a result. It does NOT grant truth, rights,
egress authority, or downstream resolution. Per
``shared.github_publication_log.ANTI_OVERCLAIM_REASON``.

Best-effort: writer failures are swallowed at the publisher boundary
(observability hiccups must never break the publish path).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "DEFAULT_PUBLICATION_LOG_PATH",
    "PUBLICATION_LOG_PATH_ENV",
    "WITNESS_EVENT_TYPE_PREFIX",
    "append_publication_witness",
    "build_witness_event",
    "reset_idempotency_cache",
]

log = logging.getLogger(__name__)

PUBLICATION_LOG_PATH_ENV: str = "HAPAX_PUBLICATION_LOG_PATH"
"""Operator override for the canonical witness path. Defaults to the
braid runner's expected location."""

DEFAULT_PUBLICATION_LOG_PATH: Path = (
    Path.home() / "hapax-state" / "publication" / "publication-log.jsonl"
)
"""Canonical witness path declared by
``scripts.braided_value_snapshot_runner.WitnessSpec("publication_log", ...)``.

Mirrors the path used by :data:`shared.github_publication_log.DEFAULT_PUBLICATION_LOG`
so a single log file aggregates GitHub-typed rows + publication-bus
rows."""

WITNESS_EVENT_TYPE_PREFIX: str = "publication.bus."
"""Event-type namespace for publication-bus rows. The classify
function in :mod:`shared.github_publication_log` registers any
non-``publication.github.*`` event_type as a present witness (see
``classify_publication_log_payload`` — returns ``"ok",
("publication_witness_present",)``)."""


# In-memory idempotency cache. Keyed on (surface, target_sha256[:16]).
# Re-firing the same (surface, target) within a single process — common
# during retry loops — does not re-append. Cross-process idempotency
# is NOT enforced here (the witness needs the latest row, not strict
# uniqueness); two workers publishing the same target produce two
# rows, which is fine.
_idempotency_lock = threading.Lock()
_seen_keys: set[tuple[str, str]] = set()


def reset_idempotency_cache() -> None:
    """Reset the in-memory dedup set. Used by tests."""

    with _idempotency_lock:
        _seen_keys.clear()


def _resolve_log_path() -> Path:
    """Resolve the canonical log path, honouring the env override."""

    raw = os.environ.get(PUBLICATION_LOG_PATH_ENV)
    if raw:
        return Path(raw)
    return DEFAULT_PUBLICATION_LOG_PATH


def _target_sha(target: str) -> str:
    """Stable 16-hex prefix of sha256(target). Used for the dedup key
    + the witness row's ``target_sha256`` field — both for idempotency
    and so consumers can correlate without re-storing the target.
    """

    return hashlib.sha256(target.encode("utf-8")).hexdigest()[:16]


def build_witness_event(
    *,
    surface: str,
    target: str,
    result: str,
    ts: datetime | None = None,
) -> dict[str, str]:
    """Construct one publication-bus witness event dict.

    Pure — no I/O. Used by the appender + by tests that need to
    inspect the event shape without writing.
    """

    timestamp = ts if ts is not None else datetime.now(UTC)
    return {
        "event_type": f"{WITNESS_EVENT_TYPE_PREFIX}{surface}",
        "ts": timestamp.isoformat(),
        "surface": surface,
        "target": target,
        "target_sha256": _target_sha(target),
        "result": result,
    }


def append_publication_witness(
    *,
    surface: str,
    target: str,
    result: str,
    log_path: Path | None = None,
    ts: datetime | None = None,
) -> bool:
    """Append a publication-bus witness row to the canonical JSONL.

    Returns ``True`` when a row was written; ``False`` when the call
    was deduplicated against an earlier (surface, target) pair OR
    when the write failed (best-effort — failures are swallowed at
    the publisher boundary so observability hiccups never break the
    publish path; the caller does not need to handle errors).

    Idempotency: in-process. The same (surface, target) pair within
    one process writes one row; the second call is a no-op. Cross-
    process: separate processes will each write — the witness rail
    needs the latest event, not strict uniqueness.

    Args:
        surface: Publisher's ``surface_name`` ClassVar (e.g.,
            ``zenodo-refusal-deposit``, ``bridgy-webmention-publish``).
        target: ``payload.target`` from the publish event.
        result: One of ``"ok"`` / ``"refused"`` / ``"error"``.
        log_path: Override for the canonical path (tests pass tmp
            paths). Production callers leave this None — the resolver
            honours the env var override.
        ts: Override for the row timestamp (tests pin time).
    """

    target_sha = _target_sha(target)
    dedup_key = (surface, target_sha)

    with _idempotency_lock:
        if dedup_key in _seen_keys:
            return False
        _seen_keys.add(dedup_key)

    event = build_witness_event(surface=surface, target=target, result=result, ts=ts)
    target_path = log_path if log_path is not None else _resolve_log_path()

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with target_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    except OSError:
        log.warning(
            "publication_bus witness append failed for surface=%s target_sha=%s",
            surface,
            target_sha,
            exc_info=True,
        )
        # Roll the dedup back so a future call may retry — operator may
        # have fixed permissions / disk and re-trigger the publish.
        with _idempotency_lock:
            _seen_keys.discard(dedup_key)
        return False
