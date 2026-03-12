"""Tests for the incident knowledge base."""

from __future__ import annotations

from pathlib import Path

from shared.incident_knowledge import (
    FailureSignature,
    FixRecord,
    IncidentKnowledgeBase,
    IncidentPattern,
    load_knowledge_base,
    save_knowledge_base,
)


def _make_kb() -> IncidentKnowledgeBase:
    """Create a test knowledge base with two patterns."""
    return IncidentKnowledgeBase(
        patterns=[
            IncidentPattern(
                id="qdrant-connection-refused",
                failure_signature=FailureSignature(
                    check="connectivity.qdrant",
                    status="failed",
                    message_pattern="connection refused",
                ),
                fixes=[
                    FixRecord(
                        action="docker_restart",
                        params={"container": "qdrant"},
                        success_rate=0.92,
                        times_used=12,
                        times_succeeded=11,
                    ),
                    FixRecord(
                        action="docker_compose_up",
                        params={"service": "qdrant"},
                        success_rate=1.0,
                        times_used=3,
                        times_succeeded=3,
                    ),
                ],
                total_occurrences=14,
            ),
            IncidentPattern(
                id="ollama-model-missing",
                failure_signature=FailureSignature(
                    check="ollama.models",
                    status="failed",
                    message_pattern="model .* not found",
                ),
                fixes=[
                    FixRecord(
                        action="ollama_pull",
                        success_rate=1.0,
                        times_used=5,
                        times_succeeded=5,
                    ),
                ],
                total_occurrences=5,
            ),
        ]
    )


class TestPatternMatching:
    def test_exact_match(self):
        kb = _make_kb()
        matches = kb.find_matching(
            "connectivity.qdrant", "failed", "connection refused on port 6333"
        )
        assert len(matches) == 1
        assert matches[0].id == "qdrant-connection-refused"

    def test_regex_match(self):
        kb = _make_kb()
        matches = kb.find_matching(
            "ollama.models", "failed", "model nomic-embed-text-v2-moe not found"
        )
        assert len(matches) == 1
        assert matches[0].id == "ollama-model-missing"

    def test_no_match(self):
        kb = _make_kb()
        matches = kb.find_matching("disk.space", "failed", "disk full")
        assert len(matches) == 0

    def test_wrong_status(self):
        kb = _make_kb()
        matches = kb.find_matching("connectivity.qdrant", "degraded", "connection refused")
        assert len(matches) == 0


class TestBestFix:
    def test_best_fix_highest_success(self):
        kb = _make_kb()
        pattern = kb.get_pattern("qdrant-connection-refused")
        assert pattern is not None
        best = pattern.best_fix()
        assert best is not None
        assert best.action == "docker_compose_up"  # 100% success rate

    def test_best_fix_for_check(self):
        kb = _make_kb()
        fix = kb.best_fix_for("connectivity.qdrant", "failed", "connection refused")
        assert fix is not None
        assert fix.action == "docker_compose_up"

    def test_no_fix_available(self):
        kb = _make_kb()
        fix = kb.best_fix_for("unknown.check", "failed", "something")
        assert fix is None


class TestFixRecordUpdate:
    def test_update_success(self):
        fix = FixRecord(action="test", times_used=10, times_succeeded=9, success_rate=0.9)
        fix.update_outcome(success=True)
        assert fix.times_used == 11
        assert fix.times_succeeded == 10
        assert abs(fix.success_rate - 10 / 11) < 0.01

    def test_update_failure(self):
        fix = FixRecord(action="test", times_used=10, times_succeeded=10, success_rate=1.0)
        fix.update_outcome(success=False)
        assert fix.times_used == 11
        assert fix.times_succeeded == 10
        assert abs(fix.success_rate - 10 / 11) < 0.01


class TestPersistence:
    def test_save_and_load(self, tmp_path: Path):
        kb = _make_kb()
        path = tmp_path / "kb.yaml"
        save_knowledge_base(kb, path)

        loaded = load_knowledge_base(path)
        assert len(loaded.patterns) == 2
        assert loaded.patterns[0].id == "qdrant-connection-refused"

    def test_load_missing_file(self, tmp_path: Path):
        kb = load_knowledge_base(tmp_path / "nonexistent.yaml")
        assert len(kb.patterns) == 0

    def test_get_pattern(self):
        kb = _make_kb()
        assert kb.get_pattern("qdrant-connection-refused") is not None
        assert kb.get_pattern("nonexistent") is None
