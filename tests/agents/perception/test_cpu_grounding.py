import json

from agents.perception.cpu_grounding import process_audio_stream, process_visual_stream
from shared.perception_schema import Phase1State


def test_cpu_grounding_schema_validation():
    audio = process_audio_stream()
    spatial = process_visual_stream()
    state = Phase1State(
        schema_version=1, timestamp="2026-05-13T20:00:00Z", audio=audio, spatial=spatial
    )
    data = json.loads(state.model_dump_json())
    assert data["schema_version"] == 1
    assert data["audio"]["scene_labels"][0]["label"] == "speech"
    assert data["spatial"]["occupancy"][0]["camera"] == "desk"
