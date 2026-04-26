"""DURF (Display Under Reflective Frame) — first full-frame HOMAGE ward.

Phase 2 (operator directive 2026-04-24T23:55Z, "BE my term content AS it IS"):
captures the LITERAL terminal content of running Claude-Code sessions via
Hyprland window capture (grim) and composites them dynamically into
1-4 panes based on the number of active sessions.

Auto-discovery: scan Hyprland clients, filter foot windows whose title
matches a session-name regex (alpha|beta|delta|epsilon), capture each
window's pixel region via ``grim -g``, load as Cairo ImageSurface,
composite into per-pane geometry.

Dynamic pane count:

* 0 sessions → ward suppressed (alpha=0; substrate bleeds through)
* 1 session  → full-frame 1920x1080
* 2 sessions → side-by-side 960x1080 each
* 3 sessions → 1 large left (960x1080) + 2 stacked right (960x540)
* 4 sessions → 2x2 grid (960x540 each)

Order (when present): delta TL → beta TR → alpha BL → epsilon BR per
operator screenshot 2026-04-24T23:50Z.

Design: ``docs/research/2026-04-24-durf-design.md``.

L-12 disclosure: Wayland window-capture is a pixel-capture path.
Mitigations:
  - Restricted to Claude-Code-titled foot windows (single-target, not desktop)
  - ``HAPAX_DURF_FORCE_ON`` env opt-in for inspection mode
  - Production gate (``desk_active`` + bytes + NOT consent-safe) suppresses
  - ``consent-safe`` egress mode hard-suppresses (poll AND render)
  - Per-capture OCR redaction (AUDIT-01) drops PNGs whose text matches
    high-confidence risk patterns (API keys, tokens, operator-home
    paths). Bypass via ``HAPAX_DURF_RAW=1`` for explicit inspection.
  - Operator manages on-screen content per existing terminal discipline

Phase 3 follow-ups (deferred): reflection layer, foreground rotation,
Bayesian-gate migration, per-region pixel masking (currently the
redaction primitive suppresses the whole pane on detect).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .durf_redaction import RedactionAction, redact_terminal_capture
from .homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(os.path.expanduser("~/projects/hapax-council/config/durf-panes.yaml"))
DEFAULT_FONT_DESCRIPTION = "Px437 IBM VGA 8x16 16"

_DESK_ACTIVE_PATH = Path(os.path.expanduser("~/.cache/hapax-daimonion/perception-state.json"))
_CONSENT_SAFE_PATH = Path("/dev/shm/hapax-compositor/consent-state.txt")
_CAPTURE_DIR = Path("/dev/shm/hapax-compositor/durf-captures")

_POLL_INTERVAL_S = 0.5  # 2 Hz Hyprland scan + capture
_ACTIVITY_WINDOW_S = 60.0
_EXIT_HYSTERESIS_S = 30.0

_ENTER_RAMP_MS = 400.0
_EXIT_RAMP_MS = 600.0

# Slow stage-share cycle (operator directive 2026-04-25): prominent → recede
# → repeat. NOT a pulse — long phases (~10s each) so it reads as breathing
# rather than blinking. Phase 3 replaces with Hapax-driven dynamic.
_CYCLE_FRONTED_ALPHA = 0.94
_CYCLE_RECEDED_ALPHA = 0.40
_CYCLE_FRONTED_S = 12.0  # prominent hold (viewer reads content)
_CYCLE_RECEDED_S = 10.0  # receded hold (other wards take stage)
_CYCLE_RAMP_S = 2.0  # cosine ease in/out between phases
_CYCLE_PERIOD_S = _CYCLE_FRONTED_S + _CYCLE_RAMP_S + _CYCLE_RECEDED_S + _CYCLE_RAMP_S

# Title-regex patterns the discovery routine matches against window titles.
# Operator's foot terminal titles include "✳ alpha", "⠐ beta" etc.
_SESSION_NAMES = ("alpha", "beta", "delta", "epsilon")

# Position-priority order for dynamic layout (delta first, then beta, alpha, epsilon)
# matches operator screenshot 2026-04-24T23:50Z.
_LAYOUT_ORDER = ("delta", "beta", "alpha", "epsilon")


def _discover_session_windows() -> list[dict[str, Any]]:
    """Run ``hyprctl clients -j`` and return windows matching session names.

    Returns list of {role, address, x, y, w, h} dicts in _LAYOUT_ORDER.
    """
    try:
        result = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if result.returncode != 0:
            return []
        clients = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    discovered: dict[str, dict[str, Any]] = {}
    for client in clients:
        title = str(client.get("title", "")).lower()
        for name in _SESSION_NAMES:
            if name in title and name not in discovered:
                at = client.get("at") or [0, 0]
                size = client.get("size") or [0, 0]
                discovered[name] = {
                    "role": name,
                    "address": client.get("address", ""),
                    "x": int(at[0]),
                    "y": int(at[1]),
                    "w": int(size[0]),
                    "h": int(size[1]),
                }
                break
    # Return in layout-order, only roles that were discovered
    return [discovered[role] for role in _LAYOUT_ORDER if role in discovered]


def _grim_capture(geom: dict[str, Any], output_path: Path) -> bool:
    """Capture window at ``geom`` to PNG. Returns True on success.

    Atomic write via tmp+rename so the render thread never sees a
    partially-written PNG. Without this, render thread reads of a
    half-written file produce per-tick load failures, manifesting as
    counter-clockwise pane blinking at the capture-rotation frequency
    (~500ms cycle through 4 panes).

    Service-context note: studio-compositor runs with WAYLAND_DISPLAY unset
    (per ``gl-env.conf`` drop-in: GST pipeline is X11). grim requires
    Wayland, so we inject WAYLAND_DISPLAY explicitly into the subprocess
    env without affecting the parent process env.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: write to .tmp then os.replace into final path
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        spec = f"{geom['x']},{geom['y']} {geom['w']}x{geom['h']}"
        env = os.environ.copy()
        env.setdefault("WAYLAND_DISPLAY", "wayland-1")
        env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
        result = subprocess.run(
            ["grim", "-g", spec, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=2.0,
            env=env,
        )
        if result.returncode != 0 or not tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
            return False
        # AUDIT-01: redact-or-suppress before publishing PNG to render.
        # Fail-closed: SUPPRESS *and* UNAVAILABLE both drop the capture.
        # Stale published path is also removed so a previously-clean
        # snapshot does not keep showing once content turns risky.
        redaction = redact_terminal_capture(tmp_path)
        if redaction.action != RedactionAction.CLEAN:
            log.info(
                "durf: capture suppressed by redaction (%s; %s)",
                redaction.action.value,
                redaction.detail,
            )
            tmp_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            return False
        os.replace(tmp_path, output_path)
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _desk_active() -> bool:
    """Read presence-state for desk_active signal (contact-mic derived)."""
    try:
        data = json.loads(_DESK_ACTIVE_PATH.read_text())
        activity = str(data.get("desk_activity", "idle")).lower()
        return activity in {"typing", "tapping", "drumming", "active"}
    except Exception:
        return False


def _consent_safe_active() -> bool:
    """Check consent-safe mode — if active, DURF must suppress."""
    try:
        return _CONSENT_SAFE_PATH.read_text().strip() == "safe"
    except Exception:
        return False


def _layout_for_count(n: int, canvas_w: int, canvas_h: int) -> list[tuple[int, int, int, int]]:
    """Return list of (x, y, w, h) rects for ``n`` panes in layout order."""
    if n <= 0:
        return []
    if n == 1:
        return [(0, 0, canvas_w, canvas_h)]
    if n == 2:
        # delta left, beta right
        return [
            (0, 0, canvas_w // 2, canvas_h),
            (canvas_w // 2, 0, canvas_w // 2, canvas_h),
        ]
    if n == 3:
        # delta large-left, beta top-right, alpha bottom-right
        return [
            (0, 0, canvas_w // 2, canvas_h),
            (canvas_w // 2, 0, canvas_w // 2, canvas_h // 2),
            (canvas_w // 2, canvas_h // 2, canvas_w // 2, canvas_h // 2),
        ]
    # n >= 4 → 2x2: delta TL, beta TR, alpha BL, epsilon BR
    half_w, half_h = canvas_w // 2, canvas_h // 2
    return [
        (0, 0, half_w, half_h),
        (half_w, 0, half_w, half_h),
        (0, half_h, half_w, half_h),
        (half_w, half_h, half_w, half_h),
    ]


class DURFCairoSource(HomageTransitionalSource):
    """Full-frame HOMAGE ward — Hyprland window capture of named sessions.

    Background thread polls Hyprland clients every 500ms, captures each
    matching window's pixel region via grim into PNGs in /dev/shm, and
    the render thread loads + composites them at 6Hz.
    """

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        font_description: str = DEFAULT_FONT_DESCRIPTION,
    ) -> None:
        super().__init__(source_id="durf")
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._font_description = font_description
        # Discovered sessions per tick
        self._discovered: list[dict[str, Any]] = []
        self._capture_paths: dict[str, Path] = {}
        self._discovered_lock = threading.Lock()
        # Gate state
        self._gate_on_since: float | None = None
        self._gate_off_since: float | None = None
        self._current_alpha: float = 0.0
        # Background polling thread
        self._stop_event = threading.Event()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="durf-window-poll", daemon=True
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        """Background — Hyprland scan + grim capture per session.

        AUDIT-01: refuses to capture when ``consent-state.txt = safe``
        (defense in depth — the render gate already suppresses, but
        the poll-time refusal also prevents pixel bytes from ever
        landing in ``/dev/shm/hapax-compositor/durf-captures``).
        """
        while not self._stop_event.is_set():
            try:
                if _consent_safe_active():
                    with self._discovered_lock:
                        self._discovered = []
                        self._capture_paths = {}
                else:
                    discovered = _discover_session_windows()
                    paths: dict[str, Path] = {}
                    for win in discovered:
                        role = win["role"]
                        out = _CAPTURE_DIR / f"{role}.png"
                        if _grim_capture(win, out):
                            paths[role] = out
                    with self._discovered_lock:
                        self._discovered = discovered
                        self._capture_paths = paths
            except Exception as e:
                log.warning("durf: poll cycle failed: %s", e, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def stop(self) -> None:
        self._stop_event.set()

    # ── Inclusion gate ───────────────────────────────────────────────

    def _gate_active(self) -> bool:
        """Gate: NOT consent-safe AND (force-on OR desk_active) AND >=1 session.

        HAPAX_DURF_FORCE_ON=1 bypasses desk_active for inspection.
        Zero discovered sessions → suppressed (operator: "ward is irrelevant").
        """
        if _consent_safe_active():
            return False
        with self._discovered_lock:
            n = len(self._discovered)
        if n == 0:
            return False
        if os.environ.get("HAPAX_DURF_FORCE_ON") == "1":
            return True
        return _desk_active()

    def _compute_alpha(self, now: float) -> float:
        """Gate + slow cycle.

        Operator directive 2026-04-25: 'It does need modulation, just not
        a pulse like that, it's too heavy handed and distracting' AND
        'It can't be static like that — it too needs to sometimes get out
        of the way at regular rates, not the only thing that matters.'

        Cycle (26s period):
          0 → 12 s : prominent  (alpha 0.94, viewer reads content)
         12 → 14 s : ramp down  (0.94 → 0.40 cosine ease)
         14 → 24 s : receded    (0.40, other wards take stage)
         24 → 26 s : ramp up    (0.40 → 0.94 cosine ease)

        When gate is False, the prominent ceiling is whatever the gate
        brought us to (entering ramp), and after hysteresis we ease all
        the way to 0. The cycle runs only inside the gate window.

        Phase 3+ replaces the deterministic cycle with a Hapax-driven
        dynamic from the ClaimEngine `valuable-development-activity`
        posterior + a stage-share signal from the director loop.
        """
        gate = self._gate_active()
        if not gate:
            if self._gate_off_since is None:
                self._gate_off_since = now
            if self._gate_on_since is not None and now - self._gate_off_since < _EXIT_HYSTERESIS_S:
                return self._current_alpha
            self._gate_on_since = None
            if now - (self._gate_off_since or now) < _EXIT_HYSTERESIS_S:
                return self._current_alpha
            dt_ms = (now - self._gate_off_since - _EXIT_HYSTERESIS_S) * 1000.0
            factor = max(0.0, 1.0 - dt_ms / _EXIT_RAMP_MS)
            return self._current_alpha * factor

        # Gate-on path
        self._gate_off_since = None
        if self._gate_on_since is None:
            self._gate_on_since = now
        gate_age = now - self._gate_on_since
        # Initial enter-ramp before cycle takes over
        if gate_age < (_ENTER_RAMP_MS / 1000.0):
            target = (gate_age * 1000.0 / _ENTER_RAMP_MS) * _CYCLE_FRONTED_ALPHA
            return max(self._current_alpha, target)

        # Slow cycle phases
        cycle_t = (gate_age - _ENTER_RAMP_MS / 1000.0) % _CYCLE_PERIOD_S
        if cycle_t < _CYCLE_FRONTED_S:
            return _CYCLE_FRONTED_ALPHA
        elif cycle_t < _CYCLE_FRONTED_S + _CYCLE_RAMP_S:
            # cosine ease 0.94 → 0.40
            ramp_t = (cycle_t - _CYCLE_FRONTED_S) / _CYCLE_RAMP_S
            import math

            ease = 0.5 - 0.5 * math.cos(math.pi * (1.0 - ramp_t))
            return _CYCLE_RECEDED_ALPHA + (_CYCLE_FRONTED_ALPHA - _CYCLE_RECEDED_ALPHA) * (
                1.0 - ease
            )
        elif cycle_t < _CYCLE_FRONTED_S + _CYCLE_RAMP_S + _CYCLE_RECEDED_S:
            return _CYCLE_RECEDED_ALPHA
        else:
            # cosine ease 0.40 → 0.94
            ramp_t = (cycle_t - _CYCLE_FRONTED_S - _CYCLE_RAMP_S - _CYCLE_RECEDED_S) / _CYCLE_RAMP_S
            import math

            ease = 0.5 - 0.5 * math.cos(math.pi * ramp_t)
            return _CYCLE_RECEDED_ALPHA + (_CYCLE_FRONTED_ALPHA - _CYCLE_RECEDED_ALPHA) * ease

    # ── CairoSource protocol ─────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        return {"alpha": self._compute_alpha(now), "now": now}

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:

        alpha = state.get("alpha", 0.0)
        self._current_alpha = alpha
        if alpha <= 0.001:
            return

        with self._discovered_lock:
            discovered = list(self._discovered)
            paths = dict(self._capture_paths)

        n = len(discovered)
        if n == 0:
            return  # operator: "ward is irrelevant" with 0 sessions

        # Atmospheric haze beneath panes
        cr.save()
        cr.set_source_rgba(0.02, 0.02, 0.05, 0.85 * alpha)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()
        cr.restore()

        rects = _layout_for_count(n, canvas_w, canvas_h)
        for win, rect in zip(discovered, rects, strict=False):
            role = win["role"]
            png_path = paths.get(role)
            self._render_pane(cr, rect, role, png_path, alpha)

    def _render_pane(
        self,
        cr: cairo.Context,
        rect: tuple[int, int, int, int],
        role: str,
        png_path: Path | None,
        alpha: float,
    ) -> None:
        """Render one pane: PNG capture composited + BitchX header."""
        import cairo as _cairo

        x, y, w, h = rect
        if png_path is None or not png_path.exists():
            self._render_empty_pane(cr, x, y, w, h, role, alpha)
            return

        try:
            img = _cairo.ImageSurface.create_from_png(str(png_path))
        except Exception:
            log.debug("durf: png load failed for %s", role, exc_info=True)
            self._render_empty_pane(cr, x, y, w, h, role, alpha)
            return

        img_w = img.get_width()
        img_h = img.get_height()
        if img_w <= 0 or img_h <= 0:
            return

        # Scale-to-fit preserving aspect ratio
        scale = min(w / img_w, h / img_h)
        scaled_w = img_w * scale
        scaled_h = img_h * scale
        offset_x = x + (w - scaled_w) / 2
        offset_y = y + (h - scaled_h) / 2

        cr.save()
        cr.translate(offset_x, offset_y)
        cr.scale(scale, scale)
        cr.set_source_surface(img, 0, 0)
        cr.paint_with_alpha(alpha)
        cr.restore()

        # Crisp border
        from .homage.rendering import active_package

        pkg = active_package()
        border = pkg.palette.bright
        cr.save()
        cr.set_line_width(2.0)
        cr.set_source_rgba(border[0], border[1], border[2], alpha)
        cr.rectangle(x, y, w, h)
        cr.stroke()
        cr.restore()

    def _render_empty_pane(
        self,
        cr: cairo.Context,
        x: int,
        y: int,
        w: int,
        h: int,
        role: str,
        alpha: float,
    ) -> None:
        """Empty-pane placeholder when capture isn't available."""
        from .homage.rendering import active_package

        pkg = active_package()
        bg = pkg.palette.background
        cr.save()
        cr.set_source_rgba(bg[0], bg[1], bg[2], bg[3] * alpha)
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_line_width(1.0)
        muted = pkg.palette.muted
        cr.set_source_rgba(muted[0], muted[1], muted[2], alpha)
        cr.rectangle(x, y, w, h)
        cr.stroke()
        cr.restore()


__all__ = ["DURFCairoSource"]
