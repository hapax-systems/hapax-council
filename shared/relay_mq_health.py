"""Read-side health and maintenance helpers for the relay SQLite MQ."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from shared.relay_mq import DEFAULT_DB_PATH

HealthLabel = Literal["ACTIVE", "CONTENDED", "MISSING", "CORRUPT", "UNREACHABLE", "IDLE", "UNKNOWN"]


@dataclass(frozen=True)
class RelayMQHealth:
    label: HealthLabel
    db_path: str
    available: bool
    pending_count: int = 0
    offered_count: int = 0
    read_count: int = 0
    accepted_count: int = 0
    stale_count: int = 0
    expired_count: int = 0
    retry_candidate_count: int = 0
    escalation_candidate_count: int = 0
    dead_letter_count: int = 0
    by_state: dict[str, int] = field(default_factory=dict)
    source_freshness: str = "UNKNOWN"
    last_tick_age_s: float | None = None
    degraded_reasons: tuple[str, ...] = ()

    @property
    def degraded(self) -> bool:
        return self.label != "ACTIVE" or bool(self.degraded_reasons)

    def summary(self) -> str:
        if not self.available:
            return f"{self.label}: relay MQ unavailable"
        return (
            f"{self.label}: pending={self.pending_count} stale={self.stale_count} "
            f"dead={self.dead_letter_count} retry={self.retry_candidate_count} "
            f"escalate={self.escalation_candidate_count}"
        )


@dataclass(frozen=True)
class MaintenanceResult:
    label: HealthLabel
    changed_count: int = 0
    reason: str | None = None


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _classify_operational_error(exc: sqlite3.Error) -> HealthLabel:
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return "CONTENDED"
    if "malformed" in text or "not a database" in text or "database disk image" in text:
        return "CORRUPT"
    return "UNKNOWN"


def _read_only_connect(db_path: Path, *, busy_timeout_ms: int = 1000) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=max(busy_timeout_ms / 1000, 0.001))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    return conn


def _readwrite_connect(db_path: Path, *, busy_timeout_ms: int = 1000) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=max(busy_timeout_ms / 1000, 0.001))
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _unavailable(db_path: Path, label: HealthLabel, reason: str) -> RelayMQHealth:
    return RelayMQHealth(
        label=label,
        db_path=str(db_path),
        available=False,
        degraded_reasons=(reason,),
    )


def tick_health(
    db_path: Path = DEFAULT_DB_PATH,
    last_tick_at: datetime | str | None = None,
    *,
    retry_interval_s: int = 900,
    busy_timeout_ms: int = 1000,
) -> RelayMQHealth | None:
    """Return queue health for RTE/CLOG consumers; never raises for MQ failures."""

    db_path = Path(db_path).expanduser()
    if not db_path.parent.exists():
        return _unavailable(db_path, "UNREACHABLE", "database_parent_unreachable")
    if not db_path.exists():
        return _unavailable(db_path, "MISSING", "database_missing")

    now = datetime.now(UTC)
    retry_cutoff = now - timedelta(seconds=retry_interval_s)
    last_tick = _coerce_datetime(last_tick_at)
    last_tick_age_s = (now - last_tick).total_seconds() if last_tick is not None else None
    source_freshness = "ACTIVE" if last_tick is not None else "UNKNOWN"

    try:
        with _read_only_connect(db_path, busy_timeout_ms=busy_timeout_ms) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or str(integrity[0]).lower() != "ok":
                return _unavailable(db_path, "CORRUPT", "integrity_check_failed")

            by_state = {
                str(row["state"]): int(row["count"])
                for row in conn.execute(
                    "SELECT state, COUNT(*) AS count FROM recipients GROUP BY state"
                )
            }
            stale_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM recipients r
                    JOIN messages m ON m.message_id = r.message_id
                    WHERE r.state IN ('offered', 'read')
                      AND m.stale_after IS NOT NULL
                      AND m.stale_after < :now
                    """,
                    {"now": now.isoformat()},
                ).fetchone()["count"]
            )
            expired_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM recipients r
                    JOIN messages m ON m.message_id = r.message_id
                    WHERE r.state IN ('offered', 'read')
                      AND m.expires_at IS NOT NULL
                      AND m.expires_at < :now
                    """,
                    {"now": now.isoformat()},
                ).fetchone()["count"]
            )
            retry_candidate_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM recipients
                    WHERE state = 'read' AND updated_at < :cutoff
                    """,
                    {"cutoff": retry_cutoff.isoformat()},
                ).fetchone()["count"]
            )
            escalation_candidate_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM recipients r
                    JOIN messages m ON m.message_id = r.message_id
                    WHERE r.state IN ('offered', 'read', 'accepted', 'deferred')
                      AND m.expires_at IS NOT NULL
                      AND m.expires_at < :now
                    """,
                    {"now": now.isoformat()},
                ).fetchone()["count"]
            )
            dead_letter_count = int(
                conn.execute("SELECT COUNT(*) AS count FROM dead_letters").fetchone()["count"]
            )
    except sqlite3.Error as exc:
        return _unavailable(db_path, _classify_operational_error(exc), str(exc))
    except OSError as exc:
        return _unavailable(db_path, "UNREACHABLE", str(exc))
    except Exception:
        return None

    offered_count = by_state.get("offered", 0)
    read_count = by_state.get("read", 0)
    accepted_count = by_state.get("accepted", 0)
    degraded_reasons: list[str] = []
    if stale_count:
        degraded_reasons.append("stale_messages")
    if expired_count:
        degraded_reasons.append("expired_messages")
    if retry_candidate_count:
        degraded_reasons.append("retry_candidates")
    if escalation_candidate_count:
        degraded_reasons.append("escalation_candidates")
    if dead_letter_count:
        degraded_reasons.append("dead_letters")
    if source_freshness == "UNKNOWN":
        degraded_reasons.append("source_freshness_unknown")

    return RelayMQHealth(
        label="ACTIVE",
        db_path=str(db_path),
        available=True,
        pending_count=offered_count + read_count,
        offered_count=offered_count,
        read_count=read_count,
        accepted_count=accepted_count,
        stale_count=stale_count,
        expired_count=expired_count,
        retry_candidate_count=retry_candidate_count,
        escalation_candidate_count=escalation_candidate_count,
        dead_letter_count=dead_letter_count,
        by_state=by_state,
        source_freshness=source_freshness,
        last_tick_age_s=last_tick_age_s,
        degraded_reasons=tuple(degraded_reasons),
    )


def execute_retries(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    retry_interval_s: int = 900,
    busy_timeout_ms: int = 1000,
) -> MaintenanceResult:
    """Re-offer read messages whose recipient row has exceeded the retry interval."""

    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        return MaintenanceResult("MISSING", reason="database_missing")
    cutoff = (datetime.now(UTC) - timedelta(seconds=retry_interval_s)).isoformat()
    now_iso = datetime.now(UTC).isoformat()
    try:
        with _readwrite_connect(db_path, busy_timeout_ms=busy_timeout_ms) as conn:
            cursor = conn.execute(
                """
                UPDATE recipients
                SET state = 'offered',
                    retry_count = retry_count + 1,
                    reason = 'retry_reoffered',
                    updated_at = :now
                WHERE state = 'read' AND updated_at < :cutoff
                """,
                {"now": now_iso, "cutoff": cutoff},
            )
            conn.commit()
            return MaintenanceResult("ACTIVE", changed_count=cursor.rowcount)
    except sqlite3.Error as exc:
        return MaintenanceResult(_classify_operational_error(exc), reason=str(exc))


def execute_escalations(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    busy_timeout_ms: int = 1000,
) -> MaintenanceResult:
    """Escalate non-terminal recipient rows whose message deadline has passed."""

    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        return MaintenanceResult("MISSING", reason="database_missing")
    now_iso = datetime.now(UTC).isoformat()
    try:
        with _readwrite_connect(db_path, busy_timeout_ms=busy_timeout_ms) as conn:
            cursor = conn.execute(
                """
                UPDATE recipients
                SET state = 'escalated',
                    reason = 'deadline_elapsed',
                    updated_at = :now
                WHERE state IN ('offered', 'read', 'accepted', 'deferred')
                  AND message_id IN (
                      SELECT message_id FROM messages
                      WHERE expires_at IS NOT NULL AND expires_at < :now
                  )
                """,
                {"now": now_iso},
            )
            conn.commit()
            return MaintenanceResult("ACTIVE", changed_count=cursor.rowcount)
    except sqlite3.Error as exc:
        return MaintenanceResult(_classify_operational_error(exc), reason=str(exc))


# Static public API marker for diff-aware unused-callable gates. Runtime callers
# are extensionless scripts, which Vulture does not parse as Python sources.
RELAY_MQ_HEALTH_PUBLIC_API = (tick_health, execute_retries, execute_escalations)
