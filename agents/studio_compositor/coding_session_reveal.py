"""CodingSessionReveal — DURF sibling for foot-terminal coding sessions.

Per cc-task ``durf-foot-coding-session-reveal`` (WSJF 14.0). The existing
:class:`agents.studio_compositor.durf_source.DURFCairoSource` captures
Codex driver tmux panes (``cx-red``, ``cx-violet``, etc). This source
captures the **operator's actual coding work** in foot-terminal tmux
sessions — the constitutive labor of building Hapax itself, made
audience-legible by default with redaction guards preserving the
privacy posture the spec ratifies.

The first ship landed discovery + capture + extended redaction. This
module now also exposes the Cairo-native ``CodingSessionReveal`` ward:
``HomageTransitionalSource`` owns the HOMAGE/FSM render lifecycle while
``ActivityRevealMixin`` owns the claim contract ActivityRouter reads.
The earlier ``CodingSessionRevealCore`` remains as a render-free test
and inspection surface.

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

import hashlib
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from agents.studio_compositor import durf_source as _durf_module
from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin
from agents.studio_compositor.durf_redaction import DURF_RAW_ENV, RISK_PATTERNS
from agents.studio_compositor.durf_source import (
    DEFAULT_FONT_DESCRIPTION,
    _line_color,
    capture_tmux_text,
    redact_terminal_lines,
    sanitize_terminal_lines,
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

#: Env var: operator-only raw inspection mode. Disables text redaction
#: for this ward but marks the snapshot ``egress_allowed=False``.
CODING_RAW_ENV = "HAPAX_DURF_CODING_RAW"

#: Env var: repo used for metadata sidecar signals. Defaults to the
#: primary council checkout, which is where the operator's visible work
#: normally lives.
CODING_REPO_ENV = "HAPAX_DURF_CODING_REPO"

#: Default presence weighting from the cc-task synthesis.
DEFAULT_BASE_LEVEL = 0.75

#: Visibility threshold named in the task's formula section.
VISIBILITY_THRESHOLD = 0.30

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
_ENTER_RAMP_S = 0.4
_EXIT_RAMP_S = 0.6
_EXIT_HYSTERESIS_S = 4.0
_FRONTED_ALPHA = 0.90
_METADATA_CACHE_TTL_S = 10.0
_DEFAULT_REPO_PATH = Path(os.path.expanduser("~/projects/hapax-council"))
_RAW_BYPASS_WARNED = False

_LEGAL_FIRST = "Ryan"
_LEGAL_MIDDLE = "Lee"
_LEGAL_LAST = "Kleeberger"


def compute_visibility_score(
    *,
    narrative_recruitment: float,
    base_level: float = DEFAULT_BASE_LEVEL,
    ceiling_budget: float = 1.0,
    consent_gate: float = 1.0,
    redaction_pass: float = 1.0,
    hardm_pass: float = 1.0,
) -> float:
    """Task-specified visibility product for the coding-session ward."""
    factors = (
        base_level,
        narrative_recruitment,
        ceiling_budget,
        consent_gate,
        redaction_pass,
        hardm_pass,
    )
    score = 1.0
    for value in factors:
        score *= max(0.0, min(1.0, float(value)))
    return max(0.0, min(1.0, score))


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
    metadata: CodingSessionMetadata | None = None
    visibility_score: float = 0.0
    wcs_row: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CodingSessionMetadata:
    """Non-label visual modulation inputs for the coding-session pane."""

    branch: str = ""
    branch_glyph: str = ""
    commits_since_main: int = 0
    open_pr_count: int = 0
    churn_lpm: float = 0.0
    captured_at: float = 0.0


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
    active = os.environ.get(DURF_RAW_ENV) == "1" or os.environ.get(CODING_RAW_ENV) == "1"
    global _RAW_BYPASS_WARNED
    if active and not _RAW_BYPASS_WARNED:
        log.warning("coding-session: raw bypass active; redaction disabled and egress disallowed")
        _RAW_BYPASS_WARNED = True
    return active


def branch_glyph(branch: str) -> str:
    """Return the four-character branch glyph: initial + stable hash."""
    cleaned = "".join(ch for ch in branch if ch.isalnum())
    if not cleaned:
        return ""
    digest = hashlib.sha1(branch.encode("utf-8")).hexdigest()[:3].upper()
    return f"{cleaned[0].upper()}{digest}"[:4]


def _run_text(cmd: list[str], *, cwd: Path, timeout_s: float = 0.8) -> str:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_git_metadata(
    repo_path: Path | None = None, *, now: float | None = None
) -> CodingSessionMetadata:
    """Best-effort git/PR sidecar values for visual modulation."""
    ts = time.time() if now is None else now
    repo = repo_path or Path(os.environ.get(CODING_REPO_ENV, str(_DEFAULT_REPO_PATH)))
    branch = _run_text(["git", "branch", "--show-current"], cwd=repo)
    if not branch:
        branch = _run_text(["git", "rev-parse", "--short", "HEAD"], cwd=repo)

    commits_text = _run_text(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=repo)
    if not commits_text:
        commits_text = _run_text(["git", "rev-list", "--count", "main..HEAD"], cwd=repo)
    try:
        commits_since_main = max(0, int(commits_text))
    except ValueError:
        commits_since_main = 0

    env_pr_count = os.environ.get("HAPAX_DURF_CODING_PR_COUNT", "").strip()
    if env_pr_count:
        try:
            open_pr_count = max(0, min(9, int(env_pr_count)))
        except ValueError:
            open_pr_count = 0
    else:
        pr_json = _run_text(
            ["gh", "pr", "list", "--state", "open", "--limit", "9", "--json", "number"],
            cwd=repo,
            timeout_s=1.2,
        )
        open_pr_count = pr_json.count('"number"') if pr_json else 0
        open_pr_count = max(0, min(9, open_pr_count))

    return CodingSessionMetadata(
        branch=branch,
        branch_glyph=branch_glyph(branch),
        commits_since_main=commits_since_main,
        open_pr_count=open_pr_count,
        captured_at=ts,
    )


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
    if _coding_raw_bypass_active():
        return CodingSessionState(
            session_name=cfg.session_name,
            tmux_target=cfg.tmux_target,
            glyph=cfg.glyph,
            visible=True,
            lines=sanitize_terminal_lines(cap.lines, max_lines=cfg.capture_lines),
            captured_at=now,
            redaction_state="raw_bypass",
        )
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
            metadata=read_git_metadata(),
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
            "metadata": snap.metadata.__dict__ if snap.metadata else None,
            "visibility_score": snap.visibility_score,
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
        redaction_pass = 1.0 if any(s.visible for s in states) else 0.0
        visibility_score = compute_visibility_score(
            narrative_recruitment=1.0 if states else 0.0,
            redaction_pass=redaction_pass,
            consent_gate=1.0 if egress_allowed else 0.0,
        )
        snap = CodingSessionSnapshot(
            sessions=states,
            captured_at=ts,
            egress_allowed=egress_allowed,
            suppression_reason=None if egress_allowed else "raw_bypass_active",
            metadata=read_git_metadata(now=ts),
            visibility_score=visibility_score,
            wcs_row=build_wcs_row(states, now=ts, egress_allowed=egress_allowed),
        )
        with self._snapshot_lock:
            self._snapshot = snap
        return snap


class CodingSessionReveal(HomageTransitionalSource, ActivityRevealMixin):
    """Cairo HOMAGE ward for the operator's foot-terminal coding tmux pane."""

    WARD_ID = "coding-session-reveal"
    SOURCE_KIND = "cairo"
    DEFAULT_HYSTERESIS_S = 30.0
    VISIBILITY_CEILING_PCT = 0.18
    SUPPRESS_WHEN_ACTIVE = frozenset(
        {
            "impingement_cascade",
            "recruitment_candidate_panel",
            "activity_variety_log",
        }
    )
    priority = 5

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        repo_path: Path | None = None,
        font_description: str = DEFAULT_FONT_DESCRIPTION,
        start_thread: bool = True,
    ) -> None:
        HomageTransitionalSource.__init__(
            self,
            source_id="coding_session_reveal",
            entering_duration_s=_ENTER_RAMP_S,
            exiting_duration_s=_EXIT_RAMP_S,
        )
        ActivityRevealMixin.__init__(self, start_poll_thread=False)
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._repo_path = repo_path
        self._font_description = font_description
        self._snapshot = CodingSessionSnapshot(
            sessions=(),
            captured_at=time.time(),
            egress_allowed=True,
            metadata=read_git_metadata(repo_path=self._repo_path),
            wcs_row=build_wcs_row((), now=time.time(), egress_allowed=True),
        )
        self._snapshot_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._gate_off_pending_since: float | None = None
        self._last_rendered_alpha = 0.0
        self._metadata_cache = self._snapshot.metadata
        self._metadata_cache_ts = 0.0
        self._last_lines: tuple[str, ...] = ()
        self._last_lines_ts: float | None = None
        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="coding-session-reveal-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._capture_poll_once()
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("coding-session reveal: poll cycle failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
        try:
            ActivityRevealMixin.stop(self)
        except Exception:
            log.debug("coding-session reveal: mixin stop failed", exc_info=True)

    def cleanup(self) -> None:
        self.stop()

    def _metadata(self, *, now: float) -> CodingSessionMetadata:
        if self._metadata_cache and now - self._metadata_cache_ts < _METADATA_CACHE_TTL_S:
            return self._metadata_cache
        self._metadata_cache = read_git_metadata(repo_path=self._repo_path, now=now)
        self._metadata_cache_ts = now
        return self._metadata_cache

    def _estimate_churn_lpm(
        self, visible_lines: tuple[str, ...], *, now: float
    ) -> tuple[float, tuple[str, ...], float]:
        prev_ts = self._last_lines_ts
        prev = self._last_lines
        self._last_lines = visible_lines
        self._last_lines_ts = now
        if prev_ts is None or not prev:
            return 0.0, visible_lines, now
        elapsed_min = max((now - prev_ts) / 60.0, 1.0 / 60.0)
        changed = abs(len(visible_lines) - len(prev))
        changed += sum(1 for old, new in zip(prev, visible_lines, strict=False) if old != new)
        return min(240.0, changed / elapsed_min), visible_lines, now

    def _capture_poll_once(self, *, now: float | None = None) -> CodingSessionSnapshot:
        ts = time.time() if now is None else now
        if _coding_off_active() or _durf_module._consent_safe_active():
            reason = "coding_off_env" if _coding_off_active() else "consent_safe"
            snap = CodingSessionSnapshot(
                sessions=(),
                captured_at=ts,
                egress_allowed=False,
                suppression_reason=reason,
                metadata=self._metadata(now=ts),
                visibility_score=0.0,
                wcs_row=build_wcs_row((), now=ts, egress_allowed=False),
            )
            with self._snapshot_lock:
                self._snapshot = snap
            self._drive_fsm(False, now=time.monotonic())
            ActivityRevealMixin.poll_once(self, now=time.monotonic())
            return snap

        metadata = self._metadata(now=ts)
        configs = discover_coding_sessions(config_path=self._config_path)
        states = tuple(_capture_one(cfg, now=ts) for cfg in configs)
        states = tuple(
            replace(state, glyph=(state.glyph or metadata.branch_glyph)[:4]) for state in states
        )
        visible_lines = next((state.lines for state in states if state.visible), ())
        churn_lpm, _, _ = self._estimate_churn_lpm(visible_lines, now=ts)
        metadata = replace(metadata, churn_lpm=churn_lpm)
        egress_allowed = not _coding_raw_bypass_active()
        redaction_pass = 1.0 if any(s.visible for s in states) else 0.0
        score = compute_visibility_score(
            narrative_recruitment=1.0 if states else 0.0,
            ceiling_budget=0.0 if self._ceiling_enforced(time.monotonic()) else 1.0,
            consent_gate=1.0 if egress_allowed else 0.0,
            redaction_pass=redaction_pass,
            hardm_pass=1.0,
        )
        snap = CodingSessionSnapshot(
            sessions=states,
            captured_at=ts,
            egress_allowed=egress_allowed,
            suppression_reason=None if egress_allowed else "raw_bypass_active",
            metadata=metadata,
            visibility_score=score,
            wcs_row=build_wcs_row(states, now=ts, egress_allowed=egress_allowed),
        )
        with self._snapshot_lock:
            self._snapshot = snap
        gate = any(s.visible for s in states) and score >= VISIBILITY_THRESHOLD and egress_allowed
        self._drive_fsm(gate, now=time.monotonic())
        ActivityRevealMixin.poll_once(self, now=time.monotonic())
        return snap

    def snapshot(self) -> CodingSessionSnapshot:
        with self._snapshot_lock:
            return self._snapshot

    def _gate_active(self) -> bool:
        with self._snapshot_lock:
            snap = self._snapshot
        return (
            snap.egress_allowed
            and snap.visibility_score >= VISIBILITY_THRESHOLD
            and any(session.visible for session in snap.sessions)
        )

    def _drive_fsm(self, gate: bool, *, now: float) -> None:
        if gate:
            self._gate_off_pending_since = None
            if self._state in (TransitionState.ABSENT, TransitionState.EXITING):
                try:
                    self.apply_transition("ticker-scroll-in", now=now)
                except Exception:
                    log.debug("coding-session reveal: enter transition failed", exc_info=True)
            return
        if self._gate_off_pending_since is None:
            self._gate_off_pending_since = now
            return
        if now - self._gate_off_pending_since >= _EXIT_HYSTERESIS_S and self._state in (
            TransitionState.HOLD,
            TransitionState.ENTERING,
        ):
            try:
                self.apply_transition("ticker-scroll-out", now=now)
            except Exception:
                log.debug("coding-session reveal: exit transition failed", exc_info=True)

    def _compute_alpha(self, now: float) -> float:
        gate = self._gate_active()
        if self._state is TransitionState.ABSENT:
            return 0.0
        if self._state is TransitionState.HOLD:
            return _FRONTED_ALPHA if gate else 0.0
        progress = self._progress(now=now)
        if self._state is TransitionState.ENTERING:
            return _FRONTED_ALPHA * progress
        return _FRONTED_ALPHA * (1.0 - progress)

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._snapshot_lock:
            snap = self._snapshot
        alpha = self._compute_alpha(now)
        self._last_rendered_alpha = alpha
        return {
            "alpha": alpha,
            "now": now,
            "sessions": [s.__dict__ for s in snap.sessions],
            "egress_allowed": snap.egress_allowed,
            "suppression_reason": snap.suppression_reason,
            "metadata": snap.metadata.__dict__ if snap.metadata else None,
            "visibility_score": snap.visibility_score,
            "wcs": snap.wcs_row,
        }

    def _compute_claim_score(self) -> float:
        with self._snapshot_lock:
            return self._snapshot.visibility_score

    def _want_visible(self) -> bool:
        return self._gate_active()

    def _mandatory_invisible(self) -> bool:
        return (
            _coding_off_active()
            or _durf_module._consent_safe_active()
            or _coding_raw_bypass_active()
        )

    def _claim_source_refs(self) -> tuple[str, ...]:
        with self._snapshot_lock:
            refs = [
                f"coding-session:{s.session_name}" for s in self._snapshot.sessions if s.visible
            ]
        refs.append("affordance:studio.coding_session_reveal")
        return tuple(refs)

    def _describe_source_registration(self) -> dict[str, Any]:
        return {
            "id": "coding_session_reveal",
            "class_name": "CodingSessionReveal",
            "kind": "cairo",
            "ward_id": type(self).WARD_ID,
        }

    def _hardm_check(self) -> None:
        return None

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
        with self._snapshot_lock:
            snap = self._snapshot
        visible = [session for session in snap.sessions if session.visible]
        if not visible:
            return
        self._render_session(cr, canvas_w, canvas_h, visible[0], snap.metadata, alpha, t)

    def _render_session(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        session: CodingSessionState,
        metadata: CodingSessionMetadata | None,
        alpha: float,
        t: float,
    ) -> None:
        from agents.studio_compositor.homage.rendering import active_package

        pkg = active_package()
        bg = pkg.palette.background
        muted = pkg.palette.muted
        warm = pkg.palette.accent_yellow
        accent = pkg.palette.accent_cyan
        commits = metadata.commits_since_main if metadata else 0
        warm_shift = min(1.0, commits / 5.0) * 0.18
        bg_rgba = (
            bg[0] * (1.0 - warm_shift) + warm[0] * warm_shift,
            bg[1] * (1.0 - warm_shift) + warm[1] * warm_shift,
            bg[2] * (1.0 - warm_shift) + warm[2] * warm_shift,
            min(bg[3], 0.88) * alpha,
        )

        cr.save()
        cr.set_source_rgba(*bg_rgba)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()
        cr.restore()

        glyph = (session.glyph or (metadata.branch_glyph if metadata else ""))[:4]
        if glyph:
            glyph_style = TextStyle(
                text=glyph,
                font_description=self._font_description,
                color_rgba=(muted[0], muted[1], muted[2], 0.72 * alpha),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.86 * alpha),
                outline_offsets=OUTLINE_OFFSETS_4,
                max_width_px=96,
                wrap="char",
            )
            render_text(cr, glyph_style, max(8, canvas_w - 84), 14)

        pad_x = 18
        line_y = 22
        line_h = 19
        max_lines = max(1, int((canvas_h - 48) / line_h))
        churn = min(1.0, (metadata.churn_lpm if metadata else 0.0) / 120.0)
        brightness = 0.76 + 0.24 * churn
        for line in session.lines[-max_lines:]:
            r, g, b, a = _line_color(line)
            style = TextStyle(
                text=line or " ",
                font_description=self._font_description,
                color_rgba=(r, g, b, min(1.0, a * alpha * brightness)),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.80 * alpha),
                outline_offsets=OUTLINE_OFFSETS_4,
                max_width_px=max(1, canvas_w - pad_x * 2),
                wrap="char",
                line_spacing=0.92,
            )
            render_text(cr, style, pad_x, line_y)
            line_y += line_h
            if line_y > canvas_h - line_h:
                break

        if metadata and metadata.open_pr_count > 0:
            dots = "." * min(9, metadata.open_pr_count)
            dot_style = TextStyle(
                text=dots,
                font_description=self._font_description,
                color_rgba=(accent[0], accent[1], accent[2], 0.70 * alpha),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.86 * alpha),
                outline_offsets=OUTLINE_OFFSETS_4,
                max_width_px=160,
                wrap="char",
            )
            render_text(cr, dot_style, max(8, canvas_w - 18 - len(dots) * 12), canvas_h - 28)

        if churn > 0.0:
            trail_alpha = (0.10 + 0.42 * churn) * alpha
            for idx in range(4):
                offset = (t * 80.0 + idx * 18.0) % max(1, canvas_w - 36)
                cr.save()
                cr.set_source_rgba(
                    accent[0], accent[1], accent[2], trail_alpha * (1.0 - idx * 0.18)
                )
                cr.rectangle(18 + offset, canvas_h - 12 - idx * 3, 24, 2)
                cr.fill()
                cr.restore()


__all__ = [
    "CODING_OFF_ENV",
    "CODING_PREFIX_ENV",
    "CODING_RAW_ENV",
    "CODING_REPO_ENV",
    "CODING_TARGET_ENV",
    "DEFAULT_BASE_LEVEL",
    "DEFAULT_AUTO_DETECT_PREFIXES",
    "DEFAULT_CONFIG_PATH",
    "CodingSessionConfig",
    "CodingSessionMetadata",
    "CodingSessionReveal",
    "CodingSessionRevealCore",
    "CodingSessionSnapshot",
    "CodingSessionState",
    "VISIBILITY_THRESHOLD",
    "build_wcs_row",
    "branch_glyph",
    "compute_visibility_score",
    "discover_coding_sessions",
    "read_git_metadata",
    # Re-exports for downstream callers and parity with durf_source.
    "RISK_PATTERNS",
    "sanitize_terminal_lines",
]
