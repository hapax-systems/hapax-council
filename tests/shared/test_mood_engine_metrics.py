"""Regression pins for mood-engine Prometheus metrics."""

from __future__ import annotations

import pytest

pytest.importorskip("prometheus_client")

from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine
from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine
from agents.hapax_daimonion.mood_valence_engine import MoodValenceEngine
from shared.mood_engine_metrics import (
    MOOD_ENGINE_LABELS,
    POSTERIOR_METRIC_NAMES,
    SIGNALS_COUNTER_NAME,
    contributed_signal_count,
    posterior_gauge_value,
    record_mood_engine_tick,
    signals_counter_value,
)


def test_metric_inventory_matches_phase_d_acceptance() -> None:
    assert POSTERIOR_METRIC_NAMES == {
        "mood_arousal": "mood_arousal_posterior_value",
        "mood_valence": "mood_valence_posterior_value",
        "mood_coherence": "mood_coherence_posterior_value",
    }
    assert SIGNALS_COUNTER_NAME == "mood_engine_signals_contributed_total"
    assert MOOD_ENGINE_LABELS == ("mood_arousal", "mood_valence", "mood_coherence")


def test_contributed_signal_count_skips_none_values() -> None:
    observations = {"a": True, "b": False, "c": None}
    assert contributed_signal_count(observations) == 2


def test_record_tick_sets_posterior_gauge_and_counter() -> None:
    before = signals_counter_value("mood_arousal") or 0.0

    record_mood_engine_tick(
        "mood_arousal",
        0.73,
        {
            "ambient_audio_rms_high": True,
            "contact_mic_onset_rate_high": None,
            "midi_clock_bpm_high": False,
        },
    )

    assert posterior_gauge_value("mood_arousal") == pytest.approx(0.73)
    assert (signals_counter_value("mood_arousal") or 0.0) - before == 2.0


def test_unknown_engine_label_is_ignored() -> None:
    record_mood_engine_tick("not_a_mood_engine", 0.9, {"x": True})
    assert posterior_gauge_value("not_a_mood_engine") is None


def test_engine_contribute_updates_metrics_for_each_mood_engine() -> None:
    before = {engine: signals_counter_value(engine) or 0.0 for engine in MOOD_ENGINE_LABELS}

    MoodArousalEngine().contribute(
        {
            "ambient_audio_rms_high": True,
            "contact_mic_onset_rate_high": None,
            "midi_clock_bpm_high": False,
            "hr_bpm_above_baseline": True,
        }
    )
    MoodValenceEngine().contribute(
        {
            "hrv_below_baseline": True,
            "skin_temp_drop": False,
            "sleep_debt_high": None,
            "voice_pitch_elevated": True,
        }
    )
    MoodCoherenceEngine().contribute(
        {
            "hrv_variability_high": False,
            "respiration_irregular": True,
            "movement_jitter_high": True,
            "skin_temp_volatility_high": None,
        }
    )

    for engine in MOOD_ENGINE_LABELS:
        assert posterior_gauge_value(engine) is not None
        assert (signals_counter_value(engine) or 0.0) - before[engine] == 3.0
