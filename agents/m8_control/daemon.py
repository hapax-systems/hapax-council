"""M8 control daemon — UDS server fronting the M8 serial write fd.

Protocol reference (per `packages/m8c-hapax/src/m8c-2.2.3/src/backends/m8_libserialport.c`):

  * ``'C'`` (0x43) + uint8 mask     — set button state (held until next set)
  * ``'K'`` (0x4B) + uint8 note + uint8 vel — keyjazz note (vel=0 = note off)
  * ``'R'`` (0x52)                   — reset/redraw display
  * ``'S'`` (0x53) + uint8 slot + R + G + B — set theme color slot

Button bitmask (per the same source file):

  bit 0 = LEFT, bit 1 = UP, bit 2 = DOWN, bit 3 = SELECT (= SHIFT),
  bit 4 = START (= PLAY), bit 5 = RIGHT, bit 6 = OPT, bit 7 = EDIT.

Held-button semantics: the M8 keeps a button pressed until the host
sends a new mask. To press-and-release, the daemon sends the mask,
sleeps briefly (~16 ms = one M8 frame), then sends 0x00. Exposed as
``hold_ms`` on `M8ButtonRequest` (default 16).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger("m8_control")

DEFAULT_SERIAL_PATH = Path("/dev/hapax-m8-serial")
DEFAULT_UDS_PATH = Path("/run/hapax/m8-control.sock")

# Button name → bit index (per m8_libserialport.c). Symbolic names are
# the canonical input; the daemon rejects unknown names with an error.
BUTTON_BITS: dict[str, int] = {
    "LEFT": 0,
    "UP": 1,
    "DOWN": 2,
    "SELECT": 3,
    "SHIFT": 3,  # alias — same bit
    "START": 4,
    "PLAY": 4,  # alias — same bit
    "RIGHT": 5,
    "OPT": 6,
    "EDIT": 7,
}

# Held-button release default — one M8 frame at ~60 fps.
DEFAULT_HOLD_MS: int = 16

# Keyjazz note range — MIDI standard (M8 follows).
MIN_NOTE: int = 0
MAX_NOTE: int = 127
MIN_VELOCITY: int = 0
MAX_VELOCITY: int = 127

# Theme slot: M8 has 13 theme color slots (per protocol notes).
MIN_THEME_SLOT: int = 0
MAX_THEME_SLOT: int = 12


# ── Pydantic request models ─────────────────────────────────────────


class M8ButtonRequest(BaseModel):
    """Press a chord of buttons; auto-release after `hold_ms`."""

    cmd: Literal["button"]
    mask: list[str] = Field(default_factory=list, description="Symbolic button names")
    hold_ms: int = Field(default=DEFAULT_HOLD_MS, ge=0, le=10000)

    @field_validator("mask")
    @classmethod
    def _validate_button_names(cls, v: list[str]) -> list[str]:
        for name in v:
            if name not in BUTTON_BITS:
                known = sorted(set(BUTTON_BITS) - {"SHIFT", "PLAY"})  # canonical names
                raise ValueError(f"unknown button: {name!r}; known: {known}")
        return v


class M8KeyjazzRequest(BaseModel):
    """Audition a single MIDI note via the M8's currently-selected instrument."""

    cmd: Literal["keyjazz"]
    note: int = Field(..., ge=MIN_NOTE, le=MAX_NOTE)
    velocity: int = Field(default=100, ge=MIN_VELOCITY, le=MAX_VELOCITY)


class M8ResetRequest(BaseModel):
    """Force the M8 display to redraw (clears + retransmits frame state)."""

    cmd: Literal["reset"]


class M8ThemeRequest(BaseModel):
    """Set one of the M8's theme color slots."""

    cmd: Literal["theme"]
    slot: int = Field(..., ge=MIN_THEME_SLOT, le=MAX_THEME_SLOT)
    r: int = Field(..., ge=0, le=255)
    g: int = Field(..., ge=0, le=255)
    b: int = Field(..., ge=0, le=255)


M8ControlRequest = M8ButtonRequest | M8KeyjazzRequest | M8ResetRequest | M8ThemeRequest


def parse_request(payload: dict) -> M8ControlRequest:
    """Dispatch on `cmd` to the right Pydantic model.

    Raises ``ValidationError`` (Pydantic) or ``ValueError`` (unknown cmd)
    on bad input. The daemon's request handler catches both and returns
    `{"ok": false, "error": ...}` to the client.
    """
    cmd = payload.get("cmd") if isinstance(payload, dict) else None
    if cmd == "button":
        return M8ButtonRequest.model_validate(payload)
    if cmd == "keyjazz":
        return M8KeyjazzRequest.model_validate(payload)
    if cmd == "reset":
        return M8ResetRequest.model_validate(payload)
    if cmd == "theme":
        return M8ThemeRequest.model_validate(payload)
    raise ValueError(f"unknown command: {cmd!r}")


# ── Byte-protocol encoders (pure functions; tested directly) ────────


def _mask_to_byte(mask: list[str]) -> int:
    out = 0
    for name in mask:
        out |= 1 << BUTTON_BITS[name]
    return out & 0xFF


def encode_button(req: M8ButtonRequest) -> bytes:
    """Encode a button press as the bytes to write to the serial port.

    Returns just the press bytes; release is sent as a separate write
    after `hold_ms` (handled by the daemon's async dispatcher, NOT here,
    so this function stays pure and trivially testable).
    """
    return bytes([ord("C"), _mask_to_byte(req.mask)])


def encode_release() -> bytes:
    """The all-buttons-released frame (mask=0)."""
    return bytes([ord("C"), 0x00])


def encode_keyjazz(req: M8KeyjazzRequest) -> bytes:
    return bytes([ord("K"), req.note, req.velocity])


def encode_reset(req: M8ResetRequest) -> bytes:  # noqa: ARG001
    return bytes([ord("R")])


def encode_theme(req: M8ThemeRequest) -> bytes:
    return bytes([ord("S"), req.slot, req.r, req.g, req.b])


# ── Daemon ──────────────────────────────────────────────────────────


class M8ControlDaemon:
    """UDS server fronting the M8 serial write fd.

    Lifecycle:
      * Open serial fd O_WRONLY | O_NONBLOCK
      * Bind UDS socket at `uds_path` with mode 0600 (operator-only)
      * Loop: accept → read line → parse → encode → write → ACK
      * On serial fd error: log + close + reopen at next request
        (handles M8 unplug/replug while the daemon stays alive)

    The daemon is a thin translator. It performs ZERO state tracking
    beyond holding the serial fd — every request is independent. M8
    state lives on the M8; m8c-hapax mirrors the display. This daemon
    is write-only.
    """

    def __init__(
        self,
        *,
        serial_path: Path = DEFAULT_SERIAL_PATH,
        uds_path: Path = DEFAULT_UDS_PATH,
        # Injection points for tests — production uses `os.open` and
        # `asyncio.start_unix_server` directly.
        serial_opener: Callable[[Path], BinaryIO] | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._serial_path = serial_path
        self._uds_path = uds_path
        self._serial_opener = serial_opener or _default_serial_opener
        self._sleep_fn = sleep_fn
        self._serial_fd: BinaryIO | None = None
        self._lock = asyncio.Lock()  # serialize serial writes

    async def handle_request(self, payload: dict) -> dict:
        """Validate, encode, write. Returns ACK dict for the client."""
        try:
            req = parse_request(payload)
        except ValidationError as e:
            return {"ok": False, "error": f"validation: {e.errors(include_url=False)}"}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        try:
            await self._write_request(req)
        except OSError as e:
            log.warning("serial write failed; closing fd for next reopen", exc_info=True)
            self._close_serial()
            return {"ok": False, "error": f"serial: {e}"}
        return {"ok": True}

    async def _write_request(self, req: M8ControlRequest) -> None:
        """Encode + write atomically (under the per-daemon lock).

        For button requests: write press, sleep `hold_ms`, write release.
        Other requests: single write.
        """
        async with self._lock:
            fd = self._ensure_serial_fd()
            if isinstance(req, M8ButtonRequest):
                fd.write(encode_button(req))
                fd.flush()
                if req.hold_ms > 0:
                    await self._sleep_fn(req.hold_ms / 1000.0)
                fd.write(encode_release())
                fd.flush()
            elif isinstance(req, M8KeyjazzRequest):
                fd.write(encode_keyjazz(req))
                fd.flush()
            elif isinstance(req, M8ResetRequest):
                fd.write(encode_reset(req))
                fd.flush()
            elif isinstance(req, M8ThemeRequest):
                fd.write(encode_theme(req))
                fd.flush()

    def _ensure_serial_fd(self) -> BinaryIO:
        if self._serial_fd is None:
            self._serial_fd = self._serial_opener(self._serial_path)
        return self._serial_fd

    def _close_serial(self) -> None:
        if self._serial_fd is not None:
            try:
                self._serial_fd.close()
            except OSError:
                log.debug("serial close raised", exc_info=True)
            self._serial_fd = None

    async def serve(self) -> None:
        """Bind the UDS server and serve forever. Used by `__main__`."""
        self._uds_path.parent.mkdir(parents=True, exist_ok=True)
        # Remove any stale socket from a prior crash.
        if self._uds_path.exists():
            self._uds_path.unlink()
        server = await asyncio.start_unix_server(self._client, path=str(self._uds_path))
        os.chmod(self._uds_path, 0o600)
        log.info("m8-control listening on %s", self._uds_path)
        try:
            async with server:
                await server.serve_forever()
        finally:
            self._close_serial()
            try:
                self._uds_path.unlink()
            except OSError:
                pass

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read one line per request; reply one JSON line per response."""
        try:
            line = await reader.readline()
            if not line:
                return
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                response = {"ok": False, "error": f"json: {e}"}
            else:
                response = await self.handle_request(payload)
            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                log.debug("writer.wait_closed raised", exc_info=True)


def _default_serial_opener(path: Path) -> BinaryIO:
    """Open the M8 CDC serial port write-only, non-blocking.

    Uses os.open + os.fdopen so we can pass O_NONBLOCK explicitly
    (Python's open() doesn't expose it directly).
    """
    fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    return os.fdopen(fd, "wb", buffering=0)
