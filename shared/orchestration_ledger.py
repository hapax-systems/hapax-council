"""Cross-runtime orchestration ledger.

Append-only JSONL ledger tracking dispatch receipts, work claims, and
team composition snapshots across Claude, Codex, and Gemini runtimes.

CASE-SDLC-REFORM-001 / SLICE-003C-CROSS-RUNTIME
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

LEDGER_DIR = Path(
    os.environ.get(
        "HAPAX_ORCHESTRATION_LEDGER_DIR",
        os.path.expanduser("~/.cache/hapax/orchestration"),
    )
)
DISPATCH_LEDGER = LEDGER_DIR / "dispatch-ledger.jsonl"
CLAIM_LEDGER = LEDGER_DIR / "claim-ledger.jsonl"


class WorkstreamMode(Enum):
    SINGLE_LANE = "single_lane"
    SHARED_COORDINATED = "shared_coordinated"
    PARALLEL_SEPARATE = "parallel_separate"


class DispatchReceipt(BaseModel):
    dispatch_id: str
    timestamp: str
    dispatcher: str
    target_lane: str
    target_platform: str
    task_id: str | None = None
    authority_case_id: str | None = None
    workstream_mode: str = WorkstreamMode.SINGLE_LANE.value
    command: str = ""
    reason: str = ""
    outcome: str = "dispatched"

    model_config = {"extra": "allow"}


class WorkClaim(BaseModel):
    lane_id: str
    timestamp: str
    task_id: str
    authority_case_id: str | None = None
    claim_type: str = "active"
    branch: str | None = None
    pr: int | None = None
    notes: str = ""

    model_config = {"extra": "allow"}


class DuplicateSessionError(Exception):
    pass


class ProtectedSessionError(Exception):
    pass


def _append(path: Path, entry: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")


def _read_entries(path: Path, model: type[BaseModel], **filters: str) -> list:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        entry = model.model_validate_json(line)
        if all(getattr(entry, k, None) == v for k, v in filters.items()):
            entries.append(entry)
    return entries


def record_dispatch(receipt: DispatchReceipt) -> None:
    _append(DISPATCH_LEDGER, receipt)


def record_claim(claim: WorkClaim) -> None:
    _append(CLAIM_LEDGER, claim)


def dispatch_history(
    *,
    lane: str | None = None,
    limit: int = 50,
) -> list[DispatchReceipt]:
    entries = _read_entries(DISPATCH_LEDGER, DispatchReceipt)
    if lane:
        entries = [e for e in entries if e.target_lane == lane]
    return entries[-limit:]


def active_claims(*, lane: str | None = None) -> list[WorkClaim]:
    entries = _read_entries(CLAIM_LEDGER, WorkClaim)
    active = [e for e in entries if e.claim_type == "active"]
    if lane:
        active = [e for e in active if e.lane_id == lane]
    return active


def check_duplicate_session(
    lane_id: str,
    platform: str,
) -> None:
    """Raise if a lane already has an active dispatch on the same platform."""
    recent = dispatch_history(lane=lane_id, limit=20)
    active_dispatches = [
        r for r in recent if r.target_platform == platform and r.outcome == "dispatched"
    ]
    if active_dispatches:
        last = active_dispatches[-1]
        raise DuplicateSessionError(
            f"Lane {lane_id} already has active {platform} dispatch "
            f"(dispatch_id={last.dispatch_id}, task={last.task_id})"
        )


PROTECTION_FILE = Path(
    os.environ.get(
        "HAPAX_SESSION_PROTECTION",
        os.path.expanduser("~/.cache/hapax/relay/session-protection.md"),
    )
)


def check_protected_session(lane_id: str) -> None:
    """Raise if the lane is listed in the session protection file."""
    if not PROTECTION_FILE.exists():
        return
    text = PROTECTION_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip().lstrip("- ")
        if stripped.startswith(f"`{lane_id}`") and "protected" in stripped.lower():
            raise ProtectedSessionError(f"Lane {lane_id} is protected: {stripped}")


DISPATCH_ORDER_KEYS = [
    "hard_gate",
    "claimed_work",
    "stale_hygiene",
    "accepted_authority_case",
    "eligible_offered",
]


def select_dispatch_priority(
    candidates: list[dict],
) -> list[dict]:
    """Sort dispatch candidates by priority bucket then WSJF score.

    Each candidate dict must have:
      - priority_bucket: one of DISPATCH_ORDER_KEYS
      - wsjf: float score (higher = more urgent)
      - task_id: str
    """

    def sort_key(c: dict) -> tuple[int, float]:
        bucket_idx = (
            DISPATCH_ORDER_KEYS.index(c["priority_bucket"])
            if c["priority_bucket"] in DISPATCH_ORDER_KEYS
            else len(DISPATCH_ORDER_KEYS)
        )
        return (bucket_idx, -c.get("wsjf", 0.0))

    return sorted(candidates, key=sort_key)


def make_dispatch_id(dispatcher: str) -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"DISPATCH-{dispatcher}-{ts}"
