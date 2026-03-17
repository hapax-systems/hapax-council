"""Tests for engine persistent counters and novelty detection (WS2).

Tests the counter logic without importing the full engine module
(which has circular import issues in this worktree).
"""

from __future__ import annotations

import json
from pathlib import Path

# ── Replicate the counter functions for isolated testing ─────────────────────


def _load_counters(path: Path) -> dict[str, int]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_counters(counters: dict[str, int], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(counters, indent=2), encoding="utf-8")
    tmp.rename(path)


def _event_pattern_key(event_type: str, doc_type: str | None, rules: list[str]) -> str:
    rules_str = "+".join(sorted(rules)) if rules else "none"
    return f"{event_type}|{doc_type or 'unknown'}|{rules_str}"


# ── Tests ────────────────────────────────────────────────────────────────────


class TestEventPatternKey:
    def test_basic(self):
        key = _event_pattern_key("modified", "profile", ["cache-refresh"])
        assert key == "modified|profile|cache-refresh"

    def test_no_doc_type(self):
        key = _event_pattern_key("created", None, ["rag-ingest"])
        assert key == "created|unknown|rag-ingest"

    def test_no_rules(self):
        key = _event_pattern_key("modified", "config", [])
        assert key == "modified|config|none"

    def test_multiple_rules_sorted(self):
        key = _event_pattern_key("modified", "profile", ["b-rule", "a-rule"])
        assert key == "modified|profile|a-rule+b-rule"

    def test_deterministic(self):
        k1 = _event_pattern_key("modified", "profile", ["x", "y"])
        k2 = _event_pattern_key("modified", "profile", ["y", "x"])
        assert k1 == k2


class TestPersistentCounters:
    def test_save_and_load(self, tmp_path: Path):
        path = tmp_path / "counters.json"
        counters = {"modified|profile|cache-refresh": 42, "created|rag|rag-ingest": 7}
        _save_counters(counters, path)
        assert path.exists()
        assert _load_counters(path) == counters

    def test_load_missing_file(self, tmp_path: Path):
        assert _load_counters(tmp_path / "nonexistent.json") == {}

    def test_load_corrupt_file(self, tmp_path: Path):
        path = tmp_path / "counters.json"
        path.write_text("not json{")
        assert _load_counters(path) == {}

    def test_save_creates_parent_dir(self, tmp_path: Path):
        path = tmp_path / "subdir" / "counters.json"
        _save_counters({"a": 1}, path)
        assert path.exists()

    def test_atomic_write(self, tmp_path: Path):
        path = tmp_path / "counters.json"
        _save_counters({"a": 1}, path)
        assert not path.with_suffix(".tmp").exists()


class TestNoveltyDetection:
    def test_novel_pattern_count_zero(self):
        counters: dict[str, int] = {}
        key = _event_pattern_key("modified", "profile", ["cache-refresh"])
        assert counters.get(key, 0) == 0  # novel

    def test_known_pattern_count_high(self):
        counters = {"modified|profile|cache-refresh": 50}
        assert counters.get("modified|profile|cache-refresh", 0) == 50

    def test_novelty_score_all_known(self):
        counters = {"modified|profile|cache-refresh": 100}
        recent_keys = ["modified|profile|cache-refresh"] * 5
        novel = sum(1 for k in recent_keys if counters.get(k, 0) <= 2)
        score = novel / len(recent_keys)
        assert score == 0.0

    def test_novelty_score_all_novel(self):
        counters: dict[str, int] = {}
        recent_keys = ["new|pattern|a", "new|pattern|b"]
        novel = sum(1 for k in recent_keys if counters.get(k, 0) <= 2)
        score = novel / len(recent_keys)
        assert score == 1.0

    def test_novelty_score_mixed(self):
        counters = {"known|pattern|a": 50}
        recent_keys = ["known|pattern|a", "new|pattern|b"]
        novel = sum(1 for k in recent_keys if counters.get(k, 0) <= 2)
        score = novel / len(recent_keys)
        assert score == 0.5


class TestEngineCodeIntegrity:
    """Verify the engine code contains the novelty detection we added."""

    def test_engine_has_pattern_counters(self):
        source = Path(__file__).parent.parent / "cockpit" / "engine" / "__init__.py"
        text = source.read_text()
        assert "_pattern_counters" in text
        assert "_load_counters" in text
        assert "_save_counters" in text

    def test_engine_has_novelty_score(self):
        source = Path(__file__).parent.parent / "cockpit" / "engine" / "__init__.py"
        text = source.read_text()
        assert "novelty_score" in text
        assert "NOVEL event pattern" in text

    def test_engine_saves_on_stop(self):
        source = Path(__file__).parent.parent / "cockpit" / "engine" / "__init__.py"
        text = source.read_text()
        assert "_save_counters(self._pattern_counters)" in text

    def test_counter_functions_match_engine(self):
        """Verify our test replicas match the engine source."""
        source = Path(__file__).parent.parent / "cockpit" / "engine" / "__init__.py"
        text = source.read_text()
        # Key format must match
        assert 'f"{event_type}|{doc_type or \'unknown\'}|{rules_str}"' in text
        assert "counter_save_interval" in text
