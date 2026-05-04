"""Tests for cc-task ``director-moves-grounding-trace-coverage``.

Three concerns:

1. **Coverage audit** — every deterministic-code fallback path the
   director can take emits a ``synthetic_grounding_markers`` entry under
   the ``fallback.*`` namespace. The R8 grounding-act gate already drops
   LLM impingements that arrive without either real grounding or a
   marker; this audit asserts the in-tree fallback helpers all stamp
   their reason correctly.

2. **Prometheus grounding-class counter** — the new
   ``hapax_director_move_grounding_total{move_type, grounding_class}``
   counter increments correctly for real / synthetic / missing classes
   when ``emit_director_intent`` (or ``emit_move_grounding`` directly)
   processes an intent.

3. **Ratio thresholds** — sanity-check the ratio thresholds match the
   cc-task acceptance criteria; the boundary cases are covered in
   ``test_director_moves_segment_smoke.py``.
"""

from __future__ import annotations

import pytest

from agents.studio_compositor import director_loop as dl
from agents.studio_compositor.director_moves_quality import (
    FALLBACK_RATIO_ACCEPTABLE_MAX,
    FALLBACK_RATIO_GOOD_MAX,
    STALE_INTENT_DOMINANCE_MIN,
    assess_director_moves_quality,
)
from shared import director_observability as obs
from shared.director_intent import (
    CompositionalImpingement,
    DirectorIntent,
)
from shared.segment_observability import QualityRating
from shared.stimmung import Stance

# ── 1. Fallback-marker coverage on every deterministic helper ────────────────


class TestFallbackCoverage:
    """Each in-tree fallback helper stamps its reason under ``fallback.*``."""

    def test_silence_hold_impingement_stamps_marker(self):
        imp = dl._silence_hold_impingement(reason="parser_json_decode")
        assert imp.synthetic_grounding_markers == ["fallback.parser_json_decode"]
        # The stub narrative passes through the no-vacuum invariant — the
        # impingement is constructed with the marker so R8 admits it as a
        # deterministic-code fallback rather than rejecting it as
        # ungrounded LLM emission.
        assert imp.grounding_provenance == []

    def test_silence_hold_default_reason_is_silence_hold(self):
        imp = dl._silence_hold_impingement()
        assert imp.synthetic_grounding_markers == ["fallback.silence_hold"]

    def test_silence_hold_fallback_intent_stamps_marker(self):
        intent = dl._silence_hold_fallback_intent(
            activity="silence",
            narrative_text="",
            reason="parser_empty_text",
            tier="narrative",
            condition_id="smoke",
        )
        assert intent.synthetic_grounding_markers == ["fallback.parser_empty_text"]
        # Operator no-vacuum invariant: every silence-hold intent carries
        # at least one impingement, also marker-stamped.
        assert len(intent.compositional_impingements) >= 1
        for imp in intent.compositional_impingements:
            assert imp.synthetic_grounding_markers
            assert imp.synthetic_grounding_markers[0].startswith("fallback.")

    def test_micromove_fallback_emit_stamps_marker(self, tmp_path, monkeypatch):
        """``_emit_micromove_fallback`` writes a record with a fallback marker."""

        intent_path = tmp_path / "director-intent.jsonl"
        narrative_state_path = tmp_path / "narrative-state.json"
        monkeypatch.setattr(dl, "_DIRECTOR_INTENT_JSONL", intent_path)
        monkeypatch.setattr(dl, "_NARRATIVE_STATE_PATH", narrative_state_path)

        loop = dl.DirectorLoop(video_slots=[], reactor_overlay=None)
        loop._emit_micromove_fallback(reason="stale_intent", condition_id="smoke")

        emitted = intent_path.read_text(encoding="utf-8").strip().splitlines()
        assert emitted, "micromove fallback emitted no record"
        import json as _json

        record = _json.loads(emitted[-1])
        assert record["synthetic_grounding_markers"] == ["fallback.micromove.stale_intent"]
        for imp in record["compositional_impingements"]:
            assert imp["synthetic_grounding_markers"][0].startswith("fallback.micromove.")


# ── 2. Prometheus grounding-class counter ────────────────────────────────────


def _move_grounding_value(move_type: str, grounding_class: str) -> float:
    """Read the current value of ``hapax_director_move_grounding_total`` for a label pair."""

    return obs._move_grounding_total.labels(
        move_type=move_type, grounding_class=grounding_class
    )._value.get()


@pytest.mark.skipif(
    not obs._METRICS_AVAILABLE,
    reason="prometheus_client not installed in this env — emit is a no-op",
)
class TestEmitMoveGrounding:
    """The new counter increments correctly for real / synthetic / missing."""

    def test_real_grounding_increments_real_class(self):
        before = _move_grounding_value("camera.hero", "real")
        intent = DirectorIntent(
            grounding_provenance=["visual.detected_action"],
            activity="react",
            stance=Stance.NOMINAL,
            narrative_text="hero shift",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="show the operator catching the lyric",
                    intent_family="camera.hero",
                    grounding_provenance=["visual.detected_action"],
                ),
            ],
        )
        obs.emit_move_grounding(intent)
        after = _move_grounding_value("camera.hero", "real")
        assert after - before == 1.0

    def test_synthetic_only_grounds_under_synthetic_class(self):
        # Use a less-loaded family to avoid ambient counter increments
        # interfering between tests.
        before = _move_grounding_value("overlay.emphasis", "synthetic")
        intent = DirectorIntent(
            grounding_provenance=[],
            synthetic_grounding_markers=["fallback.parser_non_dict"],
            activity="silence",
            stance=Stance.NOMINAL,
            narrative_text="",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="silence hold: maintain the surface",
                    intent_family="overlay.emphasis",
                    synthetic_grounding_markers=["fallback.parser_non_dict"],
                ),
            ],
        )
        obs.emit_move_grounding(intent)
        after = _move_grounding_value("overlay.emphasis", "synthetic")
        assert after - before == 1.0

    def test_top_level_intent_class_is_separate_label(self):
        """Top-level intent records under ``move_type='intent'``, not the family."""

        before = _move_grounding_value("intent", "real")
        intent = DirectorIntent(
            grounding_provenance=["album.artist", "album.title"],
            activity="music",
            stance=Stance.NOMINAL,
            narrative_text="album-anchored music narrative",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="brighten album face",
                    intent_family="ward.highlight",
                    grounding_provenance=["album.artist"],
                ),
            ],
        )
        obs.emit_move_grounding(intent)
        after = _move_grounding_value("intent", "real")
        assert after - before == 1.0

    def test_emit_director_intent_drives_move_grounding(self):
        """``emit_director_intent`` calls ``emit_move_grounding`` so callers don't need to."""

        before = _move_grounding_value("mood.tone_pivot", "real")
        intent = DirectorIntent(
            grounding_provenance=["stimmung.dimensions.coherence"],
            activity="observe",
            stance=Stance.NOMINAL,
            narrative_text="warm the room a half step",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="warm the room's color register a half step",
                    intent_family="mood.tone_pivot",
                    grounding_provenance=["stimmung.dimensions.coherence"],
                ),
            ],
        )
        obs.emit_director_intent(intent, condition_id="smoke")
        after = _move_grounding_value("mood.tone_pivot", "real")
        assert after - before == 1.0


# ── 3. Ratio threshold sanity checks ────────────────────────────────────────


class TestRatioThresholds:
    """Cc-task acceptance — the public threshold constants match the spec."""

    def test_constants_match_cc_task_spec(self):
        assert FALLBACK_RATIO_GOOD_MAX == 0.10
        assert FALLBACK_RATIO_ACCEPTABLE_MAX == 0.30
        assert STALE_INTENT_DOMINANCE_MIN == 0.50

    def test_29pct_fallback_is_acceptable(self):
        """Just under the 30% cap stays at ACCEPTABLE."""

        # 29 fallback-free records + 12 stale = 12 / 41 ≈ 0.293 fallback ratio.
        records = [
            {
                "activity": "react",
                "stance": "nominal",
                "synthetic_grounding_markers": [],
                "compositional_impingements": [
                    {
                        "narrative": "n",
                        "intent_family": "camera.hero",
                        "grounding_provenance": ["visual.detected_action"],
                        "synthetic_grounding_markers": [],
                    },
                ],
            }
            for _ in range(29)
        ]
        records.extend(
            {
                "activity": "observe",
                "stance": "nominal",
                "synthetic_grounding_markers": ["fallback.micromove.stale_intent"],
                "compositional_impingements": [
                    {
                        "narrative": "stale",
                        "intent_family": "overlay.emphasis",
                        "grounding_provenance": [],
                        "synthetic_grounding_markers": ["fallback.micromove.stale_intent"],
                    },
                ],
            }
            for _ in range(12)
        )
        # 12/41 ≈ 0.293 < 0.30 → ACCEPTABLE; stale_ratio = 0.293 < 0.50.
        assert assess_director_moves_quality(records) == QualityRating.ACCEPTABLE

    def test_30pct_fallback_is_poor(self):
        """At-or-above the 30% cap drops to POOR."""

        # 7 fallback-free records + 3 stale = 3/10 = 0.30 → POOR.
        records = [
            {
                "activity": "react",
                "stance": "nominal",
                "synthetic_grounding_markers": [],
                "compositional_impingements": [
                    {
                        "narrative": "n",
                        "intent_family": "camera.hero",
                        "grounding_provenance": ["visual.detected_action"],
                        "synthetic_grounding_markers": [],
                    },
                ],
            }
            for _ in range(7)
        ]
        records.extend(
            {
                "activity": "observe",
                "stance": "nominal",
                "synthetic_grounding_markers": ["fallback.micromove.stale_intent"],
                "compositional_impingements": [
                    {
                        "narrative": "stale",
                        "intent_family": "overlay.emphasis",
                        "grounding_provenance": [],
                        "synthetic_grounding_markers": ["fallback.micromove.stale_intent"],
                    },
                ],
            }
            for _ in range(3)
        )
        assert assess_director_moves_quality(records) == QualityRating.POOR

    def test_9pct_fallback_is_good(self):
        """Just under the 10% cap stays at GOOD."""

        # 19 fallback-free records + 1 stale = 1/20 = 0.05 < 0.10 → GOOD.
        records = [
            {
                "activity": "react",
                "stance": "nominal",
                "synthetic_grounding_markers": [],
                "compositional_impingements": [
                    {
                        "narrative": "n",
                        "intent_family": "camera.hero",
                        "grounding_provenance": ["visual.detected_action"],
                        "synthetic_grounding_markers": [],
                    },
                ],
            }
            for _ in range(19)
        ]
        records.append(
            {
                "activity": "observe",
                "stance": "nominal",
                "synthetic_grounding_markers": ["fallback.micromove.stale_intent"],
                "compositional_impingements": [
                    {
                        "narrative": "stale",
                        "intent_family": "overlay.emphasis",
                        "grounding_provenance": [],
                        "synthetic_grounding_markers": ["fallback.micromove.stale_intent"],
                    },
                ],
            }
        )
        assert assess_director_moves_quality(records) == QualityRating.GOOD
