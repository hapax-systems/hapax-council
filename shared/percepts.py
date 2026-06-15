"""Shared percept envelope — one schema across audio and visual perception.

CASE-VOICE-FOUNDATION-20260610 §5d (points-not-roles): every perception
sample, regardless of modality, travels as the same envelope —
``{timestamp, source_point, geometry_class, confidence, payload}`` — on a
shared time base (epoch seconds, ``time.time()``) so CLAP/Essentia ↔ YOLO
multi-point correlation composes. ``source_point`` is a point id from
``config/perception-registry.yaml`` (see :mod:`shared.perception_registry`).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GeometryClass(StrEnum):
    """Capture geometry of a perception point (§5d class vocabulary)."""

    PERSON_ATTACHED = "person_attached"
    SPATIAL_ARRAY = "spatial_array"
    AV_PAIRED = "av_paired"
    CONTACT = "contact"
    AMBIENT = "ambient"
    INSTRUMENT = "instrument"


class Percept(BaseModel):
    """One perception sample from one registry point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: float
    """Epoch seconds (``time.time()``) — the shared cross-modal time base."""

    source_point: str
    """Point id from config/perception-registry.yaml."""

    geometry_class: GeometryClass
    confidence: float = Field(ge=0.0, le=1.0)
    payload: dict[str, Any] = Field(default_factory=dict)
    """Modality-specific body; convention: a ``kind`` key names the percept
    type (``vad``, ``doa``, ``asr_partial``, ``person``, ``scene`` …)."""


__all__ = ["GeometryClass", "Percept"]
