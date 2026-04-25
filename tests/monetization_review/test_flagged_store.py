"""Flagged-payload partitioned-store semantics."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.monetization_review.flagged_store import (
    FlaggedRecord,
    FlaggedStore,
)


class TestRecord:
    def test_record_creates_dated_directory(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC).timestamp()
        path = store.record_block(
            capability_name="knowledge.web_search",
            surface="tts",
            rendered_payload="dangerous text",
            risk="high",
            reason="ring2 escalation",
            now=ts,
        )
        assert path == tmp_path / "2026-04-25" / "knowledge.web_search.jsonl"
        assert path.exists()

    def test_record_appends_jsonl_line(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC).timestamp()
        store.record_block(
            capability_name="cap.one",
            surface="captions",
            rendered_payload="payload one",
            risk="medium",
            reason="reason one",
            now=ts,
        )
        store.record_block(
            capability_name="cap.one",
            surface="captions",
            rendered_payload="payload two",
            risk="medium",
            reason="reason two",
            now=ts,
        )
        target = tmp_path / "2026-04-25" / "cap.one.jsonl"
        lines = target.read_text().strip().split("\n")
        assert len(lines) == 2
        rec1 = json.loads(lines[0])
        assert rec1["rendered_payload"] == "payload one"
        rec2 = json.loads(lines[1])
        assert rec2["rendered_payload"] == "payload two"

    def test_record_coerces_non_string_payload(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC).timestamp()
        store.record_block(
            capability_name="cap.dict",
            surface="overlay",
            rendered_payload={"k": "v"},
            risk="medium",
            reason="r",
            now=ts,
        )
        target = tmp_path / "2026-04-25" / "cap.dict.jsonl"
        line = target.read_text().strip()
        rec = json.loads(line)
        assert "k" in rec["rendered_payload"]


class TestIter:
    def test_iter_empty_returns_empty(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        assert store.iter_records() == []

    def test_iter_returns_records_newest_first(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        old_ts = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC).timestamp()
        new_ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC).timestamp()
        store.record_block(
            capability_name="old.cap",
            surface="tts",
            rendered_payload="old payload",
            risk="medium",
            reason="r",
            now=old_ts,
        )
        store.record_block(
            capability_name="new.cap",
            surface="tts",
            rendered_payload="new payload",
            risk="medium",
            reason="r",
            now=new_ts,
        )
        records = store.iter_records()
        assert len(records) == 2
        assert records[0].date_str == "2026-04-25"
        assert records[1].date_str == "2026-04-23"

    def test_iter_skips_non_date_directories(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        # Operator-dropped scratch dir — store must ignore.
        (tmp_path / "scratch").mkdir()
        (tmp_path / "scratch" / "notes.txt").write_text("ignore me")
        store.record_block(
            capability_name="real.cap",
            surface="tts",
            rendered_payload="real",
            risk="medium",
            reason="r",
            now=datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC).timestamp(),
        )
        records = store.iter_records()
        assert len(records) == 1
        assert records[0].capability_name == "real.cap"

    def test_iter_skips_malformed_lines(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        date_dir = tmp_path / "2026-04-25"
        date_dir.mkdir()
        target = date_dir / "cap.jsonl"
        target.write_text(
            '{"ts": 1, "capability_name": "ok", "rendered_payload": "p"}\n'
            "this line is not json\n"
            '{"ts": 2, "capability_name": "ok", "rendered_payload": "q"}\n',
            encoding="utf-8",
        )
        records = store.iter_records()
        assert len(records) == 2


class TestPrune:
    def test_prune_removes_old_directories(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        now = time.time()
        old_date = (datetime.fromtimestamp(now, tz=UTC) - timedelta(days=10)).strftime("%Y-%m-%d")
        new_date = datetime.fromtimestamp(now, tz=UTC).strftime("%Y-%m-%d")
        (tmp_path / old_date).mkdir(parents=True)
        (tmp_path / old_date / "cap.jsonl").write_text("{}\n")
        (tmp_path / new_date).mkdir(parents=True)
        (tmp_path / new_date / "cap.jsonl").write_text("{}\n")

        removed = store.prune(retention_days=7, now=now)
        assert len(removed) == 1
        assert removed[0].name == old_date
        assert not (tmp_path / old_date).exists()
        assert (tmp_path / new_date).exists()

    def test_prune_skips_recent_directories(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        now = time.time()
        recent_date = datetime.fromtimestamp(now, tz=UTC).strftime("%Y-%m-%d")
        (tmp_path / recent_date).mkdir(parents=True)
        (tmp_path / recent_date / "cap.jsonl").write_text("{}\n")

        removed = store.prune(retention_days=7, now=now)
        assert removed == []
        assert (tmp_path / recent_date).exists()

    def test_prune_ignores_non_date_directories(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        (tmp_path / "scratch").mkdir()
        (tmp_path / "scratch" / "file.txt").write_text("preserve me")

        removed = store.prune(retention_days=7)
        assert removed == []
        assert (tmp_path / "scratch").exists()

    def test_prune_on_missing_root_returns_empty(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path / "nonexistent")
        assert store.prune() == []


class TestRecordRoundTrip:
    def test_record_then_iter_yields_back_same_data(self, tmp_path: Path) -> None:
        store = FlaggedStore(root=tmp_path)
        ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC).timestamp()
        store.record_block(
            capability_name="cap.one",
            surface="tts",
            rendered_payload="phrase",
            risk="medium",
            reason="r1",
            programme_id="p-001",
            now=ts,
        )
        records = store.iter_records()
        assert len(records) == 1
        rec: FlaggedRecord = records[0]
        assert rec.capability_name == "cap.one"
        assert rec.surface == "tts"
        assert rec.rendered_payload == "phrase"
        assert rec.risk == "medium"
        assert rec.reason == "r1"
        assert rec.programme_id == "p-001"
        assert rec.ts == pytest.approx(ts)
