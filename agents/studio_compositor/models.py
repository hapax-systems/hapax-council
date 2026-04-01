"""Pydantic models for the studio compositor."""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel, Field


class CameraV4L2(BaseModel):
    """V4L2 control values for a camera."""

    gain: int | None = None
    exposure: int | None = None
    brightness: int | None = None
    contrast: int | None = None
    saturation: int | None = None
    sharpness: int | None = None
    white_balance_temperature: int | None = None
    focus_absolute: int | None = None


class CameraProfile(BaseModel):
    """A named camera profile with optional schedule/condition gating."""

    name: str
    schedule: str | None = None
    condition: str | None = None
    priority: int = 0
    cameras: dict[str, CameraV4L2] = Field(default_factory=dict)


class CameraSpec(BaseModel):
    """A single camera source."""

    role: str
    device: str
    width: int = 1280
    height: int = 720
    input_format: str = "mjpeg"
    pixel_format: str | None = None
    hero: bool = False


class RecordingConfig(BaseModel):
    """Per-camera recording configuration."""

    enabled: bool = True
    output_dir: str = str(Path.home() / "video-recording")
    segment_seconds: int = 300
    qp: int = 23


class HlsConfig(BaseModel):
    """HLS output configuration."""

    enabled: bool = True
    target_duration: int = 2
    playlist_length: int = 10
    max_files: int = 15
    output_dir: str = str(Path.home() / ".cache" / "hapax-compositor" / "hls")
    bitrate: int = 4000


class CompositorConfig(BaseModel):
    """Full compositor configuration."""

    cameras: list[CameraSpec] = Field(default_factory=list)
    output_device: str = "/dev/video42"
    output_width: int = 1920
    output_height: int = 1080
    framerate: int = 10  # was 30 — no consumer needs >10fps. Saves ~67% compositor CPU.
    bitrate: int = 8_000_000
    watchdog_timeout_ms: int = 5000
    status_interval_s: float = 5.0
    overlay_enabled: bool = True
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    hls: HlsConfig = Field(default_factory=HlsConfig)
    camera_profiles: list[CameraProfile] = Field(default_factory=list)


class TileRect(BaseModel):
    x: int
    y: int
    w: int
    h: int


class OverlayData(BaseModel):
    """Snapshot of perception state for rendering overlays."""

    production_activity: str = ""
    desk_activity: str = ""
    overhead_hand_zones: str = ""
    detected_action: str = ""
    music_genre: str = ""
    flow_state: str = ""
    flow_score: float = 0.0
    emotion_valence: float = 0.0
    emotion_arousal: float = 0.0
    audio_energy_rms: float = 0.0
    active_contracts: list[str] = Field(default_factory=list)
    persistence_allowed: bool = True
    guest_present: bool = False
    consent_phase: str = "no_guest"
    timestamp: float = 0.0
    mixer_energy: float = 0.0
    mixer_beat: float = 0.0
    mixer_bass: float = 0.0
    mixer_mid: float = 0.0
    mixer_high: float = 0.0
    mixer_active: bool = False
    beat_position: float = 0.0
    bar_position: float = 0.0
    desk_energy: float = 0.0
    desk_onset_rate: float = 0.0
    desk_spectral_centroid: float = 0.0
    heart_rate_bpm: float = 0.0
    stress_elevated: bool = False


class OverlayState:
    """Thread-safe cache for overlay rendering data."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = OverlayData()
        self._stale = True

    @property
    def data(self) -> OverlayData:
        with self._lock:
            return self._data.model_copy()

    @property
    def stale(self) -> bool:
        with self._lock:
            return self._stale

    def update(self, data: OverlayData) -> None:
        with self._lock:
            self._data = data
            self._stale = False

    def mark_stale(self) -> None:
        with self._lock:
            self._stale = True
