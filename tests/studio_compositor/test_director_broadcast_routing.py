"""Director hosting speech routes through the fail-closed broadcast gate.

Task ``segment-audio-hosting-readiness-20260607`` (AC#4 + AC#2 publish slice):
the director's ``_play_audio`` previously routed *only* to the
``private_monitor`` role and never offered audio to the public broadcast. This
connects the dormant host-broadcast executor by routing hosting speech through
``resolve_playback_decision`` — the same fail-closed classifier every other
voice callsite uses — while keeping ``private_monitor`` as the never-removed
fallback.

Invariants pinned here (behavioural, not source-grep):

* **fail-closed:** no programme, an unauthorized programme, an absent runtime
  audio-safety signal, or any error → audio stays on ``private_monitor`` and
  ``tts_active`` is NOT published.
* **no self-mint:** the director only forwards a ``programme_authorization`` the
  Programme already carries; it never fabricates one. (A programme with no
  authorization is the unauthorized case below — it fails closed.)
* **additive broadcast:** only an *allowed* ``livestream`` decision reaches the
  broadcast target, and only then is ``tts_active`` bracketed around playback
  (so the broadcast music bed is not ducked for inaudible private speech).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _FakeAudioOutput:
    """Records ``write(pcm, target=, media_role=)`` calls."""

    instances: list[_FakeAudioOutput] = []

    def __init__(self, *args, **kwargs) -> None:
        self.writes: list[tuple[str | None, str | None]] = []
        _FakeAudioOutput.instances.append(self)

    def write(self, pcm: bytes, *, target=None, media_role=None):
        self.writes.append((target, media_role))
        return SimpleNamespace(ok=True)


class _FakeRouteResult:
    def __init__(self, sink_name: str | None) -> None:
        self.sink_name = sink_name
        self.provenance = "test"


class _FakeRouter:
    sink_name: str | None = "hapax-private-monitor-sink"

    def route(self, role: str) -> _FakeRouteResult:
        return _FakeRouteResult(_FakeRouter.sink_name)


class _FakeDecision:
    """Mirrors the VoicePlaybackDecision surface _play_audio reads."""

    def __init__(self, *, allowed: bool, destination: str, target=None, media_role=None):
        self.allowed = allowed
        self.destination = destination
        self._target = target
        self.media_role = media_role

    @property
    def target(self):  # real VoicePlaybackDecision returns None when not allowed
        return self._target if self.allowed else None


@pytest.fixture
def director(monkeypatch):
    """A DirectorLoop with the playback primitives faked out.

    ``programme_provider`` is patched per test via ``director.set_programme``.
    """
    # Keep construction offline + fast (no Qdrant warm-start network call).
    import shared.config as shared_config

    def _no_qdrant():
        raise RuntimeError("qdrant disabled in unit test")

    monkeypatch.setattr(shared_config, "get_qdrant", _no_qdrant, raising=False)

    import agents.hapax_daimonion.pw_audio_output as pw_mod
    import shared.voice_output_router as vor_mod

    _FakeAudioOutput.instances.clear()
    _FakeRouter.sink_name = "hapax-private-monitor-sink"
    monkeypatch.setattr(pw_mod, "PwAudioOutput", _FakeAudioOutput)
    monkeypatch.setattr(vor_mod, "VoiceOutputRouter", _FakeRouter)

    tts_calls: list[bool] = []
    import agents.studio_compositor.vad_ducking as vad_mod

    monkeypatch.setattr(vad_mod, "publish_tts_state", lambda v: tts_calls.append(bool(v)))

    from agents.studio_compositor.director_loop import DirectorLoop

    programme_box: dict[str, object] = {"programme": None}
    loop = DirectorLoop(
        [MagicMock()], MagicMock(), programme_provider=lambda: programme_box["programme"]
    )

    def _set_programme(p):
        programme_box["programme"] = p

    return SimpleNamespace(loop=loop, tts_calls=tts_calls, set_programme=_set_programme)


def _last_write():
    assert _FakeAudioOutput.instances, "no audio output constructed"
    writes = _FakeAudioOutput.instances[-1].writes
    assert writes, "audio output never written"
    return writes[-1]


def test_no_programme_routes_private_monitor(director):
    """No active programme → no broadcast intent → private monitor, no duck."""
    director.set_programme(None)
    director.loop._play_audio(b"\x00\x00" * 100)
    target, media_role = _last_write()
    assert target == "hapax-private-monitor-sink"
    assert media_role == "Assistant"
    assert director.tts_calls == []  # tts_active never published off-broadcast


def test_unauthorized_programme_fails_closed_to_private(director, monkeypatch):
    """A programme with no fresh authorization → gate blocks → private."""
    import agents.hapax_daimonion.cpal.destination_channel as dc

    monkeypatch.setattr(
        dc,
        "resolve_playback_decision",
        lambda *a, **k: _FakeDecision(allowed=False, destination="livestream"),
    )
    director.set_programme(SimpleNamespace(programme_id="prog-1"))
    director.loop._play_audio(b"\x00\x00" * 100)
    target, _ = _last_write()
    assert target == "hapax-private-monitor-sink"
    assert director.tts_calls == []


def test_authorized_programme_broadcasts_and_brackets_tts_active(director, monkeypatch):
    """All gates pass → audio reaches the broadcast target and tts_active is
    published True before and False after playback (deepest-duck trigger)."""
    import agents.hapax_daimonion.cpal.destination_channel as dc

    monkeypatch.setattr(
        dc,
        "resolve_playback_decision",
        lambda *a, **k: _FakeDecision(
            allowed=True,
            destination="livestream",
            target="hapax-broadcast",
            media_role="Broadcast",
        ),
    )
    director.set_programme(SimpleNamespace(programme_id="prog-1"))
    director.loop._play_audio(b"\x00\x00" * 100)
    target, media_role = _last_write()
    assert target == "hapax-broadcast"
    assert media_role == "Broadcast"
    assert director.tts_calls == [True, False]  # bracketed around playback


def test_broadcast_decision_exception_falls_back_private(director, monkeypatch):
    """An error resolving the broadcast decision must fail closed to private."""
    import agents.hapax_daimonion.cpal.destination_channel as dc

    def _boom(*a, **k):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(dc, "resolve_playback_decision", _boom)
    director.set_programme(SimpleNamespace(programme_id="prog-1"))
    director.loop._play_audio(b"\x00\x00" * 100)
    target, _ = _last_write()
    assert target == "hapax-private-monitor-sink"
    assert director.tts_calls == []


def test_real_gate_default_is_fail_closed_to_private(director):
    """Integration: with the REAL gate and no runtime authorization/safety
    signals present, a programme without authorization stays private. Guards
    the no-self-mint + fail-closed contract end to end."""
    director.set_programme(SimpleNamespace(programme_id="prog-1"))
    director.loop._play_audio(b"\x00\x00" * 100)
    target, _ = _last_write()
    assert target == "hapax-private-monitor-sink"
    assert director.tts_calls == []


def test_private_route_unavailable_drops(director):
    """When the private route reports no sink, playback is dropped (no
    default-sink fallback) and nothing is written."""
    _FakeRouter.sink_name = None
    director.set_programme(None)
    director.loop._play_audio(b"\x00\x00" * 100)
    # No write occurred (output may or may not have been constructed, but the
    # private sink was unavailable so nothing was played).
    if _FakeAudioOutput.instances:
        assert _FakeAudioOutput.instances[-1].writes == []
    assert director.tts_calls == []
