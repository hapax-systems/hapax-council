"""Segment Content Ward — visual overlay for active programme segments.

When Hapax narrates a structured segment (tier_list, lecture, rant, etc.),
this ward renders the segment's topic, beat progression, and key facts as
a styled text overlay on the livestream.  Without this, the audience only
hears Hapax's voice against abstract generative visuals — the narration
references specific content the viewer cannot see.

Architecture mirrors ``CodingActivityReveal``: a poll thread reads the
segment state from SHM, drives an FSM-based alpha ramp, and renders via
Cairo on each compositor frame.

The segment state file is written by the programme loop when it activates
a segmented-content programme.  The ward reads it, renders the content,
and fades out when no segment is active.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage.transitional_source import (
    HomageTransitionalSource,
    TransitionState,
)
from agents.studio_compositor.text_render import (
    OUTLINE_OFFSETS_4,
    TextStyle,
    render_text,
)

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

# SHM file written by the programme loop with the active segment state.
SEGMENT_STATE_FILE = Path("/dev/shm/hapax-compositor/active-segment.json")

# Ramp durations — slightly slower than DURF for a more deliberate feel.
_ENTER_RAMP_S: float = 0.6
_EXIT_RAMP_S: float = 0.8
_EXIT_HYSTERESIS_S: float = 3.0

# Steady-state alpha when fronted.
_FRONTED_ALPHA: float = 0.88

# Poll cadence — 1Hz is plenty since segment state changes infrequently.
_POLL_INTERVAL_S: float = 1.0

# Default font for segment content — clean, modern, larger than DURF.
_FONT_DESCRIPTION: str = "Inter Bold 18"
_FONT_BODY: str = "Inter 15"
_FONT_BEAT: str = "Inter 14"


@dataclass(frozen=True)
class SegmentState:
    """Parsed segment state from SHM."""

    programme_id: str
    role: str
    topic: str
    narrative_beat: str
    segment_beats: tuple[str, ...]
    current_beat_index: int
    started_at: float
    planned_duration_s: float
    ward_profile: str
    ward_accent_role: str
    source_refs: tuple[str, ...]
    asset_attributions: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.programme_id


_EMPTY_STATE = SegmentState(
    programme_id="",
    role="",
    topic="",
    narrative_beat="",
    segment_beats=(),
    current_beat_index=0,
    started_at=0.0,
    planned_duration_s=0.0,
    ward_profile="",
    ward_accent_role="accent_cyan",
    source_refs=(),
    asset_attributions=(),
)


def _role_ward_defaults(role: str) -> tuple[str, str]:
    """Return (ward_profile, palette_role) for a segmented-content role."""
    try:
        from shared.programme import segmented_content_format_spec

        spec = segmented_content_format_spec(role)
    except Exception:
        spec = None
    if spec is None:
        return "", "accent_cyan"
    return spec.ward_profile, spec.ward_accent_role


def _read_segment_state(path: Path = SEGMENT_STATE_FILE) -> SegmentState:
    """Read segment state from SHM; return empty state on any failure."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _EMPTY_STATE
    if not isinstance(raw, dict) or not raw.get("programme_id"):
        return _EMPTY_STATE
    default_profile, default_accent = _role_ward_defaults(str(raw.get("role", "")))
    attributions: list[str] = []
    for item in raw.get("asset_attributions") or []:
        if isinstance(item, dict):
            source_ref = str(item.get("source_ref") or "").strip()
            title = str(item.get("title") or "").strip()
            if title and source_ref:
                attributions.append(f"{title} [{source_ref}]")
            elif source_ref:
                attributions.append(source_ref)
        elif isinstance(item, str) and item.strip():
            attributions.append(item.strip())
    return SegmentState(
        programme_id=str(raw.get("programme_id", "")),
        role=str(raw.get("role", "")),
        topic=str(raw.get("topic", "")),
        narrative_beat=str(raw.get("narrative_beat", "")),
        segment_beats=tuple(str(b) for b in (raw.get("segment_beats") or [])),
        current_beat_index=int(raw.get("current_beat_index", 0)),
        started_at=float(raw.get("started_at", 0.0)),
        planned_duration_s=float(raw.get("planned_duration_s", 3600.0)),
        ward_profile=str(raw.get("ward_profile") or default_profile),
        ward_accent_role=str(raw.get("ward_accent_role") or default_accent),
        source_refs=tuple(
            str(ref).strip() for ref in (raw.get("source_refs") or []) if str(ref).strip()
        ),
        asset_attributions=tuple(attributions[:5]),
    )


def _role_label(role: str) -> str:
    """Human-readable role label for the segment header."""
    labels = {
        "tier_list": "TIER LIST",
        "top_10": "TOP 10",
        "rant": "RANT",
        "react": "REACT",
        "iceberg": "ICEBERG",
        "interview": "INTERVIEW",
        "lecture": "LECTURE",
    }
    return labels.get(role, role.upper().replace("_", " "))


def _palette_role(pkg: Any, role: str) -> tuple[float, float, float, float]:
    value = getattr(pkg.palette, role, None)
    if value is None:
        value = pkg.palette.accent_cyan
    return value


class SegmentContentWard(HomageTransitionalSource):
    """Full-frame HOMAGE ward for segment content display.

    Renders the active segment's topic, beat progression, and elapsed
    time as a styled text overlay.  Fades in when a segment activates,
    fades out when it ends.
    """

    def __init__(
        self,
        *,
        state_file: Path = SEGMENT_STATE_FILE,
        start_thread: bool = True,
    ) -> None:
        HomageTransitionalSource.__init__(
            self,
            source_id="segment-content",
            entering_duration_s=_ENTER_RAMP_S,
            exiting_duration_s=_EXIT_RAMP_S,
        )
        self._state_file = state_file
        self._segment: SegmentState = _EMPTY_STATE
        self._segment_lock = threading.Lock()
        self._gate_off_pending_since: float | None = None
        self._last_rendered_alpha: float = 0.0
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="segment-content-poll",
                daemon=True,
            )
            self._poll_thread.start()

    # ── Lifecycle ────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("segment-content: poll failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def _poll_once(self, *, now: float | None = None) -> SegmentState:
        ts = time.monotonic() if now is None else now
        segment = _read_segment_state(self._state_file)
        with self._segment_lock:
            self._segment = segment
        gate = not segment.is_empty
        self._maybe_drive_fsm(gate, now=ts)
        return segment

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)

    # ── FSM driver ───────────────────────────────────────────────────

    def _maybe_drive_fsm(self, gate: bool, *, now: float) -> None:
        if gate:
            self._gate_off_pending_since = None
            if self._state in (TransitionState.ABSENT, TransitionState.EXITING):
                try:
                    self.apply_transition("segment-enter", now=now)
                except Exception:
                    log.debug("segment-content: FSM enter failed", exc_info=True)
            return
        # Gate OFF
        if self._gate_off_pending_since is None:
            self._gate_off_pending_since = now
            return
        elapsed_off = now - self._gate_off_pending_since
        if elapsed_off >= _EXIT_HYSTERESIS_S and self._state in (
            TransitionState.HOLD,
            TransitionState.ENTERING,
        ):
            try:
                self.apply_transition("segment-exit", now=now)
            except Exception:
                log.debug("segment-content: FSM exit failed", exc_info=True)

    # ── Alpha ────────────────────────────────────────────────────────

    def _compute_alpha(self, now: float) -> float:
        state_now = self._state
        if state_now is TransitionState.ABSENT:
            return 0.0
        if state_now is TransitionState.HOLD:
            with self._segment_lock:
                gate = not self._segment.is_empty
            return _FRONTED_ALPHA if gate else 0.0
        progress = self._progress(now=now)
        if state_now is TransitionState.ENTERING:
            return _FRONTED_ALPHA * progress
        # EXITING
        return _FRONTED_ALPHA * (1.0 - progress)

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._segment_lock:
            segment = self._segment
        alpha = self._compute_alpha(now)
        self._last_rendered_alpha = alpha
        return {
            "alpha": alpha,
            "now": now,
            "segment": segment,
        }

    # ── Render hooks ─────────────────────────────────────────────────

    def render_entering(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
        progress: float,
    ) -> None:
        ramped = dict(state)
        ramped["alpha"] = float(state.get("alpha", _FRONTED_ALPHA)) * progress
        self.render_content(cr, canvas_w, canvas_h, t, ramped)

    def render_exiting(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
        progress: float,
    ) -> None:
        ramped = dict(state)
        ramped["alpha"] = float(state.get("alpha", _FRONTED_ALPHA)) * (1.0 - progress)
        self.render_content(cr, canvas_w, canvas_h, t, ramped)

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        alpha = float(state.get("alpha", 0.0))
        self._last_rendered_alpha = alpha
        if alpha <= 0.001:
            return
        segment: SegmentState = state.get("segment", _EMPTY_STATE)
        if segment.is_empty:
            return

        from agents.studio_compositor.homage.rendering import active_package

        pkg = active_package()
        bg = pkg.palette.background
        accent = _palette_role(pkg, segment.ward_accent_role)
        bright = pkg.palette.bright
        muted = pkg.palette.muted

        # Panel dimensions — right side of screen, ~35% width
        margin = 48
        panel_w = int(canvas_w * 0.35)
        panel_h = min(canvas_h - margin * 2, 600)
        panel_x = canvas_w - panel_w - margin
        panel_y = margin

        # Background panel with subtle transparency
        cr.save()
        cr.set_source_rgba(bg[0], bg[1], bg[2], 0.75 * alpha)
        cr.rectangle(panel_x, panel_y, panel_w, panel_h)
        cr.fill()

        # Accent border — left edge only, like a sidebar indicator
        cr.set_source_rgba(accent[0], accent[1], accent[2], 0.85 * alpha)
        cr.rectangle(panel_x, panel_y, 4, panel_h)
        cr.fill()
        cr.restore()

        y_cursor = panel_y + 24
        inner_x = panel_x + 20
        max_text_w = panel_w - 40

        # Role label — small caps
        role_label = _role_label(segment.role)
        render_text(
            cr,
            TextStyle(
                text=role_label,
                font_description="Inter Bold 12",
                color_rgba=(accent[0], accent[1], accent[2], 0.9 * alpha),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.7 * alpha),
                outline_offsets=OUTLINE_OFFSETS_4,
                max_width_px=max(1, max_text_w),
            ),
            inner_x,
            y_cursor,
        )
        y_cursor += 24

        profile_bits: list[str] = []
        if segment.ward_profile:
            profile_bits.append(segment.ward_profile.replace("_", " "))
        source_count = len(segment.source_refs) or len(segment.asset_attributions)
        if source_count:
            profile_bits.append(f"{source_count} source{'s' if source_count != 1 else ''}")
        if profile_bits:
            render_text(
                cr,
                TextStyle(
                    text=" | ".join(profile_bits),
                    font_description="Inter 12",
                    color_rgba=(muted[0], muted[1], muted[2], 0.75 * alpha),
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.6 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max(1, max_text_w),
                ),
                inner_x,
                y_cursor,
            )
            y_cursor += 20

        # Topic header — large, bright
        topic = segment.topic or segment.narrative_beat or "—"
        # Truncate very long topics
        if len(topic) > 80:
            topic = topic[:77] + "..."
        render_text(
            cr,
            TextStyle(
                text=topic,
                font_description=_FONT_DESCRIPTION,
                color_rgba=(bright[0], bright[1], bright[2], 0.95 * alpha),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.85 * alpha),
                outline_offsets=OUTLINE_OFFSETS_4,
                max_width_px=max(1, max_text_w),
                wrap="word",
            ),
            inner_x,
            y_cursor,
        )
        y_cursor += 48

        # Divider line
        cr.save()
        cr.set_source_rgba(muted[0], muted[1], muted[2], 0.4 * alpha)
        cr.move_to(inner_x, y_cursor)
        cr.line_to(inner_x + max_text_w, y_cursor)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.restore()
        y_cursor += 16

        # Beat list
        current_idx = segment.current_beat_index
        for i, beat in enumerate(segment.segment_beats):
            if y_cursor > panel_y + panel_h - 70:
                break

            # Current beat — bright + arrow indicator
            if i == current_idx:
                marker = "▸"
                color = (bright[0], bright[1], bright[2], 0.95 * alpha)
            elif i < current_idx:
                # Completed — muted
                marker = "✓"
                color = (muted[0], muted[1], muted[2], 0.5 * alpha)
            else:
                # Upcoming — dim
                marker = "·"
                color = (muted[0], muted[1], muted[2], 0.7 * alpha)

            # Truncate long beat descriptions
            beat_text = beat if len(beat) <= 50 else beat[:47] + "..."
            render_text(
                cr,
                TextStyle(
                    text=f"{marker} {beat_text}",
                    font_description=_FONT_BEAT,
                    color_rgba=color,
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.6 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max(1, max_text_w),
                ),
                inner_x,
                y_cursor,
            )
            y_cursor += 24

        source_line = ""
        if segment.asset_attributions:
            source_line = segment.asset_attributions[0]
        elif segment.source_refs:
            source_line = segment.source_refs[0]
        if source_line:
            source_text = source_line if len(source_line) <= 72 else source_line[:69] + "..."
            render_text(
                cr,
                TextStyle(
                    text=f"source: {source_text}",
                    font_description="Inter 11",
                    color_rgba=(muted[0], muted[1], muted[2], 0.62 * alpha),
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.5 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max(1, max_text_w),
                ),
                inner_x,
                panel_y + panel_h - 50,
            )

        # Elapsed time at bottom
        if segment.started_at > 0:
            elapsed = time.time() - segment.started_at
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            planned_mins = int(segment.planned_duration_s // 60)
            time_text = f"{mins:02d}:{secs:02d} / {planned_mins}:00"
            render_text(
                cr,
                TextStyle(
                    text=time_text,
                    font_description="Inter 12",
                    color_rgba=(muted[0], muted[1], muted[2], 0.6 * alpha),
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.5 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max(1, max_text_w),
                ),
                inner_x,
                panel_y + panel_h - 28,
            )


__all__ = ["SegmentContentWard", "SegmentState", "SEGMENT_STATE_FILE"]
