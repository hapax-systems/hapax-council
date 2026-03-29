"""Tests for the experiment runner."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.research
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.hapax_daimonion.experiment_runner import (
    CLAIMS,
    ClaimSpec,
    analyze_claim,
    analyze_claim5,
    format_summary,
    save_results,
)


class TestClaimSpecs(unittest.TestCase):
    def test_all_claims_have_specs(self) -> None:
        for cid in (1, 2, 3, 4):
            self.assertIn(cid, CLAIMS)
            spec = CLAIMS[cid]
            self.assertIsInstance(spec, ClaimSpec)
            self.assertGreater(spec.max_sessions, 0)

    def test_claim_slugs_match_proof_dirs(self) -> None:
        proofs_dir = Path(__file__).parent.parent.parent / "agents" / "hapax_daimonion" / "proofs"
        for spec in CLAIMS.values():
            self.assertTrue(
                (proofs_dir / spec.slug).exists(),
                f"Missing proof dir: {spec.slug}",
            )


class TestAnalyzeClaim(unittest.TestCase):
    @patch("agents.hapax_daimonion.experiment_runner._fetch_scores")
    def test_no_data_returns_no_data(self, mock_fetch: unittest.mock.MagicMock) -> None:
        mock_fetch.return_value = []
        result = analyze_claim(1)
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["decision"], "no_data")

    @patch("agents.hapax_daimonion.experiment_runner._fetch_scores")
    def test_strong_evidence(self, mock_fetch: unittest.mock.MagicMock) -> None:
        """18/20 sessions above threshold → strong BF."""
        scores = []
        for i in range(20):
            sid = f"session-{i}"
            value = 0.9 if i < 18 else 0.3
            for turn in range(6):
                scores.append({"session_id": sid, "turn": turn, "value": value, "timestamp": ""})
        mock_fetch.return_value = scores
        result = analyze_claim(1)
        self.assertEqual(result["status"], "analyzed")
        self.assertEqual(result["n_sessions"], 20)
        self.assertGreater(result["bf"], 1.0)
        self.assertIn(result["decision"], ("continue", "stop_h1", "stop_max"))

    @patch("agents.hapax_daimonion.experiment_runner._fetch_scores")
    def test_sessions_below_min_turns_filtered(self, mock_fetch: unittest.mock.MagicMock) -> None:
        """Sessions with fewer than min_turns are excluded."""
        scores = []
        # Claim 1 requires min_turns=5, give sessions with only 3 turns
        for i in range(10):
            for turn in range(3):
                scores.append({"session_id": f"s-{i}", "turn": turn, "value": 0.9, "timestamp": ""})
        mock_fetch.return_value = scores
        result = analyze_claim(1)
        self.assertEqual(result["status"], "no_data")


class TestAnalyzeClaim5(unittest.TestCase):
    @patch("agents.hapax_daimonion.experiment_runner._fetch_activation_pairs")
    def test_insufficient_data(self, mock_fetch: unittest.mock.MagicMock) -> None:
        mock_fetch.return_value = [{"activation": 0.5, "tokens": 10.0, "anchor": 0.8}] * 30
        result = analyze_claim5()
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["n_turns"], 30)

    @patch("agents.hapax_daimonion.experiment_runner._fetch_activation_pairs")
    def test_sufficient_data(self, mock_fetch: unittest.mock.MagicMock) -> None:
        pairs = [
            {"activation": float(i) / 60, "tokens": float(i * 2), "anchor": 0.5 + i * 0.005}
            for i in range(60)
        ]
        mock_fetch.return_value = pairs
        result = analyze_claim5()
        self.assertEqual(result["status"], "analyzed")
        self.assertEqual(result["n_turns"], 60)
        self.assertIn("correlation_tokens", result)
        self.assertIn("correlation_anchor", result)
        self.assertIn(result["decision"], ("continue", "stop_h1", "stop_h0", "stop_max"))


class TestFormatSummary(unittest.TestCase):
    def test_format_no_data(self) -> None:
        results = [{"claim": 1, "name": "Test", "status": "no_data", "decision": "no_data"}]
        summary = format_summary(results)
        self.assertIn("No data available", summary)

    def test_format_analyzed(self) -> None:
        results = [
            {
                "claim": 1,
                "name": "Test",
                "status": "analyzed",
                "n_sessions": 10,
                "successes": 8,
                "success_rate": 0.8,
                "bf": 15.3,
                "rope": {"inside": 0.1, "outside": 0.9},
                "decision": "stop_h1",
            }
        ]
        summary = format_summary(results)
        self.assertIn("stop_h1", summary)
        self.assertIn("15.30", summary)


class TestSaveResults(unittest.TestCase):
    def test_save_creates_files(self, tmp_path: Path | None = None) -> None:
        """save_results writes JSON files to proof dirs."""
        results = [
            {"claim": 1, "name": "Test", "status": "no_data", "decision": "no_data"},
        ]
        # Just verify it doesn't crash with real proof dirs
        path = save_results(results)
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(len(data), 1)
        # Cleanup
        path.unlink(missing_ok=True)
        # Also clean per-claim file
        from agents.hapax_daimonion.experiment_runner import PROOFS_DIR

        for f in (PROOFS_DIR / "claim-1-stable-frame" / "analysis").glob("run-*.json"):
            f.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
