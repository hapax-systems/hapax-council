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
    confidence: float = Field(ge=0.0, le=1.0)  # probability of the predicted state
    basis: str  # what observation drove this prediction
    # Rosen anticipatory-model confidence / future steering-magnitude — the open,
    # affect-suffused protention weight. Distinct from `confidence`. Defaulted so
    # existing call sites are unaffected (never-remove); populated by the
    # affect/IDF REQ. See REQ-20260605-temporal-2d-band-tense-grid.
    precision: float = Field(default=0.0, ge=0.0, le=1.0)


class SurpriseField(BaseModel, frozen=True):
    """A single surprising observation in the primal impression."""

    field: str
    observed: str  # what actually happened
    expected: str  # what was predicted
    surprise: float = Field(ge=0.0, le=1.0)
    note: str = ""  # human-readable explanation


class CircadianContext(BaseModel, frozen=True):
    """Daily accumulation summary for LLM circadian reasoning."""

    session_count: int = 0
    total_minutes: int = 0
    total_flow_minutes: int = 0
    total_voice_minutes: int = 0
    dominant_activity: str = ""
    activities: dict[str, int] = Field(default_factory=dict)


class TemporalBands(BaseModel, frozen=True):
    """Complete temporal structure: retention → impression → protention.

    Tick-level retention (50s window) is always present. Multi-scale
    fields (minute/session/day) are populated when a MultiScaleContext
    is passed to the formatter.
    """

    retention: list[RetentionEntry] = Field(default_factory=list)
    impression: dict[str, object] = Field(default_factory=dict)
    protention: list[ProtentionEntry] = Field(default_factory=list)
    surprises: list[SurpriseField] = Field(default_factory=list)

    # Multi-scale retention (optional, from MultiScaleAggregator)
    minute_summaries: list[dict[str, object]] = Field(default_factory=list)
    current_session: dict[str, object] | None = None
    recent_sessions: list[dict[str, object]] = Field(default_factory=list)
    day_context: CircadianContext | None = None

    @property
    def max_surprise(self) -> float:
        """Highest surprise score across all fields. 0.0 if none."""
        return max((s.surprise for s in self.surprises), default=0.0)
