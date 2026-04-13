"""Tests for the daimonion affordance-dispatch impingement loop.

Regression coverage for the silent-failure class introduced by PR #555
(`refactor(daimonion): delete CognitiveLoop, CPAL as sole coordinator`),
which silently removed the spawn of ``impingement_consumer_loop`` while
claiming the CPAL adapter "Replaces ... impingement_consumer_loop
routing". It did not — CPAL only owns spontaneous speech surfacing.
The loop must still run to deliver six other effects:

- ``system.notify_operator`` → ``activate_notification`` delivery
- Thompson learning for ``studio.*`` / world-domain recruitment
- ``ExpressionCoordinator.coordinate`` cross-modal dispatch
- ``_system_awareness.activate``
- ``_discovery_handler.search``/``propose``

These tests mock the ImpingementConsumer and drive one iteration of the
loop body manually so the dispatch branches are exercised without
blocking on ``asyncio.sleep`` or a real daemon.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from agents._impingement import Impingement
from agents.hapax_daimonion import run_loops_aux


def _make_daemon() -> MagicMock:
    """Build a minimal daemon double with all attributes the loop reads."""
    daemon = MagicMock()
    daemon._running = True
    daemon._affordance_pipeline = MagicMock()
    daemon._affordance_pipeline.select.return_value = []
    daemon._affordance_pipeline.record_outcome = MagicMock()
    daemon._expression_coordinator = MagicMock()
    daemon._expression_coordinator.coordinate.return_value = []
    daemon._system_awareness = MagicMock()
    daemon._system_awareness.can_resolve.return_value = 0.0
    daemon._discovery_handler = MagicMock()
    daemon._discovery_handler.search.return_value = []
    return daemon


def _make_candidate(name: str, combined: float = 0.6) -> MagicMock:
    """Build an affordance pipeline candidate double."""
    candidate = MagicMock()
    candidate.capability_name = name
    candidate.combined = combined
    return candidate


def _make_impingement(source: str = "imagination", strength: float = 0.8, **content) -> Impingement:
    base_content = {"narrative": "a gentle shimmer", "material": "water"}
    base_content.update(content)
    return Impingement(
        timestamp=0.0,
        source=source,
        type="pattern_match",
        strength=strength,
        content=base_content,
        context={},
    )


async def _drive_one_iteration(daemon, candidates, imp) -> None:
    """Run the dispatch body of the loop once against a given candidate set.

    Inlines the body because the real loop does blocking I/O and sleeps.
    Kept in lockstep with ``impingement_consumer_loop`` via
    ``test_dispatch_body_stays_in_lockstep``.
    """
    _world_enabled = run_loops_aux._world_routing_enabled()
    daemon._affordance_pipeline.select.return_value = candidates

    for c in candidates:
        if c.capability_name == "system.notify_operator":
            if c.combined >= 0.4:
                from agents.notification_capability import activate_notification

                narrative = imp.content.get("narrative", imp.source)
                material = imp.content.get("material", "void")
                activate_notification(narrative, c.combined, material)
                daemon._affordance_pipeline.record_outcome(
                    c.capability_name,
                    success=True,
                    context={"source": imp.source},
                )
            continue
        if c.capability_name.startswith("studio.") and c.capability_name not in (
            "studio.midi_beat",
            "studio.midi_tempo",
            "studio.mixer_energy",
            "studio.mixer_bass",
            "studio.mixer_mid",
            "studio.mixer_high",
            "studio.desk_activity",
            "studio.desk_gesture",
            "studio.speech_emotion",
            "studio.music_genre",
            "studio.flow_state",
            "studio.audio_events",
            "studio.ambient_noise",
        ):
            if c.combined >= 0.3:
                daemon._affordance_pipeline.record_outcome(
                    c.capability_name,
                    success=True,
                    context={"source": imp.source},
                )
            continue
        if (
            any(c.capability_name.startswith(p) for p in run_loops_aux._WORLD_DOMAIN_PREFIXES)
            and _world_enabled
        ):
            if c.combined >= 0.3:
                daemon._affordance_pipeline.record_outcome(
                    c.capability_name,
                    success=True,
                    context={"source": imp.source},
                )
            continue
        if c.capability_name == "speech_production":
            continue
        if c.capability_name == "system_awareness":
            score = daemon._system_awareness.can_resolve(imp)
            if score > 0:
                daemon._system_awareness.activate(imp, score)
        elif c.capability_name == "capability_discovery":
            intent = daemon._discovery_handler.extract_intent(imp)
            results = daemon._discovery_handler.search(intent)
            if results:
                daemon._discovery_handler.propose(results)

    if len(candidates) > 1:
        recruited_pairs = [
            (c.capability_name, getattr(daemon, f"_{c.capability_name}", None))
            for c in candidates
            if c.capability_name != "speech_production"
        ]
        recruited_pairs = [(n, cap) for n, cap in recruited_pairs if cap is not None]
        if len(recruited_pairs) > 1:
            daemon._expression_coordinator.coordinate(imp.content, recruited_pairs)


class TestSpawnRegressionPin:
    """Static tests that lock in the PR #555 regression fix.

    These are deliberately redundant with the dispatch behaviour tests —
    they exist to fail loudly if a refactor removes the spawn again,
    which is exactly the failure mode PR #555 introduced.
    """

    def test_run_inner_imports_impingement_consumer_loop(self) -> None:
        from agents.hapax_daimonion import run_inner

        src = inspect.getsource(run_inner)
        assert "impingement_consumer_loop" in src, (
            "run_inner.py must import impingement_consumer_loop — PR #555 "
            "silently removed this spawn and 6 downstream effects went dead."
        )

    def test_run_inner_spawns_affordance_dispatch_loop(self) -> None:
        from agents.hapax_daimonion import run_inner

        src = inspect.getsource(run_inner)
        assert "asyncio.create_task(impingement_consumer_loop(daemon))" in src, (
            "run_inner.py must spawn impingement_consumer_loop as a "
            "background task next to _cpal_impingement_loop."
        )

    def test_impingement_consumer_loop_uses_affordance_cursor_path(self) -> None:
        """The dispatch loop must use its own cursor file.

        Sharing a cursor with the CPAL loop would cause each loop to see
        only half the impingements (whichever consumer read the line
        first). The affordance loop owns
        ``impingement-cursor-daimonion-affordance.txt``.
        """
        src = inspect.getsource(run_loops_aux.impingement_consumer_loop)
        assert "impingement-cursor-daimonion-affordance.txt" in src

    def test_loop_does_not_reference_proactive_gate(self) -> None:
        """CPAL owns spontaneous speech — loop must not touch _proactive_gate."""
        src = inspect.getsource(run_loops_aux.impingement_consumer_loop)
        assert "_proactive_gate" not in src, (
            "CPAL owns the spontaneous speech gate via "
            "CpalRunner.process_impingement → adapter.should_surface. "
            "The loop must not fire _proactive_gate or _handle_proactive_impingement."
        )

    def test_handle_proactive_impingement_is_removed(self) -> None:
        """The helper that used to duplicate CPAL's speech path is gone."""
        assert not hasattr(run_loops_aux, "_handle_proactive_impingement")

    def test_loop_skips_apperception_cascade(self) -> None:
        """Apperception cascade is owned by ApperceptionTick in VLA now."""
        src = inspect.getsource(run_loops_aux.impingement_consumer_loop)
        assert "_apperception_cascade" not in src
        assert "impingement_to_cascade_event" not in src


@pytest.fixture(autouse=True)
def _world_routing_off(monkeypatch, tmp_path):
    """Default world routing to OFF for every test.

    Individual tests that exercise world-domain routing override this
    with an explicit monkeypatch. Without this fixture the global flag
    at ``~/.cache/hapax/world-routing-enabled`` leaks into test runs.
    """
    monkeypatch.setattr(
        run_loops_aux,
        "_WORLD_ROUTING_FLAG",
        tmp_path / "world-routing-off",
    )


class TestDispatchBehaviour:
    """Exercise each dispatch branch with mocked candidates."""

    @pytest.mark.asyncio
    async def test_notification_dispatch_fires_activate_notification(self) -> None:
        daemon = _make_daemon()
        imp = _make_impingement(narrative="please tell me")
        candidate = _make_candidate("system.notify_operator", combined=0.6)

        with patch(
            "agents.notification_capability.activate_notification",
            return_value=True,
        ) as m_activate:
            await _drive_one_iteration(daemon, [candidate], imp)

        m_activate.assert_called_once()
        call_args = m_activate.call_args
        assert call_args.args[0] == "please tell me"
        assert call_args.args[1] == 0.6
        assert call_args.args[2] == "water"
        daemon._affordance_pipeline.record_outcome.assert_called_once_with(
            "system.notify_operator",
            success=True,
            context={"source": "imagination"},
        )

    @pytest.mark.asyncio
    async def test_notification_dispatch_respects_score_floor(self) -> None:
        daemon = _make_daemon()
        imp = _make_impingement()
        candidate = _make_candidate("system.notify_operator", combined=0.39)

        with patch(
            "agents.notification_capability.activate_notification",
            return_value=True,
        ) as m_activate:
            await _drive_one_iteration(daemon, [candidate], imp)

        m_activate.assert_not_called()
        daemon._affordance_pipeline.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_studio_control_records_outcome(self) -> None:
        daemon = _make_daemon()
        imp = _make_impingement()
        candidate = _make_candidate("studio.focus_camera", combined=0.5)

        await _drive_one_iteration(daemon, [candidate], imp)

        daemon._affordance_pipeline.record_outcome.assert_called_once_with(
            "studio.focus_camera",
            success=True,
            context={"source": "imagination"},
        )

    @pytest.mark.asyncio
    async def test_studio_perception_feeds_are_not_routed(self) -> None:
        """Passive perception streams like midi_beat must not record outcomes."""
        daemon = _make_daemon()
        imp = _make_impingement()
        candidate = _make_candidate("studio.midi_beat", combined=0.9)

        await _drive_one_iteration(daemon, [candidate], imp)

        daemon._affordance_pipeline.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_world_domain_routing_gated_by_flag(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            run_loops_aux,
            "_WORLD_ROUTING_FLAG",
            tmp_path / "world-routing-enabled",
        )
        daemon = _make_daemon()
        imp = _make_impingement()
        candidate = _make_candidate("world.web_search", combined=0.4)

        # Flag absent → no routing
        await _drive_one_iteration(daemon, [candidate], imp)
        daemon._affordance_pipeline.record_outcome.assert_not_called()

        # Flag present → routes
        (tmp_path / "world-routing-enabled").write_text("", encoding="utf-8")
        await _drive_one_iteration(daemon, [candidate], imp)
        daemon._affordance_pipeline.record_outcome.assert_called_once_with(
            "world.web_search",
            success=True,
            context={"source": "imagination"},
        )

    @pytest.mark.asyncio
    async def test_speech_production_is_skipped(self) -> None:
        """CPAL owns spontaneous speech — dispatch loop must not fire it."""
        daemon = _make_daemon()
        daemon._speech_capability = MagicMock()
        imp = _make_impingement()
        candidate = _make_candidate("speech_production", combined=0.9)

        await _drive_one_iteration(daemon, [candidate], imp)

        daemon._speech_capability.activate.assert_not_called()
        daemon._affordance_pipeline.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_awareness_gated_by_can_resolve(self) -> None:
        daemon = _make_daemon()
        daemon._system_awareness.can_resolve.return_value = 0.0
        imp = _make_impingement()
        candidate = _make_candidate("system_awareness", combined=0.7)

        await _drive_one_iteration(daemon, [candidate], imp)
        daemon._system_awareness.activate.assert_not_called()

        daemon._system_awareness.can_resolve.return_value = 0.8
        await _drive_one_iteration(daemon, [candidate], imp)
        daemon._system_awareness.activate.assert_called_once_with(imp, 0.8)

    @pytest.mark.asyncio
    async def test_capability_discovery_chain(self) -> None:
        daemon = _make_daemon()
        daemon._discovery_handler.extract_intent.return_value = {"query": "cactus"}
        daemon._discovery_handler.search.return_value = [{"name": "cactus-cli"}]
        imp = _make_impingement()
        candidate = _make_candidate("capability_discovery", combined=0.6)

        await _drive_one_iteration(daemon, [candidate], imp)

        daemon._discovery_handler.extract_intent.assert_called_once_with(imp)
        daemon._discovery_handler.search.assert_called_once_with({"query": "cactus"})
        daemon._discovery_handler.propose.assert_called_once_with([{"name": "cactus-cli"}])

    @pytest.mark.asyncio
    async def test_capability_discovery_no_results_skips_propose(self) -> None:
        daemon = _make_daemon()
        daemon._discovery_handler.extract_intent.return_value = {"query": "nothing"}
        daemon._discovery_handler.search.return_value = []
        imp = _make_impingement()
        candidate = _make_candidate("capability_discovery", combined=0.6)

        await _drive_one_iteration(daemon, [candidate], imp)

        daemon._discovery_handler.propose.assert_not_called()

    @pytest.mark.asyncio
    async def test_cross_modal_excludes_speech(self) -> None:
        """Speech must not be double-dispatched via cross-modal coordination."""
        daemon = _make_daemon()
        imp = _make_impingement()
        daemon._system_awareness.operational = MagicMock(medium="textual")
        daemon._discovery_handler.operational = MagicMock(medium="notification")
        candidates = [
            _make_candidate("speech_production"),
            _make_candidate("system_awareness"),
            _make_candidate("capability_discovery"),
        ]

        await _drive_one_iteration(daemon, candidates, imp)

        daemon._expression_coordinator.coordinate.assert_called_once()
        pairs = daemon._expression_coordinator.coordinate.call_args.args[1]
        names = [name for name, _ in pairs]
        assert "speech_production" not in names
        assert "system_awareness" in names or "capability_discovery" in names


class TestDispatchBodyLockstep:
    """Guard that the test's inlined body matches the real loop.

    Fails if a future edit changes the loop but forgets to update the
    test helper — the test would otherwise silently drift from the real
    implementation.
    """

    def test_dispatch_body_stays_in_lockstep(self) -> None:
        src = inspect.getsource(run_loops_aux.impingement_consumer_loop)
        # Key landmarks the test helper mirrors
        for landmark in (
            "system.notify_operator",
            "studio.midi_beat",
            "_WORLD_DOMAIN_PREFIXES",
            "speech_production",
            "system_awareness",
            "capability_discovery",
            "_expression_coordinator",
        ):
            assert landmark in src, (
                f"loop body is missing landmark {landmark!r}; "
                "update _drive_one_iteration in this test file"
            )
