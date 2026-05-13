from pydantic import BaseModel


class SceneLabel(BaseModel):
    label: str
    confidence: float


class DspState(BaseModel):
    tempo_bpm: float
    key: str
    onset_detected: bool


class DiarizationState(BaseModel):
    is_operator_speaking: bool
    active_speaker_confidence: float


class AudioState(BaseModel):
    scene_labels: list[SceneLabel]
    dsp: DspState
    diarization: DiarizationState


class OccupancyState(BaseModel):
    camera: str
    occupied: bool
    closest_depth_meters: float


class SpatialState(BaseModel):
    occupancy: list[OccupancyState]


class Phase1State(BaseModel):
    schema_version: int
    timestamp: str
    audio: AudioState
    spatial: SpatialState
