"""``CodingActivityReveal`` — DURF lifted into the activity-reveal-ward family.

Per cc-task ``activity-reveal-ward-p1-durf-migration``. The legacy
``DURFCairoSource`` class is preserved as a module-level alias so
existing layout-JSON declarations + import paths keep working without
any caller-side change. The class is renamed and re-homed here so the
P0 ``ActivityRevealMixin`` can govern visibility, ceiling, and
co-existence suppression family-wide as M8 / Polyend / Steam-Deck
variants ship in P2-P5.

Key migration moves vs. the legacy ``durf_source.DURFCairoSource``:

* **Multiple inheritance** — the class now inherits both
  ``HomageTransitionalSource`` (FSM-aware Cairo source) AND
  ``ActivityRevealMixin`` (claim contract + ceiling + suppression
  declarative slot). Both parents have non-cooperative ``__init__``;
  this class's ``__init__`` calls each explicitly so each parent's
  state is fully populated.
* **FSM ramp ownership** — the FSM in ``HomageTransitionalSource`` is
  the canonical alpha-ramp owner. Gate transitions (visible-panes-exist
  and consent-safe-not-active) drive ``apply_transition()``; the FSM's
  built-in ``_progress(now)`` and the ``render_entering`` /
  ``render_exiting`` hooks own the alpha envelope. ``entering_duration_s
  =0.4`` and ``exiting_duration_s=0.6`` match the legacy
  ``_ENTER_RAMP_MS`` / ``_EXIT_RAMP_MS``.
* **Co-existence suppression** — ``SUPPRESS_WHEN_ACTIVE = frozenset(
  {"album", "gem", "grounding_provenance_ticker"})``. When the gate is
  ON, the poll cycle writes ``visible=false`` to those wards'
  ``ward-properties.json`` entries with a short TTL; the next poll
  refreshes the TTL while the gate stays ON, so the suppression
  decays naturally when DURF exits. Fail-open: a write failure is
  logged at debug and never breaks the poll cycle.
* **Aesthetic preservation** — redaction (``redact_terminal_lines``,
  ``sanitize_terminal_lines``, ``RISK_PATTERNS``), pane layout
  (``_layout_for_count``), text rendering (``_render_text_pane``),
  capture path (``capture_tmux_text``, ``CodexPaneRegistry``), and the
  WCS row builder (``build_wcs_row``) all live in ``durf_source`` and
  are imported here. DURF still looks identical post-migration.

Spec: ``hapax-research/specs/2026-05-01-activity-reveal-ward-family-spec.md``
§3.1.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Helpers from durf_source — kept as module-attribute references rather
# than imported names so test fixtures that monkeypatch
# ``durf_source._consent_safe_active`` (and similar) reach the code
# path here too. Without the deferred reference, my class would close
# over the original function objects at import time and ignore the
# monkeypatches the existing tests set up.
from agents.studio_compositor import durf_source as _durf_module
from agents.studio_compositor.activity_reveal_ward import (
    DEFAULT_POLL_INTERVAL_S as MIXIN_POLL_INTERVAL_S,
)
from agents.studio_compositor.activity_reveal_ward import (
    ActivityRevealMixin,
)
from agents.studio_compositor.durf_source import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_FONT_DESCRIPTION,
    CodexPaneRegistry,
    DURFPaneState,
    DURFSourceSnapshot,
    _layout_for_count,
    _line_color,
    build_wcs_row,
)
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

# Ramp durations match the legacy ``durf_source._ENTER_RAMP_MS`` (400 ms)
# and ``_EXIT_RAMP_MS`` (600 ms) so the visible alpha envelope on the
# broadcast is bit-identical to pre-migration. Exit hysteresis matches
# legacy ``_EXIT_HYSTERESIS_S`` — gate must be off for this many seconds
# before the FSM exit transition fires, so a brief flicker of "no
# visible panes" doesn't strobe the surface.
_ENTER_RAMP_S: float = 0.4
_EXIT_RAMP_S: float = 0.6
_EXIT_HYSTERESIS_S: float = 4.0

# Fronted alpha — the steady-state HOLD alpha for DURF. Matches legacy
# ``durf_source._FRONTED_ALPHA``.
_FRONTED_ALPHA: float = 0.92

# Poll cadence. Matches legacy ``durf_source._POLL_INTERVAL_S`` so the
# tmux capture rhythm is unchanged.
_POLL_INTERVAL_S: float = 0.5

# Suppression TTL — refreshed each poll cycle while the gate stays ON.
# Two poll intervals so a single missed refresh does not drop the
# suppression mid-flight.
_SUPPRESSION_TTL_S: float = _POLL_INTERVAL_S * 4.0


class CodingActivityReveal(HomageTransitionalSource, ActivityRevealMixin):
    """Full-frame HOMAGE ward for bounded Codex tmux text panes.

    Inherits from both ``HomageTransitionalSource`` (FSM lifecycle, alpha
    ramp via ``_progress(now)``) and ``ActivityRevealMixin`` (claim
    contract, visibility ceiling, co-existence suppression slot).

    The mixin's poll thread is intentionally NOT started — DURF runs its
    own poll thread that drives both the WCS snapshot and the FSM
    transitions, so the mixin's claim assembly is folded into that
    single loop instead of running on a separate cadence.
    """

    # ── ActivityRevealMixin contract ────────────────────────────────
    WARD_ID = "durf"
    SOURCE_KIND = "cairo"
    DEFAULT_HYSTERESIS_S = 30.0
    VISIBILITY_CEILING_PCT = 0.15
    # Co-existence suppression — when DURF's gate is ON, write
    # ``visible=false`` to these wards' ``ward-properties.json`` entries
    # so the surface composites cleanly. P3 will retrofit the same
    # declaration to the family pool.
    SUPPRESS_WHEN_ACTIVE = frozenset({"album", "gem", "grounding_provenance_ticker"})

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        font_description: str = DEFAULT_FONT_DESCRIPTION,
        registry: CodexPaneRegistry | None = None,
        start_thread: bool = True,
    ) -> None:
        # Both parents have non-cooperative ``__init__`` (neither calls
        # ``super().__init__()``); call each one explicitly so the child
        # ends up with both parents' state.
        HomageTransitionalSource.__init__(
            self,
            source_id="durf",
            entering_duration_s=_ENTER_RAMP_S,
            exiting_duration_s=_EXIT_RAMP_S,
        )
        # Mixin runs its own poll thread by default — we suppress that
        # because DURF's poll thread drives the entire ward lifecycle
        # (WCS snapshot + FSM transitions + mixin claim) on one cadence.
        ActivityRevealMixin.__init__(self, start_poll_thread=False)

        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._font_description = font_description
        self._registry = registry or CodexPaneRegistry(config_path=self._config_path)
        self._snapshot = DURFSourceSnapshot(
            panes=(),
            captured_at=time.time(),
            wcs_row=build_wcs_row((), now=time.time(), egress_allowed=False),
        )
        self._snapshot_lock = threading.Lock()

        # Gate hysteresis tracker — matches legacy ``_gate_off_since``.
        # Tracks when the gate first went OFF so we can debounce the
        # exit transition by ``_EXIT_HYSTERESIS_S`` before firing it.
        self._gate_off_pending_since: float | None = None
        # Records the last computed alpha — used by ``state()`` so a
        # caller polling state without ticking the FSM still gets a
        # plausible alpha value (matches legacy behaviour).
        self._last_rendered_alpha: float = 0.0

        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="durf-codex-text-poll",
                daemon=True,
            )
            self._poll_thread.start()

    # ── Lifecycle ────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("durf: poll cycle failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def _poll_once(self, *, now: float | None = None) -> DURFSourceSnapshot:
        """One poll cycle — capture panes, drive FSM, write suppression, refresh claim."""
        ts = time.time() if now is None else now
        lanes, max_visible = self._registry.discover_lanes()
        panes: list[DURFPaneState] = []
        egress_allowed = True
        if _durf_module._consent_safe_active():
            egress_allowed = False
            panes = [_durf_module._suppressed_lane(lane, "consent_safe", now=ts) for lane in lanes]
        elif _durf_module._unsafe_public_bypass_active():
            egress_allowed = False
            panes = [
                _durf_module._suppressed_lane(lane, "unsafe_public_bypass", now=ts)
                for lane in lanes
            ]
        else:
            selected, overflow = _durf_module._select_lanes(lanes, max_visible)
            panes.extend(_durf_module._pane_state_from_capture(lane, now=ts) for lane in selected)
            panes.extend(
                _durf_module._suppressed_lane(lane, "not_selected", now=ts) for lane in overflow
            )
            configured_ids = {lane.lane_id for lane in selected + overflow}
            panes.extend(
                _durf_module._suppressed_lane(lane, "lane_ineligible", now=ts)
                for lane in lanes
                if lane.lane_id not in configured_ids
            )
        row = build_wcs_row(
            tuple(panes), now=ts, egress_allowed=egress_allowed, max_visible=max_visible
        )
        snapshot = DURFSourceSnapshot(panes=tuple(panes), captured_at=ts, wcs_row=row)
        with self._snapshot_lock:
            self._snapshot = snapshot

        # Gate-driven FSM + suppression. Both consult the *snapshot* the
        # poll just produced, not a live re-read, so one poll = one
        # consistent decision.
        gate = self._gate_active_from_snapshot(snapshot)
        self._maybe_drive_fsm(gate, now=time.monotonic())
        self._update_suppression(gate)
        # Refresh the mixin's claim from the same poll. The mixin's
        # poll thread is suppressed in __init__ so we drive it here
        # explicitly — one cadence, one decision.
        try:
            self.poll_once(now=time.monotonic())
        except Exception:
            log.debug("durf: mixin poll_once failed", exc_info=True)
        return snapshot

    def stop(self) -> None:
        """Idempotent shutdown — both the DURF poll thread and the mixin teardown."""
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
        # ActivityRevealMixin.stop() is idempotent; the mixin's poll
        # thread was never started but its bookkeeping still gets a
        # clean teardown for symmetry with M8 / future variants.
        try:
            ActivityRevealMixin.stop(self)
        except Exception:
            log.debug("durf: mixin stop failed", exc_info=True)

    # ── Gate detection ───────────────────────────────────────────────

    def _gate_active_from_snapshot(self, snapshot: DURFSourceSnapshot) -> bool:
        """Compute gate state from the supplied snapshot.

        Mirrors the legacy ``_gate_active`` semantics but takes a
        snapshot argument so the poll's gate decision and FSM-drive
        decision read the same data without re-acquiring the snapshot
        lock between calls.

        Also returns True when segment-playback.json exists — the DURF
        should be visible during programme narration even if no tmux
        panes are active.
        """
        if _durf_module._consent_safe_active() or _durf_module._unsafe_public_bypass_active():
            return False
        if self._SEGMENT_SHM_PATH.exists():
            return True
        return any(pane.visible for pane in snapshot.panes)

    def _gate_active(self) -> bool:
        """Live gate reader — used by ``state()`` and tests."""
        if _durf_module._consent_safe_active() or _durf_module._unsafe_public_bypass_active():
            return False
        if self._SEGMENT_SHM_PATH.exists():
            return True
        with self._snapshot_lock:
            return any(pane.visible for pane in self._snapshot.panes)

    # ── FSM driver — lifts _compute_alpha into HomageTransitionalSource ──

    def _maybe_drive_fsm(self, gate: bool, *, now: float) -> None:
        """Drive ``apply_transition`` based on gate-state changes.

        On gate ON: clear the off-debounce; if FSM is ABSENT or
        EXITING, fire ``ticker-scroll-in`` so the FSM advances to
        ENTERING and starts the alpha ramp.

        On gate OFF: start (or continue) the exit-hysteresis timer; if
        the gate has been off for ``_EXIT_HYSTERESIS_S``, fire
        ``ticker-scroll-out`` so the FSM advances to EXITING and the
        alpha ramps down.
        """
        if gate:
            self._gate_off_pending_since = None
            if self._state in (TransitionState.ABSENT, TransitionState.EXITING):
                try:
                    self.apply_transition("ticker-scroll-in", now=now)
                except Exception:
                    log.debug("durf: FSM enter transition failed", exc_info=True)
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
                self.apply_transition("ticker-scroll-out", now=now)
            except Exception:
                log.debug("durf: FSM exit transition failed", exc_info=True)

    # ── Co-existence suppression ─────────────────────────────────────

    def _update_suppression(self, gate: bool) -> None:
        """Write ``visible=false`` to ``SUPPRESS_WHEN_ACTIVE`` wards.

        Refreshed each poll while the gate stays ON; when the gate
        flips OFF, the TTL expires naturally and the suppressed wards
        return to default ``visible=true``. Late import to avoid a
        circular at module load (ward_properties imports
        text_render which is also pulled in here).
        """
        if not gate:
            return
        try:
            from agents.studio_compositor.ward_properties import (
                WardProperties,
                set_ward_properties,
            )
        except Exception:
            log.debug("durf: suppression imports failed", exc_info=True)
            return
        for ward_id in type(self).SUPPRESS_WHEN_ACTIVE:
            try:
                set_ward_properties(
                    ward_id,
                    WardProperties(visible=False),
                    _SUPPRESSION_TTL_S,
                )
            except Exception:
                log.debug("durf: suppression write failed for %s", ward_id, exc_info=True)

    # ── ActivityRevealMixin abstracts ────────────────────────────────

    def _compute_claim_score(self) -> float:
        """Recruitment score in [0.0, 1.0] from visible-pane count.

        Maps 0..4 visible panes to 0.0..1.0. Caps at 1.0 if the
        registry ever returns more than 4 (defensive — the registry's
        ``max_visible`` already clamps to 4 in practice).
        """
        with self._snapshot_lock:
            visible = sum(1 for p in self._snapshot.panes if p.visible)
        return max(0.0, min(1.0, visible / 4.0))

    def _want_visible(self) -> bool:
        return self._gate_active()

    def _mandatory_invisible(self) -> bool:
        return _durf_module._consent_safe_active() or _durf_module._unsafe_public_bypass_active()

    def _claim_source_refs(self) -> tuple[str, ...]:
        with self._snapshot_lock:
            return tuple(f"durf:lane:{p.lane_id}" for p in self._snapshot.panes if p.visible)

    def _describe_source_registration(self) -> dict[str, Any]:
        return {
            "id": "durf",
            "class_name": "CodingActivityReveal",
            "kind": "cairo",
            "alias": "DURFCairoSource",
        }

    # ── Alpha + state ────────────────────────────────────────────────

    def _compute_alpha(self, now: float) -> float:
        """FSM-driven alpha computation.

        Returns ``_FRONTED_ALPHA`` in HOLD; a linearly-ramped fraction
        of it in ENTERING / EXITING; 0.0 in ABSENT. The FSM's
        ``_progress(now)`` already provides the [0.0, 1.0] envelope so
        we just multiply.

        Backwards-compat: the legacy ``DURFCairoSource._compute_alpha``
        contract returned alpha at any time. Tests that drive
        ``state()`` without first ticking the FSM rely on the gate
        state alone, so we additionally honour the gate-direct path
        when the FSM is still in its initial HOLD-by-default state and
        the gate has never gone ON. That's the cold-start case and
        matches the legacy first-poll behaviour.
        """
        gate = self._gate_active()
        state_now = self._state
        if state_now is TransitionState.ABSENT:
            return 0.0
        if state_now is TransitionState.HOLD:
            # If the gate is ON, render at full fronted alpha. If the
            # gate is OFF but the FSM is still HOLD (mid-hysteresis
            # debounce or never-transitioned), reflect the gate state
            # so callers polling state() during the debounce window
            # get a plausible alpha matching legacy behaviour.
            return _FRONTED_ALPHA if gate else 0.0
        progress = self._progress(now=now)
        if state_now is TransitionState.ENTERING:
            return _FRONTED_ALPHA * progress
        # EXITING
        return _FRONTED_ALPHA * (1.0 - progress)

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._snapshot_lock:
            snapshot = self._snapshot
        alpha = self._compute_alpha(now)
        self._last_rendered_alpha = alpha
        return {
            "alpha": alpha,
            "now": now,
            "panes": [pane.__dict__ for pane in snapshot.panes],
            "wcs": snapshot.wcs_row,
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
        """Multiply DURF's content alpha by FSM entering progress."""
        ramped_state = dict(state)
        base = float(state.get("alpha", _FRONTED_ALPHA))
        ramped_state["alpha"] = base * progress
        self.render_content(cr, canvas_w, canvas_h, t, ramped_state)

    def render_exiting(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
        progress: float,
    ) -> None:
        """Multiply DURF's content alpha by (1 - exiting progress)."""
        ramped_state = dict(state)
        base = float(state.get("alpha", _FRONTED_ALPHA))
        ramped_state["alpha"] = base * (1.0 - progress)
        self.render_content(cr, canvas_w, canvas_h, t, ramped_state)

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

        # ── Segment mode: display programme content instead of tmux ──
        seg = self._read_segment_state()
        if seg is not None:
            self._render_segment_content(cr, canvas_w, canvas_h, alpha, seg, t)
            return

        # ── Default: tmux pane display ──
        with self._snapshot_lock:
            panes = [pane for pane in self._snapshot.panes if pane.visible]
        if not panes:
            return

        cr.save()
        cr.set_source_rgba(0.02, 0.02, 0.05, 0.82 * alpha)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()
        cr.restore()

        rects = _layout_for_count(len(panes), canvas_w, canvas_h)
        for pane, rect in zip(panes, rects, strict=False):
            self._render_text_pane(cr, rect, pane, alpha)

    # ── Segment state reader ─────────────────────────────────────────

    _SEGMENT_SHM_PATH = Path("/dev/shm/hapax-compositor/segment-playback.json")
    _seg_cache: dict[str, Any] | None = None
    _seg_cache_mtime: float = 0.0

    def _read_segment_state(self) -> dict[str, Any] | None:
        """Read segment-playback.json from SHM with mtime-based caching."""
        try:
            st = self._SEGMENT_SHM_PATH.stat()
            if st.st_mtime_ns == self._seg_cache_mtime and self._seg_cache is not None:
                return self._seg_cache
            import json

            data = json.loads(self._SEGMENT_SHM_PATH.read_text(encoding="utf-8"))
            self._seg_cache = data
            self._seg_cache_mtime = st.st_mtime_ns
            return data
        except FileNotFoundError:
            self._seg_cache = None
            return None
        except Exception:
            return self._seg_cache  # stale is better than nothing

    # ── Segment content renderer ─────────────────────────────────────

    def _render_segment_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        alpha: float,
        seg: dict[str, Any],
        t: float,
    ) -> None:
        """Render the current segment block: text + asset metadata."""
        from agents.studio_compositor.homage.rendering import active_package

        pkg = active_package()
        bright = pkg.palette.bright
        muted = pkg.palette.muted
        accent = pkg.palette.accent_cyan

        # Background scrim
        cr.save()
        cr.set_source_rgba(0.02, 0.02, 0.05, 0.78 * alpha)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()
        cr.restore()

        margin = 48
        text_x = margin
        text_y = margin + 20
        max_w = max(1, canvas_w - margin * 2)

        # Header: programme role + block progress
        block_idx = seg.get("block_index", 0)
        block_count = seg.get("block_count", 1)
        role = seg.get("role", "")
        progress_text = f"▸ {role.upper().replace('_', ' ')} · {block_idx + 1}/{block_count}"
        header_style = TextStyle(
            text=progress_text,
            font_description=self._font_description,
            color_rgba=(accent[0], accent[1], accent[2], 0.90 * alpha),
            outline_color_rgba=(0.0, 0.0, 0.0, 0.90 * alpha),
            outline_offsets=OUTLINE_OFFSETS_4,
            max_width_px=max_w,
            wrap="word",
        )
        render_text(cr, header_style, text_x, text_y)
        text_y += 36

        # Asset info (if present)
        assets = seg.get("assets", [])
        for asset in assets[:2]:
            kind = asset.get("kind", "text")
            caption = asset.get("caption") or asset.get("url") or ""
            if caption:
                asset_label = f"  [{kind.upper()}] {caption[:80]}"
                asset_style = TextStyle(
                    text=asset_label,
                    font_description=self._font_description,
                    color_rgba=(muted[0], muted[1], muted[2], 0.72 * alpha),
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.80 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max_w,
                    wrap="char",
                )
                render_text(cr, asset_style, text_x, text_y)
                text_y += 22

        # Divider line
        text_y += 8
        cr.save()
        cr.set_source_rgba(bright[0], bright[1], bright[2], 0.35 * alpha)
        cr.move_to(margin, text_y)
        cr.line_to(canvas_w - margin, text_y)
        cr.set_line_width(1.5)
        cr.stroke()
        cr.restore()
        text_y += 16

        # Block text — the narration content
        block_text = seg.get("block_text", "")
        if block_text:
            # Split into sentences for readable display
            line_h = 22
            max_lines = max(1, int((canvas_h - text_y - margin) / line_h))
            # Wrap at roughly 90 chars per line
            words = block_text.split()
            lines: list[str] = []
            current = ""
            for word in words:
                test = f"{current} {word}".strip()
                if len(test) > 90:
                    if current:
                        lines.append(current)
                    current = word
                else:
                    current = test
            if current:
                lines.append(current)

            for line in lines[:max_lines]:
                line_style = TextStyle(
                    text=line,
                    font_description=self._font_description,
                    color_rgba=(bright[0], bright[1], bright[2], 0.88 * alpha),
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.82 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max_w,
                    wrap="word",
                    line_spacing=0.95,
                )
                render_text(cr, line_style, text_x, text_y)
                text_y += line_h
                if text_y > canvas_h - margin:
                    break

    def _render_text_pane(
        self,
        cr: cairo.Context,
        rect: tuple[int, int, int, int],
        pane: DURFPaneState,
        alpha: float,
    ) -> None:
        from agents.studio_compositor.homage.rendering import active_package

        x, y, w, h = rect
        pkg = active_package()
        bg = pkg.palette.background
        muted = pkg.palette.muted
        bright = pkg.palette.bright

        cr.save()
        cr.set_source_rgba(bg[0], bg[1], bg[2], min(bg[3], 0.88) * alpha)
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_line_width(2.0)
        cr.set_source_rgba(bright[0], bright[1], bright[2], 0.65 * alpha)
        cr.rectangle(x, y, w, h)
        cr.stroke()
        cr.restore()

        marker_style = TextStyle(
            text=f">>> {pane.glyph}",
            font_description=self._font_description,
            color_rgba=(muted[0], muted[1], muted[2], 0.78 * alpha),
            outline_color_rgba=(0.0, 0.0, 0.0, 0.86 * alpha),
            outline_offsets=OUTLINE_OFFSETS_4,
            max_width_px=max(1, w - 36),
            wrap="char",
        )
        render_text(cr, marker_style, x + 18, y + 14)

        line_y = y + 48
        line_h = 19
        max_lines = max(1, int((h - 64) / line_h))
        for line in pane.lines[-max_lines:]:
            style = TextStyle(
                text=line or " ",
                font_description=self._font_description,
                color_rgba=_line_color(line),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.80 * alpha),
                outline_offsets=OUTLINE_OFFSETS_4,
                max_width_px=max(1, w - 36),
                wrap="char",
                line_spacing=0.92,
            )
            render_text(cr, style, x + 18, line_y)
            line_y += line_h
            if line_y > y + h - line_h:
                break


# Suppress unused-import warning for MIXIN_POLL_INTERVAL_S — re-exported
# in case a future PR wants to expose the mixin's own poll cadence (M8
# reads its own SHM file at a different cadence, so the mixin's value
# diverges from DURF's ``_POLL_INTERVAL_S``). Kept here for symmetry.
_REEXPORTED_MIXIN_POLL_INTERVAL_S = MIXIN_POLL_INTERVAL_S


__all__ = ["CodingActivityReveal"]
