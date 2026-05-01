from __future__ import annotations

import asyncio

import pytest

from shared.logos_control_dispatch import (
    UnsupportedLogosControlCommand,
    dispatch_logos_control,
    route_logos_control_command,
)


def test_hero_set_routes_to_logos_api_layout() -> None:
    action = route_logos_control_command(
        "studio.hero.set",
        {"camera_role": "brio-operator"},
    )

    assert action.transport == "logos-api"
    assert action.method == "POST"
    assert action.path == "/api/studio/layout"
    assert action.payload == {"mode": "hero/brio-operator"}


def test_legacy_camera_profile_routes_to_named_layout() -> None:
    action = route_logos_control_command(
        "studio.camera_profile.set",
        {"profile": "hero_screen"},
    )

    assert action.path == "/api/studio/layout"
    assert action.payload == {"mode": "hero/c920-room"}


def test_private_enable_routes_to_stream_mode_api() -> None:
    action = route_logos_control_command("studio.private.enable", {})

    assert action.transport == "logos-api"
    assert action.method == "PUT"
    assert action.path == "/api/stream/mode"
    assert action.payload == {"mode": "private"}


def test_dispatch_uses_logos_api_request_seam() -> None:
    calls: list[tuple[str, str, dict]] = []

    async def request(method: str, url: str, payload: dict) -> dict[str, object]:
        calls.append((method, url, payload))
        return {"ok": True}

    result = asyncio.run(
        dispatch_logos_control(
            "fx.chain.set",
            {"chain": "ghost"},
            base_url="http://logos.test",
            request=request,
        )
    )

    assert result == {"ok": True}
    assert calls == [("POST", "http://logos.test/api/studio/effect/select", {"preset": "ghost"})]


def test_dispatch_uses_injected_compositor_client() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def execute(self, command: str, args: dict) -> dict[str, object]:
            self.calls.append((command, args))
            return {"status": "ok"}

    client = Client()

    result = asyncio.run(
        dispatch_logos_control(
            "degraded.activate",
            {"reason": "operator"},
            compositor_client=client,
        )
    )

    assert result == {"status": "ok"}
    assert client.calls == [("degraded.activate", {"reason": "operator"})]


def test_operator_quality_route_writes_private_jsonl(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "ratings.jsonl"
    monkeypatch.setenv("HAPAX_OPERATOR_QUALITY_FEEDBACK_PATH", str(target))

    action = route_logos_control_command(
        "operator.quality.rate",
        {
            "rating": 4,
            "event_id": "oqr-dispatch",
            "occurred_at": "2026-05-01T00:12:00Z",
            "evidence_refs": ["control:stream_deck.key.13"],
        },
    )
    assert action.transport == "local-quality-feedback"

    result = asyncio.run(
        dispatch_logos_control(
            "operator.quality.rate",
            {
                "rating": 4,
                "event_id": "oqr-dispatch",
                "occurred_at": "2026-05-01T00:12:00Z",
                "evidence_refs": ["control:stream_deck.key.13"],
            },
        )
    )

    assert result["event_id"] == "oqr-dispatch"
    assert result["source_surface"] == "streamdeck"
    assert target.exists()


def test_frontend_only_command_fails_closed() -> None:
    with pytest.raises(UnsupportedLogosControlCommand):
        route_logos_control_command("terrain.focus", {"region": "ground"})
