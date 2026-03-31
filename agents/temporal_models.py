"""Temporal band data models — retention, impression, protention, surprise.

Frozen Pydantic models used by TemporalBandFormatter and consumers.
All pure data, no logic beyond computed properties.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetentionEntry(BaseModel, frozen=True):
    """A fading memory from the recent past."""

    timestamp: float
    age_s: float = Field(ge=0.0)  # seconds ago
    flow_state: str = "idle"
    activity: str = ""
    audio_energy: float = 0.0
    heart_rate: int = 0
    presence: str = ""  # PRESENT/UNCERTAIN/AWAY from Bayesian engine
    summary: str = ""


class ProtentionEntry(BaseModel, frozen=True):
    """A simple prediction about the near future."""

    predicted_state: str
    confidence: float = Field(ge=0.0, le=1.0)
    basis: str  # what observation drove this prediction


class SurpriseField(BaseModel, frozen=True):
    """A single surprising observation in the primal impression."""

    field: str
    observed: str  # what actually happened
    expected: str  # what was predicted
    surprise: float = Field(ge=0.0, le=1.0)
    note: str = ""  # human-readable explanation


class TemporalBands(BaseModel, frozen=True):
    """Complete temporal structure: retention → impression → protention."""

    retention: list[RetentionEntry] = Field(default_factory=list)
    impression: dict[str, object] = Field(default_factory=dict)
    protention: list[ProtentionEntry] = Field(default_factory=list)
    surprises: list[SurpriseField] = Field(default_factory=list)

    @property
    def max_surprise(self) -> float:
        """Highest surprise score across all fields. 0.0 if none."""
        return max((s.surprise for s in self.surprises), default=0.0)
