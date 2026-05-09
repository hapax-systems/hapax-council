"""Tests for scripts/hapax-youtube-viewer-count-producer — Phase 4 of the
orphan-ward-producers plan.

Verifies:
  - fetch_viewer_count extracts concurrentViewers as int
  - fetch_viewer_count returns 0 when API has no items
  - fetch_viewer_count returns 0 when concurrentViewers is missing
  - fetch_viewer_count returns 0 on a non-int string value
  - write_viewer_count produces a plain integer text file
    (no newline, no JSON wrapper) — WhosHereCairoSource invariant
  - write_viewer_count is atomic (.tmp + rename, never partial)
  - run_loop writes 0 when no broadcast resolves
  - run_loop writes the integer count when a broadcast resolves
  - 404 from the API → cache invalidated + count → 0
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Load the script as a module (it's in scripts/ which is not on sys.path).
SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "hapax-youtube-viewer-count-producer"
)
spec = importlib.util.spec_from_file_location("youtube_viewer_count_producer", SCRIPT_PATH)
producer = importlib.util.module_from_spec(spec)
sys.modules["youtube_viewer_count_producer"] = producer
spec.loader.exec_module(producer)


# ── fetch_viewer_count ────────────────────────────────────────────────


class TestFetchViewerCount:
    def test_extracts_concurrent_viewers_as_int(self) -> None:
        youtube = MagicMock()
        youtube.videos().list().execute.return_value = {
            "items": [{"liveStreamingDetails": {"concurrentViewers": "42"}}]
        }
        assert producer.fetch_viewer_count(youtube, "bid-001") == 42

    def test_no_items_returns_zero(self) -> None:
        youtube = MagicMock()
        youtube.videos().list().execute.return_value = {"items": []}
        assert producer.fetch_viewer_count(youtube, "bid-001") == 0

    def test_missing_concurrent_viewers_returns_zero(self) -> None:
        youtube = MagicMock()
        youtube.videos().list().execute.return_value = {"items": [{"liveStreamingDetails": {}}]}
        assert producer.fetch_viewer_count(youtube, "bid-001") == 0

    def test_non_int_string_returns_zero(self) -> None:
        youtube = MagicMock()
        youtube.videos().list().execute.return_value = {
            "items": [{"liveStreamingDetails": {"concurrentViewers": "not a number"}}]
        }
        assert producer.fetch_viewer_count(youtube, "bid-001") == 0

    def test_zero_string_returns_zero(self) -> None:
        youtube = MagicMock()
        youtube.videos().list().execute.return_value = {
            "items": [{"liveStreamingDetails": {"concurrentViewers": "0"}}]
        }
        assert producer.fetch_viewer_count(youtube, "bid-001") == 0


# ── write_viewer_count ────────────────────────────────────────────────


class TestWriteViewerCount:
    def test_writes_plain_integer_text(self, tmp_path: Path) -> None:
        path = tmp_path / "viewer-count.txt"
        producer.write_viewer_count(path, 42)
        text = path.read_text()
        # WhosHereCairoSource invariant: no newline, plain int.
        assert text == "42"

    def test_writes_zero_when_offline(self, tmp_path: Path) -> None:
        path = tmp_path / "viewer-count.txt"
        producer.write_viewer_count(path, 0)
        assert path.read_text() == "0"

    def test_atomic_via_tmp_rename(self, tmp_path: Path) -> None:
        path = tmp_path / "viewer-count.txt"
        producer.write_viewer_count(path, 5)
        # Final file present, .tmp consumed by rename.
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "subdir" / "viewer-count.txt"
        producer.write_viewer_count(path, 7)
        assert path.exists()
        assert path.read_text() == "7"

    def test_overwrites_previous_value(self, tmp_path: Path) -> None:
        path = tmp_path / "viewer-count.txt"
        producer.write_viewer_count(path, 100)
        producer.write_viewer_count(path, 50)
        assert path.read_text() == "50"


# ── run_loop ──────────────────────────────────────────────────────────


class TestRunLoop:
    def test_no_broadcast_writes_zero(self, tmp_path: Path) -> None:
        viewer_file = tmp_path / "viewer-count.txt"
        with (
            patch.object(producer, "VIEWER_COUNT_FILE", viewer_file),
            patch.object(producer, "get_google_credentials", return_value=MagicMock()),
            patch.object(producer, "build_service", return_value=MagicMock()),
            patch.object(producer, "resolve_active_broadcast_id", return_value=(None, 0.0)),
        ):
            producer.run_loop(_max_iters=1, _sleep=lambda _s: None)
        assert viewer_file.read_text() == "0"

    def test_broadcast_resolves_writes_viewer_count(self, tmp_path: Path) -> None:
        viewer_file = tmp_path / "viewer-count.txt"
        youtube = MagicMock()
        youtube.videos().list().execute.return_value = {
            "items": [{"liveStreamingDetails": {"concurrentViewers": "127"}}]
        }
        with (
            patch.object(producer, "VIEWER_COUNT_FILE", viewer_file),
            patch.object(producer, "get_google_credentials", return_value=MagicMock()),
            patch.object(producer, "build_service", return_value=youtube),
            patch.object(
                producer,
                "resolve_active_broadcast_id",
                return_value=("bid-live", 0.0),
            ),
        ):
            producer.run_loop(_max_iters=1, _sleep=lambda _s: None)
        assert viewer_file.read_text() == "127"

    def test_404_invalidates_cache_and_writes_zero(self, tmp_path: Path) -> None:
        from googleapiclient.errors import HttpError

        viewer_file = tmp_path / "viewer-count.txt"
        youtube = MagicMock()
        resp = MagicMock(status=404)
        youtube.videos().list().execute.side_effect = HttpError(resp, b"not found")
        invalidated: list[bool] = []
        with (
            patch.object(producer, "VIEWER_COUNT_FILE", viewer_file),
            patch.object(producer, "get_google_credentials", return_value=MagicMock()),
            patch.object(producer, "build_service", return_value=youtube),
            patch.object(
                producer,
                "resolve_active_broadcast_id",
                return_value=("bid-stale", 0.0),
            ),
            patch.object(
                producer,
                "invalidate_cache",
                side_effect=lambda creds: invalidated.append(True),
            ),
        ):
            producer.run_loop(_max_iters=1, _sleep=lambda _s: None)
        assert viewer_file.read_text() == "0"
        assert invalidated == [True]

    def test_loop_iterates_n_times(self, tmp_path: Path) -> None:
        """_max_iters governs loop count; sleeps are stubbed."""
        viewer_file = tmp_path / "viewer-count.txt"
        sleep_calls: list[float] = []
        with (
            patch.object(producer, "VIEWER_COUNT_FILE", viewer_file),
            patch.object(producer, "get_google_credentials", return_value=MagicMock()),
            patch.object(producer, "build_service", return_value=MagicMock()),
            patch.object(producer, "resolve_active_broadcast_id", return_value=(None, 0.0)),
        ):
            producer.run_loop(_max_iters=3, _sleep=sleep_calls.append)
        # 3 iters: sleep called twice (after 1st and 2nd; not after final)
        assert len(sleep_calls) == 2
