from __future__ import annotations

import hashlib
import json

import pytest

from shared import segment_prep_pause as pause
from shared.resident_command_r import RESIDENT_COMMAND_R_MODEL
from shared.segment_iteration_review import SEGMENT_ITERATION_REVIEW_VERSION


def _hash_payload(payload) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _passing_canary_receipt() -> dict:
    receipt = {
        "segment_iteration_review_version": SEGMENT_ITERATION_REVIEW_VERSION,
        "programme_id": "segment-prep-canary",
        "artifact_sha256": "a" * 64,
        "iteration_id": "segment-prep-canary-session",
        "automated_gate": {"passed": True},
        "eligibility_gate": {"passed": True},
        "excellence_selection": {
            "passed": True,
            "automation_passed": True,
            "team_passed": True,
        },
        "team_critique_loop": {"passed": True},
        "ready_for_next_nine": True,
        "next_nine_gate_mode": "blocking_review_receipt",
        "decision": "ready_for_next_nine",
        "resident_model_continuity": {
            "expected_model": RESIDENT_COMMAND_R_MODEL,
            "no_qwen": True,
            "no_unload_or_swap": True,
        },
    }
    receipt["review_receipt_sha256"] = _hash_payload(receipt)
    return receipt


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


@pytest.mark.parametrize("mode", ["open", "runtime_pool_load_allowed"])
def test_cli_set_runtime_modes_require_passing_canary_receipt(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    mode: str,
) -> None:
    path = tmp_path / "pause.json"
    monkeypatch.setenv(pause.STATE_ENV, str(tmp_path / "state"))

    assert pause.main(["--set", mode, "--path", str(path), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "requires a passing canary review receipt" in payload["error"]
    assert not path.exists()


def test_cli_set_open_accepts_passing_canary_receipt(tmp_path, capsys) -> None:
    path = tmp_path / "pause.json"
    receipt_path = tmp_path / "canary-review.json"
    receipt_path.write_text(json.dumps(_passing_canary_receipt()), encoding="utf-8")

    assert (
        pause.main(
            [
                "--set",
                "open",
                "--path",
                str(path),
                "--canary-review-receipt",
                str(receipt_path),
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "open"
    state = pause.load_pause_state(path)
    assert state.allows("pool_generation")
    assert state.allows("runtime_pool_load")
