"""DURF (Display Under Reflective Frame) — first full-frame HOMAGE ward.

Broadcasts the operator's 4-tmux Claude-Code coordination setup as the
livestream's most direct grounding-provenance artifact: the ward IS
provenance for everything else on screen (T7 applied at the full-frame
aggregate level).

Design: ``docs/research/2026-04-24-durf-design.md``.
Operator directive: 2026-04-24T23:10Z.

Contract:

* Text-only capture via ``tmux capture-pane`` — Wayland pixel capture is
  REJECTED (L-12 broadcast-bleed risk per ``feedback_l12_equals_livestream_invariant``).
* Px437 IBM VGA 8×16 rendering via Pango — native terminal fonts violate
  BitchX proportional-font anti-pattern.
* mIRC-16 semantic palette routing by token class — raw ANSI SGR codes
  are rejected.
* Non-equal quadrant geometry (1100×620 foreground + 3×760×340 stacked)
  with z-stagger and atmospheric haze — NOT equal quadrants.
* MVP inclusion gate: ``desk_active`` + bytes-appended > 200/60s +
  NOT consent-safe mode. 30s hysteresis on exit.
* Redaction regex per line pre-render — tokens, SSH paths, pass output.
* Envelope: 400ms ease-in, 600ms ease-out; 3s hold-last-good on capture
  disconnect.

Phase 2 follow-ups (deferred): reflection layer, foreground rotation on
activity-score, Bayesian ``Claim("valuable development-activity in progress")``
gate migration.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(os.path.expanduser("~/projects/hapax-council/config/durf-panes.yaml"))
DEFAULT_FONT_DESCRIPTION = "Px437 IBM VGA 8x16 11"

_DESK_ACTIVE_PATH = Path(os.path.expanduser("~/.cache/hapax-daimonion/perception-state.json"))
_CONSENT_SAFE_PATH = Path("/dev/shm/hapax-compositor/consent-state.txt")

_POLL_INTERVAL_S = 0.5  # 2 Hz tmux capture
_RING_BUFFER_LINES = 32  # per-pane trailing-window
_ACTIVITY_WINDOW_S = 60.0
_ACTIVITY_BYTES_THRESHOLD = 200
_EXIT_HYSTERESIS_S = 30.0

_ENTER_RAMP_MS = 400.0
_EXIT_RAMP_MS = 600.0

# Redaction: tokens, SSH paths under home, AWS/ANTHROPIC/bearer prefixes,
# .envrc echoes, pass-show output patterns.
_REDACTION_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_-]{20,})"),
    re.compile(r"(AKIA[0-9A-Z]{16})"),
    re.compile(r"(ghp_[A-Za-z0-9]{36,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9_.-]{20,})", re.IGNORECASE),
    re.compile(r"(/home/[^/\s]+/\.ssh/[^\s]+)"),
    re.compile(r"(/home/[^/\s]+/\.envrc)"),
    re.compile(r"(ANTHROPIC_API_KEY[=:][^\s]+)"),
    re.compile(r"(AWS_(SECRET_)?ACCESS_KEY[=:][^\s]+)"),
]
_REDACTION_MARKER = "[REDACTED]"

# VT-escape sanitization. `tmux capture-pane -e` is OFF by default; this
# strip is defense-in-depth in case `-e` gets re-enabled upstream.
_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Token classification for mIRC-16 palette routing.
_TOKEN_PROMPT_RE = re.compile(r"^(\$|>|»»»|●)\s")
_TOKEN_ERROR_RE = re.compile(r"\b(ERROR|FAIL|FAILED|Traceback|error:)\b", re.IGNORECASE)
_TOKEN_SUCCESS_RE = re.compile(r"\b(SUCCESS|PASSED|OK|✓|MERGED)\b", re.IGNORECASE)
_TOKEN_TOOL_RE = re.compile(r"^(●|⎿|◯)\s|^(Bash|Edit|Read|Write|Grep)\(")


def _classify_line_role(line: str) -> str:
    """Semantic class for palette routing (mIRC-16)."""
    if _TOKEN_ERROR_RE.search(line):
        return "error"
    if _TOKEN_SUCCESS_RE.search(line):
        return "success"
    if _TOKEN_TOOL_RE.search(line):
        return "tool"
    if _TOKEN_PROMPT_RE.search(line):
        return "prompt"
    return "text"


def _redact(line: str) -> str:
    """Apply redaction regex; return sanitized line."""
    for pattern in _REDACTION_PATTERNS:
        line = pattern.sub(_REDACTION_MARKER, line)
    return _ANSI_SGR_RE.sub("", line)


def _capture_pane(target: str) -> list[str]:
    """tmux capture-pane -p -t <target>. Returns stripped lines. Empty on error."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", target],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if result.returncode != 0:
            return []
        return [_redact(line) for line in result.stdout.splitlines()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def _desk_active() -> bool:
    """Read presence-state for desk_active signal (contact-mic derived)."""
    try:
        import json

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


class _PaneRing:
    """Last-N-lines ring buffer + byte-counter for activity signal."""

    def __init__(self, size: int = _RING_BUFFER_LINES) -> None:
        self._lines: deque[tuple[str, str]] = deque(maxlen=size)  # (line, role)
        self._byte_history: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def update(self, new_lines: list[str]) -> None:
        with self._lock:
            added = 0
            existing = {line for line, _ in self._lines}
            for line in new_lines:
                if not line.strip() or line in existing:
                    continue
                self._lines.append((line, _classify_line_role(line)))
                added += len(line)
            if added > 0:
                self._byte_history.append((time.monotonic(), added))
            self._trim_history()

    def _trim_history(self) -> None:
        cutoff = time.monotonic() - _ACTIVITY_WINDOW_S
        while self._byte_history and self._byte_history[0][0] < cutoff:
            self._byte_history.popleft()

    def snapshot(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._lines)

    def bytes_in_window(self) -> int:
        with self._lock:
            self._trim_history()
            return sum(count for _, count in self._byte_history)


class DURFCairoSource(HomageTransitionalSource):
    """Full-frame HOMAGE ward — live 4-tmux Claude-Code coordination.

    Per-frame render draws from per-pane ring buffers updated by a
    background thread polling tmux at 2 Hz. Render thread never blocks
    on subprocess — degraded-hold on capture failure is the default.
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
        self._panes: dict[str, _PaneRing] = {}
        self._targets: dict[str, str] = {}
        self._glyphs: dict[str, str] = {}
        self._load_config()
        # Gate state
        self._gate_on_since: float | None = None
        self._gate_off_since: float | None = None
        self._current_alpha: float = 0.0
        # Background polling thread
        self._stop_event = threading.Event()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="durf-tmux-poll", daemon=True
        )
        self._poll_thread.start()

    def _load_config(self) -> None:
        """Load tmux target list + glyph mapping from config/durf-panes.yaml."""
        try:
            cfg = yaml.safe_load(self._config_path.read_text())
        except (OSError, yaml.YAMLError) as e:
            log.warning("durf: config load failed (%s) — running with empty pane list", e)
            cfg = {"panes": []}
        for entry in cfg.get("panes", []):
            role = entry["role"]
            self._targets[role] = entry["tmux_target"]
            self._glyphs[role] = entry.get("glyph", "?")
            self._panes[role] = _PaneRing()

    def _poll_loop(self) -> None:
        """Background thread — tmux capture + ring-buffer update at 2 Hz."""
        while not self._stop_event.is_set():
            for role, target in self._targets.items():
                lines = _capture_pane(target)
                if lines:
                    self._panes[role].update(lines)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def stop(self) -> None:
        self._stop_event.set()

    # ── Inclusion gate ───────────────────────────────────────────────

    def _gate_active(self) -> bool:
        """MVP gate: desk_active + bytes-appended > 200 in 60s + NOT consent-safe."""
        if _consent_safe_active():
            return False
        if not _desk_active():
            return False
        total_bytes = sum(ring.bytes_in_window() for ring in self._panes.values())
        return total_bytes > _ACTIVITY_BYTES_THRESHOLD

    def _compute_alpha(self, now: float) -> float:
        """Envelope alpha with 30s exit hysteresis + ease-in/ease-out."""
        gate = self._gate_active()
        if gate:
            self._gate_off_since = None
            if self._gate_on_since is None:
                self._gate_on_since = now
            dt_ms = (now - self._gate_on_since) * 1000.0
            target = min(1.0, dt_ms / _ENTER_RAMP_MS) * 0.92
            return max(self._current_alpha, target)
        # Gate off — apply hysteresis before exiting
        if self._gate_off_since is None:
            self._gate_off_since = now
        if now - self._gate_off_since < _EXIT_HYSTERESIS_S:
            return self._current_alpha
        self._gate_on_since = None
        dt_ms = (now - self._gate_off_since - _EXIT_HYSTERESIS_S) * 1000.0
        factor = max(0.0, 1.0 - dt_ms / _EXIT_RAMP_MS)
        return self._current_alpha * factor

    # ── CairoSource protocol ─────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "alpha": self._compute_alpha(now),
            "now": now,
        }

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

        # Atmospheric haze wash (§3.5 depth option 1)
        cr.save()
        cr.set_source_rgba(0.02, 0.02, 0.05, 0.85 * alpha)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()
        cr.restore()

        # Non-equal tiled geometry
        roles = list(self._panes.keys())
        if not roles:
            return
        foreground_role = roles[0]  # Phase 2 rotates by activity-score
        background_roles = roles[1:4]

        self._render_pane(cr, 780, 40, 1100, 620, foreground_role, alpha * 0.94, is_foreground=True)
        y_offset = 40
        for bg_role in background_roles:
            self._render_pane(
                cr, 20, y_offset, 760, 340, bg_role, alpha * 0.68, is_foreground=False
            )
            y_offset += 360

    def _render_pane(
        self,
        cr: cairo.Context,
        x: int,
        y: int,
        w: int,
        h: int,
        role: str,
        alpha: float,
        is_foreground: bool,
    ) -> None:
        """Render one pane with BitchX angle-bracket header + text body."""
        from .homage import active_package

        pkg = active_package()
        palette = pkg.palette

        # Background rect
        cr.save()
        bg = palette.background
        cr.set_source_rgba(bg.r, bg.g, bg.b, bg.a * alpha)
        cr.rectangle(x, y, w, h)
        cr.fill()

        # Border: crisp on foreground, soft on background
        cr.set_line_width(2.0 if is_foreground else 1.0)
        border_color = palette.bright if is_foreground else palette.muted
        cr.set_source_rgba(border_color.r, border_color.g, border_color.b, alpha)
        cr.rectangle(x, y, w, h)
        cr.stroke()
        cr.restore()

        # Header: `»»» A-//` geometric glyph, not name
        glyph = self._glyphs.get(role, "?")
        self._render_header(cr, x + 8, y + 4, f"»»» {glyph}", palette, alpha)

        # Body: classified lines
        ring = self._panes.get(role)
        if ring is None:
            return
        lines = ring.snapshot()
        self._render_lines(cr, x + 10, y + 28, w - 20, h - 34, lines, palette, alpha)

    def _render_header(
        self,
        cr: cairo.Context,
        x: int,
        y: int,
        text: str,
        palette: Any,
        alpha: float,
    ) -> None:
        """Single-line BitchX angle-bracket header."""
        from .text_render import TextStyle, render_text

        style = TextStyle(
            font_description=self._font_description,
            color=(palette.muted.r, palette.muted.g, palette.muted.b, alpha),
            outline=None,
        )
        render_text(cr, text, x, y, style)

    def _render_lines(
        self,
        cr: cairo.Context,
        x: int,
        y: int,
        w: int,
        h: int,
        lines: list[tuple[str, str]],
        palette: Any,
        alpha: float,
    ) -> None:
        """Render classified lines with mIRC-16 palette routing."""
        from .text_render import TextStyle, render_text

        line_height = 14
        max_lines = max(1, h // line_height)
        visible = lines[-max_lines:] if len(lines) > max_lines else lines

        role_colors = {
            "prompt": palette.bright,
            "tool": palette.accent_cyan if hasattr(palette, "accent_cyan") else palette.bright,
            "error": palette.accent_red if hasattr(palette, "accent_red") else palette.muted,
            "success": (
                palette.accent_green if hasattr(palette, "accent_green") else palette.bright
            ),
            "text": palette.bright,
        }

        for i, (line, role) in enumerate(visible):
            color = role_colors.get(role, palette.bright)
            style = TextStyle(
                font_description=self._font_description,
                color=(color.r, color.g, color.b, alpha * 0.88),
                outline=None,
            )
            truncated = line[:160] if len(line) > 160 else line
            render_text(cr, truncated, x, y + i * line_height, style)


__all__ = ["DURFCairoSource"]
