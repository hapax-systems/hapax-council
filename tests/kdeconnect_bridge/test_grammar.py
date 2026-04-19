"""Tests for agents.kdeconnect_bridge (task #141).

Covers the grammar, the burst throttle, and the Bridge end-to-end
dispatch behavior (WS mock + sidechat write). The suite is fully
offline — no kdeconnect-cli, no websocket, no real /dev/shm writes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from agents.kdeconnect_bridge.bridge import (
    Bridge,
    BurstThrottle,
    DispatchResult,
    append_sidechat,
    websocket_dispatcher,
)
from agents.kdeconnect_bridge.grammar import parse

# ---------------------------------------------------------------- grammar


class TestGrammarCommands:
    def test_hero_with_role(self) -> None:
        p = parse("hero brio-operator")
        assert p.kind == "command"
        assert p.command == "studio.hero.set"
        assert p.args == {"camera_role": "brio-operator"}

    def test_hero_clear(self) -> None:
        p = parse("hero clear")
        assert p.kind == "command"
        assert p.command == "studio.hero.clear"
        assert p.args == {}

    def test_hero_missing_role_is_unknown(self) -> None:
        p = parse("hero")
        assert p.kind == "unknown"
        assert "requires" in p.error

    def test_vinyl_enum_45_on_33(self) -> None:
        p = parse("vinyl 45-on-33")
        assert p.kind == "command"
        assert p.command == "audio.vinyl.rate_preset"
        assert p.args == {"preset": "45-on-33"}

    def test_vinyl_enum_33(self) -> None:
        p = parse("vinyl 33")
        assert p.args == {"preset": "33"}

    def test_vinyl_enum_45(self) -> None:
        p = parse("vinyl 45")
        assert p.args == {"preset": "45"}

    def test_vinyl_custom_rate(self) -> None:
        p = parse("vinyl custom:48.7")
        assert p.kind == "command"
        assert p.args == {"preset": "custom:48.7"}

    def test_vinyl_custom_non_numeric_is_unknown(self) -> None:
        p = parse("vinyl custom:foo")
        assert p.kind == "unknown"
        assert "numeric" in p.error

    def test_vinyl_unknown_preset(self) -> None:
        p = parse("vinyl 78")
        assert p.kind == "unknown"

    def test_fx_chain(self) -> None:
        p = parse("fx ghost")
        assert p.kind == "command"
        assert p.command == "fx.chain.set"
        assert p.args == {"chain": "ghost"}

    def test_mode_research(self) -> None:
        p = parse("mode research")
        assert p.kind == "command"
        assert p.command == "mode.set"
        assert p.args == {"mode": "research"}

    def test_mode_rnd(self) -> None:
        p = parse("mode rnd")
        assert p.args == {"mode": "rnd"}

    def test_mode_rejects_others(self) -> None:
        p = parse("mode fortress")
        assert p.kind == "unknown"

    @pytest.mark.parametrize("sub", ["next", "pause", "resume"])
    def test_ward_sub(self, sub: str) -> None:
        p = parse(f"ward {sub}")
        assert p.kind == "command"
        assert p.command == f"studio.ward.{sub}"

    def test_ward_invalid(self) -> None:
        p = parse("ward stop")
        assert p.kind == "unknown"

    def test_safe(self) -> None:
        p = parse("safe")
        assert p.kind == "command"
        assert p.command == "degraded.activate"

    def test_sidechat(self) -> None:
        p = parse("sidechat hello there")
        assert p.kind == "sidechat"
        assert p.sidechat_text == "hello there"

    def test_sidechat_empty(self) -> None:
        p = parse("sidechat   ")
        assert p.kind == "unknown"

    def test_empty_message(self) -> None:
        p = parse("")
        assert p.kind == "unknown"

    def test_unknown_verb_is_structured_error(self) -> None:
        p = parse("launch nukes")
        assert p.kind == "unknown"
        assert p.error
        # Must NOT raise; must return structured result.
        assert isinstance(p.error, str)


# ---------------------------------------------------------------- throttle


class TestBurstThrottle:
    def test_allows_within_burst(self) -> None:
        t = [0.0]

        def clock() -> float:
            return t[0]

        tr = BurstThrottle(burst=4, window=0.250, clock=clock)
        assert tr.allow()
        assert tr.allow()
        assert tr.allow()
        assert tr.allow()
        # 5th message within the same 250ms window is dropped.
        assert not tr.allow()

    def test_fifth_message_within_250ms_dropped(self) -> None:
        t = [0.0]

        def clock() -> float:
            return t[0]

        tr = BurstThrottle(burst=4, window=0.250, clock=clock)
        for _ in range(4):
            assert tr.allow()
            t[0] += 0.050  # 50ms apart => 4 events span 150ms, all inside window
        # At t=0.200 we've queued 4 events at 0/50/100/150. 5th at 200 — still <250 from first.
        assert not tr.allow()

    def test_window_slides(self) -> None:
        t = [0.0]

        def clock() -> float:
            return t[0]

        tr = BurstThrottle(burst=4, window=0.250, clock=clock)
        for _ in range(4):
            assert tr.allow()
        # Advance clock past the window — oldest events age out.
        t[0] = 0.300
        assert tr.allow()


# ---------------------------------------------------------------- bridge


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, command: str, args: dict[str, Any]) -> None:
        self.calls.append((command, dict(args)))


class _RecordingAck:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        self.messages.append(message)


def _run(coro):  # pragma: no cover - tiny helper
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class TestBridgeDispatch:
    def test_hero_set_dispatches_to_ws(self) -> None:
        disp = _RecordingDispatcher()
        ack = _RecordingAck()
        bridge = Bridge(dispatcher=disp, ack=ack)

        result: DispatchResult = asyncio.run(bridge.handle("hero brio-operator"))

        assert result.dispatched is True
        assert disp.calls == [("studio.hero.set", {"camera_role": "brio-operator"})]
        assert ack.messages == ["OK: studio.hero.set"]

    def test_vinyl_preset_dispatch(self) -> None:
        disp = _RecordingDispatcher()
        bridge = Bridge(dispatcher=disp)

        asyncio.run(bridge.handle("vinyl 45-on-33"))

        assert disp.calls == [("audio.vinyl.rate_preset", {"preset": "45-on-33"})]

    def test_fx_chain_dispatch(self) -> None:
        disp = _RecordingDispatcher()
        bridge = Bridge(dispatcher=disp)

        asyncio.run(bridge.handle("fx ghost"))

        assert disp.calls == [("fx.chain.set", {"chain": "ghost"})]

    def test_mode_dispatch(self) -> None:
        disp = _RecordingDispatcher()
        bridge = Bridge(dispatcher=disp)

        asyncio.run(bridge.handle("mode research"))

        assert disp.calls == [("mode.set", {"mode": "research"})]

    def test_ward_next_dispatch(self) -> None:
        disp = _RecordingDispatcher()
        bridge = Bridge(dispatcher=disp)

        asyncio.run(bridge.handle("ward next"))

        assert disp.calls == [("studio.ward.next", {})]

    def test_safe_dispatch(self) -> None:
        disp = _RecordingDispatcher()
        bridge = Bridge(dispatcher=disp)

        asyncio.run(bridge.handle("safe"))

        assert disp.calls == [("degraded.activate", {})]

    def test_unknown_command_acks_error_without_dispatch(self) -> None:
        disp = _RecordingDispatcher()
        ack = _RecordingAck()
        bridge = Bridge(dispatcher=disp, ack=ack)

        result = asyncio.run(bridge.handle("rocket launch"))

        assert result.dispatched is False
        assert disp.calls == []
        assert ack.messages and ack.messages[0].startswith("ERR:")

    def test_throttle_drops_burst_overflow(self, tmp_path: Path) -> None:
        disp = _RecordingDispatcher()
        ack = _RecordingAck()
        t = [0.0]

        def clock() -> float:
            return t[0]

        throttle = BurstThrottle(burst=4, window=0.250, clock=clock)
        bridge = Bridge(
            dispatcher=disp,
            ack=ack,
            throttle=throttle,
            sidechat_path=tmp_path / "sidechat.jsonl",
            clock=clock,
        )

        # 4 rapid hero flips within the 250ms window.
        asyncio.run(bridge.handle("hero brio-operator"))
        t[0] = 0.050
        asyncio.run(bridge.handle("hero brio-room"))
        t[0] = 0.100
        asyncio.run(bridge.handle("hero brio-synths"))
        t[0] = 0.150
        asyncio.run(bridge.handle("hero clear"))
        # 5th within same window — throttled.
        t[0] = 0.200
        r5 = asyncio.run(bridge.handle("hero brio-operator"))

        assert len(disp.calls) == 4
        assert r5.dispatched is False
        assert r5.reason == "throttled"
        assert any("throttled" in m for m in ack.messages)


class TestBridgeSidechat:
    def test_sidechat_writes_jsonl(self, tmp_path: Path) -> None:
        disp = _RecordingDispatcher()
        sidechat_path = tmp_path / "sidechat.jsonl"
        bridge = Bridge(dispatcher=disp, sidechat_path=sidechat_path)

        result = asyncio.run(bridge.handle("sidechat remember to flip synths cam"))

        assert result.dispatched is True
        assert disp.calls == []  # sidechat never hits WS relay
        assert sidechat_path.exists()

        lines = sidechat_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["text"] == "remember to flip synths cam"
        # Uses canonical sidechat schema from shared/operator_sidechat.py.
        assert record["role"] == "operator"
        assert record["channel"] == "sidechat"
        assert "ts" in record

    def test_append_sidechat_helper(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "sidechat.jsonl"
        append_sidechat("hello", path=target)
        append_sidechat("world", path=target)

        lines = target.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["text"] == "hello"
        assert json.loads(lines[1])["text"] == "world"


class TestWebsocketDispatcher:
    def test_sends_execute_payload(self) -> None:
        sent: list[str] = []
        closed: list[bool] = []

        class FakeWS:
            async def send(self, msg: str) -> None:
                sent.append(msg)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                closed.append(True)
                return None

        class FakeConnect:
            """Mirrors websockets.connect(): awaitable AND async CM."""

            def __init__(self, ws: FakeWS) -> None:
                self._ws = ws

            def __await__(self):
                async def _inner():
                    return self._ws

                return _inner().__await__()

            async def __aenter__(self):
                return self._ws

            async def __aexit__(self, *exc):
                closed.append(True)
                return None

        def fake_connect(url: str):
            return FakeConnect(FakeWS())

        asyncio.run(
            websocket_dispatcher(
                "studio.hero.set",
                {"camera_role": "brio-operator"},
                url="ws://test/dummy",
                connect=fake_connect,
            )
        )

        assert len(sent) == 1
        payload = json.loads(sent[0])
        assert payload == {
            "type": "execute",
            "command": "studio.hero.set",
            "args": {"camera_role": "brio-operator"},
        }
        assert closed == [True]
