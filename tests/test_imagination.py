"""Tests for the imagination bus — data models, SHM publisher, and escalation."""

from __future__ import annotations

import json
from pathlib import Path

from agents.imagination import (
    CadenceController,
    ImaginationFragment,
    assemble_context,
    maybe_escalate,
    publish_fragment,
)
from agents.imagination_loop import MAX_RECENT_FRAGMENTS, ImaginationLoop

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_fragment(**overrides) -> ImaginationFragment:
    """Factory for test fragments with sensible defaults."""
    defaults = {
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


class TestImaginationFragment:
    def test_full_fragment(self) -> None:
        frag = ImaginationFragment(
            dimensions={"intensity": 0.7, "depth": 0.3},
            salience=0.8,
            continuation=True,
            narrative="a brooding passage",
            parent_id="abc123",
        )
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

    def test_fragment_material_field(self) -> None:
        frag = ImaginationFragment(
            dimensions={"intensity": 0.5},
            salience=0.3,
            continuation=False,
            narrative="test",
            material="fire",
        )
        assert frag.material == "fire"
        data = frag.model_dump()
        restored = ImaginationFragment.model_validate(data)
        assert restored.material == "fire"

    def test_fragment_material_defaults_to_water(self) -> None:
        frag = ImaginationFragment(
            dimensions={},
            salience=0.1,
            continuation=False,
            narrative="test",
        )
        assert frag.material == "water"

    def test_serialization_roundtrip(self) -> None:
        frag = _make_fragment()
        data = frag.model_dump_json()
        restored = ImaginationFragment.model_validate_json(data)
        assert restored.id == frag.id
        assert restored.narrative == frag.narrative
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

    def test_cap_is_atomic(self, tmp_path: Path) -> None:
        """Stream truncation uses staging file + rename, not in-place rewrite."""
        current = tmp_path / "current.json"
        stream = tmp_path / "stream.jsonl"

        for i in range(10):
            publish_fragment(
                _make_fragment(narrative=f"frag-{i}"),
                current_path=current,
                stream_path=stream,
                max_lines=5,
            )

        # After capping, no temp files should be left behind
        assert not (tmp_path / "stream.cap.tmp").exists()
        lines = stream.read_text().strip().splitlines()
        assert len(lines) == 5


# ---------------------------------------------------------------------------
# Task 3: Escalation tests
# ---------------------------------------------------------------------------


class TestMaybeEscalate:
    def test_escalate_high_salience_usually(self) -> None:
        frag = _make_fragment(salience=0.9)
        escalations = sum(1 for _ in range(100) if maybe_escalate(frag) is not None)
        assert escalations > 85

    def test_escalate_low_salience_rarely(self) -> None:
        frag = _make_fragment(salience=0.2)
        escalations = sum(1 for _ in range(100) if maybe_escalate(frag) is not None)
        assert escalations < 15

    def test_escalate_continuation_boosts_probability(self) -> None:
        """Continuation multiplies probability by 1.3 — verify with fixed RNG."""
        import math
        import unittest.mock

        salience = 0.5
        midpoint, steepness = 0.55, 8.0
        base_prob = 1.0 / (1.0 + math.exp(-steepness * (salience - midpoint)))
        cont_prob = min(1.0, base_prob * 1.3)
        # Pick a random value between base and cont probability
        # This value passes the continuation check but fails the base check
        test_val = (base_prob + cont_prob) / 2
        with unittest.mock.patch("agents.imagination.random") as mock_rng:
            mock_rng.random.return_value = test_val
            base_frag = _make_fragment(salience=0.5, continuation=False)
            cont_frag = _make_fragment(salience=0.5, continuation=True)
            assert maybe_escalate(base_frag) is None  # test_val > base_prob
            assert maybe_escalate(cont_frag) is not None  # test_val < cont_prob

    def test_escalation_excludes_content_references(self) -> None:
        frag = _make_fragment(salience=0.99)
        # salience=0.99 → near-certain escalation; retry to handle rare misses
        imp = None
        for _ in range(10):
            imp = maybe_escalate(frag)
            if imp is not None:
                break
        assert imp is not None
        assert "content_references" not in imp.content
        assert "narrative" in imp.content
        assert "dimensions" in imp.content

    def test_includes_dimensions(self) -> None:
        dims = {"intensity": 0.7, "tension": 0.5}
        frag = _make_fragment(dimensions=dims, salience=0.99)
        imp = None
        for _ in range(10):
            imp = maybe_escalate(frag)
            if imp is not None:
                break
        assert imp is not None
        assert imp.content["dimensions"] == dims


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

    def test_force_accelerated(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0)
        assert cc.current_interval() == 12.0
        cc.force_accelerated(True)
        assert cc.current_interval() == 4.0
        cc.force_accelerated(False)
        assert cc.current_interval() == 12.0


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
            "stimmung": {
                "overall_stance": "calm",
                "operator_stress": {"value": 0.2, "trend": "stable", "freshness_s": 5.0},
            },
            "perception": {"activity": "idle", "flow_score": "steady"},
            "watch": {"heart_rate": 72},
            "weather": {"temp": "18C"},
        }
        ctx = assemble_context([], [], sensors)
        assert "stance=calm" in ctx
        assert "activity=idle" in ctx
        assert "HR=72" in ctx
        assert "18C" in ctx

    def test_assemble_context_sensor_keys(self) -> None:
        """Verify context uses the actual sensor key names from dmn/sensor.py."""
        snapshot = {
            "stimmung": {
                "overall_stance": "nominal",
                "operator_stress": {"value": 0.3, "trend": "stable", "freshness_s": 5.0},
            },
            "perception": {"activity": "typing", "flow_score": 0.7},
            "watch": {"heart_rate": 72},
        }
        context = assemble_context([], [], snapshot)
        assert "stress=0.3" in context
        assert "flow=0.7" in context
        assert "HR=72" in context


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
        # Process many high-salience fragments to ensure at least one escalates
        for _ in range(10):
            loop._process_fragment(_make_fragment(salience=0.99))
        imps = loop.drain_impingements()
        assert len(imps) >= 1
        assert imps[0].source == "imagination"
        # Draining clears the list
        assert loop.drain_impingements() == []

    def test_no_impingement_for_low_salience(self, tmp_path: Path) -> None:
        loop = ImaginationLoop(
            current_path=tmp_path / "current.json",
            stream_path=tmp_path / "stream.jsonl",
        )
        # Low salience should rarely escalate
        for _ in range(5):
            loop._process_fragment(_make_fragment(salience=0.1))
        # Very unlikely any escalated, but not impossible — just check it's small
        imps = loop.drain_impingements()
        assert len(imps) <= 2


# ---------------------------------------------------------------------------
# Task 7: Material field validation (I7)
# ---------------------------------------------------------------------------


import pytest


def test_escalation_impingement_has_no_content_references():
    """Escalated impingement carries narrative and dimensions, not content_references."""
    import random

    random.seed(42)
    frag = ImaginationFragment(
        narrative="Something important is emerging",
        dimensions={"intensity": 0.8, "tension": 0.6},
        salience=0.9,
        continuation=False,
        material="fire",
    )
    imp = maybe_escalate(frag)
    assert imp is not None
    assert "narrative" in imp.content
    assert "dimensions" in imp.content
    assert "material" in imp.content
    assert "content_references" not in imp.content


def test_fragment_has_no_content_references():
    """ImaginationFragment carries semantic intent only — no content_references."""
    frag = ImaginationFragment(
        narrative="The workspace hums with quiet focus",
        dimensions={"intensity": 0.3, "tension": 0.1, "depth": 0.5},
        salience=0.4,
        continuation=False,
        material="water",
    )
    assert not hasattr(frag, "content_references")
    dumped = frag.model_dump()
    assert "content_references" not in dumped
    assert "intensity" in frag.dimensions


def test_material_rejects_invalid_values():
    with pytest.raises(Exception):
        ImaginationFragment(
            dimensions={},
            salience=0.5,
            continuation=False,
            narrative="test",
            material="stone",
        )
