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

import time
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
    BOREDOM = "boredom"  # system-internal: nothing interesting
    CURIOSITY = "curiosity"  # system-internal: something novel found
    EXPLORATION_OPPORTUNITY = "exploration_opp"  # system-internal: bored but see a target


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
    trace_id: str | None = None  # OTel trace ID (32-hex) for chronicle causal chains
    span_id: str | None = None  # OTel span ID (16-hex) for chronicle causal chains
    embedding: list[float] | None = None  # 768-dim vector for affordance retrieval


def render_impingement_text(imp: Impingement) -> str:
    """Render impingement content as embeddable text for affordance retrieval."""
    parts = [f"source: {imp.source}"]
    if imp.content.get("metric"):
        parts.append(f"signal: {imp.content['metric']}")
    if imp.content.get("value") is not None:
        parts.append(f"value: {imp.content['value']}")
    if imp.interrupt_token:
        parts.append(f"critical: {imp.interrupt_token}")
    return "; ".join(parts)


def cascade_depth(imp: Impingement) -> int:
    """Get the cascade depth of an impingement (0 = root, no parent)."""
    return imp.content.get("_cascade_depth", 0)


def child_impingement(
    *,
    parent: Impingement,
    source: str,
    type: ImpingementType,
    content: dict[str, Any],
    decay: float = 0.7,
    max_depth: int = 3,
) -> Impingement | None:
    """Create a child impingement with decayed strength and parent tracing.
    Returns None if max cascade depth exceeded.
    """
    depth = cascade_depth(parent) + 1
    if depth > max_depth:
        return None
    return Impingement(
        timestamp=time.time(),
        source=source,
        type=type,
        strength=parent.strength * decay,
        content={**content, "_cascade_depth": depth},
        context=parent.context,
        parent_id=parent.id,
    )
