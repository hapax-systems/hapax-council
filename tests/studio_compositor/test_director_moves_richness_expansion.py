"""Tests for cc-task `director-moves-richness-expansion` (operator outcome 3 of 5).

Three concerns:

1. The 7 new ``IntentFamily`` literals validate end-to-end through
   ``CompositionalImpingement`` and ``DirectorIntent``.
2. ``compositional_consumer`` dispatches each new family to the right
   handler with parametric state file writes (no presets — operator
   constraint).
3. ``_emit_micromove_fallback`` chooses programme-conditioned cycles —
   a ``RITUAL`` programme gets slow / fade moves; a ``HOTHOUSE_PRESSURE``
   programme gets cuts / spawns / quicken; with no programme the
   role-agnostic baseline drives.
"""

from __future__ import annotations

import json

import pytest

from agents.studio_compositor import compositional_consumer as cc
from agents.studio_compositor import director_loop as dl
from shared.compositional_affordances import (
    COMPOSITIONAL_CAPABILITIES,
    by_family,
    capability_names,
)
from shared.director_intent import (
    CompositionalImpingement,
    DirectorIntent,
)
from shared.stimmung import Stance

# ── 1. Schema-level validation of the new vocabulary ─────────────────────────


@pytest.mark.parametrize(
    "intent_family",
    [
        "transition.fade",
        "transition.cut",
        "gem.spawn",
        "composition.reframe",
        "pace.tempo_shift",
        "mood.tone_pivot",
        "programme.beat_advance",
    ],
)
def test_new_intent_family_validates(intent_family):
    """Every new family from the cc-task must validate in CompositionalImpingement."""
    imp = CompositionalImpingement(
        narrative=f"test {intent_family} narrative",
        intent_family=intent_family,
        grounding_provenance=["stimmung.dimensions.coherence"],
    )
    assert imp.intent_family == intent_family


def test_new_families_pass_through_director_intent():
    """A DirectorIntent carrying every new family round-trips through Pydantic."""
    impingements = [
        CompositionalImpingement(
            narrative=f"family check: {fam}",
            intent_family=fam,
            grounding_provenance=["stimmung.overall_stance"],
        )
        for fam in (
            "transition.fade",
            "transition.cut",
            "gem.spawn",
            "composition.reframe",
            "pace.tempo_shift",
            "mood.tone_pivot",
            "programme.beat_advance",
        )
    ]
    intent = DirectorIntent(
        activity="observe",
        stance=Stance.NOMINAL,
        narrative_text="vocabulary smoke test",
        compositional_impingements=impingements,
    )
    assert {imp.intent_family for imp in intent.compositional_impingements} == {
        "transition.fade",
        "transition.cut",
        "gem.spawn",
        "composition.reframe",
        "pace.tempo_shift",
        "mood.tone_pivot",
        "programme.beat_advance",
    }


# ── 2. Affordance catalog completeness ───────────────────────────────────────


@pytest.mark.parametrize(
    "family_prefix,minimum_count",
    [
        # transition.fade / transition.cut already had affordances under
        # `_TRANSITION` from preset-variety-plan; we keep them as the
        # recruitment targets when the LLM emits the new family tags.
        ("transition.fade", 1),
        ("transition.cut", 1),
        # gem.spawn is the new addition under `_GEM`.
        ("gem.spawn", 1),
        # composition.reframe / pace.tempo_shift / mood.tone_pivot /
        # programme.beat_advance are new families with their own catalog
        # sections in this PR.
        ("composition.reframe", 3),
        ("pace.tempo_shift", 3),
        ("mood.tone_pivot", 4),
        ("programme.beat_advance", 1),
    ],
)
def test_new_families_have_catalog_records(family_prefix, minimum_count):
    """Every new IntentFamily must have at least one affordance record."""
    records = by_family(family_prefix)
    assert len(records) >= minimum_count, (
        f"family {family_prefix!r} has {len(records)} catalog records "
        f"(expected ≥ {minimum_count}); the AffordancePipeline cannot "
        "recruit against a family with no records."
    )


def test_no_duplicate_capability_names():
    """Catalog completeness invariant — every capability name is unique."""
    names = [c.name for c in COMPOSITIONAL_CAPABILITIES]
    assert len(names) == len(set(names))


# ── 3. Dispatcher routing for the new families ───────────────────────────────


@pytest.fixture
def tmp_shm(monkeypatch, tmp_path):
    """Redirect every parametric-state SHM path to tmp_path.

    Mirrors the ``tmp_shm`` fixture in ``test_compositional_consumer.py``
    plus the four new state files this PR introduces.
    """
    monkeypatch.setattr(cc, "_HERO_CAMERA_OVERRIDE", tmp_path / "hero-camera-override.json")
    monkeypatch.setattr(cc, "_OVERLAY_ALPHA_OVERRIDES", tmp_path / "overlay-alpha-overrides.json")
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent-recruitment.json")
    monkeypatch.setattr(cc, "_YOUTUBE_DIRECTION", tmp_path / "youtube-direction.json")
    monkeypatch.setattr(cc, "_STREAM_MODE_INTENT", tmp_path / "stream-mode-intent.json")
    monkeypatch.setattr(cc, "_COMPOSITION_STATE", tmp_path / "composition-state.json")
    monkeypatch.setattr(cc, "_PACE_STATE", tmp_path / "pace-state.json")
    monkeypatch.setattr(cc, "_MOOD_STATE", tmp_path / "mood-state.json")
    monkeypatch.setattr(cc, "_PROGRAMME_ADVANCE_INTENT", tmp_path / "programme-advance-intent.json")
    return tmp_path


class TestCompositionReframe:
    def test_dispatch_writes_state_with_variant(self, tmp_shm):
        assert cc.dispatch_composition_reframe("composition.reframe.tighten", 30.0)
        data = json.loads((tmp_shm / "composition-state.json").read_text())
        assert data["reframe"] == "tighten"
        assert data["ttl_s"] == 30.0

    def test_each_variant_recorded(self, tmp_shm):
        for variant in ("tighten", "widen", "recompose"):
            cc.dispatch_composition_reframe(f"composition.reframe.{variant}", 15.0)
            data = json.loads((tmp_shm / "composition-state.json").read_text())
            assert data["reframe"] == variant


class TestPaceTempoShift:
    def test_dispatch_writes_state_with_multiplier(self, tmp_shm):
        assert cc.dispatch_pace_tempo_shift("pace.tempo_shift.slow", 30.0)
        data = json.loads((tmp_shm / "pace-state.json").read_text())
        assert data["tempo"] == "slow"
        assert data["multiplier"] == 0.7

    def test_quicken_multiplier_above_one(self, tmp_shm):
        cc.dispatch_pace_tempo_shift("pace.tempo_shift.quicken", 30.0)
        data = json.loads((tmp_shm / "pace-state.json").read_text())
        assert data["multiplier"] == 1.3

    def test_steady_is_baseline(self, tmp_shm):
        cc.dispatch_pace_tempo_shift("pace.tempo_shift.steady", 30.0)
        data = json.loads((tmp_shm / "pace-state.json").read_text())
        assert data["multiplier"] == 1.0


class TestMoodTonePivot:
    def test_dispatch_writes_pivot_variant(self, tmp_shm):
        assert cc.dispatch_mood_tone_pivot("mood.tone_pivot.warmer", 30.0)
        data = json.loads((tmp_shm / "mood-state.json").read_text())
        assert data["pivot"] == "warmer"

    @pytest.mark.parametrize("variant", ["warmer", "cooler", "brighten", "deepen"])
    def test_all_variants_route(self, tmp_shm, variant):
        cc.dispatch_mood_tone_pivot(f"mood.tone_pivot.{variant}", 15.0)
        data = json.loads((tmp_shm / "mood-state.json").read_text())
        assert data["pivot"] == variant


class TestProgrammeBeatAdvance:
    def test_dispatch_writes_intent_request(self, tmp_shm):
        assert cc.dispatch_programme_beat_advance("programme.beat_advance.next", 60.0)
        data = json.loads((tmp_shm / "programme-advance-intent.json").read_text())
        assert data["requested"] is True
        assert data["variant"] == "next"


class TestTopLevelDispatchExtended:
    def test_new_families_route_through_top_level_dispatch(self, tmp_shm):
        for name, expected_family in [
            ("composition.reframe.tighten", "composition.reframe"),
            ("pace.tempo_shift.slow", "pace.tempo_shift"),
            ("mood.tone_pivot.warmer", "mood.tone_pivot"),
            ("programme.beat_advance.next", "programme.beat_advance"),
        ]:
            rec = cc.RecruitmentRecord(name=name)
            assert cc.dispatch(rec) == expected_family

    def test_unknown_subfamily_under_known_prefix_still_dispatches(self, tmp_shm):
        """Unknown variants under known prefixes default to a sensible variant.

        composition.reframe.weird-variant is still a composition.reframe
        impingement; the dispatcher writes the variant as-is + the
        recruit marker so the operator can see the unfamiliar variant
        in the recruitment log without the dispatch failing.
        """
        rec = cc.RecruitmentRecord(name="composition.reframe.weird-variant")
        assert cc.dispatch(rec) == "composition.reframe"
        data = json.loads((tmp_shm / "composition-state.json").read_text())
        # _capability_variant returns the suffix unchanged; the consumer
        # downstream is responsible for clamping to a known variant.
        assert data["reframe"] == "weird-variant"


# ── 4. Programme-conditioned micromove cycles ────────────────────────────────


class TestProgrammeConditionedMicromove:
    def test_no_programme_uses_baseline(self):
        cycle = dl._select_micromove_cycle(None)
        assert cycle is dl._MICROMOVE_BASELINE

    def test_unknown_role_falls_through_to_baseline(self):
        cycle = dl._select_micromove_cycle("totally-unknown-role")
        assert cycle is dl._MICROMOVE_BASELINE

    @pytest.mark.parametrize(
        "role_value",
        [
            "ritual",
            "hothouse_pressure",
            "listening",
            "showcase",
            "work_block",
            "tutorial",
            "wind_down",
            "ambient",
            "experiment",
            "repair",
            "invitation",
            "interlude",
        ],
    )
    def test_each_role_has_distinct_cycle(self, role_value):
        cycle = dl._select_micromove_cycle(role_value)
        assert cycle is not dl._MICROMOVE_BASELINE
        assert len(cycle) >= 1, f"role {role_value!r} has empty micromove cycle"

    def test_ritual_biases_toward_fade_and_slow(self):
        """RITUAL programmes should pick slow / fade families primarily."""
        cycle = dl._select_micromove_cycle("ritual")
        families = {entry[0] for entry in cycle}
        assert "transition.fade" in families
        assert "pace.tempo_shift" in families
        # Ritual cycle should NOT contain hard cuts — the operator's
        # ritual register is fading, not punctuating.
        assert "transition.cut" not in families

    def test_hothouse_biases_toward_cuts_and_spawns(self):
        """HOTHOUSE_PRESSURE should pick hard cuts / gem.spawn / quicken."""
        cycle = dl._select_micromove_cycle("hothouse_pressure")
        families = {entry[0] for entry in cycle}
        assert "transition.cut" in families
        assert "gem.spawn" in families
        # Hothouse cycle should NOT contain slow fades as the primary move.
        assert "transition.fade" not in families

    def test_listening_centres_album_and_warmth(self):
        cycle = dl._select_micromove_cycle("listening")
        families = {entry[0] for entry in cycle}
        wards = {ward for entry in cycle for ward in entry[3]}
        assert "ward.highlight" in families or "homage.expand" in families
        assert "mood.tone_pivot" in families
        assert "album_overlay" in wards

    def test_no_role_cycle_uses_preset_bias(self):
        """Operator constraint NO presets — preset.bias must not appear in any role cycle."""
        all_families: set[str] = set()
        for cycle in dl._MICROMOVE_BY_ROLE.values():
            all_families.update(entry[0] for entry in cycle)
        all_families.update(entry[0] for entry in dl._MICROMOVE_BASELINE)
        assert "preset.bias" not in all_families, (
            "operator constraint violated: a programme-conditioned "
            "micromove cycle still contains preset.bias"
        )

    def test_micromove_entry_shape_is_consistent(self):
        """Every entry in every cycle has the (family, narrative, material, wards, rotation) shape."""
        all_cycles: list[list] = [dl._MICROMOVE_BASELINE]
        all_cycles.extend(dl._MICROMOVE_BY_ROLE.values())
        for cycle in all_cycles:
            for entry in cycle:
                assert len(entry) == 5
                family, narrative, material, wards, rotation = entry
                assert isinstance(family, str) and family
                assert isinstance(narrative, str) and narrative.strip()
                assert material in {"water", "fire", "earth", "air", "void"}
                assert isinstance(wards, list)
                assert rotation in {
                    "sequential",
                    "random",
                    "weighted_by_salience",
                    "paused",
                }


# ── 5. Catalog dispatcher coverage for the new families ──────────────────────


class TestNewCatalogIsRoutable:
    """Every new capability the catalog declares must dispatch (no `unknown`)."""

    def _new_family_caps(self):
        new_prefixes = (
            "composition.reframe.",
            "pace.tempo_shift.",
            "mood.tone_pivot.",
            "programme.beat_advance.",
            "gem.spawn.",
        )
        for cap in COMPOSITIONAL_CAPABILITIES:
            if cap.name.startswith(new_prefixes):
                yield cap

    def test_every_new_capability_has_dispatcher(self, tmp_shm):
        observed = list(self._new_family_caps())
        assert observed, "no new-family capabilities surfaced — fixture mismatch"
        for cap in observed:
            rec = cc.RecruitmentRecord(name=cap.name)
            family = cc.dispatch(rec)
            assert family != "unknown", f"no dispatcher for new-family capability {cap.name!r}"

    def test_capability_names_member_of_catalog(self):
        names = capability_names()
        assert "gem.spawn.fresh-mural" in names
        assert "composition.reframe.tighten" in names
        assert "pace.tempo_shift.slow" in names
        assert "mood.tone_pivot.warmer" in names
        assert "programme.beat_advance.next" in names
