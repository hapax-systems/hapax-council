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
    for raw in reversed(tail):
        signal = _parse_line(raw)
        if signal is not None:
            return signal
    return None


def _parse_line(raw: str) -> QuotaWallSignal | None:
    try:
        record = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None

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


__all__ = [
    "QUOTA_WALL_EXIT_CODE",
    "QuotaWallSignal",
    "clear_quota_wall_receipt",
    "detect_quota_wall",
    "handle_quota_wall",
    "is_quota_blocked",
    "write_quota_wall_receipt",
]
