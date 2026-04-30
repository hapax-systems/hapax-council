"""Pending-action correlation helpers for the mail monitor.

The pending-actions file is written by producer daemons that initiate
outbound verification flows. The mail monitor only reads it to classify
or annotate Hapax-labelled inbound mail; malformed or missing state is
treated as no correlation.
"""

from __future__ import annotations

import json
import logging
import time
from email.utils import parseaddr
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PENDING_ACTIONS_PATH = Path("~/.cache/mail-monitor/pending-actions.jsonl").expanduser()
CORRELATION_WINDOW_S = 10 * 60  # +/-10 min per spec §4 condition 4


def sender_email(address: str | None) -> str | None:
    """Normalize a header/address string to a lowercase email address."""
    if not address:
        return None
    _display_name, parsed = parseaddr(address)
    candidate = parsed or address.strip()
    candidate = candidate.strip().strip("<>").lower()
    if "@" not in candidate:
        return None
    local, domain = candidate.rsplit("@", 1)
    if not local or not domain:
        return None
    return f"{local}@{domain}"


def sender_domain(address: str | None) -> str | None:
    """Return the domain part of a sender address/header."""
    email_address = sender_email(address)
    if email_address is None:
        return None
    return email_address.rsplit("@", 1)[1]


def find_pending_action(
    sender_domain_value: str,
    *,
    now: float | None = None,
    path: Path = PENDING_ACTIONS_PATH,
) -> dict[str, Any] | None:
    """Find a pending-action record matching ``sender_domain_value``.

    Matching is by exact sender-domain and a +/-10 minute wall-clock
    window around the supplied ``now``. Invalid rows are ignored so a
    single bad producer record cannot block the daemon.
    """
    if not path.exists():
        return None
    reference = now if now is not None else time.time()
    cutoff_lo = reference - CORRELATION_WINDOW_S
    cutoff_hi = reference + CORRELATION_WINDOW_S
    normalized_domain = sender_domain_value.strip().lower()
    try:
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                rec_sender = str(record.get("sender_domain") or "").strip().lower()
                if rec_sender != normalized_domain:
                    continue
                rec_ts = record.get("ts") or record.get("expires") or 0
                try:
                    rec_ts_f = float(rec_ts)
                except (TypeError, ValueError):
                    continue
                if cutoff_lo <= rec_ts_f <= cutoff_hi:
                    return record
    except OSError as exc:
        log.warning("pending-actions read failed: %s", exc)
        return None
    return None
