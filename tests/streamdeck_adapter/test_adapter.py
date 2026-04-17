"""Tests for agents.streamdeck_adapter.adapter (Phase 8 item 6)."""

from __future__ import annotations

import asyncio
import json


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, command: str, args: dict) -> None:
        self.calls.append((command, dict(args)))


class TestAdapterRouting:
    def test_press_dispatches_command(self):
        from agents.streamdeck_adapter.adapter import StreamDeckAdapter
        from agents.streamdeck_adapter.key_map import parse_key_map

        dispatcher = _RecordingDispatcher()
        km = parse_key_map(
            {
                "bindings": [
                    {"key": 0, "command": "studio.camera_profile.set", "args": {"profile": "hero"}},
                ]
            }
        )
        adapter = StreamDeckAdapter(km, dispatcher)

        adapter.handle_key_press(0, True)

        assert len(adapter.events) == 1
        ev = adapter.events[0]
        assert ev.command == "studio.camera_profile.set"
        assert ev.args == {"profile": "hero"}
        assert dispatcher.calls == [("studio.camera_profile.set", {"profile": "hero"})]

    def test_release_is_ignored(self):
        from agents.streamdeck_adapter.adapter import StreamDeckAdapter
        from agents.streamdeck_adapter.key_map import parse_key_map

        dispatcher = _RecordingDispatcher()
        km = parse_key_map({"bindings": [{"key": 0, "command": "x"}]})
        adapter = StreamDeckAdapter(km, dispatcher)

        adapter.handle_key_press(0, False)

        assert adapter.events == []
        assert dispatcher.calls == []

    def test_unbound_key_drops_silently(self):
        from agents.streamdeck_adapter.adapter import StreamDeckAdapter
        from agents.streamdeck_adapter.key_map import parse_key_map

        dispatcher = _RecordingDispatcher()
        km = parse_key_map({"bindings": [{"key": 0, "command": "x"}]})
        adapter = StreamDeckAdapter(km, dispatcher)

        adapter.handle_key_press(7, True)

        assert adapter.events == []
        assert dispatcher.calls == []

    def test_multiple_presses_recorded(self):
        from agents.streamdeck_adapter.adapter import StreamDeckAdapter
        from agents.streamdeck_adapter.key_map import parse_key_map

        dispatcher = _RecordingDispatcher()
        km = parse_key_map(
            {
                "bindings": [
                    {"key": 0, "command": "a"},
                    {"key": 1, "command": "b"},
                ]
            }
        )
        adapter = StreamDeckAdapter(km, dispatcher)

        adapter.handle_key_press(0, True)
        adapter.handle_key_press(1, True)
        adapter.handle_key_press(0, True)

        assert [e.command for e in adapter.events] == ["a", "b", "a"]
        assert [c[0] for c in dispatcher.calls] == ["a", "b", "a"]

    def test_args_mutation_does_not_leak_back(self):
        from agents.streamdeck_adapter.adapter import StreamDeckAdapter
        from agents.streamdeck_adapter.key_map import parse_key_map

        dispatcher = _RecordingDispatcher()
        km = parse_key_map({"bindings": [{"key": 0, "command": "x", "args": {"n": 1}}]})
        adapter = StreamDeckAdapter(km, dispatcher)

        adapter.handle_key_press(0, True)
        dispatcher.calls[0][1]["n"] = 999

        # Second press should still see the original 1, proving the first
        # press was dispatched with a copy.
        adapter.handle_key_press(0, True)
        assert dispatcher.calls[1][1] == {"n": 1}


class TestWebsocketDispatcher:
    def test_sends_execute_payload(self):
        from agents.streamdeck_adapter.adapter import websocket_dispatcher

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
                "studio.camera_profile.set",
                {"profile": "hero"},
                url="ws://test/dummy",
                connect=fake_connect,
            )
        )
        assert len(sent) == 1
        payload = json.loads(sent[0])
        assert payload == {
            "type": "execute",
            "command": "studio.camera_profile.set",
            "args": {"profile": "hero"},
        }
        assert closed == [True]


class TestNullDevice:
    def test_sets_callback_without_error(self):
        from agents.streamdeck_adapter.adapter import make_null_device

        dev = make_null_device()

        def _cb(key: int, pressed: bool) -> None:  # pragma: no cover - no events
            pass

        dev.set_key_callback(_cb)  # must not raise
