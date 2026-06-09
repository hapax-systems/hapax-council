"""Director audio routing: fail-closed broadcast gate + private fallback.

History: per cc-task ``director-loop-semantic-audio-route`` (2026-05-01) the
director stopped hard-coding the PipeWire loopback sink literal and resolved the
``private_monitor`` role through ``shared.voice_output_router.VoiceOutputRouter``.

Now (``segment-audio-hosting-readiness-20260607``, AC#4) ``_play_audio`` also
offers hosting speech to PUBLIC_BROADCAST *through* the fail-closed
``resolve_playback_decision`` classifier, keeping ``private_monitor`` as the
never-removed fallback. These are SOURCE pins for the invariants that must not
silently regress; behavioural coverage lives in
``test_director_broadcast_routing.py``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIRECTOR_LOOP = REPO_ROOT / "agents" / "studio_compositor" / "director_loop.py"


def _method_body(name: str) -> str:
    """Extract the body of a director method as a string."""
    body = DIRECTOR_LOOP.read_text(encoding="utf-8")
    marker = f"    def {name}(self"
    start = body.index(marker)
    rest = body[start + len(marker) :]
    end = rest.index("\n    def ")
    return marker + rest[:end]


def test_play_audio_keeps_private_monitor_fallback() -> None:
    """The private_monitor role remains the never-removed fallback path."""
    body = _method_body("_play_audio")
    assert "from shared.voice_output_router import VoiceOutputRouter" in body
    assert 'route("private_monitor")' in body
    assert "result.sink_name" in body
    # notification is a separate surface and must never be the director's route.
    assert '"notification"' not in body


def test_play_audio_routes_through_fail_closed_gate() -> None:
    """Broadcast is offered THROUGH resolve_playback_decision, not swapped in.

    The director must consult the fail-closed classifier (via the helper) and
    only broadcast on an allowed ``livestream`` decision."""
    play_body = _method_body("_play_audio")
    assert "_resolve_broadcast_decision()" in play_body
    assert 'decision.destination == "livestream"' in play_body
    assert "decision.allowed" in play_body

    helper_body = _method_body("_resolve_broadcast_decision")
    assert "resolve_playback_decision" in helper_body
    # No self-minted authorization: the director only forwards an authorization
    # the Programme already carries.
    assert "programme_authorization" in helper_body
    assert 'getattr(programme, "programme_authorization"' in helper_body


def test_play_audio_drops_when_sink_unavailable() -> None:
    """When the private route reports no sink, the director fails closed."""
    body = _method_body("_play_audio")
    assert "if target is None:" in body
    assert "Audio playback dropped" in body
    assert "return" in body


def test_tts_active_published_only_while_broadcasting() -> None:
    """tts_active is bracketed around the broadcast write, never off-broadcast.

    The ``publish_tts_state`` calls live inside the ``if broadcasting:`` guards
    so private monitor speech does not duck the broadcast music bed."""
    body = _method_body("_play_audio")
    assert "publish_tts_state(True)" in body
    assert "publish_tts_state(False)" in body
    # Both publishes are guarded by the broadcasting flag.
    assert body.count("if broadcasting:") >= 2


def test_no_other_hardcoded_voice_sinks_in_director_loop() -> None:
    """No remaining literal loopback role sink anywhere in director_loop."""
    body = DIRECTOR_LOOP.read_text(encoding="utf-8")
    occurrences = body.count("input.loopback.sink.role.")
    assert occurrences == 0, (
        f"Expected 0 hardcoded loopback-sink references; found {occurrences}. "
        f"Each new occurrence should go through the VoiceOutputRouter API."
    )
