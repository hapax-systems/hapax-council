"""Assertion Receipt Ward — content pipeline decision receipts on-stream.

Renders the most recent LayoutDecisionReceipt from
``/dev/shm/hapax-compositor/segment-layout-receipt.json`` as a
checklist-style ward overlay. Ward-as-checklist, NOT ward-as-narration
(per ``feedback_show_dont_tell_director``).

The receipt is written atomically by ``layout_tick_driver`` every 30s
(or on each responsible-segment layout decision). This ward polls at
1Hz and renders a compact status view:

- Status badge (ACCEPTED / HELD / REFUSED / FALLBACK)
- Decision reason tag
- Current/previous layout
- Evidence and readback ref counts
- Unsatisfied effects
- Refusal summary (when refused)

cc-task: avsdlc-004.
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

RECEIPT_SHM_FILE = Path("/dev/shm/hapax-compositor/segment-layout-receipt.json")

_POLL_INTERVAL_S: float = 1.0
_ENTER_RAMP_S: float = 0.5
_EXIT_RAMP_S: float = 0.6
_FRONTED_ALPHA: float = 0.85

_FONT_HEADER: str = "JetBrains Mono Bold 13"
_FONT_LABEL: str = "JetBrains Mono 11"
_FONT_VALUE: str = "JetBrains Mono Bold 11"
_FONT_DETAIL: str = "JetBrains Mono 10"

_STATUS_COLORS: dict[str, tuple[float, float, float]] = {
    "accepted": (0.72, 0.87, 0.53),
    "held": (0.98, 0.74, 0.02),
    "refused": (0.98, 0.29, 0.20),
    "fallback": (0.91, 0.56, 0.26),
}


@dataclass(frozen=True)
class ReceiptSnapshot:
    status: str
    reason: str
    selected_posture: str | None
    selected_layout: str | None
    previous_layout: str | None
    evidence_count: int
    input_count: int
    readback_count: int
    satisfied_count: int
    unsatisfied: tuple[str, ...]
    denied_intents: tuple[str, ...]
    applied_layout_changes: tuple[str, ...]
    applied_ward_changes: tuple[str, ...]
    has_refusal: bool
    refusal_summary: str
    has_safety: bool
    read_at: float


_EMPTY = ReceiptSnapshot(
    status="",
    reason="",
    selected_posture=None,
    selected_layout=None,
    previous_layout=None,
    evidence_count=0,
    input_count=0,
    readback_count=0,
    satisfied_count=0,
    unsatisfied=(),
    denied_intents=(),
    applied_layout_changes=(),
    applied_ward_changes=(),
    has_refusal=False,
    refusal_summary="",
    has_safety=False,
    read_at=0.0,
)


def _read_receipt(path: Path = RECEIPT_SHM_FILE) -> ReceiptSnapshot:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _EMPTY
    if not isinstance(raw, dict) or not raw.get("status"):
        return _EMPTY

    refusal = raw.get("refusal", {})
    refusal_summary = ""
    if isinstance(refusal, dict):
        proposals = refusal.get("proposal_refusals", [])
        if proposals and isinstance(proposals, list):
            reasons = []
            for p in proposals[:3]:
                if isinstance(p, dict) and p.get("reason"):
                    reasons.append(str(p["reason"]))
            refusal_summary = "; ".join(reasons)
        elif refusal.get("message"):
            refusal_summary = str(refusal["message"])[:120]

    def _strs(key: str) -> tuple[str, ...]:
        val = raw.get(key, [])
        return tuple(str(v) for v in val) if isinstance(val, list) else ()

    return ReceiptSnapshot(
        status=str(raw.get("status", "")),
        reason=str(raw.get("reason", "")),
        selected_posture=raw.get("selected_posture"),
        selected_layout=raw.get("selected_layout"),
        previous_layout=raw.get("previous_layout"),
        evidence_count=len(raw.get("evidence_refs", [])),
        input_count=len(raw.get("input_refs", [])),
        readback_count=len(raw.get("readback_refs", [])),
        satisfied_count=len(raw.get("satisfied_effects", [])),
        unsatisfied=_strs("unsatisfied_effects"),
        denied_intents=_strs("denied_intents"),
        applied_layout_changes=_strs("applied_layout_changes"),
        applied_ward_changes=_strs("applied_ward_changes"),
        has_refusal=bool(refusal),
        refusal_summary=refusal_summary,
        has_safety=bool(raw.get("safety_arbitration")),
        read_at=time.time(),
    )


def _reason_label(reason: str) -> str:
    return reason.replace("_", " ").upper()


class AssertionReceiptWard(HomageTransitionalSource):
    """Checklist-style ward rendering content pipeline assertion receipts."""

    def __init__(
        self,
        *,
        receipt_file: Path = RECEIPT_SHM_FILE,
        start_thread: bool = True,
    ) -> None:
        HomageTransitionalSource.__init__(
            self,
            source_id="assertion-receipt",
            entering_duration_s=_ENTER_RAMP_S,
            exiting_duration_s=_EXIT_RAMP_S,
        )
        self._receipt_file = receipt_file
        self._snapshot: ReceiptSnapshot = _EMPTY
        self._snapshot_lock = threading.Lock()
        self._gate_off_since: float | None = None
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="assertion-receipt-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("assertion-receipt: poll failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def _poll_once(self, *, now: float | None = None) -> ReceiptSnapshot:
        ts = time.monotonic() if now is None else now
        snap = _read_receipt(self._receipt_file)
        with self._snapshot_lock:
            self._snapshot = snap
        gate = snap.status != ""
        self._maybe_drive_fsm(gate, now=ts)
        return snap

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)

    def _maybe_drive_fsm(self, gate: bool, *, now: float) -> None:
        if gate:
            self._gate_off_since = None
            if self._state in (TransitionState.ABSENT, TransitionState.EXITING):
                try:
                    self.apply_transition("segment-enter", now=now)
                except Exception:
                    log.debug("assertion-receipt: FSM enter failed", exc_info=True)
            return
        if self._gate_off_since is None:
            self._gate_off_since = now
            return
        if now - self._gate_off_since >= 5.0 and self._state in (
            TransitionState.HOLD,
            TransitionState.ENTERING,
        ):
            try:
                self.apply_transition("segment-exit", now=now)
            except Exception:
                log.debug("assertion-receipt: FSM exit failed", exc_info=True)

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._snapshot_lock:
            snap = self._snapshot
        alpha = self._compute_alpha(now)
        return {"alpha": alpha, "now": now, "snapshot": snap}

    def _compute_alpha(self, now: float) -> float:
        if self._state is TransitionState.ABSENT:
            return 0.0
        if self._state is TransitionState.HOLD:
            with self._snapshot_lock:
                gate = self._snapshot.status != ""
            return _FRONTED_ALPHA if gate else 0.0
        progress = self._progress(now=now)
        if self._state is TransitionState.ENTERING:
            return _FRONTED_ALPHA * progress
        return _FRONTED_ALPHA * (1.0 - progress)

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
        if alpha <= 0.001:
            return
        snap: ReceiptSnapshot = state.get("snapshot", _EMPTY)
        if not snap.status:
            return

        from agents.studio_compositor.homage.rendering import active_package

        pkg = active_package()
        bg = pkg.palette.background
        muted = pkg.palette.muted
        bright = pkg.palette.bright

        status_rgb = _STATUS_COLORS.get(snap.status, muted)

        margin = 16
        panel_w = min(canvas_w - margin * 2, 420)
        panel_x = margin
        panel_y = margin

        y_cursor = panel_y + 14
        line_h = 18
        header_h = 22
        rows = 4  # status, reason, layout, refs
        if snap.unsatisfied:
            rows += 1
        if snap.has_refusal and snap.refusal_summary:
            rows += min(len(snap.refusal_summary) // 50 + 1, 3)
        if snap.denied_intents:
            rows += 1
        if snap.applied_layout_changes or snap.applied_ward_changes:
            rows += 1
        panel_h = header_h + rows * line_h + 24

        cr.save()
        cr.set_source_rgba(bg[0], bg[1], bg[2], 0.78 * alpha)
        cr.rectangle(panel_x, panel_y, panel_w, panel_h)
        cr.fill()

        cr.set_source_rgba(status_rgb[0], status_rgb[1], status_rgb[2], 0.9 * alpha)
        cr.rectangle(panel_x, panel_y, 3, panel_h)
        cr.fill()
        cr.restore()

        inner_x = panel_x + 12
        max_tw = panel_w - 24

        render_text(
            cr,
            TextStyle(
                text="ASSERTION RECEIPT",
                font_description=_FONT_HEADER,
                color_rgba=(status_rgb[0], status_rgb[1], status_rgb[2], 0.95 * alpha),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.7 * alpha),
                outline_offsets=OUTLINE_OFFSETS_4,
                max_width_px=max(1, max_tw),
            ),
            inner_x,
            y_cursor,
        )
        y_cursor += header_h

        def _row(
            label: str, value: str, *, color: tuple[float, float, float] | None = None
        ) -> None:
            nonlocal y_cursor
            c = color or muted
            render_text(
                cr,
                TextStyle(
                    text=f"{label}: ",
                    font_description=_FONT_LABEL,
                    color_rgba=(muted[0], muted[1], muted[2], 0.7 * alpha),
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.5 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max(1, max_tw),
                ),
                inner_x,
                y_cursor,
            )
            render_text(
                cr,
                TextStyle(
                    text=value,
                    font_description=_FONT_VALUE,
                    color_rgba=(c[0], c[1], c[2], 0.9 * alpha),
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.6 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max(1, max_tw),
                ),
                inner_x + 100,
                y_cursor,
            )
            y_cursor += line_h

        _row("STATUS", snap.status.upper(), color=status_rgb)
        _row("REASON", _reason_label(snap.reason), color=bright)

        layout_str = snap.selected_layout or snap.previous_layout or "—"
        if (
            snap.previous_layout
            and snap.selected_layout
            and snap.previous_layout != snap.selected_layout
        ):
            layout_str = f"{snap.previous_layout} -> {snap.selected_layout}"
        _row("LAYOUT", layout_str)

        refs = (
            f"ev:{snap.evidence_count} in:{snap.input_count}"
            f" rb:{snap.readback_count} sat:{snap.satisfied_count}"
        )
        _row("REFS", refs)

        if snap.unsatisfied:
            _row("UNSAT", ", ".join(snap.unsatisfied), color=_STATUS_COLORS["refused"])

        if snap.denied_intents:
            denied = ", ".join(d[:30] for d in snap.denied_intents[:3])
            _row("DENIED", denied, color=_STATUS_COLORS["refused"])

        changes: list[str] = []
        changes.extend(f"L:{c}" for c in snap.applied_layout_changes[:2])
        changes.extend(f"W:{c}" for c in snap.applied_ward_changes[:2])
        if changes:
            _row("APPLIED", ", ".join(changes), color=_STATUS_COLORS["accepted"])

        if snap.has_refusal and snap.refusal_summary:
            summary = snap.refusal_summary[:100]
            render_text(
                cr,
                TextStyle(
                    text=summary,
                    font_description=_FONT_DETAIL,
                    color_rgba=(
                        _STATUS_COLORS["refused"][0],
                        _STATUS_COLORS["refused"][1],
                        _STATUS_COLORS["refused"][2],
                        0.7 * alpha,
                    ),
                    outline_color_rgba=(0.0, 0.0, 0.0, 0.5 * alpha),
                    outline_offsets=OUTLINE_OFFSETS_4,
                    max_width_px=max(1, max_tw),
                    wrap="word",
                ),
                inner_x,
                y_cursor,
            )


__all__ = ["AssertionReceiptWard", "ReceiptSnapshot", "RECEIPT_SHM_FILE"]
