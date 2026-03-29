"""Tests for the imagination bus — data models, SHM publisher, and escalation."""

from __future__ import annotations

import json
from pathlib import Path

from agents.imagination import (
    ESCALATION_THRESHOLD,
    MAX_RECENT_FRAGMENTS,
    CadenceController,
    ContentReference,
    ImaginationFragment,
    ImaginationLoop,
    assemble_context,
    maybe_escalate,
    publish_fragment,
)
from shared.impingement import ImpingementType

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_fragment(**overrides) -> ImaginationFragment:
    """Factory for test fragments with sensible defaults."""
    defaults = {
        "content_references": [
            ContentReference(kind="text", source="test", salience=0.5),
        ],
        "dimensions": {"intensity": 0.4, "tension": 0.2},
        "salience": 0.7,
        "continuation": False,
        "narrative": "test narrative",
    }
    defaults.update(overrides)
    return ImaginationFragment(**defaults)


# ---------------------------------------------------------------------------
# Task 1: Data model tests
# ---------------------------------------------------------------------------


class TestContentReference:
    def test_construction(self) -> None:
        ref = ContentReference(kind="qdrant_query", source="memory", salience=0.8)
        assert ref.kind == "qdrant_query"
        assert ref.source == "memory"
        assert ref.salience == 0.8
        assert ref.query is None

    def test_query_field(self) -> None:
        ref = ContentReference(
            kind="qdrant_query", source="memory", query="recent events", salience=0.6
        )
        assert ref.query == "recent events"


class TestImaginationFragment:
    def test_full_fragment(self) -> None:
        refs = [
            ContentReference(kind="text", source="input", salience=0.5),
            ContentReference(kind="qdrant_query", source="memory", query="mood", salience=0.9),
        ]
        frag = ImaginationFragment(
            content_references=refs,
            dimensions={"intensity": 0.7, "depth": 0.3},
            salience=0.8,
            continuation=True,
            narrative="a brooding passage",
            parent_id="abc123",
        )
        assert len(frag.content_references) == 2
        assert frag.continuation is True
        assert frag.parent_id == "abc123"
        assert len(frag.id) == 12
        assert frag.timestamp > 0

    def test_medium_agnostic_dimension_keys(self) -> None:
        """Dimensions are free-form strings — not tied to any specific medium."""
        dims = {
            "intensity": 0.5,
            "tension": 0.3,
            "diffusion": 0.1,
            "degradation": 0.0,
            "depth": 0.4,
            "pitch_displacement": 0.2,
            "temporal_distortion": 0.6,
            "spectral_color": 0.7,
            "coherence": 0.9,
        }
        frag = _make_fragment(dimensions=dims)
        assert len(frag.dimensions) == 9
        assert all(isinstance(k, str) for k in frag.dimensions)
        assert all(isinstance(v, float) for v in frag.dimensions.values())

    def test_serialization_roundtrip(self) -> None:
        frag = _make_fragment()
        data = frag.model_dump_json()
        restored = ImaginationFragment.model_validate_json(data)
        assert restored.id == frag.id
        assert restored.narrative == frag.narrative
        assert restored.content_references == frag.content_references
        assert restored.dimensions == frag.dimensions


# ---------------------------------------------------------------------------
# Task 2: SHM publisher tests
# ---------------------------------------------------------------------------


class TestPublishFragment:
    def test_writes_current_json(self, tmp_path: Path) -> None:
        current = tmp_path / "current.json"
        stream = tmp_path / "stream.jsonl"
        frag = _make_fragment()

        publish_fragment(frag, current_path=current, stream_path=stream)

        assert current.exists()
        loaded = json.loads(current.read_text())
        assert loaded["narrative"] == "test narrative"

    def test_appends_to_stream(self, tmp_path: Path) -> None:
        current = tmp_path / "current.json"
        stream = tmp_path / "stream.jsonl"

        publish_fragment(
            _make_fragment(narrative="first"), current_path=current, stream_path=stream
        )
        publish_fragment(
            _make_fragment(narrative="second"), current_path=current, stream_path=stream
        )

        lines = stream.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["narrative"] == "first"
        assert json.loads(lines[1])["narrative"] == "second"

    def test_caps_stream_at_max(self, tmp_path: Path) -> None:
        current = tmp_path / "current.json"
        stream = tmp_path / "stream.jsonl"

        for i in range(10):
            publish_fragment(
                _make_fragment(narrative=f"frag-{i}"),
                current_path=current,
                stream_path=stream,
                max_lines=5,
            )

        lines = stream.read_text().strip().splitlines()
        assert len(lines) == 5
        # Should keep the last 5
        assert json.loads(lines[0])["narrative"] == "frag-5"
        assert json.loads(lines[-1])["narrative"] == "frag-9"


# ---------------------------------------------------------------------------
# Task 3: Escalation tests
# ---------------------------------------------------------------------------


class TestMaybeEscalate:
    def test_above_threshold(self) -> None:
        frag = _make_fragment(salience=0.8)
        imp = maybe_escalate(frag)
        assert imp is not None
        assert imp.source == "imagination"
        assert imp.type == ImpingementType.SALIENCE_INTEGRATION
        assert imp.strength == 0.8

    def test_below_threshold(self) -> None:
        frag = _make_fragment(salience=0.3)
        assert maybe_escalate(frag) is None

    def test_at_threshold(self) -> None:
        frag = _make_fragment(salience=ESCALATION_THRESHOLD)
        imp = maybe_escalate(frag)
        assert imp is not None
        assert imp.strength == ESCALATION_THRESHOLD

    def test_preserves_content_refs(self) -> None:
        refs = [
            ContentReference(kind="qdrant_query", source="mem", query="q1", salience=0.9),
            ContentReference(kind="text", source="input", salience=0.4),
        ]
        frag = _make_fragment(content_references=refs, salience=0.8)
        imp = maybe_escalate(frag)
        assert imp is not None
        assert len(imp.content["content_references"]) == 2
        assert imp.content["content_references"][0]["kind"] == "qdrant_query"
        assert imp.content["content_references"][0]["query"] == "q1"

    def test_includes_dimensions(self) -> None:
        dims = {"intensity": 0.7, "tension": 0.5}
        frag = _make_fragment(dimensions=dims, salience=0.9)
        imp = maybe_escalate(frag)
        assert imp is not None
        assert imp.context["dimensions"] == dims


# ---------------------------------------------------------------------------
# Task 4: Cadence controller tests
# ---------------------------------------------------------------------------


class TestCadenceController:
    def test_starts_at_base(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0)
        assert cc.current_interval() == 12.0

    def test_accelerates_on_continuation_and_salience(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0, salience_threshold=0.3)
        frag = _make_fragment(continuation=True, salience=0.5)
        cc.update(frag)
        assert cc.current_interval() == 4.0

    def test_no_accelerate_on_low_salience(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0, salience_threshold=0.3)
        frag = _make_fragment(continuation=True, salience=0.2)
        cc.update(frag)
        assert cc.current_interval() == 12.0

    def test_no_accelerate_without_continuation(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0, salience_threshold=0.3)
        frag = _make_fragment(continuation=False, salience=0.8)
        cc.update(frag)
        assert cc.current_interval() == 12.0

    def test_decelerates_after_streak(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0, decel_count=3)
        # First accelerate
        cc.update(_make_fragment(continuation=True, salience=0.5))
        assert cc.current_interval() == 4.0
        # Three non-continuations
        for _ in range(3):
            cc.update(_make_fragment(continuation=False, salience=0.1))
        assert cc.current_interval() == 12.0

    def test_tpn_doubles_interval(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0)
        assert cc.current_interval() == 12.0
        cc.set_tpn_active(True)
        assert cc.current_interval() == 24.0
        # Also doubles accelerated
        cc.update(_make_fragment(continuation=True, salience=0.5))
        assert cc.current_interval() == 8.0


# ---------------------------------------------------------------------------
# Task 5: Context assembly tests
# ---------------------------------------------------------------------------


class TestAssembleContext:
    def test_empty_sources(self) -> None:
        ctx = assemble_context([], [], {})
        assert "## Current Observations" in ctx
        assert "(none)" in ctx

    def test_includes_observations(self) -> None:
        ctx = assemble_context(["obs1", "obs2"], [], {})
        assert "- obs1" in ctx
        assert "- obs2" in ctx

    def test_includes_fragments(self) -> None:
        frags = [
            _make_fragment(narrative="thought A", continuation=False),
            _make_fragment(narrative="thought B", continuation=True),
        ]
        ctx = assemble_context([], frags, {})
        assert "- thought A" in ctx
        assert "- (continuing) thought B" in ctx

    def test_includes_sensor_data(self) -> None:
        sensors = {
            "stimmung": {"stance": "calm", "stress": "low"},
            "perception": {"activity": "idle", "flow": "steady"},
            "watch": {"hr": 72},
            "weather": {"temp": "18C"},
        }
        ctx = assemble_context([], [], sensors)
        assert "stance=calm" in ctx
        assert "activity=idle" in ctx
        assert "HR=72" in ctx
        assert "18C" in ctx


# ---------------------------------------------------------------------------
# Task 6: ImaginationLoop tests
# ---------------------------------------------------------------------------


class TestImaginationLoop:
    def test_construction(self) -> None:
        loop = ImaginationLoop()
        assert isinstance(loop.cadence, CadenceController)
        assert loop.recent_fragments == []

    def test_stores_recent_fragments(self, tmp_path: Path) -> None:
        loop = ImaginationLoop(
            current_path=tmp_path / "current.json",
            stream_path=tmp_path / "stream.jsonl",
        )
        frag = _make_fragment(salience=0.2)
        loop._process_fragment(frag)
        assert len(loop.recent_fragments) == 1
        assert loop.recent_fragments[0] is frag

    def test_caps_recent_at_max(self, tmp_path: Path) -> None:
        loop = ImaginationLoop(
            current_path=tmp_path / "current.json",
            stream_path=tmp_path / "stream.jsonl",
        )
        for i in range(MAX_RECENT_FRAGMENTS + 3):
            loop._process_fragment(_make_fragment(narrative=f"frag-{i}", salience=0.1))
        assert len(loop.recent_fragments) == MAX_RECENT_FRAGMENTS
        assert loop.recent_fragments[0].narrative == "frag-3"

    def test_drains_impingements_high_salience(self, tmp_path: Path) -> None:
        loop = ImaginationLoop(
            current_path=tmp_path / "current.json",
            stream_path=tmp_path / "stream.jsonl",
        )
        loop._process_fragment(_make_fragment(salience=0.8))
        imps = loop.drain_impingements()
        assert len(imps) == 1
        assert imps[0].source == "imagination"
        # Draining clears the list
        assert loop.drain_impingements() == []

    def test_no_impingement_for_low_salience(self, tmp_path: Path) -> None:
        loop = ImaginationLoop(
            current_path=tmp_path / "current.json",
            stream_path=tmp_path / "stream.jsonl",
        )
        loop._process_fragment(_make_fragment(salience=0.2))
        assert loop.drain_impingements() == []
