"""Read and classify rebuild-service outcome ledger records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CLEARABLE_OUTCOMES = frozenset(
    {
        "restart_success",
        "restart_timeout_late_active",
        "skipped_no_watched_changes",
        "pull_only_updated",
        "no_service_sha_updated",
        "no_change",
        "skipped_masked",
    }
)
WARNING_OUTCOMES = frozenset({"deferred_pressure"})
HOLD_OUTCOMES = frozenset({"restart_still_in_progress"})
FAIL_OUTCOMES = frozenset(
    {
        "missing_unit",
        "restart_failed_unhealthy",
        "restart_timeout_unknown",
    }
)


@dataclass(frozen=True)
class RebuildOutcomeRecord:
    path: Path
    sha_key: str | None
    service: str | None
    current_sha: str | None
    outcome: str | None
    timestamp: str | None
    category: str
    age_s: float | None = None
    reason: str | None = None

    @property
    def clearable(self) -> bool:
        return self.category == "pass"

    @property
    def blocker(self) -> bool:
        return self.category in {"fail", "hold"}

    @property
    def warning(self) -> bool:
        return self.category == "warn"

    def to_evidence(self) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "path": str(self.path),
            "sha_key": self.sha_key,
            "service": self.service,
            "current_sha": self.current_sha,
            "outcome": self.outcome,
            "timestamp": self.timestamp,
            "category": self.category,
        }
        if self.age_s is not None:
            evidence["age_s"] = round(self.age_s, 3)
        if self.reason:
            evidence["reason"] = self.reason
        return evidence


@dataclass(frozen=True)
class RebuildOutcomeAssessment:
    state_dir: Path
    current_sha: str | None
    max_age_s: float
    records: tuple[RebuildOutcomeRecord, ...]

    @property
    def clearable_records(self) -> tuple[RebuildOutcomeRecord, ...]:
        return tuple(record for record in self.records if record.clearable)

    @property
    def blocker_records(self) -> tuple[RebuildOutcomeRecord, ...]:
        return tuple(record for record in self.records if record.blocker)

    @property
    def warning_records(self) -> tuple[RebuildOutcomeRecord, ...]:
        return tuple(record for record in self.records if record.warning)

    @property
    def stale_or_unknown_records(self) -> tuple[RebuildOutcomeRecord, ...]:
        return tuple(record for record in self.records if record.category == "stale_unknown")

    def to_evidence(self) -> dict[str, Any]:
        return {
            "state_dir": str(self.state_dir),
            "current_sha": self.current_sha,
            "max_age_s": self.max_age_s,
            "record_count": len(self.records),
            "records": [record.to_evidence() for record in self.records],
            "clearable_records": [record.to_evidence() for record in self.clearable_records],
            "blocker_records": [record.to_evidence() for record in self.blocker_records],
            "warning_records": [record.to_evidence() for record in self.warning_records],
            "stale_or_unknown_records": [
                record.to_evidence() for record in self.stale_or_unknown_records
            ],
        }


def assess_rebuild_outcome_ledger(
    state_dir: Path,
    *,
    current_sha: str | None,
    now_epoch: float,
    max_age_s: float,
) -> RebuildOutcomeAssessment:
    """Classify all current rebuild outcome JSON files in ``state_dir``."""

    records: list[RebuildOutcomeRecord] = []
    if not state_dir.exists():
        return RebuildOutcomeAssessment(
            state_dir=state_dir,
            current_sha=current_sha,
            max_age_s=max_age_s,
            records=(),
        )

    for path in sorted(state_dir.glob("last-*-outcome.json")):
        records.append(
            _read_outcome_record(
                path,
                current_sha=current_sha,
                now_epoch=now_epoch,
                max_age_s=max_age_s,
            )
        )

    return RebuildOutcomeAssessment(
        state_dir=state_dir,
        current_sha=current_sha,
        max_age_s=max_age_s,
        records=tuple(records),
    )


def _read_outcome_record(
    path: Path, *, current_sha: str | None, now_epoch: float, max_age_s: float
) -> RebuildOutcomeRecord:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return RebuildOutcomeRecord(
            path=path,
            sha_key=None,
            service=None,
            current_sha=None,
            outcome=None,
            timestamp=None,
            category="stale_unknown",
            reason=f"unreadable outcome record: {exc}",
        )

    if not isinstance(payload, Mapping):
        return RebuildOutcomeRecord(
            path=path,
            sha_key=None,
            service=None,
            current_sha=None,
            outcome=None,
            timestamp=None,
            category="stale_unknown",
            reason="outcome record is not an object",
        )

    timestamp = _optional_str(payload.get("timestamp"))
    record = RebuildOutcomeRecord(
        path=path,
        sha_key=_optional_str(payload.get("sha_key")),
        service=_optional_str(payload.get("service")),
        current_sha=_optional_str(payload.get("current_sha")),
        outcome=_optional_str(payload.get("outcome")),
        timestamp=timestamp,
        age_s=_timestamp_age_s(timestamp, now_epoch),
        category="stale_unknown",
    )

    if not current_sha:
        return _replace_reason(record, "current origin/main SHA is unavailable")
    if record.current_sha != current_sha:
        return _replace_reason(record, "outcome current_sha does not match origin/main")
    if record.age_s is None:
        return _replace_reason(record, "outcome timestamp is missing or malformed")
    if record.age_s < 0:
        return _replace_reason(record, "outcome timestamp is in the future")
    if record.age_s > max_age_s:
        return _replace_reason(record, "outcome timestamp is stale")
    if record.outcome in CLEARABLE_OUTCOMES:
        return _replace_category(record, "pass")
    if record.outcome in WARNING_OUTCOMES:
        return _replace_category(record, "warn")
    if record.outcome in HOLD_OUTCOMES:
        return _replace_category(record, "hold")
    if record.outcome in FAIL_OUTCOMES:
        return _replace_category(record, "fail")
    return _replace_reason(record, "outcome is unknown")


def _timestamp_age_s(timestamp: str | None, now_epoch: float) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return now_epoch - parsed.timestamp()


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _replace_category(record: RebuildOutcomeRecord, category: str) -> RebuildOutcomeRecord:
    return RebuildOutcomeRecord(
        path=record.path,
        sha_key=record.sha_key,
        service=record.service,
        current_sha=record.current_sha,
        outcome=record.outcome,
        timestamp=record.timestamp,
        category=category,
        age_s=record.age_s,
        reason=None,
    )


def _replace_reason(record: RebuildOutcomeRecord, reason: str) -> RebuildOutcomeRecord:
    return RebuildOutcomeRecord(
        path=record.path,
        sha_key=record.sha_key,
        service=record.service,
        current_sha=record.current_sha,
        outcome=record.outcome,
        timestamp=record.timestamp,
        category="stale_unknown",
        age_s=record.age_s,
        reason=reason,
    )
