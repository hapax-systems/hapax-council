"""m8-remote-button-control-daemon — Pydantic + byte-encoder + UDS round-trip.

cc-task `m8-remote-button-control-daemon`. Tests:

  * Pydantic validation: button name validation, MIDI note range,
    velocity range, theme slot range, theme color range, malformed
    payloads → ValidationError or ValueError
  * Byte-protocol encoders: each command type produces the documented
    M8 host-protocol bytes (per m8_libserialport.c reference)
  * Daemon write path: handle_request encodes + writes through a fake
    serial fd (no /dev/hapax-m8-serial dependency); button hold/release
    sequence emits press → sleep → release
  * UDS round-trip: client sends JSON, daemon parses + replies
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.m8_control.daemon import (
    BUTTON_BITS,
    DEFAULT_HOLD_MS,
    M8ButtonRequest,
    M8ControlDaemon,
    M8KeyjazzRequest,
    M8ResetRequest,
    M8ThemeRequest,
    encode_button,
    encode_keyjazz,
    encode_release,
    encode_reset,
    encode_theme,
    parse_request,
)

# ── Pydantic validation ────────────────────────────────────────────


class TestPydanticValidation:
    def test_button_known_names_accepted(self) -> None:
        req = M8ButtonRequest(cmd="button", mask=["EDIT", "RIGHT"])
        assert req.mask == ["EDIT", "RIGHT"]

    def test_button_unknown_name_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            M8ButtonRequest(cmd="button", mask=["TURBO"])
        assert "unknown button" in str(exc.value)

    def test_button_aliases_accepted(self) -> None:
        # SHIFT (=SELECT) and PLAY (=START) are explicit aliases.
        req = M8ButtonRequest(cmd="button", mask=["SHIFT", "PLAY"])
        assert req.mask == ["SHIFT", "PLAY"]

    def test_button_hold_ms_default(self) -> None:
        req = M8ButtonRequest(cmd="button", mask=["PLAY"])
        assert req.hold_ms == DEFAULT_HOLD_MS

    def test_button_hold_ms_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            M8ButtonRequest(cmd="button", mask=["PLAY"], hold_ms=-1)

    def test_button_hold_ms_max_enforced(self) -> None:
        # 10000 ms is the cap (10s — guards against accidental long holds).
        with pytest.raises(ValidationError):
            M8ButtonRequest(cmd="button", mask=["PLAY"], hold_ms=10001)

    def test_keyjazz_note_range(self) -> None:
        M8KeyjazzRequest(cmd="keyjazz", note=60, velocity=100)  # ok
        with pytest.raises(ValidationError):
            M8KeyjazzRequest(cmd="keyjazz", note=128, velocity=100)
        with pytest.raises(ValidationError):
            M8KeyjazzRequest(cmd="keyjazz", note=-1, velocity=100)

    def test_keyjazz_velocity_range(self) -> None:
        M8KeyjazzRequest(cmd="keyjazz", note=60, velocity=0)  # note off
        M8KeyjazzRequest(cmd="keyjazz", note=60, velocity=127)  # max
        with pytest.raises(ValidationError):
            M8KeyjazzRequest(cmd="keyjazz", note=60, velocity=128)

    def test_theme_slot_range(self) -> None:
        M8ThemeRequest(cmd="theme", slot=0, r=0, g=0, b=0)
        M8ThemeRequest(cmd="theme", slot=12, r=255, g=255, b=255)
        with pytest.raises(ValidationError):
            M8ThemeRequest(cmd="theme", slot=13, r=0, g=0, b=0)

    def test_theme_color_range(self) -> None:
        with pytest.raises(ValidationError):
            M8ThemeRequest(cmd="theme", slot=0, r=256, g=0, b=0)
        with pytest.raises(ValidationError):
            M8ThemeRequest(cmd="theme", slot=0, r=-1, g=0, b=0)

    def test_parse_request_dispatches_on_cmd(self) -> None:
        assert isinstance(parse_request({"cmd": "reset"}), M8ResetRequest)
        assert isinstance(
            parse_request({"cmd": "keyjazz", "note": 60, "velocity": 100}),
            M8KeyjazzRequest,
        )

    def test_parse_request_unknown_cmd_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown command"):
            parse_request({"cmd": "hax"})

    def test_parse_request_missing_cmd_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown command"):
            parse_request({})


# ── Byte-protocol encoders ──────────────────────────────────────────


class TestByteEncoders:
    def test_button_press_bytes(self) -> None:
        # PLAY (bit 4) + EDIT (bit 7) → 0x90
        req = M8ButtonRequest(cmd="button", mask=["PLAY", "EDIT"])
        encoded = encode_button(req)
        assert encoded[0] == ord("C")
        assert encoded[1] == 0x90  # bit 4 | bit 7

    def test_button_release_bytes(self) -> None:
        # All-buttons-released frame.
        assert encode_release() == bytes([ord("C"), 0x00])

    def test_button_alias_same_bit(self) -> None:
        """SHIFT == SELECT (bit 3); PLAY == START (bit 4) — same byte out."""
        req_a = M8ButtonRequest(cmd="button", mask=["SELECT"])
        req_b = M8ButtonRequest(cmd="button", mask=["SHIFT"])
        assert encode_button(req_a) == encode_button(req_b)

    def test_keyjazz_bytes(self) -> None:
        req = M8KeyjazzRequest(cmd="keyjazz", note=60, velocity=100)
        encoded = encode_keyjazz(req)
        assert encoded == bytes([ord("K"), 60, 100])

    def test_reset_bytes(self) -> None:
        encoded = encode_reset(M8ResetRequest(cmd="reset"))
        assert encoded == bytes([ord("R")])

    def test_theme_bytes(self) -> None:
        req = M8ThemeRequest(cmd="theme", slot=3, r=251, g=73, b=52)
        encoded = encode_theme(req)
        assert encoded == bytes([ord("S"), 3, 251, 73, 52])

    def test_button_bits_match_documented_layout(self) -> None:
        """Pin against m8_libserialport.c source-of-truth bits."""
        assert BUTTON_BITS["LEFT"] == 0
        assert BUTTON_BITS["UP"] == 1
        assert BUTTON_BITS["DOWN"] == 2
        assert BUTTON_BITS["SELECT"] == 3
        assert BUTTON_BITS["SHIFT"] == 3  # alias
        assert BUTTON_BITS["START"] == 4
        assert BUTTON_BITS["PLAY"] == 4  # alias
        assert BUTTON_BITS["RIGHT"] == 5
        assert BUTTON_BITS["OPT"] == 6
        assert BUTTON_BITS["EDIT"] == 7


# ── Daemon write path with fake serial fd ───────────────────────────


class _FakeSerial(io.BytesIO):
    """BytesIO that ignores flush() and tracks every write."""

    def flush(self) -> None:  # noqa: D401
        pass


def _fake_serial_opener_factory():
    """Returns (opener, holder) — caller can inspect holder.value after."""

    class _Holder:
        value: _FakeSerial | None = None

    holder = _Holder()

    def opener(_path: Path) -> _FakeSerial:
        if holder.value is None:
            holder.value = _FakeSerial()
        return holder.value

    return opener, holder


class TestDaemonWritePath:
    @pytest.mark.asyncio
    async def test_reset_writes_one_byte(self) -> None:
        opener, holder = _fake_serial_opener_factory()
        sleeps: list[float] = []
        daemon = M8ControlDaemon(serial_opener=opener, sleep_fn=lambda s: _record(sleeps, s))
        result = await daemon.handle_request({"cmd": "reset"})
        assert result == {"ok": True}
        assert holder.value.getvalue() == bytes([ord("R")])
        assert sleeps == []

    @pytest.mark.asyncio
    async def test_button_writes_press_then_release_with_hold(self) -> None:
        opener, holder = _fake_serial_opener_factory()
        sleeps: list[float] = []
        daemon = M8ControlDaemon(serial_opener=opener, sleep_fn=lambda s: _record(sleeps, s))
        result = await daemon.handle_request({"cmd": "button", "mask": ["PLAY"], "hold_ms": 16})
        assert result == {"ok": True}
        # Two writes: press (C, 0x10) + release (C, 0x00); one sleep of 16ms.
        assert holder.value.getvalue() == bytes([ord("C"), 0x10, ord("C"), 0x00])
        assert sleeps == [pytest.approx(0.016)]

    @pytest.mark.asyncio
    async def test_button_zero_hold_skips_sleep(self) -> None:
        opener, holder = _fake_serial_opener_factory()
        sleeps: list[float] = []
        daemon = M8ControlDaemon(serial_opener=opener, sleep_fn=lambda s: _record(sleeps, s))
        await daemon.handle_request({"cmd": "button", "mask": ["EDIT"], "hold_ms": 0})
        assert sleeps == []  # no sleep when hold_ms=0
        # Still emits both press + release.
        assert holder.value.getvalue() == bytes([ord("C"), 0x80, ord("C"), 0x00])

    @pytest.mark.asyncio
    async def test_keyjazz_writes_three_bytes(self) -> None:
        opener, holder = _fake_serial_opener_factory()
        daemon = M8ControlDaemon(serial_opener=opener)
        await daemon.handle_request({"cmd": "keyjazz", "note": 60, "velocity": 100})
        assert holder.value.getvalue() == bytes([ord("K"), 60, 100])

    @pytest.mark.asyncio
    async def test_theme_writes_five_bytes(self) -> None:
        opener, holder = _fake_serial_opener_factory()
        daemon = M8ControlDaemon(serial_opener=opener)
        await daemon.handle_request({"cmd": "theme", "slot": 0, "r": 251, "g": 73, "b": 52})
        assert holder.value.getvalue() == bytes([ord("S"), 0, 251, 73, 52])

    @pytest.mark.asyncio
    async def test_malformed_request_returns_error_no_write(self) -> None:
        opener, holder = _fake_serial_opener_factory()
        daemon = M8ControlDaemon(serial_opener=opener)
        result = await daemon.handle_request({"cmd": "button", "mask": ["TURBO"]})
        assert result["ok"] is False
        assert "validation" in result["error"]
        # Critically: serial fd was never opened, so no bytes written.
        assert holder.value is None

    @pytest.mark.asyncio
    async def test_unknown_cmd_returns_error_no_write(self) -> None:
        opener, holder = _fake_serial_opener_factory()
        daemon = M8ControlDaemon(serial_opener=opener)
        result = await daemon.handle_request({"cmd": "hax"})
        assert result == {"ok": False, "error": "unknown command: 'hax'"}
        assert holder.value is None


def _record(sink: list[float], s: float):
    """Helper coroutine factory for fake sleep."""

    async def _co():
        sink.append(s)

    return _co()


# ── UDS round-trip ──────────────────────────────────────────────────


async def _async_uds_round_trip(uds: Path, payload: bytes) -> bytes:
    """Connect via asyncio.open_unix_connection so we don't deadlock the
    same loop the daemon runs on."""
    reader, writer = await asyncio.open_unix_connection(path=str(uds))
    writer.write(payload)
    await writer.drain()
    data = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return data


class TestUdsRoundTrip:
    @pytest.mark.asyncio
    async def test_uds_client_round_trip(self, tmp_path: Path) -> None:
        """Bind daemon to tmp UDS; send JSON via asyncio socket; verify ACK."""
        opener, holder = _fake_serial_opener_factory()
        uds = tmp_path / "m8.sock"
        daemon = M8ControlDaemon(serial_opener=opener, uds_path=uds)
        server_task = asyncio.create_task(daemon.serve())
        await asyncio.sleep(0.05)  # let server bind
        try:
            data = await _async_uds_round_trip(uds, b'{"cmd":"reset"}\n')
            ack = json.loads(data.decode("utf-8").strip())
            assert ack == {"ok": True}
            assert holder.value.getvalue() == bytes([ord("R")])
        finally:
            server_task.cancel()
            try:
                await server_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    @pytest.mark.asyncio
    async def test_uds_malformed_json_returns_error(self, tmp_path: Path) -> None:
        opener, _ = _fake_serial_opener_factory()
        uds = tmp_path / "m8.sock"
        daemon = M8ControlDaemon(serial_opener=opener, uds_path=uds)
        server_task = asyncio.create_task(daemon.serve())
        await asyncio.sleep(0.05)
        try:
            data = await _async_uds_round_trip(uds, b"{not valid json\n")
            ack = json.loads(data.decode("utf-8").strip())
            assert ack["ok"] is False
            assert "json" in ack["error"]
        finally:
            server_task.cancel()
            try:
                await server_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


# ── Affordance registration pin ─────────────────────────────────────


def test_studio_m8_remote_control_affordance_registered() -> None:
    """Pin: shared/affordance_registry.py registers studio.m8_remote_control."""
    from shared.affordance_registry import STUDIO_AFFORDANCES

    names = {r.name for r in STUDIO_AFFORDANCES}
    assert "studio.m8_remote_control" in names
    record = next(r for r in STUDIO_AFFORDANCES if r.name == "studio.m8_remote_control")
    assert record.daemon == "m8_control"
    assert record.operational.consent_required is False
