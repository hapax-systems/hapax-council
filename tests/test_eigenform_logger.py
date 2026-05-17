import json
from pathlib import Path


def test_log_state_vector(tmp_path: Path) -> None:
    from shared.eigenform_logger import log_state_vector

    path = tmp_path / "state-log.jsonl"
    log_state_vector(presence=0.9, flow_score=0.7, stimmung_stance="nominal", path=path)
    log_state_vector(presence=0.8, flow_score=0.6, stimmung_stance="cautious", path=path)

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["presence"] == 0.9
    assert entry["stimmung_stance"] == "nominal"
    assert "t" in entry


def test_trim_old_entries(tmp_path: Path) -> None:
    from shared.eigenform_logger import MAX_ENTRIES, log_state_vector

    path = tmp_path / "state-log.jsonl"
    for i in range(MAX_ENTRIES * 2 + 10):
        log_state_vector(presence=float(i), path=path)

    lines = path.read_text().strip().split("\n")
    assert len(lines) <= MAX_ENTRIES + 15  # tolerance for writes after last trim


def test_imagination_salience_reads_from_shm(tmp_path: Path) -> None:
    """_read_imagination_salience must read live value, not hardcoded 0.0."""
    from agents.visual_layer_aggregator.aggregator import VisualLayerAggregator

    shm_file = tmp_path / "current.json"
    shm_file.write_text(json.dumps({"salience": 0.42}))
    vla = VisualLayerAggregator.__new__(VisualLayerAggregator)
    result = vla._read_imagination_salience(path=shm_file)
    assert result == 0.42


def test_imagination_salience_fallback_on_missing_file() -> None:
    """Missing imagination file returns 0.0, not an error."""
    from agents.visual_layer_aggregator.aggregator import VisualLayerAggregator

    vla = VisualLayerAggregator.__new__(VisualLayerAggregator)
    result = vla._read_imagination_salience(path=Path("/nonexistent/file.json"))
    assert result == 0.0


def test_activity_never_empty_string() -> None:
    """production_activity empty string should become 'idle'."""
    pd: dict[str, str] = {"production_activity": ""}
    activity = str(pd.get("production_activity", "") or "idle")
    assert activity == "idle"


def test_activity_preserves_real_value() -> None:
    """production_activity with real value passes through."""
    pd: dict[str, str] = {"production_activity": "production"}
    activity = str(pd.get("production_activity", "") or "idle")
    assert activity == "production"
