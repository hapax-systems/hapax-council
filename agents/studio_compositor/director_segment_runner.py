"""Director segment runner for programme beat -> compositor binding.

The programme loop writes the active segmented programme beat to shared
memory. This runner is the compositor-side bridge that turns the current
beat's proposal-only layout intents into bounded compositor control-plane
commands. It deliberately delegates policy to ``segment_layout_control``:
prepared artifacts may propose visible needs, but runtime readback and the
responsibility controller decide whether a layout command is admissible.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from agents.studio_compositor import layout_tick_driver
from agents.studio_compositor.segment_layout_control import (
    DEFAULT_HYSTERESIS_S,
    DEFAULT_READBACK_TTL_S,
    LayoutDecisionReason,
    LayoutDecisionStatus,
    LayoutPosture,
    LayoutResponsibilityController,
    SegmentLayoutState,
)

log = logging.getLogger(__name__)

ENV_DISABLE = "HAPAX_DIRECTOR_SEGMENT_RUNNER_DISABLED"
DEFAULT_RUNNER_INTERVAL_S = 1.0
DEFAULT_PROMPT_BINDING_TTL_S = 15.0

ACTIVE_SEGMENT_FILE = Path("/dev/shm/hapax-compositor/active-segment.json")
RECEIPT_FILE = Path("/dev/shm/hapax-compositor/director-segment-runner-receipt.json")
PROMPT_BINDING_FILE = Path("/dev/shm/hapax-compositor/director-segment-binding.json")
COMMAND_JSONL = Path("/dev/shm/hapax-compositor/director-segment-commands.jsonl")

LAYOUT_REPAIR_REASONS: frozenset[LayoutDecisionReason] = frozenset(
    {
        LayoutDecisionReason.DEFAULT_STATIC_LAYOUT_IN_RESPONSIBLE_HOSTING,
        LayoutDecisionReason.RENDERED_READBACK_MISMATCH,
        LayoutDecisionReason.SAFETY_FALLBACK,
        LayoutDecisionReason.EXPLICIT_FALLBACK,
    }
)


class SegmentCommandSink(Protocol):
    """Callable sink for compositor control-plane commands."""

    def __call__(self, command: DirectorSegmentCommand) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DirectorSegmentCommand:
    """One compositor control-plane command emitted for a programme beat."""

    command: str
    args: dict[str, Any]
    programme_id: str | None
    beat_index: int | None
    reason: str
    need_id: str | None
    selected_layout: str

    @property
    def key(self) -> tuple[str | None, int | None, str | None, str, str]:
        return (
            self.programme_id,
            self.beat_index,
            self.need_id,
            self.selected_layout,
            self.reason,
        )

    @property
    def wire_payload(self) -> dict[str, Any]:
        return {"command": self.command, "args": dict(self.args)}

    @property
    def log_payload(self) -> dict[str, Any]:
        return {
            **self.wire_payload,
            "programme_id": self.programme_id,
            "beat_index": self.beat_index,
            "reason": self.reason,
            "need_id": self.need_id,
            "selected_layout": self.selected_layout,
        }


class DirectorSegmentRunner:
    """Poll active segment state and dispatch bounded layout commands."""

    def __init__(
        self,
        *,
        layout_state: Any,
        available_layouts: Callable[[], Iterable[str]],
        command_sink: SegmentCommandSink,
        segment_state_path: Path = ACTIVE_SEGMENT_FILE,
        receipt_path: Path = RECEIPT_FILE,
        prompt_binding_path: Path = PROMPT_BINDING_FILE,
        command_jsonl_path: Path = COMMAND_JSONL,
        interval_s: float = DEFAULT_RUNNER_INTERVAL_S,
        hysteresis_s: float = DEFAULT_HYSTERESIS_S,
        readback_ttl_s: float = DEFAULT_READBACK_TTL_S,
    ) -> None:
        self.layout_state = layout_state
        self.available_layouts = available_layouts
        self.command_sink = command_sink
        self.segment_state_path = Path(segment_state_path)
        self.receipt_path = Path(receipt_path)
        self.prompt_binding_path = Path(prompt_binding_path)
        self.command_jsonl_path = Path(command_jsonl_path)
        self.interval_s = interval_s
        self.hysteresis_s = hysteresis_s
        self.readback_ttl_s = readback_ttl_s
        self._responsible_state: dict[str, Any] = {}
        self._last_successful_command_key: (
            tuple[str | None, int | None, str | None, str, str] | None
        ) = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> threading.Thread:
        """Start the polling loop in a daemon thread."""

        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run_forever,
            daemon=True,
            name="director-segment-runner",
        )
        self._thread.start()
        return self._thread

    def stop(self, timeout_s: float = 2.0) -> None:
        """Stop the polling loop."""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        self._thread = None

    def run_forever(self) -> None:
        """Run until :meth:`stop` is called."""

        log.info("director segment runner started (interval=%.1fs)", self.interval_s)
        while not self._stop.is_set():
            try:
                self.process_once()
            except Exception:
                log.warning("director segment runner tick failed; loop continues", exc_info=True)
            self._stop.wait(self.interval_s)

    def process_once(self, *, now: float | None = None) -> dict[str, Any] | None:
        """Process the current active segment state once.

        Returns the receipt payload written for this tick, or ``None`` when
        there is no active segmented programme pressure.
        """

        ts = time.time() if now is None else now
        raw_segment = _read_json_object(self.segment_state_path)
        pressure = layout_tick_driver._read_segment_layout_pressure(
            self.segment_state_path,
            now=ts,
        )
        pressure_seen = bool(pressure.get("segment_layout_pressure_seen")) or bool(
            pressure.get("segment_layout_refusals")
        )
        intents = pressure.get("segment_layout_intents")
        intent_tuple = intents if isinstance(intents, tuple) else ()
        if not pressure_seen and not intent_tuple:
            return None

        readback = layout_tick_driver._runtime_layout_readback(
            layout_state=self.layout_state,
            state=pressure,
            now=ts,
        )
        decision_state = SegmentLayoutState(
            current_layout=readback.active_layout,
            current_posture=self._responsible_state.get("current_posture")
            or _posture_for_layout(readback.active_layout),
            active_need_id=_optional_str(self._responsible_state.get("active_need_id")),
            active_priority=_optional_int(self._responsible_state.get("active_priority")) or 0,
            switched_at=_optional_float(self._responsible_state.get("switched_at")),
        )
        controller = LayoutResponsibilityController(
            available_layouts=tuple(self.available_layouts()),
            hysteresis_s=self.hysteresis_s,
            readback_ttl_s=self.readback_ttl_s,
        )
        receipt = controller.decide(
            intent_tuple,
            readback=readback,
            state=decision_state,
            now=ts,
        )
        proposal_refusals = _proposal_refusals(pressure.get("segment_layout_refusals"))
        if proposal_refusals:
            receipt = replace(
                receipt,
                refusal_metadata={
                    **dict(receipt.refusal_metadata),
                    "proposal_refusals": proposal_refusals,
                },
            )

        command = self._command_for_receipt(receipt, raw_segment=raw_segment)
        command_result: dict[str, Any] | None = None
        if command is not None:
            command_result = self._dispatch_command(command, now=ts)
            if command_result.get("status") == "ok":
                self._responsible_state.update(
                    {
                        "current_posture": receipt.selected_posture,
                        "active_need_id": receipt.need_id,
                        "active_priority": _intent_priority(intent_tuple, receipt.need_id),
                        "switched_at": ts,
                    }
                )
        elif receipt.status is LayoutDecisionStatus.ACCEPTED:
            self._responsible_state.update(
                {
                    "current_posture": receipt.selected_posture,
                    "active_need_id": receipt.need_id,
                    "active_priority": _intent_priority(intent_tuple, receipt.need_id),
                    "switched_at": self._responsible_state.get("switched_at") or ts,
                }
            )

        payload = self._receipt_payload(
            receipt=receipt,
            raw_segment=raw_segment,
            command=command,
            command_result=command_result,
            now=ts,
        )
        _write_json_atomic(self.receipt_path, payload)
        _write_json_atomic(self.prompt_binding_path, _prompt_binding_payload(payload, now=ts))
        return payload

    def _command_for_receipt(
        self,
        receipt: Any,
        *,
        raw_segment: dict[str, Any],
    ) -> DirectorSegmentCommand | None:
        selected_layout = receipt.selected_layout
        if not isinstance(selected_layout, str) or not selected_layout:
            return None
        active_layout = receipt.receipt_metadata.get("active_layout_readback")
        if active_layout == selected_layout and receipt.reason not in {
            LayoutDecisionReason.SAFETY_FALLBACK,
            LayoutDecisionReason.EXPLICIT_FALLBACK,
        }:
            return None
        if receipt.reason not in LAYOUT_REPAIR_REASONS:
            return None
        return DirectorSegmentCommand(
            command="compositor.layout.activate",
            args={
                "layout_name": selected_layout,
                "source": "director_segment_runner",
                "programme_id": _optional_str(raw_segment.get("programme_id")),
                "beat_index": _optional_int(raw_segment.get("current_beat_index")),
                "need_id": receipt.need_id,
                "need_kind": receipt.need_kind,
                "reason": receipt.reason.value,
                "authority": "runtime_layout_responsibility",
            },
            programme_id=_optional_str(raw_segment.get("programme_id")),
            beat_index=_optional_int(raw_segment.get("current_beat_index")),
            reason=receipt.reason.value,
            need_id=receipt.need_id,
            selected_layout=selected_layout,
        )

    def _dispatch_command(
        self,
        command: DirectorSegmentCommand,
        *,
        now: float,
    ) -> dict[str, Any]:
        if command.key == self._last_successful_command_key:
            return {"status": "skipped", "reason": "duplicate_successful_command"}
        try:
            result = self.command_sink(command)
        except Exception as exc:
            result = {"status": "error", "error": type(exc).__name__, "detail": str(exc)}
        log_payload = {
            "ts": now,
            **command.log_payload,
            "result": result,
        }
        _append_jsonl(self.command_jsonl_path, log_payload)
        if result.get("status") == "ok":
            self._last_successful_command_key = command.key
        return result

    def _receipt_payload(
        self,
        *,
        receipt: Any,
        raw_segment: dict[str, Any],
        command: DirectorSegmentCommand | None,
        command_result: dict[str, Any] | None,
        now: float,
    ) -> dict[str, Any]:
        visible = dict(receipt.visible_metadata)
        visible.update(
            {
                "observed_at": now,
                "programme_id": _optional_str(raw_segment.get("programme_id")),
                "beat_index": _optional_int(raw_segment.get("current_beat_index")),
                "role": _optional_str(raw_segment.get("role")),
                "topic": _optional_str(raw_segment.get("topic")),
                "prepared_artifact_ref": _prepared_artifact_ref(raw_segment),
            }
        )
        if command is not None:
            visible["command"] = command.log_payload
        if command_result is not None:
            visible["command_result"] = command_result
        visible["binding_contract"] = {
            "prepared_layout_intents_are_authority": False,
            "runtime_readback_required": True,
            "command_surface": "compositor.layout.activate",
            "grants_playback_authority": False,
            "grants_audio_authority": False,
        }
        return visible


def compositor_command_sink(socket_path: Path, *, timeout_s: float = 2.0) -> SegmentCommandSink:
    """Build a command sink backed by ``CompositorCommandClient``."""

    from agents.studio_compositor.command_client import CompositorCommandClient

    client = CompositorCommandClient(Path(socket_path), timeout_s=timeout_s)

    def _sink(command: DirectorSegmentCommand) -> dict[str, Any]:
        return client.execute(command.command, command.args)

    return _sink


def maybe_start_director_segment_runner(
    compositor: Any,
    *,
    command_socket_path: Path,
) -> DirectorSegmentRunner | None:
    """Start the runner for a ``StudioCompositor`` instance when available."""

    if _env_disabled():
        log.info("director segment runner disabled via %s", ENV_DISABLE)
        return None
    layout_state = getattr(compositor, "layout_state", None)
    store = getattr(compositor, "_layout_store", None)
    if layout_state is None or store is None:
        log.warning("director segment runner not started: layout_state or layout_store missing")
        return None
    existing = getattr(compositor, "_director_segment_runner", None)
    if existing is not None:
        return existing
    runner = DirectorSegmentRunner(
        layout_state=layout_state,
        available_layouts=store.list_available,
        command_sink=compositor_command_sink(command_socket_path),
    )
    runner.start()
    compositor._director_segment_runner = runner
    return runner


def render_director_segment_binding_prompt(
    *,
    path: Path = PROMPT_BINDING_FILE,
    now: float | None = None,
    ttl_s: float = DEFAULT_PROMPT_BINDING_TTL_S,
) -> list[str]:
    """Render a compact read-only prompt block for the director loop."""

    ts = time.time() if now is None else now
    payload = _read_json_object(path)
    if not payload:
        return []
    observed_at = _optional_float(payload.get("observed_at"))
    if observed_at is None or ts - observed_at > ttl_s:
        return []
    programme_id = _optional_str(payload.get("programme_id")) or "unknown"
    beat_index = _optional_int(payload.get("beat_index"))
    selected_layout = _optional_str(payload.get("selected_layout")) or "none"
    status = _optional_str(payload.get("status")) or "unknown"
    reason = _optional_str(payload.get("reason")) or "unknown"
    command_result = (
        payload.get("command_result") if isinstance(payload.get("command_result"), dict) else {}
    )
    command_status = command_result.get("status") if isinstance(command_result, dict) else None
    lines = [
        "## Segment director binding",
        f"- active beat: `{programme_id}` beat `{beat_index if beat_index is not None else 'unknown'}`",
        f"- runtime layout receipt: `{status}` / `{reason}` -> `{selected_layout}`",
    ]
    if command_status:
        lines.append(f"- compositor command result: `{command_status}`")
    lines.append(
        "- prepared layout intent is proposal-only; runtime readback and receipts decide layout."
    )
    return lines


def _env_disabled() -> bool:
    return os.environ.get(ENV_DISABLE, "").strip().lower() in {"1", "true", "yes", "on"}


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.debug("director segment runner write failed: %s", path, exc_info=True)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        log.debug("director segment runner command log append failed", exc_info=True)


def _prompt_binding_payload(payload: dict[str, Any], *, now: float) -> dict[str, Any]:
    keys = {
        "status",
        "reason",
        "selected_posture",
        "selected_layout",
        "previous_layout",
        "need_id",
        "need_kind",
        "programme_id",
        "beat_index",
        "role",
        "topic",
        "prepared_artifact_ref",
        "command_result",
        "binding_contract",
    }
    return {key: payload[key] for key in keys if key in payload} | {"observed_at": now}


def _proposal_refusals(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, tuple | list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _posture_for_layout(layout_name: str | None) -> LayoutPosture | None:
    if layout_name is None:
        return None
    from agents.studio_compositor.segment_layout_control import POSTURE_TO_LAYOUT

    for posture, posture_layout in POSTURE_TO_LAYOUT.items():
        if posture_layout == layout_name:
            return posture
    return None


def _intent_priority(intents: tuple[Any, ...], need_id: str | None) -> int:
    if need_id is None:
        return 0
    for intent in intents:
        if getattr(intent, "intent_id", None) == need_id:
            return _optional_int(getattr(intent, "priority", None)) or 0
    return 0


def _prepared_artifact_ref(raw_segment: dict[str, Any]) -> str | None:
    value = raw_segment.get("prepared_artifact_ref")
    if isinstance(value, dict):
        sha = _optional_str(value.get("artifact_sha256")) or _optional_str(value.get("sha256"))
        return f"prepared_artifact:{sha}" if sha else None
    text = _optional_str(value)
    if text is None:
        return None
    return text if text.startswith("prepared_artifact:") else f"prepared_artifact:{text}"


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ACTIVE_SEGMENT_FILE",
    "COMMAND_JSONL",
    "DEFAULT_RUNNER_INTERVAL_S",
    "DirectorSegmentCommand",
    "DirectorSegmentRunner",
    "ENV_DISABLE",
    "PROMPT_BINDING_FILE",
    "RECEIPT_FILE",
    "compositor_command_sink",
    "maybe_start_director_segment_runner",
    "render_director_segment_binding_prompt",
]
