"""DURF coding-session HOMAGE ward.

DURF is the full-frame coding-session ward for the studio compositor. The
default/public path is deliberately text-mode: discover Codex lanes from
coordination state, capture bounded tmux buffers, redact before rendering,
and publish a source-state/WCS row that says what was visible or suppressed.

The older Hyprland/grim pixel-capture path is intentionally not used here.
Public/default mode must not broadcast unbounded Wayland pixels when the
bounded tmux text buffer is enough to show work traces. That default also
closes the old Phase 3 "per-region pixel masking" follow-up: there are no
public pixels to mask on the live path, and the unsafe raw/pixel bypasses
fail closed before capture.

Phase 3 status is explicit in this module boundary: foreground rotation is
the salience-ranked ``_select_lanes`` output rendered by ``_layout_for_count``;
Bayesian-era gate migration is handled through ``CodingActivityReveal``'s
``ActivityRevealMixin`` claim instead of a DURF-local hardcoded gate table;
the default-on reflection layer lives beside the Cairo renderer and consumes
only redacted ``DURFPaneState.lines``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .durf_redaction import DURF_RAW_ENV, RISK_PATTERNS, RedactionAction

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(os.path.expanduser("~/projects/hapax-council/config/durf-panes.yaml"))
DEFAULT_RELAY_DIR = Path(os.path.expanduser("~/.cache/hapax/relay"))
DEFAULT_CLAIM_DIR = Path(os.path.expanduser("~/.cache/hapax"))
DEFAULT_SESSION_HEALTH_PATH = Path(
    os.path.expanduser(
        "~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/codex-session-health.md"
    )
)
DEFAULT_FONT_DESCRIPTION = "Px437 IBM VGA 8x16 15"

_CONSENT_SAFE_PATH = Path("/dev/shm/hapax-compositor/consent-state.txt")

_POLL_INTERVAL_S = 0.5
_DEFAULT_CAPTURE_LINES = 80
_MAX_CAPTURE_LINES = 120
_MAX_LINE_CHARS = 180
_DEFAULT_STALE_AFTER_S = 20.0
_DEFAULT_MAX_VISIBLE_PANES = 4

_ENTER_RAMP_MS = 400.0
_EXIT_RAMP_MS = 600.0
_EXIT_HYSTERESIS_S = 4.0
_FRONTED_ALPHA = 0.92

_LANE_ORDER = ("cx-red", "cx-green", "cx-blue", "cx-amber", "cx-cyan", "cx-violet")
_DEFAULT_GLYPHS = {
    "cx-red": "R-<>",
    "cx-green": "G-//",
    "cx-blue": "B-|/",
    "cx-amber": "A-|\\",
    "cx-cyan": "C-<>",
    "cx-violet": "V-\\\\",
}

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_OPERATOR_HOME_PREFIX = "/" + "home" + "/" + "hapax" + "/"
_LEGAL_FIRST = "Ryan"
_LEGAL_MIDDLE = "Lee"
_LEGAL_LAST = "Kleeberger"

_TEXT_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = RISK_PATTERNS + (
    ("dot_envrc", re.compile(r"(^|\s)(?:source\s+)?\.envrc\b|/\.envrc\b")),
    ("pass_command", re.compile(r"\bpass\s+(?:show|edit|insert|grep|otp|generate)\b")),
    (
        "hapax_secrets_dump",
        re.compile(r"\bhapax-secrets\s+(?:show|print|dump|env|export|cat)\b"),
    ),
    ("tilde_ssh_path", re.compile(r"(?:^|\s)~/.ssh/")),
    ("legal_name_short", re.compile(_LEGAL_FIRST + r"\s+" + _LEGAL_LAST, re.IGNORECASE)),
    (
        "legal_name_full",
        re.compile(
            _LEGAL_FIRST + r"\s+" + _LEGAL_MIDDLE + r"\s+" + _LEGAL_LAST,
            re.IGNORECASE,
        ),
    ),
    (
        "private_or_employer_data",
        re.compile(r"\b(?:employer-confidential|work-confidential|private-third-party)\b"),
    ),
)


@dataclass(frozen=True)
class CodexPaneConfig:
    lane_id: str
    tmux_target: str | None
    glyph: str
    enabled: bool = True
    capture_lines: int = _DEFAULT_CAPTURE_LINES
    stale_after_s: float = _DEFAULT_STALE_AFTER_S


@dataclass(frozen=True)
class CodexLane:
    lane_id: str
    glyph: str
    tmux_target: str | None
    enabled: bool
    capture_lines: int
    stale_after_s: float
    relay_status: str | None = None
    task_id: str | None = None
    task_status: str | None = None
    branch: str | None = None
    pr: str | None = None
    warnings: str | None = None
    source_refs: tuple[str, ...] = ()
    impingement_kind: str = "none"
    volition_reason: str = "lane metadata only"
    salience: int = 0

    @property
    def has_work_signal(self) -> bool:
        return bool(self.task_id or self.pr or self.impingement_kind != "none")


@dataclass(frozen=True)
class TmuxCaptureResult:
    ok: bool
    lines: tuple[str, ...] = ()
    reason: str | None = None
    detail: str | None = None
    command: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextRedactionResult:
    action: RedactionAction
    lines: tuple[str, ...] = ()
    matched_pattern: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class DURFPaneState:
    lane_id: str
    glyph: str
    tmux_target: str | None
    visible: bool
    lines: tuple[str, ...] = ()
    captured_at: float | None = None
    redaction_state: str = "unavailable"
    suppressed_reason: str | None = None
    source_refs: tuple[str, ...] = ()
    impingement_kind: str = "none"
    volition_reason: str = "not selected"
    public_claim_ceiling: str = "work_trace_visible"


@dataclass(frozen=True)
class DURFSourceSnapshot:
    panes: tuple[DURFPaneState, ...]
    captured_at: float
    wcs_row: dict[str, Any] = field(default_factory=dict)


def _iso_ts(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _consent_safe_active() -> bool:
    """Return whether consent-safe egress is active."""
    try:
        return _CONSENT_SAFE_PATH.read_text(encoding="utf-8").strip() == "safe"
    except OSError:
        return False


def _unsafe_public_bypass_active() -> bool:
    """Return whether a raw/unsafe capture bypass is active in public mode."""
    if os.environ.get(DURF_RAW_ENV) == "1":
        return True
    return os.environ.get("HAPAX_DURF_PIXEL_CAPTURE_UNSAFE") == "1"


def _bounded_line_count(value: int) -> int:
    return max(1, min(value, _MAX_CAPTURE_LINES))


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def sanitize_terminal_lines(
    raw_lines: list[str] | tuple[str, ...],
    *,
    max_lines: int = _DEFAULT_CAPTURE_LINES,
    max_line_chars: int = _MAX_LINE_CHARS,
) -> tuple[str, ...]:
    """Strip escape/control bytes and return a bounded public line buffer."""
    bounded = _bounded_line_count(max_lines)
    result: list[str] = []
    for raw in raw_lines[-bounded:]:
        line = _CONTROL_RE.sub("", _strip_ansi(raw)).rstrip()
        if len(line) > max_line_chars:
            line = line[: max_line_chars - 3] + "..."
        result.append(line)
    return tuple(result)


def redact_terminal_lines(lines: tuple[str, ...]) -> TextRedactionResult:
    """Fail-closed redaction for tmux text before any render path sees it."""
    if _unsafe_public_bypass_active():
        return TextRedactionResult(
            RedactionAction.SUPPRESS,
            matched_pattern="unsafe_public_bypass",
            detail="raw or pixel bypass active in public/default mode",
        )
    try:
        sanitized = sanitize_terminal_lines(lines)
    except Exception as exc:
        return TextRedactionResult(
            RedactionAction.UNAVAILABLE,
            matched_pattern="redaction_unavailable",
            detail=str(exc),
        )
    joined = "\n".join(sanitized)
    for name, pattern in _TEXT_RISK_PATTERNS:
        if pattern.search(joined):
            return TextRedactionResult(
                RedactionAction.SUPPRESS,
                matched_pattern=name,
                detail=f"matched {name}",
            )
    return TextRedactionResult(RedactionAction.CLEAN, lines=sanitized)


def capture_tmux_text(
    tmux_target: str,
    *,
    capture_lines: int = _DEFAULT_CAPTURE_LINES,
    timeout_s: float = 1.0,
) -> TmuxCaptureResult:
    """Capture a bounded tmux pane buffer without ANSI escape sequences."""
    bounded = _bounded_line_count(capture_lines)
    cmd = (
        "tmux",
        "capture-pane",
        "-p",
        "-S",
        f"-{bounded}",
        "-t",
        tmux_target,
    )
    try:
        result = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return TmuxCaptureResult(False, reason="tmux_capture_timeout", command=cmd)
    except FileNotFoundError:
        return TmuxCaptureResult(False, reason="tmux_unavailable", command=cmd)
    except OSError as exc:
        return TmuxCaptureResult(
            False,
            reason="tmux_capture_error",
            detail=str(exc),
            command=cmd,
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:200] or "tmux capture failed"
        return TmuxCaptureResult(
            False,
            reason="tmux_target_missing",
            detail=detail,
            command=cmd,
        )
    lines = sanitize_terminal_lines(tuple(result.stdout.splitlines()), max_lines=bounded)
    return TmuxCaptureResult(True, lines=lines, command=cmd)


def is_pane_stale(pane: DURFPaneState, *, now: float, stale_after_s: float) -> bool:
    if pane.captured_at is None:
        return True
    return now - pane.captured_at > stale_after_s


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        log.debug("durf: failed to parse yaml %s", path, exc_info=True)
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_claims(claim_dir: Path) -> dict[str, tuple[str, str]]:
    claims: dict[str, tuple[str, str]] = {}
    for path in sorted(claim_dir.glob("cc-active-task-cx-*")):
        lane_id = path.name.removeprefix("cc-active-task-")
        if not lane_id.startswith("cx-"):
            continue
        try:
            task_id = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if task_id:
            claims[lane_id] = (task_id, str(path))
    return claims


def _parse_session_health(path: Path) -> dict[str, dict[str, str]]:
    """Parse the Codex session-health markdown table into lane rows."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    rows: dict[str, dict[str, str]] = {}
    headers: list[str] | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and cells[0] == "Session":
            headers = cells
            continue
        if headers is None or len(cells) < len(headers):
            continue
        row = dict(zip(headers, cells, strict=False))
        session = row.get("Session", "")
        if session.startswith("cx-"):
            rows[session] = row
    return rows


def _impingement_kind_for(*, relay_status: str | None, task_id: str | None, pr: str | None) -> str:
    text = f"{relay_status or ''} {task_id or ''} {pr or ''}".lower()
    if "review" in text:
        return "review"
    if "ci" in text or "check" in text:
        return "ci"
    if "merge" in text or "merged" in text:
        return "merge"
    if "block" in text or "hold" in text:
        return "blocker"
    if "checkpoint" in text or "resume" in text:
        return "resume"
    if pr and pr not in {"-", "null", "none"}:
        return "pr"
    if task_id:
        return "claim"
    return "none"


def _salience_for(lane: CodexLane) -> int:
    score = 0
    if lane.task_id:
        score += 50
    if lane.pr and lane.pr not in {"-", "null", "none"}:
        score += 25
    if lane.impingement_kind in {"review", "ci", "blocker"}:
        score += 20
    if lane.impingement_kind == "merge":
        score += 15
    if lane.lane_id == "cx-red" and lane.impingement_kind != "none":
        score += 10
    if lane.warnings and lane.warnings != "-":
        score -= 20
    return score


def _ordered_lane_ids(lane_ids: set[str]) -> list[str]:
    ordered = [lane for lane in _LANE_ORDER if lane in lane_ids]
    ordered.extend(sorted(lane_ids.difference(_LANE_ORDER)))
    return ordered


class CodexPaneRegistry:
    """Discover Codex coding-session panes from current coordination state."""

    def __init__(
        self,
        *,
        config_path: Path = DEFAULT_CONFIG_PATH,
        relay_dir: Path = DEFAULT_RELAY_DIR,
        claim_dir: Path = DEFAULT_CLAIM_DIR,
        session_health_path: Path = DEFAULT_SESSION_HEALTH_PATH,
    ) -> None:
        self.config_path = config_path
        self.relay_dir = relay_dir
        self.claim_dir = claim_dir
        self.session_health_path = session_health_path

    def _load_config(self) -> tuple[dict[str, CodexPaneConfig], int]:
        data = _read_yaml_mapping(self.config_path)
        defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
        default_capture_lines = int(defaults.get("capture_lines", _DEFAULT_CAPTURE_LINES))
        max_visible = int(defaults.get("max_visible_panes", _DEFAULT_MAX_VISIBLE_PANES))
        stale_after = float(defaults.get("stale_after_seconds", _DEFAULT_STALE_AFTER_S))
        panes: dict[str, CodexPaneConfig] = {}
        raw_panes_obj = data.get("panes")
        raw_panes = raw_panes_obj if isinstance(raw_panes_obj, list) else []
        for raw in raw_panes:
            if not isinstance(raw, dict):
                continue
            lane_id = str(raw.get("lane") or raw.get("lane_id") or raw.get("role") or "").strip()
            if not lane_id.startswith("cx-"):
                continue
            target = str(raw.get("tmux_target") or "").strip() or None
            glyph = str(raw.get("glyph") or _DEFAULT_GLYPHS.get(lane_id, lane_id[-4:].upper()))
            panes[lane_id] = CodexPaneConfig(
                lane_id=lane_id,
                tmux_target=target,
                glyph=glyph,
                enabled=bool(raw.get("enabled", True)),
                capture_lines=int(raw.get("capture_lines", default_capture_lines)),
                stale_after_s=float(raw.get("stale_after_seconds", stale_after)),
            )
        return panes, max(1, min(max_visible, _DEFAULT_MAX_VISIBLE_PANES))

    def discover_lanes(self) -> tuple[list[CodexLane], int]:
        panes, max_visible = self._load_config()
        claims = _read_claims(self.claim_dir)
        health = _parse_session_health(self.session_health_path)
        relays: dict[str, tuple[dict[str, Any], str]] = {}
        for relay_path in sorted(self.relay_dir.glob("cx-*.yaml")):
            lane_id = relay_path.stem
            if not lane_id.startswith("cx-"):
                continue
            relays[lane_id] = (_read_yaml_mapping(relay_path), str(relay_path))

        lane_ids = set(panes) | set(claims) | set(health) | set(relays)
        lanes: list[CodexLane] = []
        for lane_id in _ordered_lane_ids(lane_ids):
            config = panes.get(
                lane_id,
                CodexPaneConfig(
                    lane_id=lane_id,
                    tmux_target=None,
                    glyph=_DEFAULT_GLYPHS.get(lane_id, lane_id[-4:].upper()),
                    enabled=True,
                ),
            )
            relay, relay_ref = relays.get(lane_id, ({}, ""))
            claim_task, claim_ref = claims.get(lane_id, ("", ""))
            health_row = health.get(lane_id, {})
            relay_status = _string_or_none(relay.get("status"))
            task_id = (
                claim_task
                or _string_or_none(relay.get("task_id"))
                or _string_or_none(relay.get("current_claim"))
                or _task_id_from_health(health_row.get("Task"))
            )
            task_status = _string_or_none(health_row.get("Task status")) or relay_status
            branch = _string_or_none(relay.get("branch")) or _string_or_none(
                health_row.get("Branch")
            )
            pr = _string_or_none(relay.get("current_pr")) or _string_or_none(health_row.get("PR"))
            warnings = _string_or_none(health_row.get("Warnings"))
            source_refs: list[str] = [str(self.config_path), str(self.session_health_path)]
            if relay_ref:
                source_refs.append(relay_ref)
            if claim_ref:
                source_refs.append(claim_ref)
            impingement_kind = _impingement_kind_for(
                relay_status=relay_status,
                task_id=task_id,
                pr=pr,
            )
            volition_reason = _volition_reason(
                lane_id=lane_id,
                task_id=task_id,
                pr=pr,
                impingement_kind=impingement_kind,
                relay_status=relay_status,
            )
            lane = CodexLane(
                lane_id=lane_id,
                glyph=config.glyph,
                tmux_target=config.tmux_target,
                enabled=config.enabled,
                capture_lines=config.capture_lines,
                stale_after_s=config.stale_after_s,
                relay_status=relay_status,
                task_id=task_id,
                task_status=task_status,
                branch=branch,
                pr=pr,
                warnings=warnings,
                source_refs=tuple(dict.fromkeys(source_refs)),
                impingement_kind=impingement_kind,
                volition_reason=volition_reason,
            )
            lanes.append(replace(lane, salience=_salience_for(lane)))
        return lanes, max_visible


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "-", "null", "None"}:
        return None
    return text


def _task_id_from_health(value: str | None) -> str | None:
    text = _string_or_none(value)
    if text is None:
        return None
    em_dash_separator = " " + chr(8212) + " "
    if em_dash_separator in text:
        return text.split(em_dash_separator, 1)[0].strip()
    if " - " in text:
        return text.split(" - ", 1)[0].strip()
    return text


def _volition_reason(
    *,
    lane_id: str,
    task_id: str | None,
    pr: str | None,
    impingement_kind: str,
    relay_status: str | None,
) -> str:
    if pr:
        return f"{lane_id} {impingement_kind} signal for PR {pr}"
    if task_id:
        return f"{lane_id} active task {task_id}"
    if relay_status:
        return f"{lane_id} relay status {relay_status}"
    return f"{lane_id} metadata only"


def _suppressed_lane(lane: CodexLane, reason: str, *, now: float) -> DURFPaneState:
    return DURFPaneState(
        lane_id=lane.lane_id,
        glyph=lane.glyph,
        tmux_target=lane.tmux_target,
        visible=False,
        captured_at=now,
        redaction_state="suppressed",
        suppressed_reason=reason,
        source_refs=lane.source_refs,
        impingement_kind=lane.impingement_kind,
        volition_reason=lane.volition_reason,
    )


def _pane_state_from_capture(lane: CodexLane, *, now: float) -> DURFPaneState:
    if not lane.enabled:
        return _suppressed_lane(lane, "lane_disabled", now=now)
    if not lane.has_work_signal:
        return _suppressed_lane(lane, "lane_ineligible", now=now)
    if not lane.tmux_target:
        return _suppressed_lane(lane, "tmux_target_unconfigured", now=now)
    capture = capture_tmux_text(lane.tmux_target, capture_lines=lane.capture_lines)
    if not capture.ok:
        return _suppressed_lane(lane, capture.reason or "tmux_capture_failed", now=now)
    redaction = redact_terminal_lines(capture.lines)
    if redaction.action is not RedactionAction.CLEAN:
        return DURFPaneState(
            lane_id=lane.lane_id,
            glyph=lane.glyph,
            tmux_target=lane.tmux_target,
            visible=False,
            captured_at=now,
            redaction_state=redaction.action.value,
            suppressed_reason=redaction.matched_pattern or "redaction_failed",
            source_refs=lane.source_refs,
            impingement_kind=lane.impingement_kind,
            volition_reason=lane.volition_reason,
        )
    return DURFPaneState(
        lane_id=lane.lane_id,
        glyph=lane.glyph,
        tmux_target=lane.tmux_target,
        visible=bool(redaction.lines),
        lines=redaction.lines,
        captured_at=now,
        redaction_state="clean",
        suppressed_reason=None if redaction.lines else "empty_tmux_buffer",
        source_refs=lane.source_refs,
        impingement_kind=lane.impingement_kind,
        volition_reason=lane.volition_reason,
    )


def build_wcs_row(
    panes: tuple[DURFPaneState, ...],
    *,
    now: float,
    egress_allowed: bool,
    max_visible: int = _DEFAULT_MAX_VISIBLE_PANES,
) -> dict[str, Any]:
    visible = [pane for pane in panes if pane.visible]
    suppressed = [pane for pane in panes if not pane.visible]
    redaction_state = "clean"
    if any(p.redaction_state == RedactionAction.UNAVAILABLE.value for p in panes):
        redaction_state = "unavailable"
    elif any(p.redaction_state == RedactionAction.SUPPRESS.value for p in panes):
        redaction_state = "suppressed"
    latest_ts = max((pane.captured_at or 0.0 for pane in panes), default=0.0) or None
    source_refs: list[str] = []
    for pane in panes:
        source_refs.extend(pane.source_refs)
    primary = visible[0] if visible else None
    if not egress_allowed:
        mode = "suppressed"
    elif visible:
        mode = "text_panes"
    else:
        mode = "metadata"
    return {
        "surface_id": "coding_sessions.durf",
        "mode": mode,
        "impingement_kind": primary.impingement_kind if primary else "none",
        "volition_reason": primary.volition_reason if primary else "no eligible clean pane",
        "visible_lanes": [pane.lane_id for pane in visible[:max_visible]],
        "suppressed_lanes": [
            {
                "lane_id": pane.lane_id,
                "reason": pane.suppressed_reason or "not_visible",
                "redaction_state": pane.redaction_state,
            }
            for pane in suppressed
        ],
        "source_refs": sorted(set(source_refs)),
        "freshness_ts": _iso_ts(latest_ts),
        "public_claim_ceiling": "work_trace_visible",
        "redaction_state": redaction_state,
        "egress_allowed": egress_allowed and bool(visible),
        "max_visible_panes": max_visible,
        "updated_at": _iso_ts(now),
    }


def _select_lanes(
    lanes: list[CodexLane], max_visible: int
) -> tuple[list[CodexLane], list[CodexLane]]:
    eligible = [lane for lane in lanes if lane.enabled and lane.has_work_signal]
    ranked = sorted(
        eligible,
        key=lambda lane: (
            -lane.salience,
            _LANE_ORDER.index(lane.lane_id) if lane.lane_id in _LANE_ORDER else 99,
        ),
    )
    return ranked[:max_visible], ranked[max_visible:]


def _line_color(line: str) -> tuple[float, float, float, float]:
    from .homage.rendering import active_package

    pkg = active_package()
    low = line.lower()
    if "error" in low or "failed" in low or "traceback" in low:
        color = pkg.palette.accent_red
    elif "passed" in low or "success" in low or "green" in low:
        color = pkg.palette.accent_green
    elif "uv run" in low or "pytest" in low or "ruff" in low or "git " in low:
        color = pkg.palette.accent_cyan
    elif line.strip().startswith((">", "$")):
        color = pkg.palette.bright
    else:
        color = pkg.palette.muted
    return (color[0], color[1], color[2], 0.92)


def _layout_for_count(n: int, canvas_w: int, canvas_h: int) -> list[tuple[int, int, int, int]]:
    if n <= 0:
        return []
    margin = 48
    gap = 26
    if n == 1:
        return [(margin, margin, canvas_w - margin * 2, canvas_h - margin * 2)]
    if n == 2:
        w = (canvas_w - margin * 2 - gap) // 2
        return [
            (margin, margin + 70, w, canvas_h - margin * 2 - 120),
            (margin + w + gap, margin, w, canvas_h - margin * 2 - 80),
        ]
    foreground_w = int(canvas_w * 0.58)
    left_w = canvas_w - foreground_w - margin * 2 - gap
    foreground = (margin + left_w + gap, margin, foreground_w, canvas_h - margin * 2)
    stack_count = min(n - 1, 3)
    stack_h = (canvas_h - margin * 2 - gap * (stack_count - 1)) // stack_count
    rects = [foreground]
    for idx in range(stack_count):
        rects.append((margin, margin + idx * (stack_h + gap), left_w, stack_h))
    return rects[:n]


# ── Backward-compat alias (cc-task `activity-reveal-ward-p1-durf-migration`) ──
#
# The class formerly defined here moved to
# ``agents.studio_compositor.coding_activity_reveal.CodingActivityReveal``
# to integrate with the activity-reveal-ward family base mixin
# (``ActivityRevealMixin``). ``DURFCairoSource`` is preserved as a
# module-level attribute so existing layout-JSON declarations + import
# paths keep working without any caller-side change.
#
# The import is implemented through module ``__getattr__`` rather than a
# top-level ``import`` to break the circular dependency:
# ``coding_activity_reveal`` imports helpers from this module on its own
# load, so a top-level back-import here would deadlock the
# partially-initialised ``coding_activity_reveal``. Lazy resolution +
# first-access caching keeps the alias hot in steady-state without the
# cycle.


def __getattr__(name: str):  # noqa: D401 — module-level __getattr__ contract
    """Lazy attribute resolution for the ``DURFCairoSource`` and
    ``CodingActivityReveal`` aliases.

    Triggered when an ``import`` / ``getattr`` resolution misses a
    direct module attribute. The lift target is resolved on first
    access, cached on the module dict, and returned.
    """

    if name in ("DURFCairoSource", "CodingActivityReveal"):
        from agents.studio_compositor.coding_activity_reveal import (
            CodingActivityReveal as _CAR,
        )

        globals()["CodingActivityReveal"] = _CAR
        globals()["DURFCairoSource"] = _CAR
        return _CAR
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CodexLane",
    "CodexPaneConfig",
    "CodexPaneRegistry",
    "CodingActivityReveal",  # noqa: F822 — resolved via module __getattr__
    "DURFCairoSource",  # noqa: F822 — resolved via module __getattr__
    "DURFPaneState",
    "DURFSourceSnapshot",
    "TextRedactionResult",
    "TmuxCaptureResult",
    "build_wcs_row",
    "capture_tmux_text",
    "is_pane_stale",
    "redact_terminal_lines",
    "sanitize_terminal_lines",
]
