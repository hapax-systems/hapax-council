"""Active-wards observer — publishes currently-rendering ward IDs.

Phase 3.5 foundation companion to ``ward_claim_bindings``. Producers
(cairo overlay draw cycles, source registry transitions, layout swaps)
call ``publish`` with the live set of ward IDs. Consumers (Phase 3.5
Layer C director envelope, post-#1437 follow-up) call ``read`` to
discover which wards' claim providers should contribute posterior
badges to the next LLM prompt.

## File contract

Single JSON object at ``/dev/shm/hapax-compositor/active_wards.json``::

    {
      "ward_ids": ["album-cover", "splat-attribution-v1", "youtube-slot-0"],
      "published_t": 1745604000.123
    }

``ward_ids`` is unordered; consumers may sort. ``published_t`` is the
producer's clock; ``read`` checks staleness against
``ACTIVE_WARDS_STALE_S`` (default 5s) and treats stale data as
"no active wards" rather than serving the last known list — a stalled
producer should not freeze the consumer's view.

## Atomic write

``publish`` writes to ``active_wards.json.tmp`` then ``os.rename``-s
into place. Concurrent readers see either the old file or the new one,
never a partial write.

## Why a file (vs in-process state)

The compositor process publishes; the director-loop process consumes.
SHM-file IPC matches the project's existing snapshot.jpg / fx-snapshot.jpg
/ perception-state.json patterns and survives crashes of either side.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

ACTIVE_WARDS_FILE: Path = Path("/dev/shm/hapax-compositor/active_wards.json")
CURRENT_LAYOUT_STATE_FILE: Path = Path("/dev/shm/hapax-compositor/current-layout-state.json")
WARD_PROPERTIES_FILE: Path = Path("/dev/shm/hapax-compositor/ward-properties.json")
ACTIVE_WARDS_STALE_S: float = 5.0


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    try:
        os.write(fd, json.dumps(payload).encode())
    finally:
        os.close(fd)
    os.rename(str(tmp), str(path))


def publish(ward_ids: Iterable[str], *, path: Path | None = None) -> None:
    """Atomically write the live set of active ward IDs.

    ``ward_ids`` is converted to a deduplicated sorted list before
    serialization; producers don't need to dedupe upstream. ``path``
    parent is ``mkdir -p``'ed on first write. ``path=None`` resolves
    to ``ACTIVE_WARDS_FILE`` at call time so test fixtures that
    monkeypatch the module-level constant take effect (Python binds
    default-arg expressions at def-time, which would otherwise capture
    the original value).

    Failures (disk full, permission, parent-dir absent on a host
    without /dev/shm) log a warning and return without raising —
    publishing is best-effort observability, not a correctness gate.
    """
    if path is None:
        path = ACTIVE_WARDS_FILE
    deduped = sorted(set(ward_ids))
    payload = {"ward_ids": deduped, "published_t": time.time()}
    try:
        _write_json_atomic(path, payload)
    except OSError:
        log.debug("active_wards publish failed", exc_info=True)


def publish_current_layout_state(
    *,
    layout_name: str | None = None,
    layout_mode: str | None = None,
    active_ward_ids: Iterable[str] | None = None,
    path: Path | None = None,
) -> None:
    """Publish durable readback of the compositor's current rendered layout.

    This is a state readback, not the ``layout-mode.txt`` command mailbox.
    Callers may update one field at a time; existing fields are preserved.
    """
    if path is None:
        path = CURRENT_LAYOUT_STATE_FILE
    payload: dict[str, object] = {}
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload.update(existing)
    except (OSError, ValueError):
        log.debug("current layout state merge failed", exc_info=True)

    if layout_name is not None:
        payload["layout_name"] = layout_name
    if layout_mode is not None:
        payload["layout_mode"] = layout_mode
    if active_ward_ids is not None:
        payload["active_ward_ids"] = sorted(set(active_ward_ids))
    payload["published_t"] = time.time()
    payload["schema_version"] = 1

    try:
        _write_json_atomic(path, payload)
    except OSError:
        log.debug("current layout state publish failed", exc_info=True)


def visible_ward_property_ids(*, path: Path | None = None) -> list[str]:
    """Return ward IDs marked visible in the ward-properties snapshot.

    This is an observability fallback for layouts whose render readbacks are
    suppressed or not wired through a SourceRegistry surface yet.
    """
    if path is None:
        path = WARD_PROPERTIES_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    wards = payload.get("wards") if isinstance(payload, dict) else None
    if not isinstance(wards, dict):
        return []
    active_ids: list[str] = []
    for ward_id, props in wards.items():
        if not isinstance(ward_id, str) or not ward_id:
            continue
        if isinstance(props, dict) and props.get("visible") is False:
            continue
        active_ids.append(ward_id)
    return sorted(set(active_ids))


def read(*, path: Path | None = None, stale_s: float = ACTIVE_WARDS_STALE_S) -> list[str]:
    """Return the current active-ward list.

    Returns an empty list when the file is missing, malformed, or
    older than ``stale_s`` seconds. Stale-as-empty matches the
    producer-died failure mode: better to render no badges than badges
    for wards that may have been removed minutes ago. ``path=None``
    resolves to ``ACTIVE_WARDS_FILE`` at call time (see ``publish``
    for the rationale).
    """
    if path is None:
        path = ACTIVE_WARDS_FILE
    try:
        if not path.exists():
            return []
        age = time.time() - path.stat().st_mtime
        if age > stale_s:
            return []
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        log.debug("active_wards read failed", exc_info=True)
        return []
    ward_ids = data.get("ward_ids")
    if not isinstance(ward_ids, list):
        return []
    return [w for w in ward_ids if isinstance(w, str)]


__all__ = [
    "ACTIVE_WARDS_FILE",
    "ACTIVE_WARDS_STALE_S",
    "CURRENT_LAYOUT_STATE_FILE",
    "WARD_PROPERTIES_FILE",
    "publish_current_layout_state",
    "publish",
    "read",
    "visible_ward_property_ids",
]
