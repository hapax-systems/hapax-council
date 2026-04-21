"""Regression pin for FINDING-F (wiring audit, 2026-04-20).

The compositor-side DuckController polls
``/dev/shm/hapax-compositor/voice-state.json`` to drive YouTube /
broadcast ducking. Pre-fix, the file was ABSENT until the first
UserStartedSpeakingFrame fired through the conversation pipeline —
which only opens after engagement detection. A quiet-operator startup
left the file missing for the entire daimonion process lifetime, so
the duck never differentiated speech from silence.

Fix: ``run_inner`` calls ``publish_vad_state(False)`` near startup so
the file exists with a known baseline from boot. Real VAD events
overwrite as they arrive.

This test confirms the baseline-publish call is wired into the
``run_inner`` startup path. Pure-call regression pin (does not run
the real coroutine end-to-end; that would require the full daemon
fixture).
"""

from __future__ import annotations


def test_run_inner_imports_publish_vad_state() -> None:
    """The startup baseline call lives in ``run_inner`` and is reachable
    via the same import path the function uses at runtime. If the call
    is removed or the import changes, this test fails."""
    import inspect

    from agents.hapax_daimonion import run_inner as run_inner_mod

    source = inspect.getsource(run_inner_mod.run_inner)
    assert "publish_vad_state" in source, (
        "run_inner must publish a baseline voice-state.json so "
        "DuckController has a known starting state. See FINDING-F."
    )
    assert "publish_vad_state(False)" in source, (
        "Baseline must publish False (no operator speech at startup); "
        "VadStatePublisher overwrites with True on real VAD events."
    )


def test_publish_vad_state_creates_voice_state_file(tmp_path, monkeypatch) -> None:
    """Sanity: publish_vad_state writes a parseable JSON file at the
    configured path. Catches contract drift where the publisher's
    write target diverges from DuckController's read target."""
    import json

    from agents.studio_compositor import vad_ducking

    monkeypatch.setattr(vad_ducking, "VOICE_STATE_FILE", tmp_path / "voice-state.json")
    vad_ducking.publish_vad_state(False)
    raw = (tmp_path / "voice-state.json").read_text()
    payload = json.loads(raw)
    assert payload["operator_speech_active"] is False
