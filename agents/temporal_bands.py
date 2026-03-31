"""Temporal band formatter — retention/impression/protention for LLM context.

Formats the perception ring buffer into Husserlian temporal bands:
  - Retention: fading past (summaries of recent history)
  - Impression: vivid present (current snapshot)
  - Protention: anticipated near-future (simple conditional predictions)

Pure logic, no I/O. Used by future LLM context builders to give agents
temporal thickness rather than flat snapshots.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agents.hapax_daimonion.perception_ring import PerceptionRing
from agents.protention_engine import ProtentionEngine

# ── Data Models ──────────────────────────────────────────────────────────────


class RetentionEntry(BaseModel, frozen=True):
    """A fading memory from the recent past."""

    timestamp: float
    age_s: float  # seconds ago
    flow_state: str = "idle"
    activity: str = ""
    audio_energy: float = 0.0
    heart_rate: int = 0
    presence: str = ""  # PRESENT/UNCERTAIN/AWAY from Bayesian engine
    summary: str = ""


class ProtentionEntry(BaseModel, frozen=True):
    """A simple prediction about the near future."""

    predicted_state: str
    confidence: float  # 0.0 to 1.0
    basis: str  # what observation drove this prediction


class SurpriseField(BaseModel, frozen=True):
    """A single surprising observation in the primal impression."""

    field: str
    observed: str  # what actually happened
    expected: str  # what was predicted
    surprise: float  # 0.0 (confirmed) to 1.0 (maximally surprising)
    note: str = ""  # human-readable explanation


class TemporalBands(BaseModel, frozen=True):
    """Complete temporal structure: retention → impression → protention."""

    retention: list[RetentionEntry] = Field(default_factory=list)
    impression: dict[str, object] = Field(default_factory=dict)
    protention: list[ProtentionEntry] = Field(default_factory=list)
    surprises: list[SurpriseField] = Field(default_factory=list)

    @property
    def max_surprise(self) -> float:
        """Highest surprise score across all fields. 0.0 if none."""
        return max((s.surprise for s in self.surprises), default=0.0)


# ── Formatter ────────────────────────────────────────────────────────────────


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
        impression = self._build_impression(current)

        # Compute surprise against last tick's protention before generating new ones
        surprises = self._compute_surprise(current, self._last_protention)

        protention = self._build_protention(ring)
        # Store for next tick's surprise comparison
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

        # Exclude the current (last) snapshot
        history = snapshots[:-1]

        for target_age in targets:
            target_ts = now - target_age
            # Find closest snapshot to target timestamp
            best = min(history, key=lambda s: abs(float(s.get("ts", 0)) - target_ts))
            age = now - float(best.get("ts", now))

            # Skip if too close to another entry we already added
            if entries and abs(age - entries[-1].age_s) < 2.0:
                continue

            flow_score = best.get("flow_score", 0.0)
            if float(flow_score) >= 0.6:
                flow_state = "active"
            elif float(flow_score) >= 0.3:
                flow_state = "warming"
            else:
                flow_state = "idle"

            activity = best.get("production_activity", "")
            audio = best.get("audio_energy_rms", 0.0)
            hr = int(best.get("heart_rate_bpm", 0))

            # Presence from Bayesian engine
            pp = best.get("presence_probability", None)
            if pp is not None:
                presence = (
                    "present" if float(pp) >= 0.7 else ("uncertain" if float(pp) >= 0.3 else "away")
                )
            else:
                presence = ""

            summary = self._summarize_snapshot(best, flow_state)

            entries.append(
                RetentionEntry(
                    timestamp=best.get("ts", 0.0),
                    age_s=round(age, 1),
                    flow_state=flow_state,
                    activity=activity,
                    audio_energy=audio,
                    heart_rate=hr,
                    presence=presence,
                    summary=summary,
                )
            )

        return entries

    def _build_impression(self, current: dict[str, object]) -> dict[str, object]:
        """Extract key fields from the current snapshot."""
        flow_score = current.get("flow_score", 0.0)
        if float(flow_score) >= 0.6:
            flow_state = "active"
        elif float(flow_score) >= 0.3:
            flow_state = "warming"
        else:
            flow_state = "idle"

        # Presence from Bayesian engine
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
            "audio_energy": round(current.get("audio_energy_rms", 0.0), 3),
            "music_genre": current.get("music_genre", ""),
            "heart_rate": int(current.get("heart_rate_bpm", 0)),
            "consent_phase": current.get("consent_phase", "no_guest"),
        }
        if presence:
            impression["presence"] = presence
            impression["presence_probability"] = round(presence_prob, 3)

        return impression

    def _compute_surprise(
        self, current: dict[str, object], last_protention: list[ProtentionEntry]
    ) -> list[SurpriseField]:
        """Compare current state against previous protention predictions.

        Surprise = high-confidence prediction that was wrong.
        Confirmation = high-confidence prediction that was right (surprise=0).
        Fields not predicted have no surprise score.
        """
        if not last_protention:
            return []

        surprises: list[SurpriseField] = []

        flow_score = current.get("flow_score", 0.0)
        flow_state = (
            "active"
            if float(flow_score) >= 0.6
            else ("warming" if float(flow_score) >= 0.3 else "idle")
        )
        activity = current.get("production_activity", "")

        for pred in last_protention:
            # Match prediction to observed state
            if pred.predicted_state in ("entering_deep_work", "flow_continuing"):
                observed_matches = flow_state == "active"
                surprises.append(
                    SurpriseField(
                        field="flow_state",
                        observed=flow_state,
                        expected="active",
                        surprise=0.0 if observed_matches else pred.confidence,
                        note="" if observed_matches else f"predicted {pred.predicted_state}",
                    )
                )
            elif pred.predicted_state == "flow_breaking" or pred.predicted_state == "flow_ending":
                observed_matches = flow_state != "active"
                surprises.append(
                    SurpriseField(
                        field="flow_state",
                        observed=flow_state,
                        expected="idle",
                        surprise=0.0 if observed_matches else pred.confidence,
                        note="" if observed_matches else "flow persisted despite prediction",
                    )
                )
            elif pred.predicted_state == "break_likely":
                observed_matches = activity in ("", "idle", "browsing")
                surprises.append(
                    SurpriseField(
                        field="activity",
                        observed=activity or "idle",
                        expected="break",
                        surprise=0.0 if observed_matches else pred.confidence,
                        note="" if observed_matches else f"still {activity}",
                    )
                )
            elif pred.predicted_state == "stress_rising":
                hr = current.get("heart_rate_bpm", 0)
                observed_matches = int(hr) > 85
                surprises.append(
                    SurpriseField(
                        field="heart_rate",
                        observed=str(hr),
                        expected=">85",
                        surprise=0.0 if observed_matches else pred.confidence,
                        note="" if observed_matches else "HR stabilized",
                    )
                )
            elif pred.predicted_state == "sustained_activity":
                observed_matches = activity == pred.basis.split()[-2] if pred.basis else True
                surprises.append(
                    SurpriseField(
                        field="activity",
                        observed=activity or "idle",
                        expected="sustained",
                        surprise=0.0 if observed_matches else pred.confidence * 0.5,
                        note="" if observed_matches else "activity changed unexpectedly",
                    )
                )
            elif pred.predicted_state == "operator_departing":
                pp = current.get("presence_probability", 1.0)
                observed_matches = float(pp) < 0.3  # actually departed
                surprises.append(
                    SurpriseField(
                        field="presence",
                        observed=f"p={float(pp):.2f}" if pp is not None else "unknown",
                        expected="departing",
                        surprise=0.0 if observed_matches else pred.confidence,
                        note="" if observed_matches else "operator stayed",
                    )
                )
            elif pred.predicted_state == "operator_returning":
                pp = current.get("presence_probability", 0.0)
                observed_matches = float(pp) >= 0.7  # actually returned
                surprises.append(
                    SurpriseField(
                        field="presence",
                        observed=f"p={pp:.2f}" if pp is not None else "unknown",
                        expected="returning",
                        surprise=0.0 if observed_matches else pred.confidence,
                        note="" if observed_matches else "operator still away",
                    )
                )
            # Engine-sourced activity predictions
            elif pred.predicted_state not in (
                "flow_likely",
                "sustained_activity",
            ):
                # Generic activity prediction from Markov chain
                if activity and activity != pred.predicted_state:
                    surprises.append(
                        SurpriseField(
                            field="activity",
                            observed=activity,
                            expected=pred.predicted_state,
                            surprise=pred.confidence * 0.7,
                            note=f"predicted {pred.predicted_state}, got {activity}",
                        )
                    )

        # Deduplicate by field (keep highest surprise)
        seen: dict[str, SurpriseField] = {}
        for s in surprises:
            if s.field not in seen or s.surprise > seen[s.field].surprise:
                seen[s.field] = s
        return list(seen.values())

    def _build_protention(self, ring: PerceptionRing) -> list[ProtentionEntry]:
        """Statistical predictions from protention engine, with trend fallback."""
        current = ring.current()
        if current is None:
            return []

        predictions: list[ProtentionEntry] = []

        # Use protention engine if available and has learned data
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

        # Trend-based fallback/supplement (always runs, engine predictions take priority)
        trend_predictions = self._trend_protention(ring, current)
        # Only add trend predictions for dimensions not already covered by engine
        engine_dimensions = {p.predicted_state for p in predictions}
        for tp in trend_predictions:
            if tp.predicted_state not in engine_dimensions:
                predictions.append(tp)

        return predictions[:5]  # cap total predictions

    def _trend_protention(self, ring: PerceptionRing, current: dict) -> list[ProtentionEntry]:
        """Simple trend-based predictions as fallback."""
        predictions: list[ProtentionEntry] = []

        flow_trend = ring.trend("flow_score", window_s=20.0)
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
        audio_trend = ring.trend("audio_energy_rms", window_s=15.0)
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
        hr_trend = ring.trend("heart_rate_bpm", window_s=20.0)
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
        presence_trend = ring.trend("presence_probability", window_s=20.0)
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

    def _summarize_snapshot(self, snapshot: dict[str, object], flow_state: str) -> str:
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

        hr = snapshot.get("heart_rate_bpm", 0)
        if int(hr) > 0:
            parts.append(f"{hr}bpm")

        pp = snapshot.get("presence_probability")
        if pp is not None and float(pp) < 0.3:
            parts.append("away")
        elif pp is not None and float(pp) < 0.7:
            parts.append("uncertain")

        return ", ".join(parts) if parts else "quiet"
