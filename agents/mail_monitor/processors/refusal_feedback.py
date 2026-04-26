"""Category E processor — operator replies that are NOT SUPPRESS.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §3.E.

Appends a refusal-brief log entry that records the *fact* of the
reply without ever surfacing the body. Sender + subject are stored
as SHA-1 digests with a per-installation salt — operator can correlate
across logs but the digest is uninvertible.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from prometheus_client import Counter

log = logging.getLogger(__name__)

REFUSAL_LOG_PATH = Path("/dev/shm/hapax-refusals/log.jsonl")

# Salt rotates per host install. We don't need cryptographic strength
# (the salt is local-only), just per-install separation so the same
# sender hashes differently on different machines.
_SALT_PATH = Path("~/.cache/mail-monitor/refusal-salt").expanduser()

REFUSAL_FEEDBACK_COUNTER = Counter(
    "hapax_mail_monitor_refusal_feedback_total",
    "Refusal-feedback log entries appended.",
    labelnames=("kind",),
)
for _kind in ("feedback", "suppress"):
    REFUSAL_FEEDBACK_COUNTER.labels(kind=_kind)


def _load_or_init_salt() -> str:
    """Return the per-install salt; create it on first call."""
    if _SALT_PATH.exists():
        return _SALT_PATH.read_text().strip()
    _SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    salt = hashlib.sha1(os.urandom(32), usedforsecurity=False).hexdigest()  # noqa: S324 — non-crypto
    _SALT_PATH.write_text(salt)
    return salt


def _hash_field(value: str | None) -> str:
    if not value:
        return ""
    salt = _load_or_init_salt()
    return hashlib.sha1((salt + value.lower().strip()).encode(), usedforsecurity=False).hexdigest()  # noqa: S324


def emit_refusal_feedback(message: dict[str, Any], *, kind: str = "feedback") -> dict[str, Any]:
    """Append one refusal-brief entry; return the entry as written.

    ``kind`` is either ``"feedback"`` (Category E) or ``"suppress"``
    (Category C). Both go to the same refusal-brief log; a sidebar
    consumer filters by ``kind``.

    The entry contains ``sender_hash``, ``subject_hash``,
    ``axiom``, and ``ts`` only — never raw sender, subject, or body.
    """
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind,
        "sender_hash": _hash_field(message.get("sender")),
        "subject_hash": _hash_field(message.get("subject")),
        "axiom": "interpersonal_transparency",
        "surface": f"mail-monitor:{kind}",
    }

    REFUSAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    try:
        with REFUSAL_LOG_PATH.open("a", encoding="utf-8") as fp:
            fp.write(line)
            fp.flush()
    except OSError as exc:
        log.warning("refusal-feedback log write failed: %s", exc)
        return entry

    REFUSAL_FEEDBACK_COUNTER.labels(kind=kind).inc()
    return entry
