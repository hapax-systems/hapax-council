"""Data models for screen awareness analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Issue:
    """A detected problem on screen."""

    severity: str  # "error", "warning", "info"
    description: str
    confidence: float  # 0.0-1.0


@dataclass
class ScreenAnalysis:
    """Structured result from screen analysis."""

    app: str
    context: str
    summary: str
    issues: list[Issue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CameraConfig:
    """Configuration for a single webcam device."""

    device: str  # /dev/v4l/by-id/... or /dev/videoN
    role: str  # "operator", "hardware", "ir"
    width: int = 1280
    height: int = 720
    input_format: str = "mjpeg"
    pixel_format: str | None = None  # "gray" for IR sensor


@dataclass
class GearObservation:
    """Observed state of a hardware device from the C920 camera."""

    device: str
    powered: bool | None  # True/False/None(can't tell)
    display_content: str
    notes: str


@dataclass
class WorkspaceAnalysis:
    """Extended analysis covering screen + operator + hardware state."""

    # Screen awareness (same as ScreenAnalysis)
    app: str
    context: str
    summary: str
    issues: list[Issue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    # Operator awareness
    operator_present: bool | None = None
    operator_activity: str = "unknown"
    operator_attention: str = "unknown"
    # Hardware awareness
    gear_state: list[GearObservation] = field(default_factory=list)
    workspace_change: bool = False
