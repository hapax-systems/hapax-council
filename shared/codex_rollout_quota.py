"""Read Codex's own entitlement-limit observations off disk.

Codex CLI records the provider's subscription limits into its session rollouts — ``limit_id:
"codex"`` with a primary window carrying ``used_percent`` / ``window_minutes`` / ``resets_at``,
plus a credits balance. That is a real headroom magnitude for the SUBSCRIPTION (not an API key),
and reading it calls no provider and spends nothing.

This exists because the estate long recorded codex quota as unobservable
(``local:codex:quota-probe:unobservable``; CASE-CAPACITY-ROUTING-001 R2, "use receipts and manual
refresh until observable"). That stopped being true upstream and nothing was watching for the exit
condition. Two consumers need the same reading — ``scripts/hapax-codex-quota-admission`` and
``scripts/hapax-platform-capability-receipts`` — so it lives here once rather than being
hand-synced twice. The estate has already paid for hand-synced duplicates drifting.

Two hazards are handled here, not by callers:

* **Content.** Rollouts hold the operator's prompts and the model's output. Only ``timestamp`` and
  ``payload.rate_limits`` are lifted out; nothing else is read, returned, or logged.
* **Size.** Rollouts reach gigabytes (one was 1.19GB in the 2026-08-09 OOM). Files are never read
  whole — reading is a bounded seek to the tail.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_SESSIONS_DIR = Path(
    os.environ.get("HAPAX_CODEX_SESSIONS_DIR", str(Path.home() / ".codex" / "sessions"))
)
ROLLOUT_GLOB = "rollout-*.jsonl"
#: Newest-by-mtime rollouts to inspect before giving up. A session that has not spoken to the
#: provider recently carries no fresh snapshot, and scanning the whole history is unbounded.
ROLLOUT_SCAN_LIMIT = 12
#: Never read a rollout whole; seek back this far from the end.
ROLLOUT_TAIL_BYTES = 512 * 1024
#: Older than this and the observation is no longer "account-live".
DEFAULT_MAX_OBSERVATION_AGE_SECONDS = 3600
#: used_percent at or above this is a wall, not headroom. Callers must fail closed on it.
EXHAUSTED_USED_PERCENT = 100.0


class RolloutQuotaUnavailable(ValueError):
    """No fresh, usable limit observation exists. The message names the next action.

    Subclasses ValueError so callers that already fail closed on bad input keep doing so without
    a second except-clause — an unavailable observation is the same class of outcome as an invalid
    one: write nothing, hold the route.
    """


@dataclass(frozen=True)
class RolloutObservation:
    """Numeric limit facts only. Carries no session id, no path, no prompt or model content."""

    observed_at: datetime
    used_percent: float
    window_minutes: int

    @property
    def remaining_percent(self) -> float:
        return round(100.0 - self.used_percent, 4)


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def _rate_limits_from_line(line: str) -> tuple[datetime, dict] | None:
    """Return (timestamp, rate_limits) for a rollout line carrying one, else None."""
    if "rate_limits" not in line:
        return None
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return None
    observed_at = _parse_utc(str(record.get("timestamp") or ""))
    if observed_at is None:
        return None
    return observed_at, limits


def _tail_lines(path: Path, *, tail_bytes: int = ROLLOUT_TAIL_BYTES) -> list[str]:
    """Read at most tail_bytes from the end of path; return complete lines, oldest first."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - tail_bytes))
        blob = handle.read()
    lines = blob.decode("utf-8", errors="replace").splitlines()
    # The first line is probably cut in half by the seek, so drop it unless we read from byte 0.
    if size > tail_bytes and lines:
        lines = lines[1:]
    return lines


def latest_rollout_observation(
    sessions_dir: Path | None = None,
    *,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_OBSERVATION_AGE_SECONDS,
) -> RolloutObservation:
    """Return the newest account-live limit observation Codex has already written to disk.

    Raises RolloutQuotaUnavailable, with an actionable message, when no fresh usable observation
    exists — including when the window is exhausted, which is a wall rather than headroom.
    """

    sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
    if not sessions_dir.is_dir():
        raise RolloutQuotaUnavailable(
            f"no codex sessions directory at {sessions_dir}; run a codex session, or point "
            "HAPAX_CODEX_SESSIONS_DIR at one"
        )
    rollouts = sorted(
        sessions_dir.rglob(ROLLOUT_GLOB),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:ROLLOUT_SCAN_LIMIT]
    if not rollouts:
        raise RolloutQuotaUnavailable(f"no codex rollouts under {sessions_dir}")

    best: tuple[datetime, dict] | None = None
    for path in rollouts:
        try:
            lines = _tail_lines(path)
        except OSError:
            continue
        for line in reversed(lines):
            found = _rate_limits_from_line(line)
            if found is not None:
                if best is None or found[0] > best[0]:
                    best = found
                break
        if best is not None:
            break

    if best is None:
        raise RolloutQuotaUnavailable(
            f"no rate_limits snapshot in the newest {len(rollouts)} codex rollout(s); "
            "run a codex session so the CLI records a fresh limit observation"
        )

    observed_at, limits = best
    age = (now - observed_at).total_seconds()
    if age < 0:
        raise RolloutQuotaUnavailable("codex limit observation is timestamped in the future")
    if age > max_age_seconds:
        raise RolloutQuotaUnavailable(
            f"newest codex limit observation is {int(age)}s old (max {max_age_seconds}s); "
            "run a codex session so the CLI records a fresh limit observation"
        )

    primary = limits.get("primary")
    if not isinstance(primary, dict):
        raise RolloutQuotaUnavailable("codex limit observation carries no primary window")
    try:
        used_percent = float(primary["used_percent"])
        window_minutes = int(primary["window_minutes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RolloutQuotaUnavailable(
            "codex primary window lacks usable used_percent/window_minutes"
        ) from exc
    if not 0.0 <= used_percent <= 1000.0 or window_minutes <= 0:
        raise RolloutQuotaUnavailable("codex primary window values are out of range")
    if used_percent >= EXHAUSTED_USED_PERCENT:
        raise RolloutQuotaUnavailable(
            f"codex primary window is exhausted (used_percent={used_percent}); that is a quota "
            "wall, not headroom — wait for the window to reset rather than admitting"
        )
    # _parse_utc already normalised to whole-second UTC.
    return RolloutObservation(
        observed_at=observed_at,
        used_percent=used_percent,
        window_minutes=window_minutes,
    )
