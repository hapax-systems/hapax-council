"""State-machine + rotation tests for the broadcast orchestrator.

Mocks ``shared.youtube_api_client.YouTubeApiClient`` so no network is
needed. Each test assembles the canned response sequence beta filed
in ``~/.cache/hapax/relay/context/2026-04-23-youtube-boost-fixtures-ytb-007.md``.
"""

from __future__ import annotations

from typing import Any

import pytest

from agents.broadcast_orchestrator.orchestrator import (
    Orchestrator,
    State,
)


class _FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, secs: float) -> None:
        self.now += secs


class _FakeClient:
    """Stand-in for YouTubeApiClient with scripted behaviour."""

    def __init__(self) -> None:
        self.enabled = True
        self.calls: list[tuple[str, dict]] = []
        self.responses: dict[str, list[Any]] = {}

    def queue(self, endpoint: str, *responses: Any) -> None:
        self.responses.setdefault(endpoint, []).extend(responses)


def _patched_api_call(client: _FakeClient, endpoint: str, **kwargs: Any):
    client.calls.append((endpoint, kwargs))
    queue = client.responses.get(endpoint, [])
    if not queue:
        return None
    val = queue.pop(0)
    if isinstance(val, Exception):
        raise val
    return val


@pytest.fixture()
def fake_client():
    return _FakeClient()


@pytest.fixture()
def orch(fake_client):
    clock = _FakeClock()
    o = Orchestrator(client=fake_client, rotation_s=39600, retry_limit=3, time_fn=clock)
    o._clock = clock  # type: ignore[attr-defined]
    return o


def _patch_api(monkeypatch, fake_client: _FakeClient) -> None:
    """Route every agents.broadcast_orchestrator.api.* call through the fake client."""

    def _wrap(endpoint: str):
        def _fn(client, **kwargs):
            return _patched_api_call(fake_client, endpoint, **kwargs)

        return _fn

    monkeypatch.setattr(
        "agents.broadcast_orchestrator.api.list_active_broadcasts",
        lambda c: _patched_api_call(fake_client, "liveBroadcasts.list"),
    )
    monkeypatch.setattr(
        "agents.broadcast_orchestrator.api.discover_stream_id",
        lambda c: _patched_api_call(fake_client, "liveStreams.list"),
    )
    monkeypatch.setattr(
        "agents.broadcast_orchestrator.api.insert_broadcast",
        _wrap("liveBroadcasts.insert"),
    )
    monkeypatch.setattr(
        "agents.broadcast_orchestrator.api.bind_broadcast",
        _wrap("liveBroadcasts.bind"),
    )
    monkeypatch.setattr(
        "agents.broadcast_orchestrator.api.transition_broadcast",
        _wrap("liveBroadcasts.transition"),
    )
    monkeypatch.setattr(
        "agents.broadcast_orchestrator.api.update_video_metadata",
        _wrap("videos.update"),
    )


def test_initial_discovery_no_active(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    fake_client.queue("liveBroadcasts.list", [])
    orch.run_once()
    assert orch.state == State.INACTIVE


def test_initial_discovery_single_active(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    fake_client.queue(
        "liveBroadcasts.list",
        [
            {
                "id": "broadcast-abc-123",
                "snippet": {"actualStartTime": "2026-04-23T00:00:15Z"},
            }
        ],
    )
    fake_client.queue("liveStreams.list", "stream-id-mno")
    orch.run_once()
    assert orch.state == State.ACTIVE
    assert orch.tracking.active_broadcast_id == "broadcast-abc-123"
    assert orch.tracking.cached_stream_id == "stream-id-mno"


def test_active_no_rotation_under_threshold(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    # Pretend already discovered: skip ahead.
    orch._tracking.active_broadcast_id = "broadcast-abc-123"
    orch._tracking.active_started_ts = orch._time()
    orch._tracking.cached_stream_id = "stream-id-mno"
    orch._set_state(State.ACTIVE)
    orch._clock.advance(1000)  # well under 11h
    orch.run_once()
    assert orch.state == State.ACTIVE
    assert ("liveBroadcasts.insert", {}) not in [(c[0], {}) for c in fake_client.calls]


def test_full_rotation_at_11h_boundary(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    orch._tracking.active_broadcast_id = "broadcast-old-111"
    orch._tracking.active_started_ts = orch._time()
    orch._tracking.cached_stream_id = "stream-id-mno"
    orch._set_state(State.ACTIVE)
    orch._clock.advance(40000)  # past 11h
    # _continue_rotation_new re-discovers the stream every tick so a mid-
    # rotation RTMP signal change is picked up; queue an active stream.
    fake_client.queue("liveStreams.list", "stream-id-mno")
    fake_client.queue(
        "liveBroadcasts.insert",
        {"id": "broadcast-new-444", "snippet": {}, "status": {}},
    )
    fake_client.queue("liveBroadcasts.bind", {"id": "broadcast-new-444"})
    fake_client.queue(
        "liveBroadcasts.transition",
        {"id": "broadcast-new-444", "status": {"lifeCycleStatus": "testing"}},
        {"id": "broadcast-new-444", "status": {"lifeCycleStatus": "live"}},
        {"id": "broadcast-old-111", "status": {"lifeCycleStatus": "complete"}},
    )
    fake_client.queue("videos.update", {"id": "broadcast-new-444", "snippet": {}})

    orch.run_once()

    assert orch.state == State.ACTIVE
    assert orch.tracking.active_broadcast_id == "broadcast-new-444"
    endpoints = [c[0] for c in fake_client.calls]
    assert endpoints == [
        "liveStreams.list",
        "liveBroadcasts.insert",
        "liveBroadcasts.bind",
        "liveBroadcasts.transition",
        "liveBroadcasts.transition",
        "liveBroadcasts.transition",
        "videos.update",
    ]


def test_rotation_holds_when_insert_fails(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    orch._tracking.active_broadcast_id = "broadcast-old-111"
    orch._tracking.active_started_ts = orch._time()
    orch._tracking.cached_stream_id = "stream-id-mno"
    orch._set_state(State.ACTIVE)
    orch._clock.advance(40000)
    fake_client.queue("liveStreams.list", "stream-id-mno")
    fake_client.queue("liveBroadcasts.insert", None)  # quota silent-skip
    orch.run_once()
    assert orch.state == State.ROTATING_NEW
    assert orch.tracking.incoming_broadcast_id is None


def test_rotation_holds_when_bind_fails(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    orch._tracking.active_broadcast_id = "broadcast-old-111"
    orch._tracking.active_started_ts = orch._time()
    orch._tracking.cached_stream_id = "stream-id-mno"
    orch._set_state(State.ACTIVE)
    orch._clock.advance(40000)
    fake_client.queue("liveStreams.list", "stream-id-mno")
    fake_client.queue(
        "liveBroadcasts.insert",
        {"id": "broadcast-new-444", "snippet": {}, "status": {}},
    )
    fake_client.queue("liveBroadcasts.bind", None)
    orch.run_once()
    assert orch.state == State.ROTATING_NEW
    # incoming_broadcast_id retained so retry doesn't re-insert
    assert orch.tracking.incoming_broadcast_id == "broadcast-new-444"


def test_rotation_defers_when_no_active_stream(monkeypatch, orch, fake_client):
    """Regression for the ghost-broadcast loop: when no liveStream is active
    (RTMP feed not currently pushing), the rotation in ROTATING_NEW must
    defer instead of inserting a broadcast that can't be transitioned to
    testing. Earlier behavior bound to the first inactive stream + entered
    a 5-minute retry loop burning ~600 quota/hour.
    """
    _patch_api(monkeypatch, fake_client)
    orch._tracking.active_broadcast_id = "broadcast-old-111"
    orch._tracking.active_started_ts = orch._time()
    orch._tracking.cached_stream_id = "stream-id-stale"  # populated, but stale
    orch._set_state(State.ACTIVE)
    orch._clock.advance(40000)  # past 11h, would normally rotate
    # discover_stream_id returns None (no active stream queued).
    orch.run_once()
    # Stayed in ROTATING_NEW so next tick can retry; no insert call yet.
    assert orch.state == State.ROTATING_NEW
    assert orch.tracking.incoming_broadcast_id is None
    endpoints = [c[0] for c in fake_client.calls]
    assert "liveBroadcasts.insert" not in endpoints
    assert "liveBroadcasts.bind" not in endpoints
    assert "liveBroadcasts.transition" not in endpoints
    # cached_stream_id was overwritten to None so the next tick can detect
    # signal arrival without staleness.
    assert orch.tracking.cached_stream_id is None


def test_vod_loss_alert_after_12h(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    orch._tracking.active_broadcast_id = "broadcast-old-111"
    orch._tracking.active_started_ts = orch._time()
    orch._tracking.cached_stream_id = "stream-id-mno"
    orch._tracking.incoming_broadcast_id = "broadcast-new-444"
    orch._set_state(State.ROTATING_OLD)
    orch._clock.advance(13 * 3600)  # past 12h cap
    fake_client.queue("liveBroadcasts.transition", None)  # complete fails
    sent: list[tuple[str, str]] = []

    def _capture(message, **kwargs):
        sent.append((kwargs.get("priority", ""), message))

    monkeypatch.setattr("shared.notify.send_notification", _capture)
    orch.run_once()
    assert any("VOD lost" in m for _, m in sent)


def test_disabled_client_no_calls(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    fake_client.enabled = False
    orch.run_once()
    assert fake_client.calls == []


def test_rotation_blocks_without_stream_id(monkeypatch, orch, fake_client):
    _patch_api(monkeypatch, fake_client)
    orch._tracking.active_broadcast_id = "broadcast-old-111"
    orch._tracking.active_started_ts = orch._time()
    orch._tracking.cached_stream_id = None
    orch._set_state(State.ACTIVE)
    orch._clock.advance(40000)
    sent: list[str] = []

    def _capture(message, **kwargs):
        sent.append(message)

    monkeypatch.setattr("shared.notify.send_notification", _capture)
    orch.run_once()
    assert orch.state == State.ACTIVE  # blocked, did not enter rotation
    assert any("stream_id" in m for m in sent)
