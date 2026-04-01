import time


def test_consume_impingements_from_jsonl(tmp_path):
    from agents._apperception import consume_perception_impingements
    from shared.impingement import Impingement, ImpingementType

    jsonl_path = tmp_path / "impingements.jsonl"
    imp = Impingement(
        timestamp=time.time(),
        source="perception.ir_person_detected",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.7,
        content={"metric": "ir_person_detected", "value": 0, "delta": -1.0},
    )
    jsonl_path.write_text(imp.model_dump_json() + "\n")
    events = consume_perception_impingements(path=jsonl_path, cursor=0)
    assert len(events) >= 1
    assert events[0].source == "prediction_error"
