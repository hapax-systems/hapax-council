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
                "stance": "calm",
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
                "stance": "nominal",
                "operator_stress": {"value": 0.3, "trend": "stable", "freshness_s": 5.0},
            },
            "perception": {"activity": "typing", "flow_score": 0.7},
            "watch": {"heart_rate": 72},
        }
        context = assemble_context([], [], snapshot)
        assert "stress=0.3" in context
        assert "flow=0.7" in context
        assert "HR=72" in context

    def test_perceptual_field_block_present_when_snapshot_carries_it(self) -> None:
        """A populated ``perceptual_field`` in the snapshot widens the prompt.

        Closes the meta-architectural Bayesian audit Fix #2 (2026-05-03):
        the imagination-narrative recruitment query was being born from a
        4-key text snippet (activity / flow_score / presence / heart_rate).
        With the full PerceptualField dump in the snapshot, the assembled
        context carries data from ≥5 of the 13 typed sub-fields so the
        downstream cosine-similarity query can actually distinguish
        compositionally distinct world states.
        """
        snapshot = {
            "perceptual_field": {
                "audio": {
                    "contact_mic": {"desk_activity": "typing", "desk_energy": 0.42},
                    "midi": {"transport_state": "PLAYING", "tempo": 88.0},
                },
                "visual": {
                    "detected_action": "scratching",
                    "overhead_hand_zones": ["turntable"],
                },
                "ir": {"ir_hand_zone": "turntable", "ir_heart_rate_bpm": 71},
                "album": {"artist": "Madvillain", "title": "Madvillainy"},
                "chat": {"recent_message_count": 4, "unique_authors": 2},
                "context": {"working_mode": "rnd", "stream_live": True},
                "stimmung": {
                    "dimensions": {"intensity": 0.7, "tension": 0.3},
                    "overall_stance": "seeking",
                },
                "presence": {"state": "PRESENT", "probability": 0.92},
                "tendency": {"desk_energy_rate": 0.05, "chat_heating_rate": 0.1},
                "homage": {"package_name": "bitchx", "voice_register": "textmode"},
            },
        }
        ctx = assemble_context([], [], snapshot)
        assert "## Perceptual Field" in ctx
        assert "```json" in ctx
        # Pin: ≥5 of the 13 sub-fields must show up in the assembled
        # prompt (the regression that the audit's Fix #2 closes — the
        # slim-snapshot bottleneck collapsed everything to 4 keys).
        sub_fields_seen = sum(
            1
            for marker in (
                "audio",
                "visual",
                "ir",
                "album",
                "chat",
                "context",
                "stimmung",
                "presence",
                "stream_health",
                "tendency",
                "homage",
                "camera_classifications",
            )
            if f'"{marker}":' in ctx
        )
        assert sub_fields_seen >= 5, (
            f"Expected ≥5 PerceptualField sub-fields in assembled context, "
            f"saw {sub_fields_seen}. The slim-snapshot bottleneck has regressed."
        )
        # Spot-check: specific values from at least three different
        # sub-fields are reachable to the LLM (so the narrative it
        # produces — the eventual cosine-similarity retrieval query — can
        # cite them).
        assert "Madvillainy" in ctx  # album.title
        assert "scratching" in ctx  # visual.detected_action
        assert "turntable" in ctx  # ir.ir_hand_zone

    def test_perceptual_field_block_absent_when_snapshot_lacks_it(self) -> None:
        """Backwards compatibility: legacy slim snapshots still produce a
        usable prompt without the Perceptual Field block.

        The DMN sensor's PerceptualField build is wrapped in a try/except
        so a sub-read failure degrades to ``perceptual_field`` absent. In
        that branch the prompt falls back to the legacy ``System State`` /
        ``Time`` / ``Music`` / ``Goals`` / ``Fortress`` sections — which
        chronicle and exploration consumers continue to depend on.
        """
        snapshot = {
            "stimmung": {"stance": "calm"},
            "perception": {"activity": "idle", "flow_score": 0.3},
        }
        ctx = assemble_context([], [], snapshot)
        assert "## Perceptual Field" not in ctx
        # Legacy slim-section markers still present.
        assert "## System State" in ctx
        assert "stance=calm" in ctx

    def test_perceptual_field_block_handles_unserializable_payload(self) -> None:
        """Pathologically non-JSON-serializable payloads degrade to repr,
        never crash the imagination tick.
        """

        class _Unserializable:
            def __repr__(self) -> str:
                return "<unserializable_marker>"

        snapshot = {"perceptual_field": {"weird": _Unserializable()}}
        ctx = assemble_context([], [], snapshot)
        assert "## Perceptual Field" in ctx
        # Either the json.dumps succeeded (won't, here) or the repr
        # fallback fired — the section must still be present.
        assert "weird" in ctx or "unserializable_marker" in ctx


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
        assert loop.recent_fragments[0].narrative == frag.narrative

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


# ---------------------------------------------------------------------------
# Task 8: JSON-fence-strip parser — fixes Command-R 35B 50% pydantic-ai failure
# ---------------------------------------------------------------------------
#
# Background: imagination_loop.py runs `Agent(reasoning, output_type=
# ImaginationFragment)`. The `reasoning` alias routes through LiteLLM →
# TabbyAPI → Command-R 35B EXL3, which wraps every JSON response in
# ```json ... ``` fences regardless of prompt instructions. pydantic-ai
# 1.63 cannot strip fences before its internal JSON parse, so it raises
# UnexpectedModelBehavior on ~50% of ticks (verified live in journalctl
# 2026-05-02). Pre-fix path fell through directly to the markdown-prose
# extractor, which yields a degenerate `salience=0.20` floor. The
# JSON-fence-strip parser recovers the structured fragment with full
# salience / dimension fidelity, restoring the affordance pipeline's
# downstream stimmung modulation.


class TestJsonFenceStripParser:
    """Tests for `_extract_fragment_from_json` — the structured-output recovery path."""

    def _full_payload(self, **overrides) -> dict:
        payload = {
            "dimensions": {
                "intensity": 0.6,
                "tension": 0.4,
                "depth": 0.5,
                "coherence": 0.7,
                "spectral_color": 0.3,
                "temporal_distortion": 0.2,
                "degradation": 0.1,
                "pitch_displacement": 0.4,
                "diffusion": 0.5,
            },
            "salience": 0.55,
            "continuation": False,
            "narrative": "soft thunder over open water",
            "material": "water",
        }
        payload.update(overrides)
        return payload

    def test_bare_json(self) -> None:
        from agents.imagination_loop import _extract_fragment_from_json

        text = json.dumps(self._full_payload())
        frag = _extract_fragment_from_json(text)
        assert frag is not None
        assert frag.salience == 0.55
        assert frag.material == "water"
        assert len(frag.dimensions) == 9

    def test_json_fence_wrapped(self) -> None:
        """Command-R's actual output shape: ```json\\n{...}\\n```"""
        from agents.imagination_loop import _extract_fragment_from_json

        body = json.dumps(self._full_payload(salience=0.62, material="fire"))
        text = f"```json\n{body}\n```"
        frag = _extract_fragment_from_json(text)
        assert frag is not None
        assert frag.salience == 0.62
        assert frag.material == "fire"
        # Critical: salience preserved from real model output, not 0.20 floor.
        assert frag.salience > 0.5

    def test_bare_fence_no_lang(self) -> None:
        from agents.imagination_loop import _extract_fragment_from_json

        body = json.dumps(self._full_payload())
        text = f"```\n{body}\n```"
        frag = _extract_fragment_from_json(text)
        assert frag is not None

    def test_json_inside_prose(self) -> None:
        """Some Command-R responses prefix narration before the JSON."""
        from agents.imagination_loop import _extract_fragment_from_json

        body = json.dumps(self._full_payload(salience=0.4))
        text = f"Sure, here's the imagination fragment you asked for:\n\n{body}"
        frag = _extract_fragment_from_json(text)
        assert frag is not None
        assert frag.salience == 0.4

    def test_returns_none_on_pure_prose(self) -> None:
        """Pure prose with no JSON object falls through to markdown extractor."""
        from agents.imagination_loop import _extract_fragment_from_json

        text = "## Imagination\nA gentle drift through quiet thought.\n\nintensity: 0.4"
        assert _extract_fragment_from_json(text) is None

    def test_returns_none_on_invalid_shape(self) -> None:
        """JSON that doesn't satisfy ImaginationFragment validation returns None."""
        from agents.imagination_loop import _extract_fragment_from_json

        text = json.dumps({"foo": "bar"})  # missing required fields
        assert _extract_fragment_from_json(text) is None

    def test_returns_none_on_empty(self) -> None:
        from agents.imagination_loop import _extract_fragment_from_json

        assert _extract_fragment_from_json("") is None
        assert _extract_fragment_from_json("   \n\n  ") is None

    def test_lifts_salience_above_markdown_floor(self) -> None:
        """The whole point: fence-strip path preserves real salience.

        The pre-fix markdown-prose extractor on fenced JSON cannot find a
        ``## Salience`` header AND its loose ``salience\\s*[:=]`` regex
        does not match the JSON-style ``"salience":0.65`` (no space-after
        colon, dropped in the regex's grouping). It falls back to the
        ``0.20`` floor — exactly the live audit signal:
        ``recovered fragment via markdown fallback (salience=0.20, ...)``.
        The fence-strip path recovers the real model-emitted salience.
        """
        from agents.imagination_loop import (
            _extract_fragment_from_json,
            _extract_fragment_from_markdown,
        )

        body = json.dumps(self._full_payload(salience=0.65))
        fenced_text = f"```json\n{body}\n```"

        # Fence-strip path: recovers real salience from structured JSON.
        frag_json = _extract_fragment_from_json(fenced_text)
        assert frag_json is not None
        assert frag_json.salience == 0.65
        assert frag_json.material == "water"
        assert len(frag_json.dimensions) == 9
        # All 9 dimensions preserved at their actual values (not centred 0.5).
        assert frag_json.dimensions["intensity"] == 0.6
        assert frag_json.dimensions["coherence"] == 0.7

        # Old markdown-prose path on the same fenced text: floors salience
        # at 0.20 because no ``## Salience\\nN`` header is present. This
        # is the precise live-audit failure mode the fence-strip fix
        # eliminates.
        frag_md = _extract_fragment_from_markdown(fenced_text)
        assert frag_md is not None
        assert frag_md.salience == 0.20  # the degenerate floor — buggy path
        # Most dimensions also default to 0.5 in the prose extractor.
        assert frag_md.dimensions["coherence"] == 0.5
        # Critical regression marker: the fence-strip path recovers
        # ~3.25x more salience signal than the prose-fallback path.
        assert frag_json.salience > frag_md.salience * 3


class TestTickFenceStripFallback:
    """Tests for the structured-fail → JSON-fence-strip → markdown fallback chain."""

    def test_fence_strip_short_circuits_markdown_fallback(self, tmp_path: Path) -> None:
        """When the text agent returns fenced JSON, recovery stops at fence-strip."""
        import asyncio
        import unittest.mock

        loop = ImaginationLoop(
            current_path=tmp_path / "current.json",
            stream_path=tmp_path / "stream.jsonl",
            visual_observation_path=tmp_path / "obs.txt",
        )

        body = json.dumps(
            {
                "dimensions": {
                    k: 0.5
                    for k in [
                        "intensity",
                        "tension",
                        "depth",
                        "coherence",
                        "spectral_color",
                        "temporal_distortion",
                        "degradation",
                        "pitch_displacement",
                        "diffusion",
                    ]
                },
                "salience": 0.7,
                "continuation": False,
                "narrative": "warm rain over slate",
                "material": "earth",
            }
        )
        fenced = f"```json\n{body}\n```"

        # Fake structured agent that always blows up (mirrors Command-R's
        # observed UnexpectedModelBehavior on every other tick).
        class _BlowupAgent:
            async def run(self, _ctx):  # noqa: ANN001
                raise RuntimeError("UnexpectedModelBehavior simulator")

        # Fake text agent that returns the fenced JSON Command-R actually emits.
        class _FencedJsonAgent:
            async def run(self, _ctx):  # noqa: ANN001
                class _R:
                    output = fenced

                return _R()

        loop._agent = _BlowupAgent()
        loop._text_agent = _FencedJsonAgent()

        # Bypass cadence/visual observation reads; assemble_context still runs.
        with unittest.mock.patch("agents.imagination_loop.assemble_context", return_value="ctx"):
            frag = asyncio.run(loop.tick(observations=[], sensor_snapshot={}))

        assert frag is not None
        # Critical: salience preserved from JSON, NOT degraded to 0.20 floor.
        assert frag.salience == 0.7
        assert frag.material == "earth"
        # And the fragment was published.
        assert (tmp_path / "current.json").exists()

    def test_falls_through_to_markdown_for_pure_prose(self, tmp_path: Path) -> None:
        """When response has no JSON, markdown-prose extractor still runs."""
        import asyncio
        import unittest.mock

        loop = ImaginationLoop(
            current_path=tmp_path / "current.json",
            stream_path=tmp_path / "stream.jsonl",
            visual_observation_path=tmp_path / "obs.txt",
        )

        prose = (
            "## Imagination Fragment\n"
            "A slow drift through dappled light.\n\n"
            "## Expressive Dimensions\n"
            "intensity: 0.4\n"
            "tension: 0.1\n\n"
            "## Material\n"
            "water\n\n"
            "## Salience\n"
            "0.35\n"
        )

        class _BlowupAgent:
            async def run(self, _ctx):  # noqa: ANN001
                raise RuntimeError("UnexpectedModelBehavior simulator")

        class _ProseAgent:
            async def run(self, _ctx):  # noqa: ANN001
                class _R:
                    output = prose

                return _R()

        loop._agent = _BlowupAgent()
        loop._text_agent = _ProseAgent()

        with unittest.mock.patch("agents.imagination_loop.assemble_context", return_value="ctx"):
            frag = asyncio.run(loop.tick(observations=[], sensor_snapshot={}))

        assert frag is not None
        assert frag.material == "water"
        assert frag.salience == 0.35

    def test_structured_agent_success_skips_fallback(self, tmp_path: Path) -> None:
        """When the structured agent succeeds, neither fallback path runs.

        Pinned regression: the fence-strip path is *only* a fallback. It
        must not steal control from a healthy structured tick.
        """
        import asyncio
        import unittest.mock

        loop = ImaginationLoop(
            current_path=tmp_path / "current.json",
            stream_path=tmp_path / "stream.jsonl",
            visual_observation_path=tmp_path / "obs.txt",
        )

        good = ImaginationFragment(
            dimensions={"intensity": 0.8, "depth": 0.6},
            salience=0.85,
            continuation=False,
            narrative="bright structured tick",
            material="fire",
        )

        class _StructuredAgent:
            async def run(self, _ctx):  # noqa: ANN001
                class _R:
                    output = good

                return _R()

        text_agent_called = []

        class _TextAgent:
            async def run(self, _ctx):  # noqa: ANN001
                text_agent_called.append(True)
                raise AssertionError("text agent must not run on structured success")

        loop._agent = _StructuredAgent()
        loop._text_agent = _TextAgent()

        with unittest.mock.patch("agents.imagination_loop.assemble_context", return_value="ctx"):
            frag = asyncio.run(loop.tick(observations=[], sensor_snapshot={}))

        assert frag is not None
        assert frag.salience == 0.85
        assert frag.material == "fire"
        assert text_agent_called == [], "fallback agent ran on structured success"
