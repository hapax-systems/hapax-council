"""Multi-scale temporal hierarchy — minute/session/day summaries.

WS1: extends the perception ring buffer (50s window) with longer-term
temporal structure. Three scales above the tick level:

  Tick (2.5s)  → Ring buffer (existing, 20 snapshots)
  Minute       → MinuteBuffer (rolling, last 30 minutes)
  Session      → SessionBuffer (activity-bounded episodes)
  Day          → DaySummary (accumulated from sessions)

All statistical. No LLM calls at the minute/session level — just
aggregation. The local LLM can be used for narrative summarization
when context is requested, but the data structures are pure logic.

Used by: temporal_bands.py (multi-scale retention bands),
         content_scheduler.py (session-aware content selection),
         protention_engine (richer circadian/session patterns).
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from pydantic import BaseModel, Field

# ── Minute Summary ───────────────────────────────────────────────────────────


class MinuteSummary(BaseModel, frozen=True):
    """Statistical summary of one minute of perception data."""

    timestamp: float  # start of the minute
    activity: str = ""  # dominant activity (mode)
    flow_state: str = "idle"  # dominant flow state
    flow_mean: float = 0.0
    audio_mean: float = 0.0
    hr_mean: float = 0.0
    snapshot_count: int = 0
    voice_active: bool = False
    # Perception-informed classification fields
    operator_present: bool = False
    person_count_max: int = 0
    consent_phase: str = "no_guest"
    stress_elevated: bool = False


class MinuteBuffer:
    """Rolling buffer of minute-level summaries.

    Call tick() every perception tick (~2.5s) with the current snapshot.
    Internally accumulates snapshots and produces a MinuteSummary every 60s.
    Keeps the last 30 minutes.
    """

    def __init__(self, maxlen: int = 30) -> None:
        self._summaries: deque[MinuteSummary] = deque(maxlen=maxlen)
        self._current_minute: list[dict[str, Any]] = []
        self._minute_start: float = 0.0

    def tick(self, snapshot: dict[str, Any]) -> MinuteSummary | None:
        """Feed a perception snapshot. Returns summary when a minute closes."""
        ts = snapshot.get("timestamp", snapshot.get("ts", time.time()))

        if not self._current_minute:
            self._minute_start = ts
            self._current_minute.append(snapshot)
            return None

        elapsed = ts - self._minute_start
        if elapsed < 60.0:
            self._current_minute.append(snapshot)
            return None

        # Close the minute
        summary = self._close_minute()
        self._current_minute = [snapshot]
        self._minute_start = ts
        return summary

    def flush(self) -> MinuteSummary | None:
        """Force-close current minute (e.g., on shutdown)."""
        if len(self._current_minute) >= 2:
            return self._close_minute()
        return None

    @property
    def summaries(self) -> list[MinuteSummary]:
        """All minute summaries, oldest first."""
        return list(self._summaries)

    @property
    def latest(self) -> MinuteSummary | None:
        return self._summaries[-1] if self._summaries else None

    def __len__(self) -> int:
        return len(self._summaries)

    def _close_minute(self) -> MinuteSummary:
        snaps = self._current_minute
        activities = [s.get("production_activity", "") for s in snaps]
        flow_scores = [s.get("flow_score", 0.0) for s in snaps]
        audio_vals = [s.get("audio_energy_rms", 0.0) for s in snaps]
        hr_vals = [float(s.get("heart_rate_bpm", 0)) for s in snaps]

        activity = _mode(activities)
        flow_mean = sum(flow_scores) / len(flow_scores) if flow_scores else 0.0
        flow_state = "active" if flow_mean >= 0.6 else ("warming" if flow_mean >= 0.3 else "idle")
        audio_mean = sum(audio_vals) / len(audio_vals) if audio_vals else 0.0
        hr_mean = sum(hr_vals) / len(hr_vals) if hr_vals else 0.0

        voice_active = any(
            s.get("voice_session", {}).get("active", False)
            for s in snaps
            if isinstance(s.get("voice_session"), dict)
        )

        # Perception-informed classification fields
        operator_present = any(s.get("presence_state", "") == "PRESENT" for s in snaps)
        person_counts = [int(s.get("person_count", 0)) for s in snaps]
        person_count_max = max(person_counts) if person_counts else 0
        consent_phases = [s.get("consent_phase", "no_guest") for s in snaps]
        consent_phase = _mode(consent_phases) or "no_guest"
        stress_elevated = any(s.get("stress_elevated", False) for s in snaps)

        summary = MinuteSummary(
            timestamp=self._minute_start,
            activity=activity,
            flow_state=flow_state,
            flow_mean=round(flow_mean, 3),
            audio_mean=round(audio_mean, 4),
            hr_mean=round(hr_mean, 1),
            snapshot_count=len(snaps),
            voice_active=voice_active,
            operator_present=operator_present,
            person_count_max=person_count_max,
            consent_phase=consent_phase,
            stress_elevated=stress_elevated,
        )
        self._summaries.append(summary)
        return summary


# ── Session Summary ──────────────────────────────────────────────────────────


class SessionSummary(BaseModel, frozen=True):
    """Summary of a contiguous activity session (bounded by activity change)."""

    start_ts: float
    end_ts: float
    duration_s: float
    activity: str = ""
    flow_state: str = "idle"  # dominant
    flow_peak: float = 0.0
    flow_mean: float = 0.0
    minute_count: int = 0
    voice_turns: int = 0


class SessionBuffer:
    """Accumulates minute summaries into activity-bounded sessions.

    Call observe() with each MinuteSummary. When the dominant activity
    changes, the previous session is closed and returned.
    Keeps the last 10 sessions.
    """

    def __init__(self, maxlen: int = 10) -> None:
        self._sessions: deque[SessionSummary] = deque(maxlen=maxlen)
        self._current_minutes: list[MinuteSummary] = []

    def observe(self, minute: MinuteSummary) -> SessionSummary | None:
        """Feed a minute summary. Returns closed session on activity change."""
        if not self._current_minutes:
            self._current_minutes.append(minute)
            return None

        prev_activity = self._current_minutes[-1].activity
        if minute.activity != prev_activity and (minute.activity or prev_activity):
            session = self._close_session()
            self._current_minutes = [minute]
            return session

        self._current_minutes.append(minute)
        return None

    def flush(self) -> SessionSummary | None:
        """Force-close current session."""
        if len(self._current_minutes) >= 1:
            return self._close_session()
        return None

    @property
    def sessions(self) -> list[SessionSummary]:
        return list(self._sessions)

    @property
    def latest(self) -> SessionSummary | None:
        return self._sessions[-1] if self._sessions else None

    def __len__(self) -> int:
        return len(self._sessions)

    def _close_session(self) -> SessionSummary:
        mins = self._current_minutes
        first = mins[0]
        last = mins[-1]

        activities = [m.activity for m in mins]
        activity = _mode(activities)

        flow_means = [m.flow_mean for m in mins]
        flow_mean = sum(flow_means) / len(flow_means) if flow_means else 0.0
        flow_peak = max(flow_means) if flow_means else 0.0
        flow_state = "active" if flow_mean >= 0.6 else ("warming" if flow_mean >= 0.3 else "idle")

        voice_count = sum(1 for m in mins if m.voice_active)

        duration = last.timestamp - first.timestamp + 60.0  # include last minute

        session = SessionSummary(
            start_ts=first.timestamp,
            end_ts=last.timestamp + 60.0,
            duration_s=round(duration, 1),
            activity=activity,
            flow_state=flow_state,
            flow_peak=round(flow_peak, 3),
            flow_mean=round(flow_mean, 3),
            minute_count=len(mins),
            voice_turns=voice_count,
        )
        self._sessions.append(session)
        self._current_minutes = []
        return session


# ── Day Summary ──────────────────────────────────────────────────────────────


class DaySummary(BaseModel):
    """Accumulated summary of the day so far."""

    session_count: int = 0
    total_minutes: int = 0
    dominant_activity: str = ""
    total_flow_minutes: int = 0
    total_voice_minutes: int = 0
    activities: dict[str, int] = Field(default_factory=dict)  # activity → minutes


def compute_day_summary(
    sessions: list[SessionSummary],
    minutes: list[MinuteSummary],
) -> DaySummary:
    """Compute a day summary from accumulated sessions and minutes."""
    activities: dict[str, int] = {}
    flow_minutes = 0
    voice_minutes = 0

    for m in minutes:
        act = m.activity or "idle"
        activities[act] = activities.get(act, 0) + 1
        if m.flow_state == "active":
            flow_minutes += 1
        if m.voice_active:
            voice_minutes += 1

    dominant = max(activities, key=activities.get) if activities else ""  # type: ignore[arg-type]

    return DaySummary(
        session_count=len(sessions),
        total_minutes=len(minutes),
        dominant_activity=dominant,
        total_flow_minutes=flow_minutes,
        total_voice_minutes=voice_minutes,
        activities=activities,
    )


# ── Multi-Scale Context ──────────────────────────────────────────────────────


class MultiScaleContext(BaseModel, frozen=True):
    """Complete multi-scale temporal context for LLM prompt injection."""

    recent_minutes: list[MinuteSummary] = Field(default_factory=list)  # last 5
    current_session: SessionSummary | None = None
    recent_sessions: list[SessionSummary] = Field(default_factory=list)  # last 3
    day: DaySummary = Field(default_factory=DaySummary)


class MultiScaleAggregator:
    """Aggregates perception ticks into multi-scale temporal context.

    Call tick() every perception tick. Internally manages minute and session
    buffers. Call context() to get the current multi-scale snapshot.
    """

    def __init__(self) -> None:
        self._minute_buffer = MinuteBuffer()
        self._session_buffer = SessionBuffer()

    def tick(self, snapshot: dict[str, Any]) -> MinuteSummary | None:
        """Feed a perception snapshot through all scales.

        Returns the MinuteSummary when a minute boundary is crossed, None otherwise.
        """
        minute = self._minute_buffer.tick(snapshot)
        if minute is not None:
            self._session_buffer.observe(minute)
        return minute

    def context(self) -> MultiScaleContext:
        """Build the current multi-scale context."""
        minutes = self._minute_buffer.summaries
        sessions = self._session_buffer.sessions

        # Current session: what we're accumulating now
        current = None
        if self._session_buffer._current_minutes:
            mins = self._session_buffer._current_minutes
            if mins:
                flow_means = [m.flow_mean for m in mins]
                flow_mean = sum(flow_means) / len(flow_means)
                current = SessionSummary(
                    start_ts=mins[0].timestamp,
                    end_ts=mins[-1].timestamp + 60.0,
                    duration_s=round((mins[-1].timestamp - mins[0].timestamp + 60.0), 1),
                    activity=_mode([m.activity for m in mins]),
                    flow_state="active"
                    if flow_mean >= 0.6
                    else ("warming" if flow_mean >= 0.3 else "idle"),
                    flow_peak=round(max(flow_means), 3),
                    flow_mean=round(flow_mean, 3),
                    minute_count=len(mins),
                )

        day = compute_day_summary(sessions, minutes)

        return MultiScaleContext(
            recent_minutes=minutes[-5:],
            current_session=current,
            recent_sessions=sessions[-3:],
            day=day,
        )

    def format_xml(self, ctx: MultiScaleContext) -> str:
        """Format multi-scale context as XML for LLM prompt injection."""
        parts: list[str] = ["<temporal_scales>"]

        if ctx.recent_minutes:
            parts.append("  <minutes>")
            for m in ctx.recent_minutes:
                parts.append(
                    f'    <minute activity="{m.activity}" flow="{m.flow_state}" '
                    f'hr="{m.hr_mean:.0f}" audio="{m.audio_mean:.3f}" />'
                )
            parts.append("  </minutes>")

        if ctx.current_session:
            s = ctx.current_session
            parts.append(
                f'  <current_session activity="{s.activity}" flow="{s.flow_state}" '
                f'duration_m="{s.duration_s / 60:.0f}" flow_peak="{s.flow_peak:.2f}" />'
            )

        if ctx.recent_sessions:
            parts.append("  <recent_sessions>")
            for s in ctx.recent_sessions:
                parts.append(
                    f'    <session activity="{s.activity}" duration_m="{s.duration_s / 60:.0f}" '
                    f'flow="{s.flow_state}" />'
                )
            parts.append("  </recent_sessions>")

        d = ctx.day
        if d.total_minutes > 0:
            acts = ", ".join(
                f"{k}:{v}m" for k, v in sorted(d.activities.items(), key=lambda x: -x[1])[:3]
            )
            parts.append(
                f'  <day sessions="{d.session_count}" minutes="{d.total_minutes}" '
                f'flow_minutes="{d.total_flow_minutes}" dominant="{d.dominant_activity}" '
                f'activities="{acts}" />'
            )

        parts.append("</temporal_scales>")
        return "\n".join(parts)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mode(values: list[str]) -> str:
    counts: dict[str, int] = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)  # type: ignore[arg-type]
