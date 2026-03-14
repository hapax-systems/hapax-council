"""Tests for shared.coherence — governance chain integrity (§4.8)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from shared.coherence import CoherenceGap, CoherenceReport, check_coherence


class TestCoherenceReport(unittest.TestCase):
    def test_empty_is_coherent(self):
        report = CoherenceReport(
            gaps=(), total_rules=0, total_implications=0, linked_implications=0, coverage_ratio=0.0
        )
        assert report.is_coherent

    def test_gaps_not_coherent(self):
        gap = CoherenceGap("missing_link", "r1", "i1", "test")
        report = CoherenceReport(
            gaps=(gap,),
            total_rules=1,
            total_implications=1,
            linked_implications=0,
            coverage_ratio=0.0,
        )
        assert not report.is_coherent


class TestCoherenceIntegration(unittest.TestCase):
    """Test against actual axiom registry."""

    def test_real_registry(self):
        """Run coherence check against the real project axioms."""
        report = check_coherence()
        # We expect some orphan implications (not all are linked yet)
        assert report.total_rules > 0
        assert report.total_implications > 0
        # Verify structure is valid
        assert 0.0 <= report.coverage_ratio <= 1.0

    def test_missing_link_detected(self):
        """Constitutive rule linking to non-existent implication is caught."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # Write minimal registry
            (tmp / "registry.yaml").write_text(
                yaml.dump(
                    {
                        "schema_version": "1-0-0",
                        "axioms": [
                            {
                                "id": "test_axiom",
                                "text": "Test",
                                "weight": 50,
                                "type": "softcoded",
                                "created": "2026-01-01",
                                "status": "active",
                            }
                        ],
                    }
                )
            )

            # Write implications
            (tmp / "implications").mkdir()
            (tmp / "implications" / "test-axiom.yaml").write_text(
                yaml.dump(
                    {
                        "axiom_id": "test_axiom",
                        "implications": [
                            {
                                "id": "ta-001",
                                "tier": "T0",
                                "text": "Test implication",
                                "enforcement": "block",
                                "canon": "textualist",
                            }
                        ],
                    }
                )
            )

            # Write constitutive rules with bad link
            (tmp / "constitutive-rules.yaml").write_text(
                yaml.dump(
                    {
                        "rules": [
                            {
                                "id": "cr-test",
                                "brute_pattern": "data/*",
                                "institutional_type": "test-data",
                                "context": "test",
                                "match_type": "path",
                                "linked_implications": ["ta-001", "nonexistent-999"],
                            }
                        ],
                    }
                )
            )

            report = check_coherence(axioms_path=tmp)
            missing = [g for g in report.gaps if g.gap_type == "missing_link"]
            assert len(missing) == 1
            assert missing[0].target_id == "nonexistent-999"

    def test_orphan_implication_detected(self):
        """Implication not linked from any rule is reported as orphan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            (tmp / "registry.yaml").write_text(
                yaml.dump(
                    {
                        "schema_version": "1-0-0",
                        "axioms": [
                            {
                                "id": "test_axiom",
                                "text": "Test",
                                "weight": 50,
                                "type": "softcoded",
                                "created": "2026-01-01",
                                "status": "active",
                            }
                        ],
                    }
                )
            )

            (tmp / "implications").mkdir()
            (tmp / "implications" / "test-axiom.yaml").write_text(
                yaml.dump(
                    {
                        "axiom_id": "test_axiom",
                        "implications": [
                            {
                                "id": "ta-001",
                                "tier": "T0",
                                "text": "Linked",
                                "enforcement": "block",
                                "canon": "t",
                            },
                            {
                                "id": "ta-002",
                                "tier": "T1",
                                "text": "Orphan",
                                "enforcement": "warn",
                                "canon": "t",
                            },
                        ],
                    }
                )
            )

            # Rule only links ta-001, ta-002 is orphan
            (tmp / "constitutive-rules.yaml").write_text(
                yaml.dump(
                    {
                        "rules": [
                            {
                                "id": "cr-test",
                                "brute_pattern": "data/*",
                                "institutional_type": "test-data",
                                "context": "test",
                                "match_type": "path",
                                "linked_implications": ["ta-001"],
                            }
                        ],
                    }
                )
            )

            report = check_coherence(axioms_path=tmp)
            orphans = [g for g in report.gaps if g.gap_type == "orphan_implication"]
            assert len(orphans) == 1
            assert orphans[0].source_id == "ta-002"
            assert report.linked_implications == 1
            assert report.coverage_ratio == 0.5

    def test_full_coverage(self):
        """All implications linked → full coverage, no orphans."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            (tmp / "registry.yaml").write_text(
                yaml.dump(
                    {
                        "schema_version": "1-0-0",
                        "axioms": [
                            {
                                "id": "test_axiom",
                                "text": "Test",
                                "weight": 50,
                                "type": "softcoded",
                                "created": "2026-01-01",
                                "status": "active",
                            }
                        ],
                    }
                )
            )

            (tmp / "implications").mkdir()
            (tmp / "implications" / "test-axiom.yaml").write_text(
                yaml.dump(
                    {
                        "axiom_id": "test_axiom",
                        "implications": [
                            {
                                "id": "ta-001",
                                "tier": "T0",
                                "text": "A",
                                "enforcement": "block",
                                "canon": "t",
                            },
                        ],
                    }
                )
            )

            (tmp / "constitutive-rules.yaml").write_text(
                yaml.dump(
                    {
                        "rules": [
                            {
                                "id": "cr-test",
                                "brute_pattern": "data/*",
                                "institutional_type": "test-data",
                                "context": "test",
                                "match_type": "path",
                                "linked_implications": ["ta-001"],
                            }
                        ],
                    }
                )
            )

            report = check_coherence(axioms_path=tmp)
            assert report.is_coherent
            assert report.coverage_ratio == 1.0


if __name__ == "__main__":
    unittest.main()
