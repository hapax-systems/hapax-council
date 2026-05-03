"""Smoke tests for the agents.audio_health package extract.

Verifies that the public API surface exists, is importable from both
the new canonical location (agents.audio_health) and the re-export
shim (agents.audio_signal_assertion), and that the two are identical.
"""

from __future__ import annotations

import numpy as np


def test_package_imports_from_canonical_location():
    """agents.audio_health exports all expected primitives."""
    from agents.audio_health import (
        BAD_STEADY_STATES,
        Classification,
    )

    assert Classification.SILENT == "silent"
    assert Classification.CLIPPING == "clipping"
    assert isinstance(BAD_STEADY_STATES, frozenset)
    assert len(BAD_STEADY_STATES) == 3


def test_reexport_shim_matches_canonical():
    """agents.audio_signal_assertion re-exports are the same objects."""
    from agents.audio_health.classifier import Classification as CanonicalClassification
    from agents.audio_health.classifier import classify as canonical_classify
    from agents.audio_health.probes import ProbeConfig as CanonicalProbeConfig
    from agents.audio_health.transitions import (
        TransitionDetector as CanonicalTransitionDetector,
    )
    from agents.audio_signal_assertion.classifier import Classification as ShimClassification
    from agents.audio_signal_assertion.classifier import classify as shim_classify
    from agents.audio_signal_assertion.probes import ProbeConfig as ShimProbeConfig
    from agents.audio_signal_assertion.transitions import (
        TransitionDetector as ShimTransitionDetector,
    )

    assert CanonicalClassification is ShimClassification
    assert canonical_classify is shim_classify
    assert CanonicalProbeConfig is ShimProbeConfig
    assert CanonicalTransitionDetector is ShimTransitionDetector


def test_measure_pcm_via_new_package():
    """measure_pcm works through the new package path."""
    from agents.audio_health import Classification, classify, measure_pcm

    # Silence: all zeros
    samples = np.zeros(4800, dtype=np.int16)
    m = measure_pcm(samples)
    assert m.rms_dbfs <= -100.0
    label = classify(m)
    assert label == Classification.SILENT


def test_classifier_config_from_env():
    """ClassifierConfig.from_env() works via new package."""
    from agents.audio_health import ClassifierConfig

    config = ClassifierConfig.from_env()
    assert config.silence_floor_dbfs == -55.0
    assert config.tone_crest_max == 2.0


def test_transition_detector_via_new_package():
    """TransitionDetector works through the new package path."""
    from agents.audio_health import Classification, TransitionDetector

    detector = TransitionDetector(stage_names=("test-stage",))
    events = detector.record_probe(
        "test-stage",
        Classification.MUSIC_VOICE,
        captured_at=1000.0,
        duration_s=2.0,
    )
    assert events == []
    assert detector.stage("test-stage").current_state == Classification.MUSIC_VOICE
