"""CPU-only multimodal grounding orchestration."""

import time
from datetime import UTC, datetime
from pathlib import Path

from shared.perception_schema import (
    AudioState,
    DiarizationState,
    DspState,
    OccupancyState,
    Phase1State,
    SceneLabel,
    SpatialState,
)

STATE_PATH = Path("/dev/shm/hapax-perception/phase1_state.json")


def process_audio_stream() -> AudioState:
    # Stubbed audio stream ingestion
    return AudioState(
        scene_labels=[
            SceneLabel(label="speech", confidence=0.95),
            SceneLabel(label="keyboard typing", confidence=0.82),
        ],
        dsp=DspState(tempo_bpm=120.5, key="C major", onset_detected=False),
        diarization=DiarizationState(is_operator_speaking=True, active_speaker_confidence=0.98),
    )


def process_visual_stream() -> SpatialState:
    # Stubbed spatial stream ingestion
    return SpatialState(
        occupancy=[OccupancyState(camera="desk", occupied=True, closest_depth_meters=0.8)]
    )


def main():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    while True:
        state = Phase1State(
            schema_version=1,
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            audio=process_audio_stream(),
            spatial=process_visual_stream(),
        )
        STATE_PATH.write_text(state.model_dump_json(), encoding="utf-8")
        time.sleep(1)


if __name__ == "__main__":
    main()
