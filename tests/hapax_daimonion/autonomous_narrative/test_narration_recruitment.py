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
    return SimpleNamespace(
        id="test-imp-001",
        source=source,
        content={"narrative": "test signal", "metric": "test"},
        intent_family=None,
        interrupt_token=None,
        strength=0.6,
    )


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


class TestDispatchAutonomousNarration:
    """Test _dispatch_autonomous_narration from run_loops_aux."""

    def test_successful_narration_records_success_and_inhibition(self, tmp_path: Path):
        """When compose returns text and emit succeeds, record_outcome(success=True)
        and add_inhibition should both be called."""
        from agents.hapax_daimonion.run_loops_aux import _dispatch_autonomous_narration

        daemon = _fake_daemon()
        imp = _fake_imp()
        candidate = _fake_candidate()

        with (
            patch(
                "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
                return_value="Hapax observes shifting patterns in the recruitment pipeline.",
            ),
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

            # Thompson outcome recorded as success
            daemon._affordance_pipeline.record_outcome.assert_called_once()
            call_args = daemon._affordance_pipeline.record_outcome.call_args
            assert call_args[0][0] == "narration.autonomous_first_system"
            assert call_args[1]["success"] is True  # kwarg

            # Refractory inhibition set
            daemon._affordance_pipeline.add_inhibition.assert_called_once()
            inhibit_args = daemon._affordance_pipeline.add_inhibition.call_args
            assert inhibit_args[1]["duration_s"] == 120.0

            # Metric recorded as "allow"
            mock_metric.assert_called_with("allow")

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
