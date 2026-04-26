"""Weekly out-of-label audit digest.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §5.4.

Tail the ``api-calls.jsonl`` audit log; for each ``messages.get``
entry whose ``label`` field is not one of the four ``Hapax/*`` names,
append a ``mail_out_of_label_read`` refusal-brief entry. Defense in
depth: spec §5.3 (``messages.list`` query gate) should already
prevent any out-of-label read; this digest exists as the tripwire if
that gate ever drifts.

Designed to run weekly under
``hapax-mail-monitor-weekly-digest.timer``. The default ``--lookback``
of 7 days matches the timer cadence + provides a 1-day overlap so a
late-firing timer never misses an entry.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any

from prometheus_client import Counter

from agents.mail_monitor.audit import AUDIT_LOG_PATH, read_audit_entries
from agents.mail_monitor.label_bootstrap import HAPAX_LABEL_NAMES
from agents.mail_monitor.processors.refusal_feedback import emit_refusal_feedback

log = logging.getLogger(__name__)

DEFAULT_LOOKBACK_S = 7 * 24 * 3600

DIGEST_RESULTS_COUNTER = Counter(
    "hapax_mail_monitor_digest_runs_total",
    "Weekly audit-digest runs by outcome.",
    labelnames=("result",),
)
for _result in ("clean", "out_of_label_found", "read_error"):
    DIGEST_RESULTS_COUNTER.labels(result=_result)

OUT_OF_LABEL_COUNTER = Counter(
    "hapax_mail_monitor_digest_out_of_label_total",
    "Out-of-label messages.get entries the digest has surfaced.",
)


def _is_in_hapax_scope(entry: dict[str, Any]) -> bool:
    """Return True iff this audit entry is a Hapax-scoped read.

    A ``messages.get`` is in scope when its ``label`` field equals one
    of the four ``Hapax/*`` names. Other API methods (modify, watch,
    labels.list, etc.) are not scope-restricted by the digest — they
    don't read message content.
    """
    if entry.get("method") != "messages.get":
        return True
    label = entry.get("label") or ""
    return label in HAPAX_LABEL_NAMES


def _within_lookback(entry: dict[str, Any], cutoff_s: float) -> bool:
    """True if the entry's ``ts`` is newer than ``cutoff_s``."""
    ts = entry.get("ts")
    if not ts:
        return False
    try:
        struct = time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return time.mktime(struct) >= cutoff_s


def scan_audit_log(*, lookback_s: int = DEFAULT_LOOKBACK_S) -> list[dict[str, Any]]:
    """Return out-of-label ``messages.get`` entries within lookback window.

    Pure function — no IO besides reading the audit log path. Tests
    monkeypatch ``audit.AUDIT_LOG_PATH`` and ``digest.AUDIT_LOG_PATH``
    to point at a tmp file.
    """
    entries = read_audit_entries(AUDIT_LOG_PATH)
    cutoff = time.time() - lookback_s
    return [e for e in entries if _within_lookback(e, cutoff) and not _is_in_hapax_scope(e)]


def run_digest(*, lookback_s: int = DEFAULT_LOOKBACK_S) -> int:
    """Run one digest pass; return the count of out-of-label reads found.

    For each out-of-label entry, append a refusal-brief log line so
    the operator sidebar reflects the gap.
    """
    try:
        offenders = scan_audit_log(lookback_s=lookback_s)
    except Exception:  # noqa: BLE001 - run-loop must be resilient
        DIGEST_RESULTS_COUNTER.labels(result="read_error").inc()
        log.exception("audit log read failed")
        return 0

    if not offenders:
        DIGEST_RESULTS_COUNTER.labels(result="clean").inc()
        log.info(
            "audit digest: clean — 0 out-of-label messages.get in last %d days",
            lookback_s // 86400,
        )
        return 0

    DIGEST_RESULTS_COUNTER.labels(result="out_of_label_found").inc()
    for entry in offenders:
        OUT_OF_LABEL_COUNTER.inc()
        emit_refusal_feedback(
            {
                "subject": entry.get("messageId", ""),
                "sender": entry.get("label", "<unlabelled>"),
            },
            kind="mail_out_of_label_read",
        )

    log.warning(
        "audit digest: %d out-of-label messages.get entries surfaced as refusal-brief",
        len(offenders),
    )
    return len(offenders)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m agents.mail_monitor.digest``."""
    parser = argparse.ArgumentParser(
        prog="python -m agents.mail_monitor.digest",
        description="Weekly out-of-label audit digest.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="How many days of audit history to scan (default 7).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_digest(lookback_s=args.lookback_days * 86400)
    # Always exit 0: the digest's job is to LOG findings, not to fail
    # systemd. Alerts come from the refusal-brief sidebar / Prometheus.
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
