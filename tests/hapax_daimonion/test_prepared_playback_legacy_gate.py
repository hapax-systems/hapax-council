from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shared.programme import ProgrammeContent


def _context(content: ProgrammeContent) -> SimpleNamespace:
    return SimpleNamespace(programme=SimpleNamespace(content=content))


def test_live_prior_prepared_script_does_not_suppress_live_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.hapax_daimonion import run_loops_aux

    monkeypatch.delenv(run_loops_aux.PREP_VERBATIM_LEGACY_ENV, raising=False)
    monkeypatch.setattr(run_loops_aux, "_ensure_prepped_loaded", lambda: None)

    content = ProgrammeContent(
        hosting_context="hapax_responsible_live",
        prepared_script=["Prepared words are prior context, not direct playback."],
    )

    assert run_loops_aux._try_prepared_delivery(_context(content)) is None


def test_legacy_verbatim_requires_delivery_mode_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.hapax_daimonion import run_loops_aux

    monkeypatch.setattr(run_loops_aux, "_ensure_prepped_loaded", lambda: None)
    legacy_content = ProgrammeContent(
        delivery_mode="verbatim_legacy",
        prepared_script=["Legacy direct playback."],
    )
    live_prior_content = ProgrammeContent(
        delivery_mode="live_prior",
        prepared_script=["Live prior playback must still compose."],
    )

    monkeypatch.delenv(run_loops_aux.PREP_VERBATIM_LEGACY_ENV, raising=False)
    assert run_loops_aux._try_prepared_delivery(_context(legacy_content)) is None

    monkeypatch.setenv(run_loops_aux.PREP_VERBATIM_LEGACY_ENV, "1")
    assert run_loops_aux._try_prepared_delivery(_context(live_prior_content)) is None
    assert run_loops_aux._try_prepared_delivery(_context(legacy_content)) == (
        run_loops_aux._DELIVERY_WAIT
    )


@pytest.mark.asyncio
async def test_prepared_playback_loop_skips_live_prior_content_even_when_env_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.hapax_daimonion import run_loops_aux

    synthesize = Mock(return_value=b"pcm")
    cpal = SimpleNamespace(_tts_manager=SimpleNamespace(synthesize=synthesize))
    daemon = SimpleNamespace(_running=True, _cpal_runner=cpal)
    active = SimpleNamespace(
        programme_id="prog-live-prior",
        content=ProgrammeContent(
            delivery_mode="live_prior",
            prepared_script=["This should not be synthesized by the legacy loop."],
        ),
    )
    store = SimpleNamespace(active_programme=lambda: active)

    async def stop_after_sleep(_delay: float) -> None:
        daemon._running = False

    monkeypatch.setenv(run_loops_aux.PREP_VERBATIM_LEGACY_ENV, "1")
    monkeypatch.setattr(run_loops_aux, "_ensure_prepped_loaded", lambda: None)
    monkeypatch.setattr(run_loops_aux.asyncio, "sleep", stop_after_sleep)
    monkeypatch.setattr("shared.programme_store.default_store", lambda: store)

    await run_loops_aux.prepared_playback_loop(daemon)

    synthesize.assert_not_called()
