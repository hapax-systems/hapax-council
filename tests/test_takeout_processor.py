"""Tests for Tier 3 parsers (location, photos, purchases), progress tracking,
and batch processing."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.takeout.models import ServiceConfig
from shared.takeout.parsers import location, photos, purchases
from shared.takeout.processor import process_takeout, process_batch, ProcessResult
from shared.takeout.progress import ProgressTracker


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_zip(files: dict[str, str | bytes]) -> zipfile.ZipFile:
    """Create an in-memory ZIP with the given files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


# ── Location parser ──────────────────────────────────────────────────────────

class TestLocationParser:
    CONFIG = ServiceConfig(
        parser="location",
        takeout_path="Location History",
        tier=3,
        data_path="structured",
        modality_defaults=["spatial", "temporal", "behavioral"],
        content_type="location",
    )

    def test_parse_semantic_place_visit(self):
        data = json.dumps({
            "timelineObjects": [
                {
                    "placeVisit": {
                        "location": {
                            "name": "Home Studio",
                            "address": "123 Music Lane",
                            "placeId": "ChIJ...",
                            "latitudeE7": 377749290,
                            "longitudeE7": -1224193030,
                        },
                        "duration": {
                            "startTimestamp": "2025-06-15T14:00:00Z",
                            "endTimestamp": "2025-06-15T18:00:00Z",
                        },
                    }
                }
            ]
        })
        zf = make_zip({
            "Takeout/Location History/Semantic Location History/2025/JUNE.json": data,
        })
        records = list(location.parse(zf, self.CONFIG))
        assert len(records) == 1
        r = records[0]
        assert r.location == "Home Studio"
        assert r.structured_fields["duration_minutes"] == 240
        assert "spatial" in r.modality_tags

    def test_parse_activity_segment(self):
        data = json.dumps({
            "timelineObjects": [
                {
                    "activitySegment": {
                        "activityType": "IN_VEHICLE",
                        "duration": {
                            "startTimestamp": "2025-06-15T09:00:00Z",
                            "endTimestamp": "2025-06-15T09:30:00Z",
                        },
                        "distance": 15000,
                    }
                }
            ]
        })
        zf = make_zip({
            "Takeout/Location History/Semantic Location History/2025/JUNE.json": data,
        })
        records = list(location.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert "In Vehicle" in records[0].title

    def test_skip_short_activity(self):
        """Activities under 5 minutes should be skipped."""
        data = json.dumps({
            "timelineObjects": [
                {
                    "activitySegment": {
                        "activityType": "WALKING",
                        "duration": {
                            "startTimestamp": "2025-06-15T09:00:00Z",
                            "endTimestamp": "2025-06-15T09:02:00Z",
                        },
                    }
                }
            ]
        })
        zf = make_zip({
            "Takeout/Location History/Semantic Location History/2025/JUNE.json": data,
        })
        records = list(location.parse(zf, self.CONFIG))
        assert records == []

    def test_parse_raw_records(self):
        data = json.dumps({
            "locations": [
                {"timestamp": "1718456400000", "latitudeE7": 377749290, "longitudeE7": -1224193030},
                {"timestamp": "1718456401000", "latitudeE7": 377749290, "longitudeE7": -1224193030},
            ]
        })
        zf = make_zip({"Takeout/Location History/Records.json": data})
        records = list(location.parse(zf, self.CONFIG))
        # Aggregated by day
        assert len(records) >= 1

    def test_prefer_semantic_over_raw(self):
        semantic = json.dumps({
            "timelineObjects": [{
                "placeVisit": {
                    "location": {"name": "Coffee Shop"},
                    "duration": {
                        "startTimestamp": "2025-06-15T08:00:00Z",
                        "endTimestamp": "2025-06-15T09:00:00Z",
                    },
                }
            }]
        })
        raw = json.dumps({"locations": [
            {"timestamp": "1718456400000", "latitudeE7": 377749290, "longitudeE7": -1224193030},
        ]})
        zf = make_zip({
            "Takeout/Location History/Semantic Location History/2025/JUNE.json": semantic,
            "Takeout/Location History/Records.json": raw,
        })
        records = list(location.parse(zf, self.CONFIG))
        # Should only have the semantic record
        assert len(records) == 1
        assert "Coffee Shop" in records[0].location


# ── Photos parser ─────────────────────────────────────────────────────────────

class TestPhotosParser:
    CONFIG = ServiceConfig(
        parser="photos",
        takeout_path="Google Photos",
        tier=3,
        data_path="structured",
        modality_defaults=["media", "spatial", "temporal"],
        content_type="photo",
    )

    def test_parse_photo_metadata(self):
        meta = json.dumps({
            "title": "sunset.jpg",
            "description": "Beautiful sunset at the beach",
            "photoTakenTime": {"timestamp": "1718456400"},
            "geoData": {"latitude": 37.7749, "longitude": -122.4194},
            "people": [{"name": "Alice"}],
        })
        zf = make_zip({"Takeout/Google Photos/Album/sunset.jpg.json": meta})
        records = list(photos.parse(zf, self.CONFIG))
        assert len(records) == 1
        r = records[0]
        assert r.title == "sunset.jpg"
        assert "sunset" in r.text.lower()
        assert "37.7749" in r.location
        assert "Alice" in r.people

    def test_skip_no_title(self):
        meta = json.dumps({"description": "no title photo"})
        zf = make_zip({"Takeout/Google Photos/Album/photo.json": meta})
        records = list(photos.parse(zf, self.CONFIG))
        assert records == []

    def test_photo_without_location(self):
        meta = json.dumps({
            "title": "indoor.jpg",
            "photoTakenTime": {"timestamp": "1718456400"},
        })
        zf = make_zip({"Takeout/Google Photos/Album/indoor.jpg.json": meta})
        records = list(photos.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert records[0].location == ""

    def test_skip_zero_coordinates(self):
        """Coordinates at (0, 0) should be treated as no location."""
        meta = json.dumps({
            "title": "test.jpg",
            "geoData": {"latitude": 0.0, "longitude": 0.0},
        })
        zf = make_zip({"Takeout/Google Photos/test.jpg.json": meta})
        records = list(photos.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert records[0].location == ""


# ── Purchases parser ──────────────────────────────────────────────────────────

class TestPurchasesParser:
    CONFIG = ServiceConfig(
        parser="purchases",
        takeout_path="Purchases",
        tier=3,
        data_path="structured",
        modality_defaults=["behavioral"],
        content_type="purchase",
    )

    def test_parse_json_purchase(self):
        data = json.dumps([
            {
                "title": "Elektron Digitakt II",
                "price": "899.99",
                "currency": "USD",
                "merchant": "Sweetwater",
                "date": "2025-06-15",
                "category": "Musical Instruments",
            }
        ])
        zf = make_zip({"Takeout/Purchases/purchases.json": data})
        records = list(purchases.parse(zf, self.CONFIG))
        assert len(records) == 1
        r = records[0]
        assert "Digitakt" in r.title
        assert r.structured_fields["merchant"] == "Sweetwater"
        assert "Musical Instruments" in r.categories

    def test_skip_empty_title(self):
        data = json.dumps([{"title": "", "price": "10"}])
        zf = make_zip({"Takeout/Purchases/purchases.json": data})
        records = list(purchases.parse(zf, self.CONFIG))
        assert records == []

    def test_single_purchase_dict(self):
        data = json.dumps({
            "title": "USB-C Cable",
            "price": "12.99",
        })
        zf = make_zip({"Takeout/Purchases/order.json": data})
        records = list(purchases.parse(zf, self.CONFIG))
        assert len(records) == 1


# ── Progress tracker ──────────────────────────────────────────────────────────

class TestProgressTracker:
    def test_create_and_track(self, tmp_path):
        tracker = ProgressTracker("test-run", progress_dir=tmp_path)

        assert not tracker.is_completed("chrome")

        tracker.start_service("chrome")
        assert not tracker.is_completed("chrome")

        tracker.complete_service("chrome", records=150, skipped=10)
        assert tracker.is_completed("chrome")

    def test_resume(self, tmp_path):
        """Progress should survive recreation (simulating resume)."""
        tracker1 = ProgressTracker("test-run", progress_dir=tmp_path)
        tracker1.start_service("chrome")
        tracker1.complete_service("chrome", records=100)

        # Recreate tracker — should load saved state
        tracker2 = ProgressTracker("test-run", progress_dir=tmp_path)
        assert tracker2.is_completed("chrome")

    def test_fail_service(self, tmp_path):
        tracker = ProgressTracker("test-run", progress_dir=tmp_path)
        tracker.start_service("gmail")
        tracker.fail_service("gmail", "Out of memory")
        assert not tracker.is_completed("gmail")

        summary = tracker.summary()
        assert summary["failed"] == 1

    def test_get_incomplete(self, tmp_path):
        tracker = ProgressTracker("test-run", progress_dir=tmp_path)
        tracker.start_service("chrome")
        tracker.complete_service("chrome", records=100)

        incomplete = tracker.get_incomplete_services(["chrome", "keep", "gmail"])
        assert incomplete == ["keep", "gmail"]

    def test_summary(self, tmp_path):
        tracker = ProgressTracker("test-run", progress_dir=tmp_path)
        tracker.start_service("chrome")
        tracker.complete_service("chrome", records=100)
        tracker.start_service("gmail")
        tracker.fail_service("gmail", "error")

        summary = tracker.summary()
        assert summary["completed"] == 1
        assert summary["failed"] == 1
        assert summary["services"]["chrome"]["records"] == 100

    def test_empty_tracker(self, tmp_path):
        tracker = ProgressTracker("empty", progress_dir=tmp_path)
        summary = tracker.summary()
        assert summary["completed"] == 0
        assert summary["failed"] == 0


# ── Batch processing ────────────────────────────────────────────────────────


def _write_test_zip(path: Path, files: dict[str, str | bytes]) -> Path:
    """Create a real ZIP file on disk for process_takeout."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    return path


class TestProcessBatch:
    """Tests for multi-ZIP batch processing."""

    def _make_chrome_zip(self, path: Path) -> Path:
        """Create a ZIP with a minimal Chrome history."""
        history = json.dumps({
            "Browser History": [
                {"title": "Test Page", "url": "https://example.com", "time_usec": 1718456400000000},
            ]
        })
        return _write_test_zip(path, {
            "Takeout/Chrome/BrowserHistory.json": history,
        })

    def _make_search_zip(self, path: Path) -> Path:
        """Create a ZIP with minimal Search activity."""
        activity = json.dumps([
            {"title": "Searched for python testing", "time": "2025-06-15T14:00:00.000Z"},
        ])
        return _write_test_zip(path, {
            "Takeout/My Activity/Search/MyActivity.json": activity,
        })

    def test_batch_aggregates_results(self, tmp_path):
        """Batch should aggregate record counts from multiple ZIPs."""
        zip1 = self._make_chrome_zip(tmp_path / "takeout-001.zip")
        zip2 = self._make_search_zip(tmp_path / "takeout-002.zip")

        result = process_batch(
            [zip1, zip2],
            output_dir=tmp_path / "output",
            structured_path=tmp_path / "structured.jsonl",
            dry_run=True,
        )

        assert isinstance(result, ProcessResult)
        assert result.services_found  # Should find at least chrome and/or search
        assert len(result.services_processed) >= 1

    def test_batch_single_zip_same_as_direct(self, tmp_path):
        """Batch with one ZIP should produce same results as direct call."""
        zip1 = self._make_chrome_zip(tmp_path / "takeout.zip")

        batch_result = process_batch(
            [zip1],
            output_dir=tmp_path / "batch-out",
            structured_path=tmp_path / "batch-structured.jsonl",
            dry_run=True,
        )

        direct_result = process_takeout(
            zip1,
            output_dir=tmp_path / "direct-out",
            structured_path=tmp_path / "direct-structured.jsonl",
            dry_run=True,
        )

        assert batch_result.services_found == direct_result.services_found

    def test_batch_defers_fact_generation(self, tmp_path):
        """Batch should call generate_facts once at the end, not per ZIP."""
        zip1 = self._make_chrome_zip(tmp_path / "takeout-001.zip")
        zip2 = self._make_search_zip(tmp_path / "takeout-002.zip")

        with patch("shared.takeout.processor.process_takeout", wraps=process_takeout) as mock_pt:
            process_batch(
                [zip1, zip2],
                output_dir=tmp_path / "output",
                structured_path=tmp_path / "structured.jsonl",
            )

            # Every call to process_takeout should have _skip_facts=True
            for call in mock_pt.call_args_list:
                assert call.kwargs.get("_skip_facts") is True

    def test_batch_resume_per_zip(self, tmp_path):
        """Each ZIP in a batch should have independent resume tracking."""
        zip1 = self._make_chrome_zip(tmp_path / "takeout-001.zip")
        zip2 = self._make_search_zip(tmp_path / "takeout-002.zip")

        # First run
        result1 = process_batch(
            [zip1, zip2],
            output_dir=tmp_path / "output",
            structured_path=tmp_path / "structured.jsonl",
        )

        # Second run with --resume should skip completed services
        result2 = process_batch(
            [zip1, zip2],
            output_dir=tmp_path / "output",
            structured_path=tmp_path / "structured2.jsonl",
            resume=True,
        )

        # Should still report same services as processed
        assert len(result2.services_processed) >= len(result1.services_processed)

    def test_batch_empty_zip(self, tmp_path):
        """Batch should handle ZIPs with no known services gracefully."""
        empty_zip = _write_test_zip(tmp_path / "empty.zip", {
            "Takeout/Unknown/file.txt": "nothing useful",
        })

        result = process_batch(
            [empty_zip],
            output_dir=tmp_path / "output",
            structured_path=tmp_path / "structured.jsonl",
            dry_run=True,
        )

        assert result.records_written == 0
        assert result.errors == []

    def test_process_takeout_skip_facts_flag(self, tmp_path):
        """_skip_facts=True should prevent fact generation."""
        zip1 = self._make_chrome_zip(tmp_path / "takeout.zip")

        with patch("shared.takeout.profiler_bridge.generate_facts") as mock_gen:
            process_takeout(
                zip1,
                output_dir=tmp_path / "output",
                structured_path=tmp_path / "structured.jsonl",
                _skip_facts=True,
            )
            mock_gen.assert_not_called()


# ── F-2.3: services_processed excludes partially-failed services ─────────

def test_services_processed_excludes_partial_failures(tmp_path):
    """services_processed should not include services that errored mid-parse."""
    # Create a ZIP with a valid chrome entry
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Takeout/Chrome/BrowserHistory.json", json.dumps({
            "Browser History": [
                {"url": "https://example.com", "title": "Test", "time_usec": 13370000000000000}
            ]
        }))
    buf.seek(0)
    zip_path = tmp_path / "takeout.zip"
    zip_path.write_bytes(buf.getvalue())

    # Patch the parser to raise mid-processing
    def failing_parser(zf, config):
        from shared.takeout.models import NormalizedRecord
        yield NormalizedRecord(
            record_id="ok-1", platform="google", service="chrome",
            title="Test Page", content_type="browser_history",
            text="first record", modality_tags=["text"],
        )
        raise RuntimeError("simulated mid-parse failure")

    with patch("shared.takeout.processor._load_parser", return_value=failing_parser):
        result = process_takeout(
            zip_path,
            services=["chrome"],
            output_dir=tmp_path / "output",
            structured_path=tmp_path / "structured.jsonl",
        )

    # The service had an error, so it should NOT be in services_processed
    assert "chrome" not in result.services_processed
    assert len(result.errors) == 1
    # But the records written before the error should still be counted
    assert result.records_by_service.get("chrome", 0) == 1


# ── Resume cleans orphaned .md files ────────────────────────────────────────

def test_resume_cleans_orphaned_md_files(tmp_path):
    """On resume, orphaned .md files from interrupted unstructured services are removed."""
    from shared.takeout.progress import ProgressTracker
    from shared.takeout.processor import _run_id

    # Create a Keep ZIP (unstructured data_path)
    keep_data = json.dumps({
        "textContent": "Fresh note content",
        "title": "Fresh Note",
    })
    zip_path = _write_test_zip(tmp_path / "takeout.zip", {
        "Takeout/Keep/note1.json": keep_data,
    })
    output_dir = tmp_path / "output"
    structured = tmp_path / "structured.jsonl"

    # First run — creates output files
    result1 = process_takeout(
        zip_path,
        services=["keep"],
        output_dir=output_dir,
        structured_path=structured,
    )
    assert result1.records_written >= 1
    keep_dir = output_dir / "keep"
    assert keep_dir.exists()

    # Plant an orphan .md file to simulate interrupted run
    orphan = keep_dir / "orphan-from-last-run.md"
    orphan.write_text("leftover content")
    assert orphan.exists()

    # Delete progress tracker state to simulate interrupted run
    # (service was NOT completed, so resume should re-process it)
    run_id = _run_id(zip_path)
    progress_tracker = ProgressTracker(run_id)
    progress_file = progress_tracker.progress_file
    if progress_file.exists():
        progress_file.unlink()

    # Resume run — should clean the directory first, then re-write
    result2 = process_takeout(
        zip_path,
        services=["keep"],
        output_dir=output_dir,
        structured_path=structured,
        resume=True,
    )
    assert result2.records_written >= 1
    # The orphan should be gone
    assert not orphan.exists()
    # But the service dir should be recreated with fresh files
    assert keep_dir.exists()
