"""Cross-modal fusion: contact mic DSP + IR hand zone disambiguation."""

from __future__ import annotations

from agents.hapax_daimonion.backends.contact_mic import _classify_activity


def _classify_activity_with_ir(
    energy: float,
    onset_rate: float,
    centroid: float,
    autocorr_peak: float = 0.0,
    ir_hand_zone: str = "none",
    ir_hand_activity: str = "none",
) -> str:
    """Classify desk activity with IR hand zone disambiguation.

    Base classification from DSP metrics, then refine with IR context:
    - turntable zone + sliding/tapping → scratching
    - mpc-pads zone + tapping energy → pad-work
    """
    base = _classify_activity(energy, onset_rate, centroid, autocorr_peak)
    if base == "idle":
        return "idle"
    if ir_hand_zone == "turntable" and ir_hand_activity in ("sliding", "tapping"):
        return "scratching"
    if ir_hand_zone == "mpc-pads" and base in ("tapping", "active"):
        return "pad-work"
    return base
