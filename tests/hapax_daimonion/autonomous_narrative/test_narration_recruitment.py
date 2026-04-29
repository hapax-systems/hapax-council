"""Tests for the pipeline-recruited autonomous narration dispatch.

Replaces test_gates.py and test_loop_integration.py after the
de-expert-system migration. Verifies that _dispatch_autonomous_narration
composes → emits → records outcome → sets refractory inhibition.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _fake_imp(source: str = "test.impingement") -> SimpleNamespace:
    imp = SimpleNamespace(
        id="test-imp-001",
        source=source,
        content={"narrative": "test signal", "metric": "test"},
        intent_family=None,
        interrupt_token=None,
        strength=0.6,
    )
    if source == "endogenous.narrative_drive":
        imp.content.update(
            {
                "wcs_snapshot_ref": "wcs:audio.broadcast_voice:voice-output-witness",
                "route_evidence_ref": "route:audio.broadcast_voice:health_witness_required",
                "public_claim_evidence_ref": "claim_posture:bounded_nonassertive_narration",
            }
        )
    return imp


def _fake_candidate(score: float = 0.5) -> SimpleNamespace:
    return SimpleNamespace(
        capability_name="narration.autonomous_first_system",
        combined=score,
        similarity=score,
        payload={"daemon": "daimonion"},
    )


def _fake_daemon() -> MagicMock:
    daemon = MagicMock()
    daemon._running = True
    daemon._affordance_pipeline = MagicMock()
    daemon.programme_manager = None
    daemon.perception = MagicMock()
    daemon.perception.latest = None
    daemon.session = MagicMock()
    daemon.session.is_active = False
    return daemon


@pytest.fixture(autouse=True)
def _triad_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from shared import narration_triad

    monkeypatch.setattr(narration_triad, "TRIAD_LEDGER_PATH", tmp_path / "triads.jsonl")
    monkeypatch.setattr(narration_triad, "TRIAD_STATE_PATH", tmp_path / "triad-state.json")


class TestDispatchAutonomousNarration:
    """Test _dispatch_autonomous_narration from run_loops_aux."""

    def test_successful_narration_records_success_and_inhibition(self, tmp_path: Path):
        """Speech emission opens semantic debt before learning succeeds."""
        from agents.hapax_daimonion.run_loops_aux import _dispatch_autonomous_narration

        daemon = _fake_daemon()
        imp = _fake_imp()
        candidate = _fake_candidate()

        with (
            patch(
                "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
                return_value="Hapax observes shifting patterns in the recruitment pipeline.",
            ) as compose_mock,
            patch(
                "agents.hapax_daimonion.autonomous_narrative.emit.emit_narrative",
                return_value=True,
            ),
            patch(
                "agents.hapax_daimonion.autonomous_narrative.emit.record_metric",
            ) as mock_metric,
            patch(
                "agents.hapax_daimonion.autonomous_narrative.state_readers.assemble_context",
                return_value=SimpleNamespace(
                    programme=None,
                    stimmung_tone="ambient",
                    director_activity="observe",
                    chronicle_events=(),
                    vault_context=SimpleNamespace(is_empty=lambda: True),
                ),
            ),
        ):
            _dispatch_autonomous_narration(daemon, imp, candidate)

            assert "operator_referent" in compose_mock.call_args.kwargs
            daemon._affordance_pipeline.record_outcome.assert_called_once()
            call_args = daemon._affordance_pipeline.record_outcome.call_args
            assert call_args[0][0] == "narration.autonomous_first_system"
            assert call_args[1]["success"] is False  # semantic outcome still open
            assert call_args[1]["context"]["learning_update_allowed"] is False
            assert call_args[1]["context"]["semantic_status"] == "open"

            # Refractory inhibition set
            daemon._affordance_pipeline.add_inhibition.assert_called_once()
            inhibit_args = daemon._affordance_pipeline.add_inhibition.call_args
            assert inhibit_args[1]["duration_s"] == 120.0

            # Metric recorded as "allow"
            mock_metric.assert_called_with("allow")

    def test_partial_emit_records_success_with_partial_metric(self):
        from agents.hapax_daimonion.autonomous_narrative.emit import EmitResult
        from agents.hapax_daimonion.run_loops_aux import _dispatch_autonomous_narration

        daemon = _fake_daemon()

        with (
            patch(
                "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
                return_value="Signal density changes in the recent window.",
            ),
            patch(
                "agents.hapax_daimonion.autonomous_narrative.emit.emit_narrative",
                return_value=EmitResult(
                    impingement_written=True,
                    jsonl_chronicle_written=True,
                    chronicle_recorded=False,
                ),
            ),
            patch(
                "agents.hapax_daimonion.autonomous_narrative.emit.record_metric",
            ) as mock_metric,
            patch(
                "agents.hapax_daimonion.autonomous_narrative.state_readers.assemble_context",
                return_value=SimpleNamespace(
                    programme=None,
                    stimmung_tone="ambient",
                    director_activity="observe",
                    chronicle_events=(),
                    vault_context=SimpleNamespace(is_empty=lambda: True),
                ),
            ),
        ):
            _dispatch_autonomous_narration(daemon, _fake_imp(), _fake_candidate())

        daemon._affordance_pipeline.record_outcome.assert_called_once()
        assert daemon._affordance_pipeline.record_outcome.call_args.kwargs["success"] is False
        assert (
            daemon._affordance_pipeline.record_outcome.call_args.kwargs["context"][
                "learning_update_allowed"
            ]
            is False
        )
        mock_metric.assert_called_with("partial_success")

    def test_compose_returns_none_records_failure(self):
        """When compose returns None (LLM silent), record_outcome(success=False)."""
        from agents.hapax_daimonion.run_loops_aux import _dispatch_autonomous_narration

        daemon = _fake_daemon()
        imp = _fake_imp()
        candidate = _fake_candidate()

        with (
            patch(
                "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
                return_value=None,
            ),
            patch(
                "agents.hapax_daimonion.autonomous_narrative.emit.record_metric",
            ) as mock_metric,
            patch(
                "agents.hapax_daimonion.autonomous_narrative.state_readers.assemble_context",
                return_value=SimpleNamespace(
                    programme=None,
                    stimmung_tone="ambient",
                    director_activity="observe",
                    chronicle_events=(),
                    vault_context=SimpleNamespace(is_empty=lambda: True),
                ),
            ),
        ):
            _dispatch_autonomous_narration(daemon, imp, candidate)

            daemon._affordance_pipeline.record_outcome.assert_called_once()
            call_args = daemon._affordance_pipeline.record_outcome.call_args
            assert call_args[1]["success"] is False  # failure
            mock_metric.assert_called_with("llm_silent")

            # No inhibition set on failure
            daemon._affordance_pipeline.add_inhibition.assert_not_called()

    def test_emit_failure_records_failure(self):
        """When emit_narrative returns False, record failure."""
        from agents.hapax_daimonion.run_loops_aux import _dispatch_autonomous_narration

        daemon = _fake_daemon()

        with (
            patch(
                "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
                return_value="Some narration text.",
            ),
            patch(
                "agents.hapax_daimonion.autonomous_narrative.emit.emit_narrative",
                return_value=False,
            ),
            patch(
                "agents.hapax_daimonion.autonomous_narrative.emit.record_metric",
            ) as mock_metric,
            patch(
                "agents.hapax_daimonion.autonomous_narrative.state_readers.assemble_context",
                return_value=SimpleNamespace(
                    programme=None,
                    stimmung_tone="ambient",
                    director_activity="observe",
                    chronicle_events=(),
                    vault_context=SimpleNamespace(is_empty=lambda: True),
                ),
            ),
        ):
            _dispatch_autonomous_narration(daemon, _fake_imp(), _fake_candidate())

            daemon._affordance_pipeline.record_outcome.assert_called_once()
            call_args = daemon._affordance_pipeline.record_outcome.call_args
            assert call_args[1]["success"] is False
            mock_metric.assert_called_with("write_failed")
            daemon._affordance_pipeline.add_inhibition.assert_not_called()

    def test_narration_drive_uses_composed_text_not_raw_drive_text(self):
        from agents.hapax_daimonion.run_loops_aux import _dispatch_autonomous_narration

        daemon = _fake_daemon()
        imp = _fake_imp("endogenous.narrative_drive")
        imp.content.update(
            {
                "drive": "narration",
                "narrative": "raw pressure text that must not be spoken directly",
            }
        )
        candidate = _fake_candidate()

        with (
            patch(
                "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
                return_value="Composed public narration.",
            ),
            patch(
                "agents.hapax_daimonion.autonomous_narrative.emit.emit_narrative",
                return_value=True,
            ) as emit_mock,
            patch("agents.hapax_daimonion.autonomous_narrative.emit.record_metric"),
            patch(
                "agents.hapax_daimonion.autonomous_narrative.state_readers.assemble_context",
                return_value=SimpleNamespace(
                    programme=None,
                    stimmung_tone="ambient",
                    director_activity="observe",
                    chronicle_events=(),
                    vault_context=SimpleNamespace(is_empty=lambda: True),
                ),
            ),
        ):
            _dispatch_autonomous_narration(daemon, imp, candidate)

        assert emit_mock.call_args.args[0] == "Composed public narration."
        assert "raw pressure" not in emit_mock.call_args.args[0]
        assert emit_mock.call_args.kwargs["impulse_id"] == "test-imp-001"


class TestNarrationDriveFallback:
    """Explicit narration drives must not disappear when retrieval misses."""

    def test_detects_only_typed_narration_drive(self):
        from agents.hapax_daimonion.run_loops_aux import _is_narration_drive_impingement

        imp = _fake_imp("endogenous.narrative_drive")
        imp.content["drive"] = "narration"

        assert _is_narration_drive_impingement(imp) is True
        assert _is_narration_drive_impingement(_fake_imp("exploration.stimmung")) is False

        imp.content["drive"] = "observation"
        assert _is_narration_drive_impingement(imp) is False

    def test_builds_candidate_from_drive_strength(self):
        from agents.hapax_daimonion.run_loops_aux import _narration_drive_fallback_candidate

        imp = _fake_imp("endogenous.narrative_drive")
        imp.content["drive"] = "narration"
        imp.strength = 0.42

        candidate = _narration_drive_fallback_candidate(imp)

        assert candidate.capability_name == "narration.autonomous_first_system"
        assert candidate.combined == pytest.approx(0.42)
        assert candidate.similarity == pytest.approx(0.42)
        assert candidate.payload["source"] == "endogenous.narrative_drive"
        assert candidate.payload["capability_contract_evidence"] == "typed_narration_drive"
        assert candidate.payload["impulse_id"] == "test-imp-001"
        assert candidate.payload["action_tendency"] == "speak"
        assert candidate.payload["speech_act_candidate"] == "autonomous_narrative"
        assert candidate.payload["strength_posterior"] == pytest.approx(0.42)
        assert candidate.payload["evidence_refs"] == [
            "source:endogenous.narrative_drive",
            "drive:narration",
            "impingement:test-imp-001",
        ]

    def test_dispatches_when_retrieval_misses_narration(self):
        from agents.hapax_daimonion import run_loops_aux

        daemon = _fake_daemon()
        imp = _fake_imp("endogenous.narrative_drive")
        imp.content["drive"] = "narration"
        candidates = [SimpleNamespace(capability_name="system.exploration_deficit", combined=0.7)]

        with patch.object(run_loops_aux, "_dispatch_autonomous_narration") as dispatch:
            dispatched = run_loops_aux._dispatch_narration_drive_fallback_if_needed(
                daemon, imp, candidates
            )

        assert dispatched is True
        dispatch.assert_called_once()
        assert dispatch.call_args.args[0] is daemon
        assert dispatch.call_args.args[1] is imp
        assert dispatch.call_args.args[2].capability_name == "narration.autonomous_first_system"

    def test_does_not_duplicate_successful_narration_recruitment(self):
        from agents.hapax_daimonion import run_loops_aux

        daemon = _fake_daemon()
        imp = _fake_imp("endogenous.narrative_drive")
        imp.content["drive"] = "narration"
        candidates = [_fake_candidate(score=0.5)]

        with patch.object(run_loops_aux, "_dispatch_autonomous_narration") as dispatch:
            dispatched = run_loops_aux._dispatch_narration_drive_fallback_if_needed(
                daemon, imp, candidates
            )

        assert dispatched is False
        dispatch.assert_not_called()


class TestAffordanceRegistration:
    """Verify narration.autonomous_first_system is properly registered."""

    def test_narration_affordance_in_all_affordances(self):
        from shared.affordance_registry import ALL_AFFORDANCES

        names = [a.name for a in ALL_AFFORDANCES]
        assert "narration.autonomous_first_system" in names

    def test_narration_affordance_properties(self):
        from shared.affordance_registry import EXPRESSION_AFFORDANCES

        narration = [
            a for a in EXPRESSION_AFFORDANCES if a.name == "narration.autonomous_first_system"
        ]
        assert len(narration) == 1
        record = narration[0]
        assert record.daemon == "daimonion"
        assert record.operational.latency_class == "slow"
        assert record.operational.medium == "speech"

    def test_narration_domain_in_domains(self):
        from shared.affordance_registry import AFFORDANCE_DOMAINS

        assert "narration" in AFFORDANCE_DOMAINS


class TestLegacyRemoval:
    """Verify that the legacy loop + gates modules are fully removed."""

    def test_loop_module_not_importable(self):
        with pytest.raises(ImportError):
            import agents.hapax_daimonion.autonomous_narrative.loop  # noqa: F401

    def test_gates_module_not_importable(self):
        with pytest.raises(ImportError):
            import agents.hapax_daimonion.autonomous_narrative.gates  # noqa: F401

    def test_run_inner_does_not_reference_autonomous_narrative_loop(self):
        import inspect  # noqa: PLC0415

        from agents.hapax_daimonion import run_inner  # noqa: PLC0415

        source = inspect.getsource(run_inner)
        assert "autonomous_narrative_loop" not in source
