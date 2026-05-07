from __future__ import annotations

import json

import pytest

from shared import segment_prep_pause as pause


def test_missing_pause_state_fails_closed_to_research_only(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pause.json"
    monkeypatch.delenv(pause.PAUSE_MODE_ENV, raising=False)
    monkeypatch.delenv(pause.AUTHORITY_MODE_ENV, raising=False)
    monkeypatch.setenv(pause.PAUSE_FILE_ENV, str(path))

    state = pause.load_pause_state()

    assert state.mode == "research_only"
    assert state.allows("research")
    assert not state.allows("pool_generation")
    assert state.path == str(path)


def test_research_only_blocks_pool_generation_but_allows_research(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(pause.PAUSE_FILE_ENV, str(tmp_path / "pause.json"))
    monkeypatch.setenv(pause.PAUSE_MODE_ENV, "research_only")
    monkeypatch.setenv(pause.PAUSE_REASON_ENV, "test pause")

    state = pause.assert_segment_prep_allowed("research")

    assert state.mode == "research_only"
    with pytest.raises(pause.SegmentPrepPaused, match="pool_generation"):
        pause.assert_segment_prep_allowed("pool_generation")


def test_file_state_allows_docs_and_audit_but_blocks_canary(tmp_path) -> None:
    path = tmp_path / "pause.json"
    path.write_text(
        json.dumps({"mode": "docs_only", "reason": "write-up pass"}),
        encoding="utf-8",
    )

    state = pause.load_pause_state(path)

    assert state.allows("docs")
    assert state.allows("audit")
    assert not state.allows("canary")
    with pytest.raises(pause.SegmentPrepPaused, match="write-up pass"):
        pause.assert_segment_prep_allowed("pool_generation", path=path)


def test_env_mode_overrides_file_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "pause.json"
    path.write_text(json.dumps({"mode": "paused"}), encoding="utf-8")
    monkeypatch.setenv(pause.PAUSE_MODE_ENV, "pool_generation_allowed")

    state = pause.assert_segment_prep_allowed("pool_generation", path=path)

    assert state.mode == "pool_generation_allowed"
    assert state.source == f"env:{pause.PAUSE_MODE_ENV}"


def test_authority_env_names_override_pause_env_names(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pause.json"
    monkeypatch.setenv(pause.PAUSE_FILE_ENV, str(path))
    monkeypatch.setenv(pause.PAUSE_MODE_ENV, "research_only")
    monkeypatch.setenv(pause.AUTHORITY_MODE_ENV, "runtime_pool_load_allowed")

    state = pause.assert_segment_prep_allowed("runtime_pool_load")

    assert state.mode == "runtime_pool_load_allowed"
    assert state.source == f"env:{pause.AUTHORITY_MODE_ENV}"


def test_cli_check_returns_nonzero_when_activity_is_blocked(tmp_path, capsys) -> None:
    path = tmp_path / "pause.json"
    pause.save_pause_state("research_only", reason="operator pause", path=path)

    assert pause.main(["--check", "--activity", "pool_generation", "--path", str(path)]) == 1

    captured = capsys.readouterr()
    assert "research_only" in captured.err
    assert "operator pause" in captured.err


def test_cli_set_and_clear_round_trip(tmp_path, capsys) -> None:
    path = tmp_path / "pause.json"

    assert pause.main(["--set", "canary_allowed", "--path", str(path), "--json"]) == 0
    set_payload = json.loads(capsys.readouterr().out)
    assert set_payload["mode"] == "canary_allowed"
    assert pause.load_pause_state(path).allows("canary")

    assert pause.main(["--clear", "--path", str(path), "--json"]) == 0
    clear_payload = json.loads(capsys.readouterr().out)
    assert clear_payload["mode"] == "research_only"
    assert not path.exists()
