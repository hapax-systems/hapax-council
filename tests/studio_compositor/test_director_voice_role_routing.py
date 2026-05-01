"""Director audio routing uses the role-keyed VoiceOutputRouter API.

Per cc-task ``director-loop-semantic-audio-route`` (WSJF 8.5,
2026-05-01): the director's ``_play_audio`` previously hard-coded the
PipeWire target literal ``input.loopback.sink.role.assistant``. This
test pins that the director now resolves the target through
``shared.voice_output_router.VoiceOutputRouter`` (semantic
``private_monitor`` role) so the canonical role → sink mapping lives
in one place (``config/voice-output-routes.yaml``).

Stacks on the role-API delivery in cc-task
``voice-output-router-semantic-api`` (beta) — beta added the
``VoiceOutputRouter`` class + ``VoiceRole`` literal alongside the
existing ``resolve_voice_output_route()`` policy machinery in the
same module.

Source pin only — no runtime path execution. The director_loop module
is too large + hardware-coupled to instantiate in unit tests; pinning
the source contract is the right granularity for this PR.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIRECTOR_LOOP = REPO_ROOT / "agents" / "studio_compositor" / "director_loop.py"


def _play_audio_body() -> str:
    """Extract the body of the ``_play_audio`` method as a string."""
    body = DIRECTOR_LOOP.read_text(encoding="utf-8")
    marker = "    def _play_audio(self, pcm: bytes) -> None:"
    start = body.index(marker)
    rest = body[start + len(marker) :]
    end = rest.index("\n    def ")
    return marker + rest[:end]


def test_play_audio_imports_voice_output_router() -> None:
    """The role-keyed semantic API is imported inside _play_audio."""
    body = _play_audio_body()
    assert "from shared.voice_output_router import VoiceOutputRouter" in body


def test_play_audio_routes_private_monitor_role() -> None:
    """The director's TTS routes through the ``private_monitor`` role.
    Pin that the director picks the assistant-equivalent semantic role
    (``private_monitor``) and not ``broadcast`` or ``notification``,
    which are separate surfaces."""
    body = _play_audio_body()
    assert 'router.route("private_monitor")' in body
    assert '"broadcast"' not in body
    assert '"notification"' not in body


def test_play_audio_uses_sink_name_attribute() -> None:
    """The router's RouteResult exposes ``sink_name`` for the concrete
    PipeWire target. Pin its use rather than re-constructing the target
    inline."""
    body = _play_audio_body()
    assert "result.sink_name" in body


def test_play_audio_falls_back_when_sink_unavailable() -> None:
    """When the router reports ``sink_name == None`` (provenance
    ``unavailable``), the director must fall back to the literal sink
    so audio doesn't go silent. Pin the fallback so a future refactor
    doesn't accidentally drop it."""
    body = _play_audio_body()
    assert "input.loopback.sink.role.assistant" in body


def test_no_other_hardcoded_voice_sinks_in_director_loop() -> None:
    """The hardcoded sink replacement is exhaustive for director_loop:
    the only remaining literal is the fallback in _play_audio + a
    docstring reference inside the same method. Pin so future patches
    don't sneak new hard-coded sinks past the role-keyed API."""
    body = DIRECTOR_LOOP.read_text(encoding="utf-8")
    occurrences = body.count("input.loopback.sink.role.")
    assert occurrences == 2, (
        f"Expected 2 hardcoded loopback-sink references (fallback literal "
        f"+ docstring mention); found {occurrences}. Each new occurrence "
        f"should go through the VoiceOutputRouter API."
    )
    body_block = _play_audio_body()
    assert body_block.count("input.loopback.sink.role.") == 2
