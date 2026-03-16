"""Tests for cross-domain contradiction detection.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.contradiction_detector import (
    Contradiction,
    _check_briefing_vs_drift,
    _check_briefing_vs_health,
    detect_contradictions,
)


class TestBriefingVsHealth(unittest.TestCase):
    def test_healthy_briefing_with_failures_contradicts(self):
        briefing = "# Briefing\n## Stack healthy, 0 issues\nAll good."
        health = json.dumps({"status": "degraded", "failed": 3, "degraded": 2, "healthy": 14})

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as bf:
            bf.write(briefing)
            bp = Path(bf.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as hf:
            hf.write(health)
            hp = Path(hf.name)

        try:
            with (
                patch("agents.contradiction_detector.BRIEFING_PATH", bp),
                patch("agents.contradiction_detector.HEALTH_HISTORY", hp),
            ):
                results = _check_briefing_vs_health()
                assert len(results) == 1
                assert results[0].severity == "high"
                assert "briefing" in results[0].domain_a
                assert "health" in results[0].domain_b
        finally:
            bp.unlink()
            hp.unlink()

    def test_degraded_briefing_with_healthy_system_contradicts(self):
        briefing = "# Briefing\n## Stack DEGRADED, 20 items\nBad."
        health = json.dumps({"status": "healthy", "failed": 0, "degraded": 0, "healthy": 20})

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as bf:
            bf.write(briefing)
            bp = Path(bf.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as hf:
            hf.write(health)
            hp = Path(hf.name)

        try:
            with (
                patch("agents.contradiction_detector.BRIEFING_PATH", bp),
                patch("agents.contradiction_detector.HEALTH_HISTORY", hp),
            ):
                results = _check_briefing_vs_health()
                assert len(results) == 1
                assert results[0].severity == "medium"
                assert "stale" in results[0].suggestion.lower()
        finally:
            bp.unlink()
            hp.unlink()

    def test_consistent_state_no_contradiction(self):
        briefing = "# Briefing\n## Stack healthy\nAll good."
        health = json.dumps({"status": "healthy", "failed": 0, "degraded": 0, "healthy": 20})

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as bf:
            bf.write(briefing)
            bp = Path(bf.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as hf:
            hf.write(health)
            hp = Path(hf.name)

        try:
            with (
                patch("agents.contradiction_detector.BRIEFING_PATH", bp),
                patch("agents.contradiction_detector.HEALTH_HISTORY", hp),
            ):
                results = _check_briefing_vs_health()
                assert len(results) == 0
        finally:
            bp.unlink()
            hp.unlink()


class TestBriefingVsDrift(unittest.TestCase):
    def test_drift_omitted_from_briefing(self):
        briefing = "# Briefing\n## Stack healthy\nEverything fine."
        drift = json.dumps({"drift_items": [{"severity": "high"} for _ in range(8)]})

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as bf:
            bf.write(briefing)
            bp = Path(bf.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as df:
            df.write(drift)
            dp = Path(df.name)

        try:
            with (
                patch("agents.contradiction_detector.BRIEFING_PATH", bp),
                patch("agents.contradiction_detector.DRIFT_REPORT", dp),
            ):
                results = _check_briefing_vs_drift()
                assert len(results) == 1
                assert results[0].severity == "high"
                assert "omit" in results[0].source_id
        finally:
            bp.unlink()
            dp.unlink()

    def test_no_high_drift_no_contradiction(self):
        briefing = "# Briefing\n## Stack healthy\n"
        drift = json.dumps({"drift_items": [{"severity": "low"} for _ in range(3)]})

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as bf:
            bf.write(briefing)
            bp = Path(bf.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as df:
            df.write(drift)
            dp = Path(df.name)

        try:
            with (
                patch("agents.contradiction_detector.BRIEFING_PATH", bp),
                patch("agents.contradiction_detector.DRIFT_REPORT", dp),
            ):
                results = _check_briefing_vs_drift()
                assert len(results) == 0
        finally:
            bp.unlink()
            dp.unlink()


class TestDetectContradictions(unittest.TestCase):
    def test_returns_list(self):
        with (
            patch("agents.contradiction_detector.BRIEFING_PATH", Path("/nonexistent")),
            patch("agents.contradiction_detector.DRIFT_REPORT", Path("/nonexistent")),
            patch("agents.contradiction_detector.HEALTH_HISTORY", Path("/nonexistent")),
            patch("agents.contradiction_detector.OPERATOR_PROFILE", Path("/nonexistent")),
        ):
            results = detect_contradictions()
            assert isinstance(results, list)

    def test_contradiction_dataclass_fields(self):
        c = Contradiction(
            domain_a="x",
            domain_b="y",
            assertion_a="claim 1",
            assertion_b="claim 2",
            severity="high",
            suggestion="investigate",
            source_id="test:1",
        )
        assert c.domain_a == "x"
        assert c.severity == "high"
