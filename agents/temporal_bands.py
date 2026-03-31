"""Temporal band formatter — retention/impression/protention for LLM context.

Formats the perception ring buffer into Husserlian temporal bands:
  - Retention: fading past (summaries of recent history)
  - Impression: vivid present (current snapshot)
  - Protention: anticipated near-future (simple conditional predictions)

Pure logic, no I/O. Used by future LLM context builders to give agents
temporal thickness rather than flat snapshots.
"""

from __future__ import annotations

from agents.hapax_daimonion.perception_ring import PerceptionRing
from agents.protention_engine import ProtentionEngine
from agents.temporal_models import (
    ProtentionEntry,
    RetentionEntry,
    SurpriseField,
    TemporalBands,
)
from agents.temporal_surprise import compute_surprise
from agents.temporal_trend import trend_protention

# Re-export models for backward compatibility
__all__ = [
    "RetentionEntry",
    "ProtentionEntry",
    "SurpriseField",
    "TemporalBands",
    "TemporalBandFormatter",
]


class TemporalBandFormatter:
    """Format a perception ring into temporal bands.

    Retention: 3 entries sampled from ring (recent, mid, far).
    Impression: current snapshot.
    Protention: statistical predictions from engine (with trend fallback).
    """

    def __init__(self, protention_engine: ProtentionEngine | None = None) -> None:
        self._protention_engine = protention_engine
        self._last_protention: list[ProtentionEntry] = []

    def format(self, ring: PerceptionRing) -> TemporalBands:
        """Build temporal bands from the ring buffer state."""
        current = ring.current()
        if current is None:
            return TemporalBands()

        now = current.get("ts", 0.0)
        retention = self._build_retention(ring, now)
        impression = _build_impression(current)
        surprises = compute_surprise(current, self._last_protention)
        protention = self._build_protention(ring)
        self._last_protention = protention

        return TemporalBands(
            retention=retention,
            impression=impression,
            protention=protention,
            surprises=surprises,
        )

    def format_xml(self, bands: TemporalBands) -> str:
        """Format bands as XML tags for LLM context injection."""
        parts: list[str] = ["<temporal_context>"]

        if bands.retention:
            parts.append("  <retention>")
            for r in bands.retention:
                attrs = f'age_s="{r.age_s:.0f}" flow="{r.flow_state}" activity="{r.activity}"'
                if r.presence:
                    attrs += f' presence="{r.presence}"'
                parts.append(f"    <memory {attrs}>{r.summary}</memory>")
            parts.append("  </retention>")

        if bands.impression:
            parts.append("  <impression>")
            surprise_map = {s.field: s for s in bands.surprises}
            for key, val in bands.impression.items():
                sf = surprise_map.get(key)
                if sf and sf.surprise > 0.3:
                    parts.append(
                        f'    <{key} surprise="{sf.surprise:.2f}" '
                        f'expected="{sf.expected}">{val}</{key}>'
                    )
                else:
                    parts.append(f"    <{key}>{val}</{key}>")
            parts.append("  </impression>")

        if bands.protention:
            parts.append("  <protention>")
            for p in bands.protention:
                parts.append(
                    f'    <prediction state="{p.predicted_state}" '
                    f'confidence="{p.confidence:.2f}">{p.basis}</prediction>'
                )
            parts.append("  </protention>")

        parts.append("</temporal_context>")
        return "\n".join(parts)

    def _build_retention(self, ring: PerceptionRing, now: float) -> list[RetentionEntry]:
        """Sample 3 retention entries: recent (~5s), mid (~15s), far (~40s)."""
        entries: list[RetentionEntry] = []
        targets = [5.0, 15.0, 40.0]

        snapshots = ring.snapshots
        if len(snapshots) < 2:
            return entries

        history = snapshots[:-1]

        for target_age in targets:
            target_ts = now - target_age
            best = min(history, key=lambda s: abs(float(s.get("ts", 0)) - target_ts))
            age = now - float(best.get("ts", now))

            if entries and abs(age - entries[-1].age_s) < 2.0:
                continue

            flow_score = float(best.get("flow_score", 0.0))
            if flow_score >= 0.6:
                flow_state = "active"
            elif flow_score >= 0.3:
                flow_state = "warming"
            else:
                flow_state = "idle"

            pp = best.get("presence_probability", None)
            if pp is not None:
                presence = (
                    "present" if float(pp) >= 0.7 else ("uncertain" if float(pp) >= 0.3 else "away")
                )
            else:
                presence = ""

            entries.append(
                RetentionEntry(
                    timestamp=best.get("ts", 0.0),
                    age_s=round(age, 1),
                    flow_state=flow_state,
                    activity=best.get("production_activity", ""),
                    audio_energy=best.get("audio_energy_rms", 0.0),
                    heart_rate=int(best.get("heart_rate_bpm", 0)),
                    presence=presence,
                    summary=_summarize_snapshot(best, flow_state),
                )
            )

        return entries

    def _build_protention(self, ring: PerceptionRing) -> list[ProtentionEntry]:
        """Statistical predictions from protention engine, with trend fallback."""
        current = ring.current()
        if current is None:
            return []

        predictions: list[ProtentionEntry] = []

        if self._protention_engine is not None:
            from datetime import datetime

            snapshot = self._protention_engine.predict(
                current_activity=current.get("production_activity", ""),
                flow_score=current.get("flow_score", 0.0),
                hour=datetime.now().hour,
            )
            for pred in snapshot.top_predictions:
                predictions.append(
                    ProtentionEntry(
                        predicted_state=pred.predicted_value,
                        confidence=pred.probability,
                        basis=pred.basis,
                    )
                )

        engine_dims = {p.predicted_state for p in predictions}
        for tp in trend_protention(ring, current):
            if tp.predicted_state not in engine_dims:
                predictions.append(tp)

        return predictions[:5]


# ── Module-level helpers ─────────────────────────────────────────────────────


def _build_impression(current: dict[str, object]) -> dict[str, object]:
    """Extract key fields from the current snapshot."""
    flow_score = float(current.get("flow_score", 0.0))
    if flow_score >= 0.6:
        flow_state = "active"
    elif flow_score >= 0.3:
        flow_state = "warming"
    else:
        flow_state = "idle"

    presence_prob = current.get("presence_probability")
    if presence_prob is not None:
        if float(presence_prob) >= 0.7:
            presence = "present"
        elif float(presence_prob) >= 0.3:
            presence = "uncertain"
        else:
            presence = "away"
    else:
        presence = ""

    impression: dict[str, object] = {
        "flow_state": flow_state,
        "flow_score": round(flow_score, 2),
        "activity": current.get("production_activity", ""),
        "audio_energy": round(float(current.get("audio_energy_rms", 0.0)), 3),
        "music_genre": current.get("music_genre", ""),
        "heart_rate": int(current.get("heart_rate_bpm", 0)),
        "consent_phase": current.get("consent_phase", "no_guest"),
    }
    if presence:
        impression["presence"] = presence
        impression["presence_probability"] = round(presence_prob, 3)

    return impression


def _summarize_snapshot(snapshot: dict[str, object], flow_state: str) -> str:
    """One-line human-readable summary of a past snapshot."""
    parts: list[str] = []

    activity = snapshot.get("production_activity", "")
    if activity and activity != "idle":
        parts.append(activity)
    elif flow_state != "idle":
        parts.append(f"flow:{flow_state}")

    genre = snapshot.get("music_genre", "")
    if genre:
        parts.append(genre)

    hr = int(snapshot.get("heart_rate_bpm", 0))
    if hr > 0:
        parts.append(f"{hr}bpm")

    pp = (
        float(snapshot.get("presence_probability", 0.0))
        if snapshot.get("presence_probability") is not None
        else None
    )
    if pp is not None and pp < 0.3:
        parts.append("away")
    elif pp is not None and pp < 0.7:
        parts.append("uncertain")

    return ", ".join(parts) if parts else "quiet"
