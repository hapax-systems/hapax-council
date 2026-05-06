"""Tightness pin for the speech-representing audio reactivity surfaces.

Per `feedback_audio_reactivity_must_be_tight_speech_representation`
(operator directive 2026-05-06): the waveform at the center of the
Sierpinski triangle IS Hapax's speech representation, and the M8
oscilloscope is the M8 device's own speech surface. Smoothing /
attenuation / freshness gates that LAG the audio signal weaken
Hapax's on-broadcast voice.

Concretely: the audio→visual response on these two surfaces must be
< 1 frame from audio sample (16.67ms at 60fps). That requires:

1. The IIR/EMA coefficient on the modulation path is α=1.0 (passthrough,
   no smoothing).
2. A bounded BURST_CLAMP exists for safety (per-event amplitude cap to
   prevent pathological excursions) but it does NOT temporally smooth.
3. The waveform DRAW reads raw samples, not the smoothed value.

This test pins the contract so the IIR coefficients can't silently
regress to lossy values (e.g., the historical α=0.3 from PR #2639 /
#2651 era which lagged ~3-5 frames).

Gap #10 (audio-reactivity-runtime-witness-and-calibration-harness) +
gap #32 (tightness property test) collapsed into this static pin.
"""

from __future__ import annotations

from agents.studio_compositor.m8_oscilloscope_source import (
    AMPLITUDE_BURST_CLAMP,
    AMPLITUDE_IIR_ALPHA,
    LINE_WIDTH_AMPLITUDE_SCALE,
)
from agents.studio_compositor.sierpinski_renderer import (
    SIERPINSKI_AUDIO_ATTACK_ALPHA,
    SIERPINSKI_AUDIO_BURST_CLAMP,
    SIERPINSKI_AUDIO_RELEASE_ALPHA,
)


class TestSierpinskiSpeechSurfaceTightness:
    """Pin the Sierpinski center waveform — Hapax's speech representation.

    The 9-frame regression (#2639 IIR α=0.3 → 3-5 frame lag) MUST NOT
    return. Both attack and release alphas must be passthrough (1.0),
    and the burst clamp must be set (bounded amplitude, not low-pass
    smoothing).
    """

    def test_attack_alpha_is_passthrough(self) -> None:
        assert SIERPINSKI_AUDIO_ATTACK_ALPHA == 1.0, (
            "Sierpinski center waveform is Hapax's speech surface. The IIR "
            "attack alpha MUST be 1.0 (passthrough). Any value < 1.0 lags "
            "the audio signal and weakens speech representation."
        )

    def test_release_alpha_is_passthrough(self) -> None:
        assert SIERPINSKI_AUDIO_RELEASE_ALPHA == 1.0, (
            "Sierpinski center waveform is Hapax's speech surface. The IIR "
            "release alpha MUST be 1.0 (passthrough). Anything else creates "
            "decay tails that lag the audio."
        )

    def test_burst_clamp_set(self) -> None:
        # BURST_CLAMP bounds amplitude per-event but does NOT smooth
        # temporally. It must be set (non-None, in (0, 1]) — operator
        # directive: "bounded-amplitude not low-pass-filtered amplitude".
        assert 0.0 < SIERPINSKI_AUDIO_BURST_CLAMP <= 1.0, (
            "Sierpinski burst clamp must be in (0, 1]. Operator directive: "
            "bounded-amplitude not low-pass-filtered amplitude."
        )


class TestM8OscilloscopeSpeechSurfaceTightness:
    """Pin the M8 oscilloscope — the M8 device's own speech surface.

    Same tightness contract as Sierpinski center waveform: passthrough
    alpha + bounded burst clamp. The historical α=0.3 (#2651) lagged
    M8 percussion by 3-5 frames; bounded-amplitude clamp now bounds
    pathological excursions without temporal lag.
    """

    def test_amplitude_alpha_is_passthrough(self) -> None:
        assert AMPLITUDE_IIR_ALPHA == 1.0, (
            "M8 oscilloscope is the M8 device's audio-as-visual surface. "
            "AMPLITUDE_IIR_ALPHA MUST be 1.0 (passthrough). Any value < 1.0 "
            "lags M8 audio and weakens the per-ward speech representation."
        )

    def test_burst_clamp_set(self) -> None:
        assert 0.0 < AMPLITUDE_BURST_CLAMP <= 1.0, (
            "M8 burst clamp must be in (0, 1]. Operator directive: "
            "bounded-amplitude not low-pass-filtered amplitude."
        )

    def test_line_width_amplitude_scale_present(self) -> None:
        # The line-width modulation lives downstream of the (now passthrough)
        # smoothed value. Validate the module still exposes a configurable
        # scale, so calibration changes go via constants not code edits.
        assert LINE_WIDTH_AMPLITUDE_SCALE > 0.0


class TestSpeechSurfaceCalibrationContract:
    """Pin the calibration contract.

    Future calibration changes adjust the BURST_CLAMP value (bounded
    amplitude) NOT the IIR alpha (which would re-introduce smoothing).
    The relationship is:

        smoothed = smoothed × (1 − α) + clamp(raw, 0, BURST_CLAMP) × α

    With α=1.0 this reduces to ``smoothed = clamp(raw)`` — passthrough
    with bounded peaks. Calibration knobs:

    - BURST_CLAMP — peak amplitude ceiling
    - LINE_WIDTH_AMPLITUDE_SCALE — visual translation factor

    The IIR alpha is NOT a calibration knob; it is fixed at passthrough.
    """

    def test_speech_surface_alphas_are_fixed_at_passthrough(self) -> None:
        # All three speech-surface alphas (Sierpinski attack, Sierpinski
        # release, M8 amplitude) must be passthrough. This is the
        # constitutional contract of the speech surface.
        alphas = {
            "SIERPINSKI_AUDIO_ATTACK_ALPHA": SIERPINSKI_AUDIO_ATTACK_ALPHA,
            "SIERPINSKI_AUDIO_RELEASE_ALPHA": SIERPINSKI_AUDIO_RELEASE_ALPHA,
            "M8_AMPLITUDE_IIR_ALPHA": AMPLITUDE_IIR_ALPHA,
        }
        non_passthrough = {n: v for n, v in alphas.items() if v != 1.0}
        assert not non_passthrough, (
            f"Speech-surface alphas must all be 1.0 (passthrough). "
            f"Non-passthrough values found: {non_passthrough}. "
            f"To bound amplitude safely, adjust the BURST_CLAMP, NOT the alpha."
        )
