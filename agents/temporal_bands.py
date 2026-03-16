"""Temporal band formatter — retention/impression/protention for LLM context.

Formats the perception ring buffer into Husserlian temporal bands:
  - Retention: fading past (summaries of recent history)
  - Impression: vivid present (current snapshot)
  - Protention: anticipated near-future (simple conditional predictions)

Pure logic, no I/O. Used by future LLM context builders to give agents
temporal thickness rather than flat snapshots.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.hapax_voice.perception_ring import PerceptionRing

# ── Data Models ──────────────────────────────────────────────────────────────


class RetentionEntry(BaseModel, frozen=True):
    """A fading memory from the recent past."""

    timestamp: float
    age_s: float  # seconds ago
    flow_state: str = "idle"
    activity: str = ""
    audio_energy: float = 0.0
    heart_rate: int = 0
    summary: str = ""


class ProtentionEntry(BaseModel, frozen=True):
    """A simple prediction about the near future."""

    predicted_state: str
    confidence: float  # 0.0 to 1.0
    basis: str  # what observation drove this prediction


class TemporalBands(BaseModel, frozen=True):
    """Complete temporal structure: retention → impression → protention."""

    retention: list[RetentionEntry] = Field(default_factory=list)
    impression: dict[str, Any] = Field(default_factory=dict)
    protention: list[ProtentionEntry] = Field(default_factory=list)


# ── Formatter ────────────────────────────────────────────────────────────────


class TemporalBandFormatter:
    """Format a perception ring into temporal bands.

    Retention: 3 entries sampled from ring (recent, mid, far).
    Impression: current snapshot.
    Protention: simple conditional predictions from trends.
    """

    def format(self, ring: PerceptionRing) -> TemporalBands:
        """Build temporal bands from the ring buffer state."""
        current = ring.current()
        if current is None:
            return TemporalBands()

        now = current.get("ts", 0.0)
        retention = self._build_retention(ring, now)
        impression = self._build_impression(current)
        protention = self._build_protention(ring)

        return TemporalBands(
            retention=retention,
            impression=impression,
            protention=protention,
        )

    def format_xml(self, bands: TemporalBands) -> str:
        """Format bands as XML tags for LLM context injection."""
        parts: list[str] = ["<temporal_context>"]

        if bands.retention:
            parts.append("  <retention>")
            for r in bands.retention:
                parts.append(
                    f'    <memory age_s="{r.age_s:.0f}" flow="{r.flow_state}" '
                    f'activity="{r.activity}">{r.summary}</memory>'
                )
            parts.append("  </retention>")

        if bands.impression:
            parts.append("  <impression>")
            for key, val in bands.impression.items():
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
            best = min(history, key=lambda s: abs(s.get("ts", 0) - target_ts))
            age = now - best.get("ts", now)

            # Skip if too close to another entry we already added
            if entries and abs(age - entries[-1].age_s) < 2.0:
                continue

            flow_score = best.get("flow_score", 0.0)
            if flow_score >= 0.6:
                flow_state = "active"
            elif flow_score >= 0.3:
                flow_state = "warming"
            else:
                flow_state = "idle"

            activity = best.get("production_activity", "")
            audio = best.get("audio_energy_rms", 0.0)
            hr = int(best.get("heart_rate_bpm", 0))

            summary = self._summarize_snapshot(best, flow_state)

            entries.append(
                RetentionEntry(
                    timestamp=best.get("ts", 0.0),
                    age_s=round(age, 1),
                    flow_state=flow_state,
                    activity=activity,
                    audio_energy=audio,
                    heart_rate=hr,
                    summary=summary,
                )
            )

        return entries

    def _build_impression(self, current: dict[str, Any]) -> dict[str, Any]:
        """Extract key fields from the current snapshot."""
        flow_score = current.get("flow_score", 0.0)
        if flow_score >= 0.6:
            flow_state = "active"
        elif flow_score >= 0.3:
            flow_state = "warming"
        else:
            flow_state = "idle"

        return {
            "flow_state": flow_state,
            "flow_score": round(flow_score, 2),
            "activity": current.get("production_activity", ""),
            "audio_energy": round(current.get("audio_energy_rms", 0.0), 3),
            "music_genre": current.get("music_genre", ""),
            "heart_rate": int(current.get("heart_rate_bpm", 0)),
            "consent_phase": current.get("consent_phase", "no_guest"),
        }

    def _build_protention(self, ring: PerceptionRing) -> list[ProtentionEntry]:
        """Simple conditional predictions from ring trends."""
        predictions: list[ProtentionEntry] = []

        # Flow trend
        flow_trend = ring.trend("flow_score", window_s=20.0)
        current = ring.current()
        if current is None:
            return predictions

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

    def _summarize_snapshot(self, snapshot: dict[str, Any], flow_state: str) -> str:
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
        if hr > 0:
            parts.append(f"{hr}bpm")

        return ", ".join(parts) if parts else "quiet"
