"""U8 — compositor preset-family-bias consumer in AffordancePipeline.

Tests the SOFT-PRIOR multiplier wired into `AffordancePipeline.select()`:
when a candidate's `capability_name` starts with `fx.family.`, the
final `combined` score is multiplied by the per-mode weight from
`shared/visual_mode_bias.py::PRESET_FAMILY_WEIGHTS[mode]`.

Per cc-task `u8-compositor-preset-bias-consumer` AC#1, the multiplier
applies in the live select() path, not as a separate filter. AC#3
asserts that fx.family.calm-textural scores higher in research mode
than in rnd mode (and vice versa for high-energy families).

Cache invalidation (AC#2): `get_visual_mode_bias()` reads the
working-mode file at-call cost; the pipeline calls it once per
`select()` invocation. Mode flips via `hapax-working-mode` therefore
take effect on the next pipeline tick (≤60s).

The score-differential test asserts the per-mode tilt the operator
expects:
  * research mode: calm-textural × 1.2 vs rnd × 1.0 (factor 1.2×)
  * rnd mode: audio-reactive × 1.2 vs research × 0.9 (factor ~1.33×)

(Tilt magnitudes were compressed on 2026-05-03 per the visual-
monoculture audit — the prior 2.5× / 2.14× factors made selection
winner-take-all over the last 2h of recruitment. New weights keep
the directional tilt but let similarity scoring decide within the
mode-appropriate lean.)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.affordance import ActivationState, SelectionCandidate
from shared.impingement import Impingement, ImpingementType
from shared.visual_mode_bias import (
    PRESET_FAMILY_WEIGHTS,
    VisualModeBias,
    visual_mode_bias_for,
)


def _candidate(name: str, combined: float = 0.5) -> SelectionCandidate:
    return SelectionCandidate(
        capability_name=name,
        similarity=0.5,
        combined=combined,
        payload={},
    )


# ── Per-mode weight table sanity ────────────────────────────────────


class TestPresetFamilyWeightsTable:
    """Pin the per-mode weight values the consumer relies on. If the
    operator retunes these constants, the consumer behavior changes
    accordingly — but tests assert the tilt direction, not absolute
    numbers, so retuning preserves the contract while shifting weights.
    """

    def test_research_mode_favors_calm_textural(self) -> None:
        research = PRESET_FAMILY_WEIGHTS["research"]
        rnd = PRESET_FAMILY_WEIGHTS["rnd"]
        assert research["fx.family.calm-textural"] > rnd["fx.family.calm-textural"]

    def test_rnd_mode_favors_audio_reactive(self) -> None:
        rnd = PRESET_FAMILY_WEIGHTS["rnd"]
        research = PRESET_FAMILY_WEIGHTS["research"]
        assert rnd["fx.family.audio-reactive"] > research["fx.family.audio-reactive"]

    def test_warm_minimal_favors_research(self) -> None:
        assert (
            PRESET_FAMILY_WEIGHTS["research"]["fx.family.warm-minimal"]
            > PRESET_FAMILY_WEIGHTS["rnd"]["fx.family.warm-minimal"]
        )

    def test_glitch_dense_favors_rnd(self) -> None:
        assert (
            PRESET_FAMILY_WEIGHTS["rnd"]["fx.family.glitch-dense"]
            > PRESET_FAMILY_WEIGHTS["research"]["fx.family.glitch-dense"]
        )


# ── VisualModeBias.family_weight surface ────────────────────────────


class TestFamilyWeightLookup:
    def test_known_capability_returns_per_mode_weight(self) -> None:
        bias = visual_mode_bias_for("research")
        # Compressed to 1.2 on 2026-05-03 (was 1.5) — visual-monoculture
        # rebalance.
        assert bias.family_weight("fx.family.calm-textural") == 1.2

    def test_unknown_capability_returns_default(self) -> None:
        bias = visual_mode_bias_for("research")
        assert bias.family_weight("fx.family.nonexistent") == 1.0

    def test_default_argument_overrides_default(self) -> None:
        bias = visual_mode_bias_for("research")
        assert bias.family_weight("fx.family.nonexistent", default=2.5) == 2.5


# ── Pipeline-level multiplier behavior ──────────────────────────────


class TestPipelineMultiplier:
    """The multiplier is applied INSIDE the per-candidate scoring loop,
    after action_tendency_prior_for_candidate has run. We test it via
    the bias-snapshot integration rather than driving the full select()
    end-to-end (which requires Qdrant + embeddings + activation state)
    — equivalent to D-28's `_apply_programme_bias` pattern."""

    def _apply_u8_multiplier(
        self, candidates: list[SelectionCandidate], bias: VisualModeBias
    ) -> list[SelectionCandidate]:
        """Replicate the inline u8 multiplier logic for unit testing.

        This mirrors the lines added in shared/affordance_pipeline.py
        right after action_tendency_prior_for_candidate. Keeping the
        test-side replica narrow keeps regression coverage tight: if
        the production code's prefix or default-weight shape ever
        drifts, the live integration test below catches it.
        """
        for c in candidates:
            if c.capability_name.startswith("fx.family."):
                c.combined *= bias.family_weight(c.capability_name)
        return candidates

    def test_calm_textural_scores_higher_in_research(self) -> None:
        cands_research = [_candidate("fx.family.calm-textural", combined=1.0)]
        cands_rnd = [_candidate("fx.family.calm-textural", combined=1.0)]
        self._apply_u8_multiplier(cands_research, visual_mode_bias_for("research"))
        self._apply_u8_multiplier(cands_rnd, visual_mode_bias_for("rnd"))
        assert cands_research[0].combined > cands_rnd[0].combined
        # Numeric pin: 1.2 vs 1.0 → 1.2× ratio (compressed from 2.5× on
        # 2026-05-03 per visual-monoculture rebalance).
        assert cands_research[0].combined == pytest.approx(1.2)
        assert cands_rnd[0].combined == pytest.approx(1.0)

    def test_audio_reactive_scores_higher_in_rnd(self) -> None:
        cands_rnd = [_candidate("fx.family.audio-reactive", combined=1.0)]
        cands_research = [_candidate("fx.family.audio-reactive", combined=1.0)]
        self._apply_u8_multiplier(cands_rnd, visual_mode_bias_for("rnd"))
        self._apply_u8_multiplier(cands_research, visual_mode_bias_for("research"))
        assert cands_rnd[0].combined > cands_research[0].combined

    def test_non_fx_family_capability_unchanged(self) -> None:
        """The multiplier is a NO-OP on non-fx.family capabilities —
        cam.hero, ward.size, overlay.* etc. pass through with their
        original combined score."""
        cands = [
            _candidate("cam.hero.overhead", combined=0.7),
            _candidate("ward.size.album", combined=0.4),
            _candidate("overlay.token-pole", combined=0.3),
        ]
        original_scores = [c.combined for c in cands]
        self._apply_u8_multiplier(cands, visual_mode_bias_for("research"))
        for c, original in zip(cands, original_scores, strict=True):
            assert c.combined == original

    def test_unknown_fx_family_capability_passes_through(self) -> None:
        """Per family_weight default=1.0: an fx.family.* capability NOT
        in the PRESET_FAMILY_WEIGHTS table is unchanged. This protects
        against an operator-added family that hasn't yet been weight-
        tuned — it competes naturally instead of being silently zeroed."""
        cands = [_candidate("fx.family.experimental-new-family", combined=0.5)]
        self._apply_u8_multiplier(cands, visual_mode_bias_for("research"))
        assert cands[0].combined == 0.5


# ── Live integration: AffordancePipeline.select() picks up the bias ──


class TestPipelineLiveIntegration:
    """Drive `AffordancePipeline.select()` through the production scoring loop."""

    def _candidate_pair(self) -> list[SelectionCandidate]:
        payload = {
            "content_risk": "tier_0_owned",
            "monetization_risk": "none",
            "public_capable": False,
        }
        return [
            SelectionCandidate(
                capability_name="fx.family.calm-textural",
                similarity=1.0,
                payload=dict(payload),
            ),
            SelectionCandidate(
                capability_name="fx.family.audio-reactive",
                similarity=1.0,
                payload=dict(payload),
            ),
        ]

    def _select_with_bias(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
    ) -> tuple[list[SelectionCandidate], MagicMock]:
        from shared.affordance_pipeline import AffordancePipeline

        pipeline = AffordancePipeline()
        pipeline._retrieve = MagicMock(return_value=self._candidate_pair())
        pipeline._active_programme_cached = MagicMock(return_value=None)
        pipeline._exploration.compute_and_publish = MagicMock(return_value=None)
        bias = MagicMock(return_value=visual_mode_bias_for(mode))
        monkeypatch.setattr("shared.affordance_pipeline.get_visual_mode_bias", bias)
        monkeypatch.setattr("shared.affordance_pipeline._record_recruitment", lambda _name: None)
        monkeypatch.setattr("shared.governance.quiet_frame_subscriber.install", lambda: None)
        monkeypatch.setattr(ActivationState, "thompson_sample", lambda _self: 0.5)
        monkeypatch.setenv("HAPAX_AFFORDANCE_RECENCY_WEIGHT", "0")
        monkeypatch.setenv("HAPAX_AFFORDANCE_THOMPSON_DECAY", "1")
        monkeypatch.setenv("HAPAX_RECRUITMENT_LOG", "0")
        monkeypatch.setenv("HAPAX_DISPATCH_TRACE", "0")

        winners = pipeline.select(
            Impingement(
                timestamp=1.0,
                source="test.u8",
                type=ImpingementType.ABSOLUTE_THRESHOLD,
                strength=1.0,
                content={"metric": "preset-family-bias"},
                embedding=[1.0, 0.0, 0.0],
            ),
            top_k=2,
        )
        return winners, bias

    def test_select_applies_research_family_weight_to_winner(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        winners, bias = self._select_with_bias(monkeypatch, "research")

        assert winners[0].capability_name == "fx.family.calm-textural"
        assert winners[0].combined > winners[1].combined
        bias.assert_called_once()

    def test_select_applies_rnd_family_weight_to_winner(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        winners, bias = self._select_with_bias(monkeypatch, "rnd")

        assert winners[0].capability_name == "fx.family.audio-reactive"
        assert winners[0].combined > winners[1].combined
        bias.assert_called_once()
