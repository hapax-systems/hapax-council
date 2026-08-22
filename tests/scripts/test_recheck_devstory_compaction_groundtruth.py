"""Tests for the dev-story compaction ground-truth recheck command.

The command is the durable witness for the compaction discriminator, so its own failure
paths matter: a recheck that reports success without checking anything is worse than no
recheck at all.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "recheck-devstory-compaction-groundtruth.py"
)
_spec = importlib.util.spec_from_file_location("recheck_groundtruth", _SCRIPT)
assert _spec and _spec.loader
recheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recheck)


def _write_transcript(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def _summary(uuid: str) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "sessionId": "s",
        "timestamp": "2026-08-22T00:00:00.000Z",
        "isCompactSummary": True,
        "message": {"role": "user", "content": "summary"},
    }


def _turn(uuid: str) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "sessionId": "s",
        "timestamp": "2026-08-22T00:00:00.000Z",
        "message": {"role": "user", "content": "operator turn"},
    }


def _install(monkeypatch, tmp_path: Path, ground_truth: dict) -> None:
    monkeypatch.setattr(recheck, "PROJECTS", tmp_path)
    monkeypatch.setattr(recheck, "GROUND_TRUTH", ground_truth)


def test_missing_groundtruth_exits_nonzero(monkeypatch, tmp_path, capsys):
    """Absence of the witness must not read as success — the whole point of the command."""
    _write_transcript(tmp_path / "proj" / "other.jsonl", [_turn("u1")])
    _install(monkeypatch, tmp_path, {"absent-session": (1, [1])})

    assert recheck.main([]) == 2
    out = capsys.readouterr().out
    assert "NOT RECHECKED" in out
    assert "Next action" in out


def test_missing_groundtruth_opt_out_is_explicit(monkeypatch, tmp_path, capsys):
    _write_transcript(tmp_path / "proj" / "other.jsonl", [_turn("u1")])
    _install(monkeypatch, tmp_path, {"absent-session": (1, [1])})

    assert recheck.main(["--allow-missing-groundtruth"]) == 0
    assert "WITHOUT a witness" in capsys.readouterr().out


def test_matching_groundtruth_passes(monkeypatch, tmp_path, capsys):
    _write_transcript(
        tmp_path / "proj" / "pinned.jsonl",
        [_turn("u1"), _summary("c1"), _turn("u2"), _summary("c2")],
    )
    _install(monkeypatch, tmp_path, {"pinned": (2, [2, 4])})

    assert recheck.main([]) == 0
    assert "GROUND-TRUTH RECHECK PASSED" in capsys.readouterr().out


def test_mismatched_positions_fail(monkeypatch, tmp_path, capsys):
    """A stale pinned expectation must fail loudly, with a next action."""
    _write_transcript(tmp_path / "proj" / "pinned.jsonl", [_turn("u1"), _summary("c1")])
    _install(monkeypatch, tmp_path, {"pinned": (1, [99])})

    assert recheck.main([]) == 1
    out = capsys.readouterr().out
    assert "FAILURES" in out
    assert "Next action" in out


def test_wrong_count_fails(monkeypatch, tmp_path):
    _write_transcript(tmp_path / "proj" / "pinned.jsonl", [_summary("c1")])
    _install(monkeypatch, tmp_path, {"pinned": (2, [1])})

    assert recheck.main([]) == 1


def test_find_transcript_searches_project_subdirectories(monkeypatch, tmp_path):
    _write_transcript(tmp_path / "proj-a" / "sess.jsonl", [_turn("u1")])
    monkeypatch.setattr(recheck, "PROJECTS", tmp_path)

    found = recheck.find_transcript("sess")
    assert found is not None and found.name == "sess.jsonl"
    assert recheck.find_transcript("nope") is None


def test_raw_marker_count_counts_wire_markers(tmp_path):
    path = tmp_path / "t.jsonl"
    _write_transcript(path, [_turn("u1"), _summary("c1"), _summary("c2")])
    assert recheck.raw_marker_count(path) == 2
