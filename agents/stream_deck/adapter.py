"""Stream Deck control surface adapter - Phase 1 (task #140).

Owns the manifest (Pydantic-validated YAML) and the synchronous
``on_key_press(slot: int)`` entry point that physical Stream Deck
hardware — or any Phase 2 bridge — will drive. Key-presses resolve to
a single ``(command, args)`` pair and are dispatched to the Logos
control plane through Logos API or an explicit local compositor handler.

Deliberately thin: the adapter holds no studio / compositor state; it
is a routing table plus a dispatcher. Phase 2 will register key-image
rendering and the real ``streamdeck`` library as a device driver.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from shared.logos_control_dispatch import DEFAULT_LOGOS_API_BASE_URL, dispatch_logos_control
from shared.telemetry import hapax_span

log = logging.getLogger(__name__)

DEFAULT_CONTROL_BASE_URL = DEFAULT_LOGOS_API_BASE_URL

# StreamDeck Mini is a 3×5 matrix. Phase 2 can extend by adding new
# device rows here; the adapter checks the declared device against the
# slot range at manifest-load time.
_DEVICE_SLOT_COUNTS: dict[str, int] = {
    "mini": 15,
    "xl": 32,  # reserved for Phase 2 — bounds-checking is already correct.
}


# ── Manifest model ──────────────────────────────────────────────────────────


class StreamDeckKey(BaseModel):
    """A single physical-key → command mapping."""

    slot: int = Field(..., ge=0, description="0-indexed key position, top-left → bottom-right")
    label: str = Field("", description="Operator-facing label, also included in logs")
    icon: str | None = Field(None, description="Advisory icon filename for Phase 2 key rendering")
    command: str = Field(..., min_length=1, description="Dotted command-registry name")
    args: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True, "extra": "forbid"}


class StreamDeckManifest(BaseModel):
    """Full manifest covering every physical key on one Stream Deck device."""

    version: int = Field(..., ge=1)
    device: str = Field(..., description="StreamDeck model identifier (e.g. 'mini', 'xl')")
    keys: list[StreamDeckKey]

    model_config = {"extra": "forbid"}

    @field_validator("device")
    @classmethod
    def _known_device(cls, value: str) -> str:
        if value not in _DEVICE_SLOT_COUNTS:
            raise ValueError(f"unknown device '{value}' — supported: {sorted(_DEVICE_SLOT_COUNTS)}")
        return value

    @model_validator(mode="after")
    def _validate_keys(self) -> StreamDeckManifest:
        slot_count = _DEVICE_SLOT_COUNTS[self.device]
        seen: set[int] = set()
        for key in self.keys:
            if key.slot >= slot_count:
                raise ValueError(
                    f"slot {key.slot} out of range for device '{self.device}' "
                    f"(valid: 0..{slot_count - 1})"
                )
            if key.slot in seen:
                raise ValueError(f"duplicate slot {key.slot} in manifest")
            seen.add(key.slot)
        return self

    def slot_count(self) -> int:
        """Physical slot capacity of the declared device."""
        return _DEVICE_SLOT_COUNTS[self.device]

    def for_slot(self, slot: int) -> StreamDeckKey | None:
        for key in self.keys:
            if key.slot == slot:
                return key
        return None


class StreamDeckManifestError(ValueError):
    """Raised when a manifest file cannot be parsed or validated."""


def load_manifest(path: Path) -> StreamDeckManifest:
    """Load and validate a manifest YAML file.

    Wraps PyYAML + Pydantic failures in a single ``StreamDeckManifestError``
    so callers (and the systemd unit) can degrade to an idle state
    without a bare traceback.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StreamDeckManifestError(f"manifest not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise StreamDeckManifestError(f"manifest YAML parse error: {exc}") from exc

    if not isinstance(raw, dict):
        raise StreamDeckManifestError("manifest root must be a mapping")
    try:
        return StreamDeckManifest.model_validate(raw)
    except ValidationError as exc:
        raise StreamDeckManifestError(f"manifest validation failed: {exc}") from exc


# ── Dispatch result + adapter ───────────────────────────────────────────────


CommandDispatcher = Callable[[str, dict[str, Any]], Awaitable[None]]


class DispatchResult(BaseModel):
    """Outcome of a single key-press dispatch, exposed to tests and logs."""

    slot: int
    command: str | None
    args: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    status: str  # "dispatched" | "unknown-slot" | "out-of-range" | "error"
    error: str | None = None

    model_config = {"extra": "forbid"}


class StreamDeckAdapter:
    """Resolve Stream Deck key-presses to command-registry dispatches.

    The adapter owns a manifest and a dispatcher; ``on_key_press(slot)``
    is the single entry point. Dispatch errors are caught, logged, and
    surfaced in ``events`` — they never propagate to the caller, which
    is critical for the driver thread that reads the USB HID device.
    """

    def __init__(
        self,
        manifest: StreamDeckManifest,
        dispatcher: CommandDispatcher,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._manifest = manifest
        self._dispatcher = dispatcher
        self._loop = loop
        self._events: list[DispatchResult] = []

    @property
    def manifest(self) -> StreamDeckManifest:
        return self._manifest

    @property
    def events(self) -> list[DispatchResult]:
        """Return a copy of the dispatch log (primarily for tests)."""
        return list(self._events)

    def on_key_press(self, slot: int) -> DispatchResult:
        """Dispatch the command registered for ``slot``.

        Returns the :class:`DispatchResult`. Always succeeds at the
        Python level — unknown slots, out-of-range slots, and dispatch
        errors are recorded and returned without raising.
        """
        slot_count = self._manifest.slot_count()
        if slot < 0 or slot >= slot_count:
            result = DispatchResult(
                slot=slot,
                command=None,
                status="out-of-range",
                error=f"slot {slot} outside 0..{slot_count - 1}",
            )
            log.warning(
                "stream-deck: slot %d out of range for device %s (0..%d)",
                slot,
                self._manifest.device,
                slot_count - 1,
            )
            self._events.append(result)
            return result

        key = self._manifest.for_slot(slot)
        if key is None:
            result = DispatchResult(slot=slot, command=None, status="unknown-slot")
            log.info("stream-deck: slot %d has no binding; ignoring press", slot)
            self._events.append(result)
            return result

        with hapax_span(
            "control",
            "stream_deck.press",
            metadata={
                "slot": str(slot),
                "command": key.command,
                "label": key.label,
            },
        ):
            try:
                self._schedule_dispatch(key)
            except Exception as exc:  # noqa: BLE001 — must never bubble to HID thread
                log.exception("stream-deck: dispatch error for slot %d (%s)", slot, key.command)
                result = DispatchResult(
                    slot=slot,
                    command=key.command,
                    args=dict(key.args),
                    label=key.label,
                    status="error",
                    error=str(exc),
                )
                self._events.append(result)
                return result

        log.info(
            "stream-deck: slot %d [%s] → %s args=%s",
            slot,
            key.label,
            key.command,
            key.args,
        )
        result = DispatchResult(
            slot=slot,
            command=key.command,
            args=dict(key.args),
            label=key.label,
            status="dispatched",
        )
        self._events.append(result)
        return result

    def _schedule_dispatch(self, key: StreamDeckKey) -> None:
        """Bridge the sync HID callback to the async dispatcher."""
        coro = self._dispatcher(key.command, dict(key.args))
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(coro)
                return
        asyncio.run_coroutine_threadsafe(coro, loop)


# ── Default dispatcher ──────────────────────────────────────────────────────


async def websocket_dispatcher(
    command: str,
    args: dict[str, Any],
    *,
    url: str,
    connect: Callable[[str], Any] | None = None,
) -> None:
    """Post a single explicit legacy ``execute`` frame to a WebSocket.

    This helper has no production default URL. Runtime callers use
    :func:`logos_control_dispatcher`; tests inject ``connect`` here to avoid
    requiring the ``websockets`` package.
    """
    if connect is None:
        import websockets  # lazy import: module imports cleanly in test envs without it.

        connect = websockets.connect  # type: ignore[assignment]

    payload = json.dumps({"type": "execute", "command": command, "args": args})
    async with await connect(url) as ws:
        await ws.send(payload)


async def logos_control_dispatcher(
    command: str,
    args: dict[str, Any],
    *,
    base_url: str = DEFAULT_CONTROL_BASE_URL,
    request: Callable[[str, str, dict[str, Any]], Awaitable[Any]] | None = None,
) -> None:
    """Dispatch one key press through Logos API or local compositor control."""

    await dispatch_logos_control(command, args, base_url=base_url, request=request)
