"""Tests for Health Connect SQLite parser — extracts daily summaries."""
from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

from agents.health_connect_parser import (
    extract_zip,
    format_daily_summary,
    parse_health_db,
    write_rag_documents,
)


class TestExtractZip:
    """Extracts Health Connect backup zip to temp directory."""

    def test_extracts_sqlite_db(self, tmp_path):
        """Finds and extracts the SQLite database from the zip."""
        zip_path = tmp_path / "Health Connect.zip"
        db_data = _create_test_db()
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("health_connect.db", db_data)
        result = extract_zip(zip_path, tmp_path / "extracted")
        assert result is not None
        assert result.exists()
        assert result.suffix == ".db"

    def test_returns_none_for_missing_db(self, tmp_path):
        """Returns None when zip contains no SQLite database."""
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "nothing here")
        result = extract_zip(zip_path, tmp_path / "extracted")
        assert result is None


class TestParseHealthDb:
    """Extracts daily aggregates from Health Connect SQLite."""

    def test_extracts_heart_rate_daily(self, health_db_path):
        """Aggregates heart rate readings into daily min/max/mean."""
        days = parse_health_db(health_db_path)
        assert len(days) >= 1
        day = days[0]
        assert "resting_hr" in day
        assert isinstance(day["resting_hr"], (int, float))

    def test_extracts_sleep_sessions(self, health_db_path):
        """Parses sleep session start/end and stage durations."""
        days = parse_health_db(health_db_path)
        day = days[0]
        assert "sleep_start" in day or "sleep_duration_min" in day

    def test_extracts_steps(self, health_db_path):
        """Sums step count per day."""
        days = parse_health_db(health_db_path)
        day = days[0]
        assert "steps" in day
        assert day["steps"] >= 0

    def test_handles_empty_db(self, tmp_path):
        """Returns empty list for database with no health records."""
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        days = parse_health_db(db_path)
        assert days == []


class TestFormatDailySummary:
    """Formats daily data as markdown with YAML frontmatter."""

    def test_includes_frontmatter(self):
        """Output has YAML frontmatter with required keys."""
        day = _sample_day_data()
        md = format_daily_summary(day)
        assert md.startswith("---\n")
        assert "content_type: daily_health_summary" in md
        assert "source_service: health_connect" in md
        assert "device: pixel_watch_4" in md

    def test_includes_all_metrics(self):
        """Summary body contains all available metrics."""
        day = _sample_day_data()
        md = format_daily_summary(day)
        assert "Resting HR" in md
        assert "Steps" in md
        assert "Sleep" in md


class TestWriteRagDocuments:
    """Writes daily summaries to rag-sources/health-connect/."""

    def test_writes_markdown_files(self, tmp_path):
        """Creates one .md file per day in output directory."""
        days = [_sample_day_data(), _sample_day_data("2026-03-11")]
        write_rag_documents(days, tmp_path)
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 2

    def test_skips_existing_unchanged(self, tmp_path):
        """Does not overwrite files if content unchanged."""
        days = [_sample_day_data()]
        write_rag_documents(days, tmp_path)
        first_mtime = (tmp_path / "health-2026-03-12.md").stat().st_mtime
        import time
        time.sleep(0.05)
        write_rag_documents(days, tmp_path)
        second_mtime = (tmp_path / "health-2026-03-12.md").stat().st_mtime
        assert first_mtime == second_mtime


# ── Fixtures & Helpers ──

def _create_test_db() -> bytes:
    """Create a minimal Health Connect SQLite database as bytes."""
    # We need to write to a temp file because sqlite3 can't write to BytesIO directly
    import os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE IF NOT EXISTS heart_rate_record (
            uid TEXT, time INTEGER, bpm REAL
        )""")
        conn.execute("INSERT INTO heart_rate_record VALUES ('1', 1741795200, 72.0)")
        conn.execute("INSERT INTO heart_rate_record VALUES ('2', 1741795260, 68.0)")
        conn.commit()
        conn.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


@pytest.fixture
def health_db_path(tmp_path):
    """Create a test Health Connect SQLite database."""
    db_path = tmp_path / "health_connect.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE heart_rate_record (
        uid TEXT, time INTEGER, bpm REAL
    )""")
    conn.execute("""CREATE TABLE steps_record (
        uid TEXT, start_time INTEGER, end_time INTEGER, count INTEGER
    )""")
    conn.execute("""CREATE TABLE sleep_session_record (
        uid TEXT, start_time INTEGER, end_time INTEGER
    )""")
    # Populate with test data
    base_ts = 1741795200  # epoch for a test date
    for i in range(24):
        conn.execute("INSERT INTO heart_rate_record VALUES (?, ?, ?)",
                     (f"hr-{i}", base_ts + i * 3600, 65 + i % 10))
    conn.execute("INSERT INTO steps_record VALUES ('s1', ?, ?, 8234)",
                 (base_ts, base_ts + 86400))
    conn.execute("INSERT INTO sleep_session_record VALUES ('sl1', ?, ?)",
                 (base_ts - 3600, base_ts + 25200))
    conn.commit()
    conn.close()
    return db_path


def _sample_day_data(date: str = "2026-03-12") -> dict:
    return {
        "date": date,
        "resting_hr": 62,
        "steps": 8234,
        "sleep_start": "23:15",
        "sleep_end": "06:48",
        "sleep_duration_min": 453,
        "active_minutes": 42,
    }


class TestPhoneSkipLogic:
    """Skips dates already covered by phone-posted data."""

    def test_skips_phone_posted_dates(self, tmp_path):
        """Does not overwrite files posted by phone (device: pixel_10)."""
        # Write a phone-posted file
        phone_content = "---\ndevice: pixel_10\n---\n# Health\nPhone data"
        (tmp_path / "health-2026-03-12.md").write_text(phone_content)
        days = [_sample_day_data()]
        write_rag_documents(days, tmp_path)
        # File should still contain phone data
        content = (tmp_path / "health-2026-03-12.md").read_text()
        assert "device: pixel_10" in content

    def test_writes_when_no_phone_data(self, tmp_path):
        """Writes normally when no phone-posted file exists."""
        days = [_sample_day_data()]
        write_rag_documents(days, tmp_path)
        content = (tmp_path / "health-2026-03-12.md").read_text()
        assert "device: pixel_watch_4" in content

    def test_force_overrides_phone_skip(self, tmp_path):
        """--force flag overrides phone skip for backfill."""
        phone_content = "---\ndevice: pixel_10\n---\n# Health\nPhone data"
        (tmp_path / "health-2026-03-12.md").write_text(phone_content)
        days = [_sample_day_data()]
        write_rag_documents(days, tmp_path, force=True)
        content = (tmp_path / "health-2026-03-12.md").read_text()
        assert "device: pixel_watch_4" in content


class TestRagIntegration:
    """Verify health-connect documents are recognized by ingest pipeline."""

    def test_source_service_auto_detected(self):
        """Ingest auto-detects source_service from health-connect path."""
        import importlib
        import sys
        import types

        # Stub heavy optional deps so agents.ingest can be imported in test env
        stubs: dict[str, types.ModuleType] = {}
        stub_names = (
            "watchdog", "watchdog.events", "watchdog.observers",
            "docling", "docling.document_converter", "docling.chunking",
            "qdrant_client", "qdrant_client.models", "ollama",
        )
        for mod_name in stub_names:
            if mod_name not in sys.modules:
                mod = types.ModuleType(mod_name)
                sys.modules[mod_name] = mod
                stubs[mod_name] = mod

        # Provide required names on stub modules
        sys.modules["watchdog.events"].FileSystemEventHandler = type("FileSystemEventHandler", (), {})  # type: ignore[attr-defined]
        sys.modules["watchdog.observers"].Observer = type("Observer", (), {})  # type: ignore[attr-defined]

        try:
            # Force re-import in case module was partially cached
            if "agents.ingest" in sys.modules:
                importlib.reload(sys.modules["agents.ingest"])
            from agents.ingest import enrich_payload

            payload = {"source": str(Path.home() / "documents/rag-sources/health-connect/health-2026-03-12.md")}
            result = enrich_payload(payload, {})
            assert result.get("source_service") == "health_connect"
        finally:
            # Clean up stubs we added
            for mod_name in stubs:
                sys.modules.pop(mod_name, None)
