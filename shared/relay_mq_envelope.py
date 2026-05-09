from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MessageType = Literal["dispatch", "advisory", "escalation", "query"]
RecipientState = Literal["offered", "read", "accepted", "processed", "deferred", "escalated"]

PRIORITY_FRESHNESS: dict[int, tuple[int, int]] = {
    0: (600, 3600),
    1: (3600, 28800),
    2: (28800, 259200),
    3: (86400, 604800),
}

VALID_TRANSITIONS: dict[RecipientState, set[RecipientState]] = {
    "offered": {"read"},
    "read": {"accepted", "deferred", "escalated"},
    "accepted": {"processed", "deferred", "escalated"},
    "deferred": {"accepted", "escalated"},
    "processed": set(),
    "escalated": set(),
}

REASON_REQUIRED_TARGETS: set[RecipientState] = {"deferred", "escalated"}


def _uuid7() -> str:
    """Generate a UUID v7 (time-ordered, random). Python 3.12 lacks uuid.uuid7()."""
    timestamp_ms = int(time.time() * 1000)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    uuid_int = (timestamp_ms & 0xFFFFFFFFFFFF) << 80
    uuid_int |= 0x7 << 76
    uuid_int |= rand_a << 64
    uuid_int |= 0x2 << 62
    uuid_int |= rand_b
    return str(uuid.UUID(int=uuid_int))


def compute_payload_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def validate_transition(
    current: RecipientState,
    target: RecipientState,
    reason: str | None = None,
) -> None:
    valid_targets = VALID_TRANSITIONS.get(current, set())
    if target not in valid_targets:
        raise TransitionError(
            f"Invalid transition: {current} -> {target}. "
            f"Valid targets from {current}: {valid_targets or 'none (terminal state)'}"
        )
    if target in REASON_REQUIRED_TARGETS and not reason:
        raise ValueError(f"Reason is required when transitioning to {target}")


def serialize_tags(tags: list[str] | None) -> str | None:
    if tags is None:
        return None
    return json.dumps(tags)


def deserialize_tags(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return json.loads(raw)


class TransitionError(ValueError):
    pass


class DiskPressureError(Exception):
    pass


class Envelope(BaseModel):
    message_id: str = Field(default_factory=_uuid7)
    version: int = Field(default=1)
    sender: str
    message_type: MessageType
    priority: int = Field(default=2, ge=0, le=3)
    subject: str
    authority_case: str | None = None
    authority_item: str | None = None
    parent_message_id: str | None = None
    recipients_spec: str
    payload: str | None = None
    payload_path: str | None = None
    payload_hash: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    stale_after: datetime | None = None
    tags: list[str] | None = None

    @model_validator(mode="after")
    def _validate_envelope(self) -> Envelope:
        self.sender = self.sender.strip().lower().replace("_", "-")

        if len(self.subject) > 200:
            self.subject = self.subject[:200]

        if self.message_type == "dispatch" and self.authority_case is None:
            raise ValueError("Dispatch messages require authority_case (R2 I1)")

        if self.payload is not None and self.payload_path is not None:
            raise ValueError("Exactly one of payload or payload_path must be set, not both (R2 I2)")
        if self.payload is None and self.payload_path is None:
            raise ValueError("Exactly one of payload or payload_path must be set (R2 I2)")

        if self.payload_hash is None and self.payload is not None:
            self.payload_hash = compute_payload_hash(self.payload)

        stale_offset, expire_offset = PRIORITY_FRESHNESS[self.priority]
        if self.stale_after is None:
            self.stale_after = self.created_at + timedelta(seconds=stale_offset)
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(seconds=expire_offset)

        return self
