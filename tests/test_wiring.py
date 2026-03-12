"""Tests for the multi-source perception wiring layer.

Config validation, behavior aliasing, cadence group construction, aggregation functions.
Hypothesis monotonicity: adding a source can only add behaviors, never remove.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.source_naming import qualify
from agents.hapax_voice.wiring import (
    BackendType,
    GovernanceBinding,
    SourceSpec,
    WiringConfig,
    aggregate_any,
    aggregate_max,
    aggregate_mean,
    build_behavior_alias,
    build_cadence_groups,
)

# ---------------------------------------------------------------------------
# Fixtures — minimal valid config
# ---------------------------------------------------------------------------


def _minimal_config() -> WiringConfig:
    return WiringConfig(
        sources=(
            SourceSpec("monitor_mix", BackendType.AUDIO_ENERGY, "fast_audio"),
            SourceSpec("oxi_one", BackendType.AUDIO_ENERGY, "fast_audio"),
            SourceSpec("face_cam", BackendType.EMOTION, "slow_visual"),
            SourceSpec("overhead_gear", BackendType.EMOTION, "slow_visual"),
        ),
        cadence_groups={"fast_audio": 0.05, "slow_visual": 3.0},
        mc_binding=GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam"),
        obs_binding=GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam"),
    )


def _make_qualified_behaviors() -> dict[str, Behavior]:
    """Simulate behaviors dict after parameterized backends have contributed."""
    wm = 100.0
    return {
        "audio_energy_rms:monitor_mix": Behavior(0.7, watermark=wm),
        "audio_onset:monitor_mix": Behavior(False, watermark=wm),
        "audio_energy_rms:oxi_one": Behavior(0.3, watermark=wm),
        "audio_onset:oxi_one": Behavior(False, watermark=wm),
        "emotion_valence:face_cam": Behavior(0.2, watermark=wm),
        "emotion_arousal:face_cam": Behavior(0.6, watermark=wm),
        "emotion_dominant:face_cam": Behavior("neutral", watermark=wm),
        "emotion_valence:overhead_gear": Behavior(0.0, watermark=wm),
        "emotion_arousal:overhead_gear": Behavior(0.1, watermark=wm),
        "emotion_dominant:overhead_gear": Behavior("neutral", watermark=wm),
        "vad_confidence": Behavior(0.0, watermark=wm),
        "timeline_mapping": Behavior(None, watermark=wm),
    }


# ===========================================================================
# WiringConfig validation
# ===========================================================================


class TestWiringConfigValidation:
    def test_valid_config_constructs(self):
        cfg = _minimal_config()
        assert len(cfg.sources) == 4

    def test_unknown_cadence_group_raises(self):
        with pytest.raises(ValueError, match="unknown cadence group"):
            WiringConfig(
                sources=(SourceSpec("monitor_mix", BackendType.AUDIO_ENERGY, "nonexistent"),),
                cadence_groups={"fast_audio": 0.05},
                mc_binding=GovernanceBinding(
                    energy_source="monitor_mix", emotion_source="monitor_mix"
                ),
                obs_binding=GovernanceBinding(
                    energy_source="monitor_mix", emotion_source="monitor_mix"
                ),
            )

    def test_mc_energy_source_not_in_sources_raises(self):
        with pytest.raises(ValueError, match="mc_binding.energy_source"):
            WiringConfig(
                sources=(SourceSpec("monitor_mix", BackendType.AUDIO_ENERGY, "fast_audio"),),
                cadence_groups={"fast_audio": 0.05},
                mc_binding=GovernanceBinding(
                    energy_source="nonexistent", emotion_source="monitor_mix"
                ),
                obs_binding=GovernanceBinding(
                    energy_source="monitor_mix", emotion_source="monitor_mix"
                ),
            )

    def test_obs_emotion_source_not_in_sources_raises(self):
        with pytest.raises(ValueError, match="obs_binding.emotion_source"):
            WiringConfig(
                sources=(SourceSpec("monitor_mix", BackendType.AUDIO_ENERGY, "fast_audio"),),
                cadence_groups={"fast_audio": 0.05},
                mc_binding=GovernanceBinding(
                    energy_source="monitor_mix", emotion_source="monitor_mix"
                ),
                obs_binding=GovernanceBinding(
                    energy_source="monitor_mix", emotion_source="nonexistent"
                ),
            )

    def test_duplicate_source_spec_raises(self):
        with pytest.raises(ValueError, match="Duplicate"):
            WiringConfig(
                sources=(
                    SourceSpec("monitor_mix", BackendType.AUDIO_ENERGY, "fast_audio"),
                    SourceSpec("monitor_mix", BackendType.AUDIO_ENERGY, "fast_audio"),
                ),
                cadence_groups={"fast_audio": 0.05},
                mc_binding=GovernanceBinding(
                    energy_source="monitor_mix", emotion_source="monitor_mix"
                ),
                obs_binding=GovernanceBinding(
                    energy_source="monitor_mix", emotion_source="monitor_mix"
                ),
            )

    def test_same_source_different_backend_types_ok(self):
        """Same source_id with different backend types is valid (e.g., audio + emotion from same device)."""
        cfg = WiringConfig(
            sources=(
                SourceSpec("monitor_mix", BackendType.AUDIO_ENERGY, "fast_audio"),
                SourceSpec("monitor_mix", BackendType.ENERGY_ARC, "fast_audio"),
            ),
            cadence_groups={"fast_audio": 0.05},
            mc_binding=GovernanceBinding(energy_source="monitor_mix", emotion_source="monitor_mix"),
            obs_binding=GovernanceBinding(
                energy_source="monitor_mix", emotion_source="monitor_mix"
            ),
        )
        assert len(cfg.sources) == 2

    def test_invalid_source_id_in_spec_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            SourceSpec("Bad-Id", BackendType.AUDIO_ENERGY, "fast_audio")


# ===========================================================================
# Behavior aliasing
# ===========================================================================


class TestBehaviorAliasing:
    def test_alias_maps_bare_name_to_qualified_behavior(self):
        behaviors = _make_qualified_behaviors()
        binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        alias = build_behavior_alias(behaviors, binding)
        assert alias["audio_energy_rms"] is behaviors["audio_energy_rms:monitor_mix"]
        assert alias["emotion_arousal"] is behaviors["emotion_arousal:face_cam"]

    def test_alias_contains_all_governance_names(self):
        behaviors = _make_qualified_behaviors()
        binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        alias = build_behavior_alias(behaviors, binding)
        expected = {
            "audio_energy_rms",
            "audio_onset",
            "emotion_valence",
            "emotion_arousal",
            "emotion_dominant",
            "vad_confidence",
            "timeline_mapping",
        }
        assert set(alias.keys()) == expected

    def test_alias_update_propagates(self):
        """Updating the qualified behavior in the engine is visible through the alias."""
        behaviors = _make_qualified_behaviors()
        binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        alias = build_behavior_alias(behaviors, binding)

        # Update the source behavior
        behaviors["audio_energy_rms:monitor_mix"].update(0.95, 200.0)
        # Alias should see the update (same object)
        assert alias["audio_energy_rms"].value == 0.95

    def test_different_bindings_select_different_sources(self):
        """MC and OBS can bind to different emotion sources."""
        behaviors = _make_qualified_behaviors()
        mc_binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        obs_binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="overhead_gear")
        mc_alias = build_behavior_alias(behaviors, mc_binding)
        obs_alias = build_behavior_alias(behaviors, obs_binding)

        assert mc_alias["emotion_arousal"] is behaviors["emotion_arousal:face_cam"]
        assert obs_alias["emotion_arousal"] is behaviors["emotion_arousal:overhead_gear"]

    def test_stream_behaviors_added_to_alias(self):
        behaviors = _make_qualified_behaviors()
        binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        stream = {
            "stream_bitrate": Behavior(4500.0, watermark=100.0),
            "stream_encoding_lag": Behavior(30.0, watermark=100.0),
        }
        alias = build_behavior_alias(behaviors, binding, stream_behaviors=stream)
        assert "stream_bitrate" in alias
        assert alias["stream_bitrate"].value == 4500.0

    def test_missing_qualified_behavior_excluded(self):
        """If a qualified behavior doesn't exist, it's silently excluded from the alias."""
        behaviors = {"vad_confidence": Behavior(0.0, watermark=100.0)}
        binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        alias = build_behavior_alias(behaviors, binding)
        assert "audio_energy_rms" not in alias
        assert "vad_confidence" in alias


# ===========================================================================
# Cadence group construction
# ===========================================================================


class TestBuildCadenceGroups:
    def test_creates_groups_from_config(self):
        cfg = _minimal_config()
        groups = build_cadence_groups(cfg)
        assert "fast_audio" in groups
        assert "slow_visual" in groups
        assert groups["fast_audio"].interval_s == 0.05
        assert groups["slow_visual"].interval_s == 3.0

    def test_groups_have_empty_backend_lists(self):
        cfg = _minimal_config()
        groups = build_cadence_groups(cfg)
        for group in groups.values():
            assert len(group.backends) == 0


# ===========================================================================
# Aggregation functions
# ===========================================================================


class TestAggregateMax:
    def test_selects_highest(self):
        behaviors = {
            "audio_energy_rms:a": Behavior(0.3, watermark=100.0),
            "audio_energy_rms:b": Behavior(0.7, watermark=100.0),
            "audio_energy_rms:c": Behavior(0.5, watermark=100.0),
        }
        result = aggregate_max(behaviors, "audio_energy_rms")
        assert result.value == 0.7

    def test_watermark_is_minimum(self):
        behaviors = {
            "audio_energy_rms:a": Behavior(0.3, watermark=100.0),
            "audio_energy_rms:b": Behavior(0.7, watermark=98.0),
            "audio_energy_rms:c": Behavior(0.5, watermark=99.0),
        }
        result = aggregate_max(behaviors, "audio_energy_rms")
        assert result.watermark == 98.0

    def test_empty_returns_zero(self):
        result = aggregate_max({}, "audio_energy_rms")
        assert result.value == 0.0

    def test_single_source(self):
        behaviors = {"audio_energy_rms:a": Behavior(0.5, watermark=100.0)}
        result = aggregate_max(behaviors, "audio_energy_rms")
        assert result.value == 0.5


class TestAggregateMean:
    def test_averages(self):
        behaviors = {
            "audio_energy_rms:a": Behavior(0.3, watermark=100.0),
            "audio_energy_rms:b": Behavior(0.6, watermark=100.0),
            "audio_energy_rms:c": Behavior(0.9, watermark=100.0),
        }
        result = aggregate_mean(behaviors, "audio_energy_rms")
        assert abs(result.value - 0.6) < 1e-9

    def test_watermark_is_minimum(self):
        behaviors = {
            "audio_energy_rms:a": Behavior(0.3, watermark=100.0),
            "audio_energy_rms:b": Behavior(0.6, watermark=95.0),
        }
        result = aggregate_mean(behaviors, "audio_energy_rms")
        assert result.watermark == 95.0

    def test_empty_returns_zero(self):
        result = aggregate_mean({}, "audio_energy_rms")
        assert result.value == 0.0


class TestAggregateAny:
    def test_true_when_one_true(self):
        behaviors = {
            "audio_onset:a": Behavior(False, watermark=100.0),
            "audio_onset:b": Behavior(True, watermark=100.0),
            "audio_onset:c": Behavior(False, watermark=100.0),
        }
        result = aggregate_any(behaviors, "audio_onset")
        assert result.value is True

    def test_false_when_all_false(self):
        behaviors = {
            "audio_onset:a": Behavior(False, watermark=100.0),
            "audio_onset:b": Behavior(False, watermark=100.0),
        }
        result = aggregate_any(behaviors, "audio_onset")
        assert result.value is False

    def test_watermark_is_minimum(self):
        behaviors = {
            "audio_onset:a": Behavior(True, watermark=100.0),
            "audio_onset:b": Behavior(False, watermark=97.0),
        }
        result = aggregate_any(behaviors, "audio_onset")
        assert result.watermark == 97.0

    def test_empty_returns_false(self):
        result = aggregate_any({}, "audio_onset")
        assert result.value is False


# ===========================================================================
# Hypothesis property tests
# ===========================================================================

valid_source_ids = st.from_regex(r"[a-z][a-z0-9_]{0,9}", fullmatch=True)


class TestWiringProperties:
    @given(st.lists(valid_source_ids, min_size=1, max_size=8, unique=True))
    def test_adding_source_only_adds_behaviors_never_removes(self, source_ids: list[str]):
        """Given N sources, adding one more produces a strict superset of qualified names."""
        if len(source_ids) < 2:
            return  # need at least 2 to compare subset/superset

        from agents.hapax_voice.backends.audio_energy import AudioEnergyBackend

        base_sources = source_ids[:-1]
        all_sources = source_ids

        base_provides: set[str] = set()
        for sid in base_sources:
            base_provides |= AudioEnergyBackend(sid).provides

        all_provides: set[str] = set()
        for sid in all_sources:
            all_provides |= AudioEnergyBackend(sid).provides

        assert base_provides.issubset(all_provides)
        # Adding a source added new behaviors
        assert len(all_provides) > len(base_provides)

    @given(st.lists(valid_source_ids, min_size=1, max_size=5, unique=True))
    def test_behavior_count_equals_source_count_times_base_count(self, source_ids: list[str]):
        """Total qualified behaviors = N_sources × N_base_names."""
        from agents.hapax_voice.backends.audio_energy import AudioEnergyBackend

        unparameterized = AudioEnergyBackend()
        base_count = len(unparameterized.provides)

        all_provides: set[str] = set()
        for sid in source_ids:
            all_provides |= AudioEnergyBackend(sid).provides

        assert len(all_provides) == len(source_ids) * base_count

    @given(valid_source_ids, valid_source_ids)
    def test_alias_always_resolves_to_bound_source(self, energy_src: str, emotion_src: str):
        """build_behavior_alias maps bare names to the binding's specified source."""
        behaviors = {
            qualify("audio_energy_rms", energy_src): Behavior(0.5, watermark=100.0),
            qualify("audio_onset", energy_src): Behavior(False, watermark=100.0),
            qualify("emotion_valence", emotion_src): Behavior(0.0, watermark=100.0),
            qualify("emotion_arousal", emotion_src): Behavior(0.5, watermark=100.0),
            qualify("emotion_dominant", emotion_src): Behavior("neutral", watermark=100.0),
        }
        binding = GovernanceBinding(energy_source=energy_src, emotion_source=emotion_src)
        alias = build_behavior_alias(behaviors, binding)

        if "audio_energy_rms" in alias:
            assert alias["audio_energy_rms"] is behaviors[qualify("audio_energy_rms", energy_src)]
        if "emotion_arousal" in alias:
            assert alias["emotion_arousal"] is behaviors[qualify("emotion_arousal", emotion_src)]


# ===========================================================================
# Activity backend wiring
# ===========================================================================


class TestActivityWiring:
    def test_activity_backend_type_exists(self):
        assert BackendType.ACTIVITY.value == "activity"

    def test_activity_binding_optional(self):
        """GovernanceBinding works without activity_source (backward compat)."""
        binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        assert binding.activity_source is None

    def test_activity_alias_resolves(self):
        """When activity_source is set, bare 'activity_level' resolves to qualified."""
        behaviors = {
            **_make_qualified_behaviors(),
            "activity_level:overhead_gear": Behavior(0.55, watermark=100.0),
        }
        binding = GovernanceBinding(
            energy_source="monitor_mix",
            emotion_source="face_cam",
            activity_source="overhead_gear",
        )
        alias = build_behavior_alias(behaviors, binding)
        assert "activity_level" in alias
        assert alias["activity_level"].value == 0.55

    def test_activity_aggregate_max_across_sources(self):
        behaviors = {
            "activity_level:overhead_gear": Behavior(0.3, watermark=100.0),
            "activity_level:side_cam": Behavior(0.8, watermark=100.0),
        }
        result = aggregate_max(behaviors, "activity_level")
        assert result.value == 0.8

    def test_backward_compat_no_activity_source(self):
        """No activity_source → alias doesn't include activity_level."""
        behaviors = _make_qualified_behaviors()
        binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        alias = build_behavior_alias(behaviors, binding)
        assert "activity_level" not in alias
