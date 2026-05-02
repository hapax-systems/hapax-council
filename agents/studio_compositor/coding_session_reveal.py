"""CodingSessionReveal — DURF sibling for foot-terminal coding sessions.

Per cc-task ``durf-foot-coding-session-reveal`` (WSJF 14.0). The existing
:class:`agents.studio_compositor.durf_source.DURFCairoSource` captures
Codex driver tmux panes (``cx-red``, ``cx-violet``, etc). This source
captures the **operator's actual coding work** in foot-terminal tmux
sessions — the constitutive labor of building Hapax itself, made
audience-legible by default with redaction guards preserving the
privacy posture the spec ratifies.

This is the **Phase 0** ship: discovery + capture + extended redaction
+ snapshot/state surface, but NOT yet the cairo render path or the
metadata-sidecar visual modulation (git glyph, PR dot row, churn
brightness). Phase 1 follow-on will subclass
:class:`HomageTransitionalSource` and wire ``render_content``; this
file deliberately stops at the data layer so the redaction extensions
can ship reviewable in isolation.

Architectural choice: standalone class (no ``ActivityRevealMixin``
inheritance). The activity-reveal-ward family base class
(``activity-reveal-ward-p0-base-class`` cc-task) is currently
unclaimed; per the lane directive, build standalone first, refactor
onto the family later when the P0 base lands. The internal contracts
(``state()`` shape, ``stop()``, snapshot dataclass) mirror the DURF
source so the family migration is a name-change refactor.

Capture mechanism: ``tmux capture-pane`` retargeted at operator's
foot-tmux sessions. Reuses the existing
:func:`agents.studio_compositor.durf_source.capture_tmux_text` helper
verbatim — no Wayland pixel capture path is added.

Discovery:

* ``HAPAX_DURF_CODING_TARGET`` env var — explicit single tmux target
  (``"coding-foo:0.0"`` etc). Highest priority.
* ``config/durf-coding-panes.yaml`` — operator-curated session list
  with optional auto-detect prefixes (default: ``coding-*``,
  ``dev-*``, ``hapax-claude-*``).
* Auto-detect: ``tmux ls`` filtered by configured prefixes.

Privacy posture: opt-out by default with safe redaction floor.
``HAPAX_DURF_CODING_OFF=1`` suppresses the entire ward for the current
process (operator-recruitable per-session disable). The redaction
layer extends ``durf_redaction.RISK_PATTERNS`` with foot-specific
patterns (SSH public keys, other-user homes, claude-cli chat markers,
``.envrc`` references, ``pass`` invocations).
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agents.studio_compositor.durf_redaction import DURF_RAW_ENV, RISK_PATTERNS
from agents.studio_compositor.durf_source import (
    capture_tmux_text,
    redact_terminal_lines,
    sanitize_terminal_lines,
)

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path(
    os.path.expanduser("~/projects/hapax-council/config/durf-coding-panes.yaml")
)

#: Env var: explicit single tmux target. Highest discovery priority.
CODING_TARGET_ENV = "HAPAX_DURF_CODING_TARGET"

#: Env var: per-session opt-out kill switch. Suppresses the entire ward.
CODING_OFF_ENV = "HAPAX_DURF_CODING_OFF"

#: Env var: prefix override for tmux session auto-detect. Defaults
#: combine into the auto-detect list when this is unset.
CODING_PREFIX_ENV = "HAPAX_DURF_CODING_PREFIX"

#: Default tmux session prefixes auto-detected when no explicit target
#: + no config-file panes are configured.
DEFAULT_AUTO_DETECT_PREFIXES: tuple[str, ...] = (
    "coding-",
    "dev-",
    "hapax-claude-",
)

_DEFAULT_CAPTURE_LINES = 80
_DEFAULT_STALE_AFTER_S = 20.0
_POLL_INTERVAL_S = 0.5


# ── Snapshot dataclasses ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CodingSessionConfig:
    """One operator coding tmux session entry from
    ``config/durf-coding-panes.yaml``."""

    session_name: str
    tmux_target: str
    glyph: str = ""
    enabled: bool = True
    capture_lines: int = _DEFAULT_CAPTURE_LINES


@dataclass(frozen=True)
class CodingSessionState:
    """Per-session render state at one capture tick."""

    session_name: str
    tmux_target: str
    glyph: str
    visible: bool
    lines: tuple[str, ...] = ()
    captured_at: float | None = None
    redaction_state: str = "unavailable"
    suppressed_reason: str | None = None
    public_claim_ceiling: str = "work_trace_visible"


@dataclass(frozen=True)
class CodingSessionSnapshot:
    """Multi-session snapshot returned by the poll thread."""

    sessions: tuple[CodingSessionState, ...]
    captured_at: float
    egress_allowed: bool = True
    suppression_reason: str | None = None
    wcs_row: dict[str, Any] = field(default_factory=dict)


def _iso_ts(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _coding_off_active() -> bool:
    """``HAPAX_DURF_CODING_OFF=1`` → suppress the ward for this session."""
    return os.environ.get(CODING_OFF_ENV) == "1"


def _coding_raw_bypass_active() -> bool:
    """``HAPAX_DURF_RAW=1`` is already used by DURF Codex-lane redaction.

    A separate ``HAPAX_DURF_CODING_RAW=1`` is reserved for operator-only
    inspection mode (per the spec) — when set, the ward emits clean
    captures even if a risk pattern matches. NEVER set in public mode;
    the snapshot still flips ``egress_allowed=False`` so any consumer
    that respects the flag will not broadcast.
    """
    return os.environ.get(DURF_RAW_ENV) == "1" or os.environ.get("HAPAX_DURF_CODING_RAW") == "1"


# ── Discovery ─────────────────────────────────────────────────────────────


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        log.debug("coding-session: failed to parse yaml %s", path, exc_info=True)
        return {}
    return raw if isinstance(raw, dict) else {}


def _list_tmux_sessions(timeout_s: float = 1.0) -> tuple[str, ...]:
    """Return tmux session names via ``tmux list-sessions -F#S``.

    Empty tuple on tmux missing / no sessions / parse failure.
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#S"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ()
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _resolve_prefixes(config_prefixes: tuple[str, ...] | None) -> tuple[str, ...]:
    """Combine env override + config file prefixes + defaults.

    The env var ``HAPAX_DURF_CODING_PREFIX`` takes the highest priority
    when set (comma-separated). Config-file prefixes are next.
    Defaults fill in if both are empty.
    """
    env = os.environ.get(CODING_PREFIX_ENV, "").strip()
    if env:
        return tuple(p.strip() for p in env.split(",") if p.strip())
    if config_prefixes:
        return config_prefixes
    return DEFAULT_AUTO_DETECT_PREFIXES


def discover_coding_sessions(
    config_path: Path | None = None,
) -> tuple[CodingSessionConfig, ...]:
    """Resolve the operator's coding tmux session targets.

    Priority order (each level used only when the higher level produces
    nothing):

      1. ``HAPAX_DURF_CODING_TARGET`` env (single explicit target).
      2. ``config/durf-coding-panes.yaml`` ``panes:`` list.
      3. Auto-detect via ``tmux ls`` filtered by prefix list.
    """
    explicit = os.environ.get(CODING_TARGET_ENV, "").strip()
    if explicit:
        # Use the leading "<session>:..." substring as a friendly name.
        session_name = explicit.split(":", 1)[0]
        return (
            CodingSessionConfig(
                session_name=session_name,
                tmux_target=explicit,
                glyph="",
                enabled=True,
            ),
        )

    cfg_path = config_path or DEFAULT_CONFIG_PATH
    raw = _read_yaml_mapping(cfg_path)
    panes_raw = raw.get("panes") or []
    config_panes: list[CodingSessionConfig] = []
    if isinstance(panes_raw, list):
        for entry in panes_raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("session") or entry.get("name") or "").strip()
            target = str(entry.get("tmux_target") or "").strip()
            if not target:
                continue
            config_panes.append(
                CodingSessionConfig(
                    session_name=name or target.split(":", 1)[0],
                    tmux_target=target,
                    glyph=str(entry.get("glyph", "")),
                    enabled=bool(entry.get("enabled", True)),
                    capture_lines=int(entry.get("capture_lines", _DEFAULT_CAPTURE_LINES)),
                )
            )
    if config_panes:
        return tuple(p for p in config_panes if p.enabled)

    config_prefixes_raw = raw.get("auto_detect_prefixes")
    config_prefixes: tuple[str, ...] | None = None
    if isinstance(config_prefixes_raw, list):
        config_prefixes = tuple(str(p) for p in config_prefixes_raw if p)

    prefixes = _resolve_prefixes(config_prefixes)
    sessions = _list_tmux_sessions()
    discovered = [
        CodingSessionConfig(
            session_name=s,
            tmux_target=f"{s}:0.0",
            glyph="",
            enabled=True,
        )
        for s in sessions
        if any(s.startswith(p) for p in prefixes)
    ]
    return tuple(discovered)


# ── Capture + render helpers ─────────────────────────────────────────────


def _suppressed_session(
    cfg: CodingSessionConfig,
    *,
    reason: str,
    now: float,
) -> CodingSessionState:
    return CodingSessionState(
        session_name=cfg.session_name,
        tmux_target=cfg.tmux_target,
        glyph=cfg.glyph,
        visible=False,
        captured_at=now,
        redaction_state="suppressed",
        suppressed_reason=reason,
    )


def _capture_one(cfg: CodingSessionConfig, *, now: float) -> CodingSessionState:
    """Capture + redact one tmux pane into a CodingSessionState."""
    cap = capture_tmux_text(cfg.tmux_target, capture_lines=cfg.capture_lines)
    if not cap.ok:
        return _suppressed_session(cfg, reason=cap.reason or "tmux_unavailable", now=now)
    redact = redact_terminal_lines(cap.lines)
    if redact.action.value == "suppress":
        return _suppressed_session(
            cfg, reason=redact.matched_pattern or "redaction_suppress", now=now
        )
    if redact.action.value == "unavailable":
        return _suppressed_session(
            cfg, reason=redact.matched_pattern or "redaction_unavailable", now=now
        )
    return CodingSessionState(
        session_name=cfg.session_name,
        tmux_target=cfg.tmux_target,
        glyph=cfg.glyph,
        visible=True,
        lines=redact.lines,
        captured_at=now,
        redaction_state="clean",
    )


def build_wcs_row(
    sessions: tuple[CodingSessionState, ...],
    *,
    now: float,
    egress_allowed: bool,
) -> dict[str, Any]:
    """World capability surface row describing the ward's state."""
    visible_count = sum(1 for s in sessions if s.visible)
    return {
        "ward": "coding_session_reveal",
        "captured_at": _iso_ts(now),
        "egress_allowed": egress_allowed,
        "session_count": len(sessions),
        "visible_count": visible_count,
        "suppressed_reasons": sorted(
            {s.suppressed_reason for s in sessions if s.suppressed_reason is not None}
        ),
    }


# ── The source ───────────────────────────────────────────────────────────


class CodingSessionRevealCore:
    """Core capture + snapshot machinery; no Cairo rendering yet.

    The class is intentionally render-agnostic so Phase 1 can subclass
    :class:`HomageTransitionalSource` and pull state via :meth:`state`
    without re-implementing capture. Tests drive the core directly with
    ``start_thread=False`` so they never spawn the poll thread.
    """

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        start_thread: bool = True,
    ) -> None:
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._snapshot = CodingSessionSnapshot(
            sessions=(),
            captured_at=time.time(),
            egress_allowed=True,
            wcs_row={},
        )
        self._snapshot_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="coding-session-poll",
                daemon=True,
            )
            self._poll_thread.start()

    # ── Public surface ───────────────────────────────────────────────

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)

    def state(self) -> dict[str, Any]:
        """Return a render-ready snapshot dict.

        Contract mirrors :meth:`DURFCairoSource.state` so the family
        migration in Phase 1+ is a name change.
        """
        with self._snapshot_lock:
            snap = self._snapshot
        return {
            "now": time.monotonic(),
            "sessions": [s.__dict__ for s in snap.sessions],
            "egress_allowed": snap.egress_allowed,
            "suppression_reason": snap.suppression_reason,
            "wcs": snap.wcs_row,
        }

    def snapshot(self) -> CodingSessionSnapshot:
        """Return the current snapshot dataclass directly (test affordance)."""
        with self._snapshot_lock:
            return self._snapshot

    # ── Internal poll ────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("coding-session: poll cycle failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def poll_once(self, *, now: float | None = None) -> CodingSessionSnapshot:
        """One capture cycle. Public so tests can drive it deterministically."""
        ts = time.time() if now is None else now
        if _coding_off_active():
            snap = CodingSessionSnapshot(
                sessions=(),
                captured_at=ts,
                egress_allowed=False,
                suppression_reason="coding_off_env",
                wcs_row=build_wcs_row((), now=ts, egress_allowed=False),
            )
            with self._snapshot_lock:
                self._snapshot = snap
            return snap

        configs = discover_coding_sessions(config_path=self._config_path)
        states = tuple(_capture_one(cfg, now=ts) for cfg in configs)
        egress_allowed = not _coding_raw_bypass_active()
        snap = CodingSessionSnapshot(
            sessions=states,
            captured_at=ts,
            egress_allowed=egress_allowed,
            suppression_reason=None if egress_allowed else "raw_bypass_active",
            wcs_row=build_wcs_row(states, now=ts, egress_allowed=egress_allowed),
        )
        with self._snapshot_lock:
            self._snapshot = snap
        return snap


__all__ = [
    "CODING_OFF_ENV",
    "CODING_PREFIX_ENV",
    "CODING_TARGET_ENV",
    "DEFAULT_AUTO_DETECT_PREFIXES",
    "DEFAULT_CONFIG_PATH",
    "CodingSessionConfig",
    "CodingSessionRevealCore",
    "CodingSessionSnapshot",
    "CodingSessionState",
    "build_wcs_row",
    "discover_coding_sessions",
    # Re-exports for downstream callers and parity with durf_source.
    "RISK_PATTERNS",
    "sanitize_terminal_lines",
]
