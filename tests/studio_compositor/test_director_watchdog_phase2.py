"""Director liveness watchdog — Phase 2 tests.

Spec: docs/research/2026-04-20-livestream-halt-investigation.md §13 Phase 2

Phase 2 ships three behaviors on top of Phase 1's age-gated sd_notify:
  §8.2: process-wide single-flight lock + non-blocking acquire on
        _call_activity_llm — second concurrent caller returns "" without
        making the LLM call, increments
        hapax_director_tick_skipped_in_flight_total.
  §7.1: speak the micromove on opportunistic timeout, gated 1-of-N so a
        sustained timeout doesn't spam the broadcast.

These tests target the lock + the speak-gate in isolation; full LLM-call
integration is exercised by the existing director_loop integration suite.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest  # noqa: TC002 — runtime import for fixtures + decorators

import agents.studio_compositor.director_loop as dl_mod


@pytest.fixture(autouse=True)
def reset_lock_and_metrics():
    """Each test starts with the lock released."""
    # Drain any held lock from a prior test (single acquire+release suffices
    # — threading.Lock is binary, an acquire-when-free leaves it held until
    # the next release; loop here would oscillate forever).
    if dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False):
        dl_mod._DIRECTOR_LLM_LOCK.release()
    yield
    if dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False):
        dl_mod._DIRECTOR_LLM_LOCK.release()


class _FakeSlot:
    def __init__(self, slot_id: int) -> None:
        self.slot_id = slot_id
        self._title = "test video"
        self._channel = "test channel"
        self.is_active = slot_id == 0


class _FakeReactor:
    def set_header(self, *a, **k) -> None: ...
    def set_text(self, *a, **k) -> None: ...
    def set_speaking(self, *a, **k) -> None: ...
    def feed_pcm(self, *a, **k) -> None: ...


def _make_director():
    """Construct a DirectorLoop matching test_director_loop_rules_retired's
    pattern; we only exercise the lock + micromove paths."""
    return dl_mod.DirectorLoop(
        video_slots=[_FakeSlot(0), _FakeSlot(1), _FakeSlot(2)],
        reactor_overlay=_FakeReactor(),
    )


class TestSingleFlightLock:
    def test_lock_acquired_releases_after_call(self) -> None:
        director = _make_director()
        with patch.object(dl_mod, "LITELLM_KEY", "dummy"):
            with patch.object(
                director, "_call_activity_llm_locked", return_value="some response"
            ) as mock_locked:
                result = director._call_activity_llm("prompt", None)
        assert result == "some response"
        mock_locked.assert_called_once()
        # Lock must be released after a successful call.
        assert dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False)
        dl_mod._DIRECTOR_LLM_LOCK.release()

    def test_lock_released_on_inner_exception(self) -> None:
        director = _make_director()
        with patch.object(dl_mod, "LITELLM_KEY", "dummy"):
            with patch.object(
                director,
                "_call_activity_llm_locked",
                side_effect=RuntimeError("simulated"),
            ):
                with pytest.raises(RuntimeError, match="simulated"):
                    director._call_activity_llm("prompt", None)
        # Lock MUST be released even on exception.
        assert dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False)
        dl_mod._DIRECTOR_LLM_LOCK.release()

    def test_second_concurrent_call_skips_with_metric(self) -> None:
        director = _make_director()
        with patch.object(dl_mod, "LITELLM_KEY", "dummy"):
            # Simulate prior call holding the lock.
            assert dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False)
            try:
                with patch(
                    "shared.director_observability.emit_director_tick_skipped_in_flight"
                ) as mock_emit:
                    result = director._call_activity_llm("prompt", None)
            finally:
                dl_mod._DIRECTOR_LLM_LOCK.release()
        assert result == ""
        mock_emit.assert_called_once_with(reason="lock_held")

    def test_no_litellm_key_skips_lock_acquire(self) -> None:
        director = _make_director()
        with patch.object(dl_mod, "LITELLM_KEY", ""):
            with patch.object(director, "_call_activity_llm_locked") as mock_locked:
                result = director._call_activity_llm("prompt", None)
        assert result == ""
        # _call_activity_llm_locked must not be invoked when key is missing.
        mock_locked.assert_not_called()
        # Lock must NOT be held.
        assert dl_mod._DIRECTOR_LLM_LOCK.acquire(blocking=False)
        dl_mod._DIRECTOR_LLM_LOCK.release()


class TestSpeakMicromoveGate:
    def test_micromove_speaks_on_first_llm_empty_tick(self) -> None:
        director = _make_director()
        # _emit_intent_artifacts and _speak_activity are heavyweight; mock both.
        with patch.object(dl_mod, "_emit_intent_artifacts"):
            with patch.object(director, "_speak_activity") as mock_speak:
                director._emit_micromove_fallback(reason="llm_empty", condition_id="test")
        mock_speak.assert_called_once()
        # First positional arg is the narrative text.
        spoken_text = mock_speak.call_args.args[0]
        assert isinstance(spoken_text, str) and len(spoken_text) > 0

    def test_micromove_speak_gated_one_in_n(self) -> None:
        director = _make_director()
        n = dl_mod._MICROMOVE_SPEAK_EVERY_N
        with patch.object(dl_mod, "_emit_intent_artifacts"):
            with patch.object(director, "_speak_activity") as mock_speak:
                # 2*N + 1 ticks → 3 speaks (at 0, N, 2N).
                for _ in range(2 * n + 1):
                    director._emit_micromove_fallback(reason="llm_empty", condition_id="test")
        assert mock_speak.call_count == 3

    def test_no_speak_for_non_llm_empty_reason(self) -> None:
        director = _make_director()
        with patch.object(dl_mod, "_emit_intent_artifacts"):
            with patch.object(director, "_speak_activity") as mock_speak:
                director._emit_micromove_fallback(reason="parser_error", condition_id="test")
                director._emit_micromove_fallback(reason="degraded_mode", condition_id="test")
        # Other reasons must NOT trigger speech (visual-only fallback).
        mock_speak.assert_not_called()

    def test_micromove_actually_emits_intent_artifacts(self) -> None:
        """Regression pin for the DirectorIntent.stance bug: pre-fix the
        construction always raised ValidationError and the fallback
        emitted nothing — every llm_empty tick was a silent no-op
        violation of the operator no-vacuum invariant."""
        director = _make_director()
        with patch.object(dl_mod, "_emit_intent_artifacts") as mock_emit:
            director._emit_micromove_fallback(reason="llm_empty", condition_id="test")
        mock_emit.assert_called_once()
        # Verify the constructed intent has the stance field set.
        intent = mock_emit.call_args.args[0]
        assert intent.stance is not None

    def test_speak_failure_does_not_break_micromove_emission(self) -> None:
        """Speak failure must NOT raise out of _emit_micromove_fallback —
        suppression of speak fault is the contract. (The downstream
        intent emission has its own resilience path tested separately.)"""
        director = _make_director()
        with patch.object(dl_mod, "_emit_intent_artifacts"):
            with patch.object(director, "_speak_activity", side_effect=RuntimeError("tts down")):
                # Must not raise.
                director._emit_micromove_fallback(reason="llm_empty", condition_id="test")
