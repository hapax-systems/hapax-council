"""Logos API routes for scout decision tracking."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/api", tags=["scout"])

DECISIONS_FILE = Path(__file__).parent.parent.parent.parent / "profiles" / "scout-decisions.jsonl"


class ScoutDecisionRequest(BaseModel):
    decision: str
    notes: str = ""

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in ("adopted", "deferred", "dismissed"):
            raise ValueError("decision must be 'adopted', 'deferred', or 'dismissed'")
        return v


@router.post("/scout/{component}/decide")
async def record_decision(component: str, body: ScoutDecisionRequest):
    record = {
        "component": component,
        "decision": body.decision,
        "timestamp": datetime.now(UTC).isoformat(),
        "notes": body.notes,
    }
    DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
    return record


@router.get("/scout/decisions")
async def get_decisions():
    if not DECISIONS_FILE.is_file():
        return {"decisions": []}
    decisions = []
    for line in DECISIONS_FILE.read_text().strip().splitlines():
        if line.strip():
            decisions.append(json.loads(line))
    return {"decisions": decisions}
