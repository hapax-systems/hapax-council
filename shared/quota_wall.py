"""Quota wall detection and graceful exit for Claude/Codex lanes.

When a headless lane hits a rate limit (HTTP 429 or quota exhaustion),
this module detects it from the output.jsonl stream, writes a relay
receipt, and signals the wrapper to exit cleanly rather than tight-loop.

Detection signals (from Claude Code stream-json output):
  - {"type":"system","subtype":"api_retry","error_status":429,"error":"rate_limit"}
  - {"type":"rate_limit_event","rate_limit_info":{"status":"rejected",...}}
  - {"type":"assistant",...,"error":"rate_limit"}

The relay receipt goes to ~/.cache/hapax/relay/receipts/<role>-quota-wall.yaml
so the RTE and watchdog know not to restart/kick the lane.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

QUOTA_WALL_EXIT_CODE = 75

RELAY_RECEIPT_DIR = Path(
    os.environ.get(
        "HAPAX_RELAY_RECEIPT_DIR",
        str(Path.home() / ".cache/hapax/relay/receipts"),
    )
)


def detect_quota_wall(output_path: Path, tail_lines: int = 50) -> QuotaWallSignal | None:
    """Scan the tail of a lane's output.jsonl for rate-limit signals.

    Returns a QuotaWallSignal if quota wall detected, None otherwise.
    """
    try:
        lines = output_path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return None

    tail = lines[-tail_lines:] if len(lines) > tail_lines else lines
    fallback: QuotaWallSignal | None = None
    fallback_session_id: str | None = None
    for raw in reversed(tail):
        record = _json_record(raw)
        if record is None:
            continue
        signal = _parse_record(record)
        if signal is None:
            continue
        if signal.kind == "rate_limit_event":
            candidate_session_id = _session_id(record)
            if fallback is None or _same_session(candidate_session_id, fallback_session_id):
                return signal
            continue
        if fallback is None:
            fallback = signal
            fallback_session_id = _session_id(record)
    return fallback


def _json_record(raw: str) -> dict[str, Any] | None:
    try:
        record = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _session_id(record: dict[str, Any]) -> str | None:
    value = record.get("session_id")
    return value if isinstance(value, str) and value else None


def _same_session(candidate: str | None, fallback: str | None) -> bool:
    return candidate is None or fallback is None or candidate == fallback


def _parse_line(raw: str) -> QuotaWallSignal | None:
    record = _json_record(raw)
    if record is None:
        return None
    return _parse_record(record)


def _parse_record(record: dict[str, Any]) -> QuotaWallSignal | None:
    msg_type = record.get("type", "")
    subtype = record.get("subtype", "")

    if msg_type == "rate_limit_event":
        info = record.get("rate_limit_info", {})
        if info.get("status") == "rejected":
            return QuotaWallSignal(
                kind="rate_limit_event",
                resets_at=info.get("resetsAt"),
                rate_limit_type=info.get("rateLimitType"),
                is_overage=info.get("isUsingOverage", False),
            )

    if msg_type == "system" and subtype == "api_retry":
        if record.get("error_status") == 429 or record.get("error") == "rate_limit":
            return QuotaWallSignal(
                kind="api_retry_429",
                resets_at=None,
                rate_limit_type=None,
                is_overage=False,
            )

    if record.get("error") == "rate_limit":
        return QuotaWallSignal(
            kind="error_rate_limit",
            resets_at=None,
            rate_limit_type=None,
            is_overage=False,
        )

    return None


class QuotaWallSignal:
    """Parsed rate-limit signal from Claude Code output."""

    __slots__ = ("kind", "resets_at", "rate_limit_type", "is_overage")

    def __init__(
        self,
        *,
        kind: str,
        resets_at: int | None,
        rate_limit_type: str | None,
        is_overage: bool,
    ) -> None:
        self.kind = kind
        self.resets_at = resets_at
        self.rate_limit_type = rate_limit_type
        self.is_overage = is_overage

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "resets_at": self.resets_at,
            "rate_limit_type": self.rate_limit_type,
            "is_overage": self.is_overage,
        }


def write_quota_wall_receipt(role: str, signal: QuotaWallSignal) -> Path:
    """Write a relay receipt indicating this lane is quota-blocked.

    Returns the path of the written receipt.
    """
    RELAY_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = RELAY_RECEIPT_DIR / f"{role}-quota-wall.yaml"
    now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")

    resets_at_str = ""
    if signal.resets_at:
        resets_at_str = (
            datetime.fromtimestamp(signal.resets_at, tz=UTC).isoformat().replace("+00:00", "Z")
        )

    content = (
        f"role: {role}\n"
        f"status: quota_blocked\n"
        f"detected_at: {now}\n"
        f"signal_kind: {signal.kind}\n"
        f"rate_limit_type: {signal.rate_limit_type or 'unknown'}\n"
        f"resets_at: {resets_at_str or 'unknown'}\n"
        f"is_overage: {signal.is_overage}\n"
        f"action: exit_clean_await_restart\n"
    )
    receipt_path.write_text(content, encoding="utf-8")
    log.info("quota wall receipt written for %s at %s", role, receipt_path)
    return receipt_path


def clear_quota_wall_receipt(role: str) -> bool:
    """Remove a quota wall receipt when the lane resumes successfully."""
    receipt_path = RELAY_RECEIPT_DIR / f"{role}-quota-wall.yaml"
    try:
        receipt_path.unlink()
        return True
    except FileNotFoundError:
        return False


def is_quota_blocked(role: str) -> bool:
    """Check if a lane currently has a quota wall receipt."""
    receipt_path = RELAY_RECEIPT_DIR / f"{role}-quota-wall.yaml"
    return receipt_path.exists()


def handle_quota_wall(role: str, output_path: Path) -> int:
    """Full quota wall handling: detect, write receipt, return exit code.

    Returns QUOTA_WALL_EXIT_CODE if quota wall detected, 0 otherwise.
    Called by the headless wrapper after Claude exits.
    """
    signal = detect_quota_wall(output_path)
    if signal is None:
        clear_quota_wall_receipt(role)
        return 0

    log.warning(
        "quota wall detected for %s: kind=%s type=%s resets_at=%s",
        role,
        signal.kind,
        signal.rate_limit_type,
        signal.resets_at,
    )
    write_quota_wall_receipt(role, signal)
    return QUOTA_WALL_EXIT_CODE


def _read_receipt_resets_at(role: str) -> str | None:
    """Return the role's quota-wall receipt ``resets_at`` ISO string, or None when
    the receipt is absent / has no known reset time (``unknown``) / is unparseable."""
    receipt_path = RELAY_RECEIPT_DIR / f"{role}-quota-wall.yaml"
    try:
        text = receipt_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("resets_at:"):
            value = line.split(":", 1)[1].strip()
            return value if value and value != "unknown" else None
    return None


def compute_backoff_seconds(
    role: str,
    streak: int,
    base: int,
    cap: int,
    *,
    now_epoch: float | None = None,
    jitter: int = 0,
) -> int:
    """Seconds to wait before restarting a quota-walled lane — the fix for the
    flat-30s restart thrash.

    If the role's receipt reports a *future* ``resets_at`` → wait until the reset
    plus a 30s cushion, clamped to ``[base, cap]`` (never re-hit the wall, never
    sleep past the cap). Otherwise grow exponentially as
    ``base * 2**min(streak-1, 6)`` (30→60→120→…→cap), clamped to ``[base, cap]``,
    plus ``jitter`` to decorrelate herds. ``now_epoch``/``jitter`` are injectable
    for deterministic tests.
    """
    resets_at = _read_receipt_resets_at(role)
    if resets_at is not None:
        now = time.time() if now_epoch is None else now_epoch
        try:
            reset_epoch = datetime.fromisoformat(resets_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            reset_epoch = None
        if reset_epoch is not None and reset_epoch > now:
            return max(base, min(cap, int(reset_epoch - now + 30)))
    exponential = base * 2 ** min(max(streak - 1, 0), 6)
    return max(base, min(cap, exponential + jitter))


__all__ = [
    "QUOTA_WALL_EXIT_CODE",
    "QuotaWallSignal",
    "clear_quota_wall_receipt",
    "compute_backoff_seconds",
    "detect_quota_wall",
    "handle_quota_wall",
    "is_quota_blocked",
    "write_quota_wall_receipt",
]
