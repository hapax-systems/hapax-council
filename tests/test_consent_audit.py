"""Tests for historical consent audit.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.consent_audit import AuditResult, FlaggedDocument, purge_flagged, scan_historical_audio


def _write_rag_doc(directory: Path, name: str, frontmatter: dict, body: str = "") -> Path:
    """Write a markdown file with YAML frontmatter."""
    import yaml

    path = directory / name
    fm_text = yaml.dump(frontmatter, default_flow_style=False).strip()
    path.write_text(f"---\n{fm_text}\n---\n{body}")
    return path


class TestScanHistoricalAudio(unittest.TestCase):
    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("agents.consent_audit.RAG_AUDIO_DIR", Path(tmpdir)):
                result = scan_historical_audio()
                assert result.scanned == 0
                assert result.flagged == 0

    def test_single_speaker_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            _write_rag_doc(
                d,
                "note-001.md",
                {
                    "content_type": "vocal_note",
                    "speaker_count": 1,
                },
            )
            with patch("agents.consent_audit.RAG_AUDIO_DIR", d):
                result = scan_historical_audio()
                assert result.scanned == 1
                assert result.flagged == 0
                assert result.clean == 1

    def test_multi_speaker_without_consent_flagged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            _write_rag_doc(
                d,
                "conv-001.md",
                {
                    "content_type": "conversation",
                    "speaker_count": 2,
                    "speakers": ["SPEAKER_00", "SPEAKER_01"],
                },
            )
            with patch("agents.consent_audit.RAG_AUDIO_DIR", d):
                result = scan_historical_audio()
                assert result.flagged == 1
                assert result.documents[0].speaker_count == 2

    def test_multi_speaker_with_consent_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            _write_rag_doc(
                d,
                "conv-002.md",
                {
                    "content_type": "conversation",
                    "speaker_count": 2,
                    "consent_label": [{"owner": "wife", "readers": ["operator"]}],
                    "provenance": ["contract-wife"],
                },
            )
            with patch("agents.consent_audit.RAG_AUDIO_DIR", d):
                result = scan_historical_audio()
                assert result.flagged == 0
                assert result.clean == 1

    def test_mixed_documents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            _write_rag_doc(d, "note-001.md", {"content_type": "vocal_note", "speaker_count": 1})
            _write_rag_doc(
                d,
                "conv-001.md",
                {
                    "content_type": "conversation",
                    "speaker_count": 3,
                    "speakers": ["A", "B", "C"],
                },
            )
            _write_rag_doc(d, "listen-001.md", {"content_type": "listening_log"})
            with patch("agents.consent_audit.RAG_AUDIO_DIR", d):
                result = scan_historical_audio()
                assert result.scanned == 3
                assert result.flagged == 1
                assert result.clean == 2


class TestPurgeFlagged(unittest.TestCase):
    def test_dry_run_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            doc = d / "conv-001.md"
            doc.write_text("content")

            result = AuditResult(
                documents=[
                    FlaggedDocument(
                        path=str(doc),
                        content_type="conversation",
                        speaker_count=2,
                        timestamp="",
                        reason="test",
                    )
                ]
            )
            deleted = purge_flagged(result, dry_run=True)
            assert deleted == 1
            assert doc.exists()  # not actually deleted

    def test_actual_purge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            doc = d / "conv-001.md"
            doc.write_text("content")

            result = AuditResult(
                documents=[
                    FlaggedDocument(
                        path=str(doc),
                        content_type="conversation",
                        speaker_count=2,
                        timestamp="",
                        reason="test",
                    )
                ]
            )
            deleted = purge_flagged(result, dry_run=False)
            assert deleted == 1
            assert not doc.exists()


class TestSaveReport(unittest.TestCase):
    def test_saves_json(self):
        from agents.consent_audit import save_report

        result = AuditResult(
            scanned=10,
            flagged=2,
            clean=8,
            scan_timestamp="2026-03-15T00:00:00",
            documents=[
                FlaggedDocument(
                    path="/tmp/test.md",
                    content_type="conversation",
                    speaker_count=2,
                    timestamp="",
                    reason="test",
                )
            ],
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            report_path = Path(f.name)

        try:
            with patch("agents.consent_audit.REPORT_PATH", report_path):
                save_report(result)
            data = json.loads(report_path.read_text())
            assert data["scanned"] == 10
            assert data["flagged"] == 2
            assert len(data["flagged_documents"]) == 1
        finally:
            report_path.unlink(missing_ok=True)
