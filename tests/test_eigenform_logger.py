import json
from pathlib import Path


def test_default_call_uses_isolated_sinks(tmp_path, monkeypatch) -> None:
    from shared import eigenform_logger

    # Exercise the production no-path call so removing conftest isolation leaks
    # into the subprocess HOME checked by test_persistent_sink_isolation.
    ring = tmp_path / "state-log.jsonl"
    monkeypatch.setattr(eigenform_logger, "EIGENFORM_LOG", ring)
    eigenform_logger.log_state_vector(presence=0.6)
    assert ring.read_text() == eigenform_logger.PERSISTENT_LOG.read_text()


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
