"""Tests for parameterized perception backends — source-qualified behavior names.

Trinary per backend: no source (backward compat) / with source / invalid source.
Registration conflict tests. Hypothesis disjointness properties.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agents.hapax_voice.backends.audio_energy import AudioEnergyBackend
from agents.hapax_voice.backends.emotion import EmotionBackend
from agents.hapax_voice.backends.energy_arc import EnergyArcBackend

# Valid source IDs for Hypothesis
valid_source_ids = st.from_regex(r"[a-z0-9_]{1,20}", fullmatch=True)


# ===========================================================================
# AudioEnergyBackend parameterization
# ===========================================================================


class TestAudioEnergyBackendParameterization:
    """Trinary on source_id: None / valid / invalid."""

    def test_no_source_id_backward_compatible(self):
        b = AudioEnergyBackend()
        assert b.name == "audio_energy"
        assert b.provides == frozenset({"audio_energy_rms", "audio_onset"})

    def test_with_source_id_qualifies_name(self):
        b = AudioEnergyBackend("monitor_mix")
        assert b.name == "audio_energy:monitor_mix"

    def test_with_source_id_qualifies_provides(self):
        b = AudioEnergyBackend("monitor_mix")
        assert b.provides == frozenset(
            {
                "audio_energy_rms:monitor_mix",
                "audio_onset:monitor_mix",
            }
        )

    def test_invalid_source_id_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            AudioEnergyBackend("Bad-Id")

    def test_empty_source_id_raises(self):
        with pytest.raises(ValueError, match="empty"):
            AudioEnergyBackend("")

    def test_different_sources_produce_different_names(self):
        a = AudioEnergyBackend("monitor_mix")
        b = AudioEnergyBackend("oxi_one")
        assert a.name != b.name
        assert a.provides.isdisjoint(b.provides)


# ===========================================================================
# EmotionBackend parameterization
# ===========================================================================


class TestEmotionBackendParameterization:
    """Trinary on source_id: None / valid / invalid."""

    def test_no_source_id_backward_compatible(self):
        b = EmotionBackend()
        assert b.name == "emotion"
        assert b.provides == frozenset(
            {
                "emotion_valence",
                "emotion_arousal",
                "emotion_dominant",
            }
        )

    def test_with_source_id_qualifies_name(self):
        b = EmotionBackend("face_cam")
        assert b.name == "emotion:face_cam"

    def test_with_source_id_qualifies_provides(self):
        b = EmotionBackend("face_cam")
        assert b.provides == frozenset(
            {
                "emotion_valence:face_cam",
                "emotion_arousal:face_cam",
                "emotion_dominant:face_cam",
            }
        )

    def test_invalid_source_id_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            EmotionBackend("Face-Cam")

    def test_different_sources_produce_different_names(self):
        a = EmotionBackend("face_cam")
        b = EmotionBackend("overhead_gear")
        assert a.name != b.name
        assert a.provides.isdisjoint(b.provides)


# ===========================================================================
# EnergyArcBackend parameterization
# ===========================================================================


class TestEnergyArcBackendParameterization:
    """Trinary on source_id: None / valid / invalid."""

    def test_no_source_id_backward_compatible(self):
        b = EnergyArcBackend()
        assert b.name == "energy_arc"
        assert b.provides == frozenset({"energy_arc_phase", "energy_arc_intensity"})

    def test_with_source_id_qualifies_name(self):
        b = EnergyArcBackend("monitor_mix")
        assert b.name == "energy_arc:monitor_mix"

    def test_with_source_id_qualifies_provides(self):
        b = EnergyArcBackend("monitor_mix")
        assert b.provides == frozenset(
            {
                "energy_arc_phase:monitor_mix",
                "energy_arc_intensity:monitor_mix",
            }
        )

    def test_invalid_source_id_raises(self):
        with pytest.raises(ValueError, match="lowercase"):
            EnergyArcBackend("Bad")


# ===========================================================================
# Registration: conflict detection via PerceptionEngine
# ===========================================================================


class TestParameterizedBackendRegistration:
    """Two instances with different source_ids register without conflict."""

    def test_two_audio_different_sources_no_conflict(self):
        a = AudioEnergyBackend("monitor_mix")
        b = AudioEnergyBackend("oxi_one")
        # Provides sets are disjoint — no conflict
        assert a.provides.isdisjoint(b.provides)

    def test_two_emotion_different_sources_no_conflict(self):
        a = EmotionBackend("face_cam")
        b = EmotionBackend("overhead_gear")
        assert a.provides.isdisjoint(b.provides)

    def test_parameterized_and_unparameterized_no_conflict(self):
        """Unparameterized and parameterized produce different names — no conflict."""
        a = AudioEnergyBackend()
        b = AudioEnergyBackend("monitor_mix")
        assert a.provides.isdisjoint(b.provides)

    def test_same_source_id_produces_identical_provides(self):
        """Two backends with the same source_id produce identical provides — would conflict."""
        a = AudioEnergyBackend("monitor_mix")
        b = AudioEnergyBackend("monitor_mix")
        assert a.provides == b.provides


# ===========================================================================
# Hypothesis property tests
# ===========================================================================


class TestParameterizedBackendProperties:
    @given(valid_source_ids, valid_source_ids)
    def test_different_source_ids_produce_disjoint_audio_provides(self, s1: str, s2: str):
        """For any two distinct source_ids, provides sets are disjoint."""
        if s1 != s2:
            a = AudioEnergyBackend(s1)
            b = AudioEnergyBackend(s2)
            assert a.provides.isdisjoint(b.provides)

    @given(valid_source_ids, valid_source_ids)
    def test_different_source_ids_produce_disjoint_emotion_provides(self, s1: str, s2: str):
        """For any two distinct source_ids, provides sets are disjoint."""
        if s1 != s2:
            a = EmotionBackend(s1)
            b = EmotionBackend(s2)
            assert a.provides.isdisjoint(b.provides)

    @given(valid_source_ids)
    def test_source_count_preserves_behavior_count(self, source: str):
        """Parameterized backend has same number of provides as unparameterized."""
        unparameterized = AudioEnergyBackend()
        parameterized = AudioEnergyBackend(source)
        assert len(unparameterized.provides) == len(parameterized.provides)

    @given(valid_source_ids)
    def test_all_provides_are_qualified(self, source: str):
        """Every behavior name in parameterized provides contains the source."""
        b = AudioEnergyBackend(source)
        for name in b.provides:
            assert f":{source}" in name
