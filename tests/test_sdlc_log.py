"""Tests for shared.sdlc_log — SDLC decision event persistence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.sdlc_log import log_sdlc_event, read_sdlc_events, rotate_sdlc_log


class TestLogSdlcEvent:
    def test_creates_file_and_appends(self, tmp_path, monkeypatch):
        log_path = tmp_path / "sdlc-events.jsonl"
        monkeypatch.setattr("shared.sdlc_log.SDLC_LOG", log_path)

        log_sdlc_event("triage", issue_number=42, result={"type": "bug"}, duration_ms=150)
        log_sdlc_event("review", pr_number=10, result={"verdict": "approve"})

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 2
        entry = json.loads(lines[0])
        assert entry["stage"] == "triage"
        assert entry["issue_number"] == 42
        assert entry["result"]["type"] == "bug"
        assert "timestamp" in entry

    def test_handles_missing_parent_dir(self, tmp_path, monkeypatch):
        log_path = tmp_path / "nested" / "dir" / "sdlc-events.jsonl"
        monkeypatch.setattr("shared.sdlc_log.SDLC_LOG", log_path)
        log_sdlc_event("plan", issue_number=1)
        assert log_path.exists()


class TestReadSdlcEvents:
    def test_reads_and_filters_by_stage(self, tmp_path, monkeypatch):
        log_path = tmp_path / "sdlc-events.jsonl"
        monkeypatch.setattr("shared.sdlc_log.SDLC_LOG", log_path)

        log_sdlc_event("triage", issue_number=1)
        log_sdlc_event("review", pr_number=2)
        log_sdlc_event("triage", issue_number=3)

        all_events = read_sdlc_events()
        assert len(all_events) == 3

        triage_only = read_sdlc_events(stage_filter="triage")
        assert len(triage_only) == 2

    def test_limit(self, tmp_path, monkeypatch):
        log_path = tmp_path / "sdlc-events.jsonl"
        monkeypatch.setattr("shared.sdlc_log.SDLC_LOG", log_path)
        for i in range(10):
            log_sdlc_event("triage", issue_number=i)
        events = read_sdlc_events(limit=3)
        assert len(events) == 3

    def test_empty_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shared.sdlc_log.SDLC_LOG", tmp_path / "nope.jsonl")
        assert read_sdlc_events() == []


class TestRotateSdlcLog:
    def test_rotation(self, tmp_path, monkeypatch):
        log_path = tmp_path / "sdlc-events.jsonl"
        monkeypatch.setattr("shared.sdlc_log.SDLC_LOG", log_path)
        for i in range(20):
            log_sdlc_event("triage", issue_number=i)
        rotate_sdlc_log(max_lines=10, keep_lines=5)
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 5
        last = json.loads(lines[-1])
        assert last["issue_number"] == 19

    def test_no_rotation_below_threshold(self, tmp_path, monkeypatch):
        log_path = tmp_path / "sdlc-events.jsonl"
        monkeypatch.setattr("shared.sdlc_log.SDLC_LOG", log_path)
        for i in range(5):
            log_sdlc_event("triage", issue_number=i)
        rotate_sdlc_log(max_lines=10, keep_lines=5)
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 5
