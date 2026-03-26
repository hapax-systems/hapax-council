"""Impingement — a detected deviation from the DMN's predictive model.

The universal currency of the activation cascade. Every impingement
represents something the DMN couldn't resolve internally and needs
to broadcast for capability recruitment.

Impingements are:
- Immutable (frozen Pydantic models)
- Traceable (id + parent_id for cascade chains)
- Typed (statistical deviation, pattern match, salience integration, absolute threshold)
- Scored (strength determines activation level of recruited capabilities)
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ImpingementType(StrEnum):
    """How the impingement was detected."""

    STATISTICAL_DEVIATION = "statistical_deviation"  # sensor differs from running average
    PATTERN_MATCH = "pattern_match"  # matches an interrupt token
    SALIENCE_INTEGRATION = "salience_integration"  # multi-modal salience exceeds threshold
    ABSOLUTE_THRESHOLD = "absolute_threshold"  # value outside acceptable range regardless of delta


class Impingement(BaseModel, frozen=True):
    """A detected deviation from the DMN's predictive model.

    Created by the DMN's sensory/evaluative ticks when signals cannot
    be resolved internally. Broadcast to all registered capabilities
    for recruitment.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float
    source: str  # which sensor/channel ("dmn.sensory", "audio.vad", "fortress.state")
    type: ImpingementType
    strength: float = Field(ge=0.0, le=1.0)  # activation value
    content: dict[str, Any] = Field(default_factory=dict)  # what was detected
    context: dict[str, Any] = Field(default_factory=dict)  # system state at detection
    interrupt_token: str | None = None  # if pattern-matched, which token
    parent_id: str | None = None  # for cascade tracing
