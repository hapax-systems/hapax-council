"""tests/test_stimmung_dmn_health.py — DMN health feeding into stimmung."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

from agents.visual_layer_aggregator.stimmung_methods import update_dmn_health


class TestDmnHealthStimmung:
    def test_stale_dmn_degrades_health(self, tmp_path: Path) -> None:
        status_path = tmp_path / "status.json"
        status_path.write_text(
            json.dumps({"timestamp": time.time() - 60, "buffer_entries": 5, "uptime_s": 120})
        )
        collector = MagicMock()
        update_dmn_health(collector, status_path)
        collector.update_health.assert_called_once()
        args = collector.update_health.call_args
        assert args[0] == (0, 1)
        assert args[1]["failed_checks"] == ["dmn_stale"]

    def test_fresh_dmn_no_degradation(self, tmp_path: Path) -> None:
        status_path = tmp_path / "status.json"
        status_path.write_text(
            json.dumps({"timestamp": time.time(), "buffer_entries": 5, "uptime_s": 120})
        )
        collector = MagicMock()
        update_dmn_health(collector, status_path)
        collector.update_health.assert_not_called()

    def test_empty_buffer_after_startup_degrades(self, tmp_path: Path) -> None:
        status_path = tmp_path / "status.json"
        status_path.write_text(
            json.dumps({"timestamp": time.time(), "buffer_entries": 0, "uptime_s": 120})
        )
        collector = MagicMock()
        update_dmn_health(collector, status_path)
        collector.update_health.assert_called_once()
        args = collector.update_health.call_args
        assert args[1]["failed_checks"] == ["dmn_empty_buffer"]

    def test_empty_buffer_during_startup_ok(self, tmp_path: Path) -> None:
        status_path = tmp_path / "status.json"
        status_path.write_text(
            json.dumps({"timestamp": time.time(), "buffer_entries": 0, "uptime_s": 30})
        )
        collector = MagicMock()
        update_dmn_health(collector, status_path)
        collector.update_health.assert_not_called()

    def test_missing_file_no_error(self, tmp_path: Path) -> None:
        collector = MagicMock()
        update_dmn_health(collector, tmp_path / "nope.json")
        collector.update_health.assert_not_called()

    def test_malformed_json_no_error(self, tmp_path: Path) -> None:
        status_path = tmp_path / "status.json"
        status_path.write_text("not json")
        collector = MagicMock()
        update_dmn_health(collector, status_path)
        collector.update_health.assert_not_called()
