"""Append-only audit log for every Gmail API call mail-monitor makes.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §5.4.

Each call to ``messages.get`` / ``messages.modify`` /
``users.settings.filters.create`` writes one JSON line to
``~/.cache/mail-monitor/api-calls.jsonl``. The operator can inspect at
any time. A weekly digest (``mail-monitor-012``) tails this log to
detect any out-of-label read — defense in depth for spec §5.3 / §5.4.

The log records *only* `messageId` and `label`, never sender, subject,
or body. Callers must ensure they pass the message id and the
*resolved* label name they used to filter the read. Body content
never enters this log.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

AUDIT_LOG_PATH = Path("~/.cache/mail-monitor/api-calls.jsonl").expanduser()

ApiMethod = Literal[
    "messages.get",
    "messages.modify",
    "users.settings.filters.create",
    "users.settings.filters.list",
    "users.labels.list",
    "users.labels.create",
    "users.watch",
    "users.history.list",
]

_LOCK = threading.Lock()


def audit_call(
    method: ApiMethod,
    *,
    message_id: str | None = None,
    filter_id: str | None = None,
    label: str | None = None,
    scope: str = "gmail.modify",
    result: str = "ok",
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one JSON line to :data:`AUDIT_LOG_PATH`.

    The call is best-effort — IO errors are logged but never raised, so
    audit-log loss never crashes the daemon. Use a process-wide lock to
    avoid interleaved writes when called from concurrent threads.
    """
    record: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": method,
        "scope": scope,
        "result": result,
    }
    if message_id is not None:
        record["messageId"] = message_id
    if filter_id is not None:
        record["filterId"] = filter_id
    if label is not None:
        record["label"] = label
    if extra:
        record.update(extra)

    line = json.dumps(record, separators=(",", ":")) + "\n"
    with _LOCK:
        try:
            AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fp:
                fp.write(line)
                # Flush so the digest job sees the call within 1s of the call
                # itself rather than waiting for OS buffer flush.
                fp.flush()
                os.fsync(fp.fileno())
        except OSError as exc:
            log.warning("audit log write failed: %s", exc)


def read_audit_entries(path: Path = AUDIT_LOG_PATH) -> list[dict[str, Any]]:
    """Read all audit entries (used by the weekly digest in mail-monitor-012)."""
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning("malformed audit line: %s (%s)", line[:80], exc)
    return entries
