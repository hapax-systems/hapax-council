"""tests/test_reverie_prediction_monitor.py — P7 uniforms-freshness watchdog.

Minimal coverage for the new P7 prediction added in the delta PR-2
follow-up. Does not backfill tests for P1–P6; those predate this work.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

from agents import reverie_prediction_monitor as monitor


def _patch_uniforms(path: Path):
    """Context helper that points UNIFORMS_FILE at tmp_path."""
    return patch.object(monitor, "UNIFORMS_FILE", path)


class TestP7UniformsFreshness:
    def test_fresh_file_reports_healthy(self, tmp_path: Path) -> None:
        path = tmp_path / "uniforms.json"
        path.write_text("{}", encoding="utf-8")
        with _patch_uniforms(path):
            result = monitor.p7_uniforms_freshness()
        assert result.name == "P7_uniforms_freshness"
        assert result.healthy is True
        assert result.alert is None
        assert result.actual < monitor._P7_WARN_AGE_S

    def test_warning_window_is_healthy_but_not_alerting(self, tmp_path: Path) -> None:
        path = tmp_path / "uniforms.json"
        path.write_text("{}", encoding="utf-8")
        warn_mtime = time.time() - (monitor._P7_WARN_AGE_S + 5)
        os.utime(path, (warn_mtime, warn_mtime))
        with _patch_uniforms(path):
            result = monitor.p7_uniforms_freshness()
        assert result.healthy is True
        assert result.alert is None
        assert result.actual >= monitor._P7_WARN_AGE_S
        assert result.actual < monitor._P7_CRIT_AGE_S

    def test_critical_age_reports_unhealthy_with_alert(self, tmp_path: Path) -> None:
        path = tmp_path / "uniforms.json"
        path.write_text("{}", encoding="utf-8")
        crit_mtime = time.time() - (monitor._P7_CRIT_AGE_S + 10)
        os.utime(path, (crit_mtime, crit_mtime))
        with _patch_uniforms(path):
            result = monitor.p7_uniforms_freshness()
        assert result.healthy is False
        assert result.alert is not None
        assert "critical" in result.alert
        assert result.actual >= monitor._P7_CRIT_AGE_S

    def test_missing_file_is_unhealthy(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.json"
        with _patch_uniforms(path):
            result = monitor.p7_uniforms_freshness()
        assert result.healthy is False
        assert result.alert is not None
        assert "missing" in result.alert
        assert result.actual == -1.0

    def test_explicit_now_override_lets_us_compute_age_deterministically(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "uniforms.json"
        path.write_text("{}", encoding="utf-8")
        mtime = 1_000_000.0
        os.utime(path, (mtime, mtime))
        with _patch_uniforms(path):
            result = monitor.p7_uniforms_freshness(now=1_000_000.0 + 45.0)
        assert result.healthy is True
        assert result.alert is None
        assert result.actual == 45.0

    def test_sample_includes_p7_and_p8(self, tmp_path: Path) -> None:
        """p7 and p8 must land in sample() output alongside the other six."""
        path = tmp_path / "uniforms.json"
        path.write_text("{}", encoding="utf-8")
        # Point P8's ``snapshot`` away from real ``/dev/shm`` by patching
        # the module-level paths inside the debug_uniforms helper.
        from agents.reverie import debug_uniforms

        predictions_shm = tmp_path / "predictions.json"
        predictions_jsonl = tmp_path / "predictions.jsonl"
        with (
            _patch_uniforms(path),
            patch.object(monitor, "PREDICTIONS_SHM", predictions_shm),
            patch.object(monitor, "PREDICTIONS_JSONL", predictions_jsonl),
            patch.object(monitor, "_query_chronicle", return_value=[]),
            patch.object(monitor, "_load_activation_state", return_value={}),
            patch.object(monitor, "_load_associations", return_value={}),
            patch.object(monitor, "_load_perception", return_value={}),
            patch.object(debug_uniforms, "UNIFORMS_FILE", tmp_path / "missing-u.json"),
            patch.object(debug_uniforms, "PLAN_FILE", tmp_path / "missing-p.json"),
        ):
            result = monitor.sample()

        prediction_names = [p.name for p in result.predictions]
        assert "P7_uniforms_freshness" in prediction_names
        assert "P8_uniforms_coverage" in prediction_names
        assert len(result.predictions) == 8


class TestP8UniformsCoverage:
    def test_healthy_when_deficit_within_threshold(self, tmp_path: Path) -> None:
        from agents.reverie import debug_uniforms

        uniforms_path = tmp_path / "uniforms.json"
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            """{"version": 2, "targets": {"main": {"passes": [
                {"node_id": "noise", "uniforms": {"amplitude": 0.7}},
                {"node_id": "color", "uniforms": {"brightness": 1.0}}
            ]}}}"""
        )
        uniforms_path.write_text('{"noise.amplitude": 0.7, "color.brightness": 1.0}')
        with (
            patch.object(debug_uniforms, "UNIFORMS_FILE", uniforms_path),
            patch.object(debug_uniforms, "PLAN_FILE", plan_path),
        ):
            result = monitor.p8_uniforms_coverage()
        assert result.name == "P8_uniforms_coverage"
        assert result.healthy is True
        assert result.alert is None
        assert result.actual == 0.0

    def test_degraded_when_deficit_exceeds_threshold(self, tmp_path: Path) -> None:
        import json as _json

        from agents.reverie import debug_uniforms

        uniforms_path = tmp_path / "uniforms.json"
        plan_path = tmp_path / "plan.json"
        # 10 plan defaults, only 3 written → deficit 7 (> allowed 5)
        passes = [{"node_id": f"node{i}", "uniforms": {"param": 0.0}} for i in range(10)]
        plan_path.write_text(_json.dumps({"version": 2, "targets": {"main": {"passes": passes}}}))
        uniforms_path.write_text(_json.dumps({f"node{i}.param": 0.0 for i in range(3)}))
        with (
            patch.object(debug_uniforms, "UNIFORMS_FILE", uniforms_path),
            patch.object(debug_uniforms, "PLAN_FILE", plan_path),
        ):
            result = monitor.p8_uniforms_coverage()
        assert result.healthy is False
        assert result.alert is not None
        assert "deficit" in result.alert
        assert result.actual == 7.0

    def test_missing_uniforms_reports_unhealthy(self, tmp_path: Path) -> None:
        from agents.reverie import debug_uniforms

        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            '{"version": 2, "targets": {"main": {"passes": '
            '[{"node_id": "noise", "uniforms": {"amplitude": 0.7}}]}}}'
        )
        with (
            patch.object(debug_uniforms, "UNIFORMS_FILE", tmp_path / "missing.json"),
            patch.object(debug_uniforms, "PLAN_FILE", plan_path),
        ):
            result = monitor.p8_uniforms_coverage()
        assert result.healthy is False
        assert result.alert is not None
        assert "missing" in result.alert

    def test_missing_plan_reports_unhealthy(self, tmp_path: Path) -> None:
        from agents.reverie import debug_uniforms

        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text('{"noise.amplitude": 0.7}')
        with (
            patch.object(debug_uniforms, "UNIFORMS_FILE", uniforms_path),
            patch.object(debug_uniforms, "PLAN_FILE", tmp_path / "missing.json"),
        ):
            result = monitor.p8_uniforms_coverage()
        assert result.healthy is False
        assert result.alert is not None
        assert "plan.json missing" in result.alert
