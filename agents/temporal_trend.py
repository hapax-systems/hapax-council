"""Trend-based protention — simple fallback predictions from ring buffer slopes.

Extracts flow, audio, HR, and presence trends from the perception ring
to generate anticipatory protention entries when the full ProtentionEngine
has insufficient training data.
"""

from __future__ import annotations

import math

from agents.hapax_daimonion.perception_ring import PerceptionRing
from agents.temporal_models import ProtentionEntry


def _safe_trend(ring: PerceptionRing, key: str, window_s: float) -> float:
    """Get trend value, returning 0.0 for None/NaN."""
    val = ring.trend(key, window_s=window_s)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 0.0
    return val


def trend_protention(ring: PerceptionRing, current: dict) -> list[ProtentionEntry]:
    """Simple trend-based predictions as fallback."""
    predictions: list[ProtentionEntry] = []

    flow_trend = _safe_trend(ring, "flow_score", 20.0)
    flow_score = current.get("flow_score", 0.0)

    if flow_trend > 0.01 and flow_score > 0.3:
        predictions.append(
            ProtentionEntry(
                predicted_state="entering_deep_work",
                confidence=min(0.8, 0.4 + flow_trend * 20),
                basis="flow score rising steadily",
            )
        )
    elif flow_trend < -0.02 and flow_score > 0.3:
        predictions.append(
            ProtentionEntry(
                predicted_state="flow_breaking",
                confidence=min(0.7, 0.3 + abs(flow_trend) * 15),
                basis="flow score declining",
            )
        )

    # Audio trend (music stopping → break)
    audio_trend = _safe_trend(ring, "audio_energy_rms", 15.0)
    audio_energy = current.get("audio_energy_rms", 0.0)
    if audio_trend < -0.005 and audio_energy < 0.02:
        music_genre = current.get("music_genre", "")
        if music_genre:
            predictions.append(
                ProtentionEntry(
                    predicted_state="break_likely",
                    confidence=0.5,
                    basis="audio dropping after music",
                )
            )

    # Heart rate trend (elevated → stress approaching)
    hr_trend = _safe_trend(ring, "heart_rate_bpm", 20.0)
    hr = current.get("heart_rate_bpm", 0)
    if hr_trend > 0.5 and hr > 80:
        predictions.append(
            ProtentionEntry(
                predicted_state="stress_rising",
                confidence=min(0.6, 0.3 + hr_trend * 0.2),
                basis="heart rate climbing",
            )
        )

    # Presence trend (Bayesian posterior declining → operator may leave)
    presence_trend = _safe_trend(ring, "presence_probability", 20.0)
    presence_prob = current.get("presence_probability")
    if presence_prob is not None:
        if presence_trend < -0.01 and presence_prob > 0.3:
            predictions.append(
                ProtentionEntry(
                    predicted_state="operator_departing",
                    confidence=min(0.7, 0.3 + abs(presence_trend) * 20),
                    basis="presence probability declining",
                )
            )
        elif presence_trend > 0.01 and presence_prob < 0.7:
            predictions.append(
                ProtentionEntry(
                    predicted_state="operator_returning",
                    confidence=min(0.7, 0.3 + presence_trend * 20),
                    basis="presence probability rising",
                )
            )

    # Activity stability → sustained state
    if len(ring) >= 5:
        recent = ring.window(12.0)
        activities = [s.get("production_activity", "") for s in recent]
        if activities and all(a == activities[0] for a in activities) and activities[0]:
            predictions.append(
                ProtentionEntry(
                    predicted_state="sustained_activity",
                    confidence=0.7,
                    basis=f"stable {activities[0]} for {len(recent)} ticks",
                )
            )

    return predictions
