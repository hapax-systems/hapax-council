from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from agents.hapax_daimonion import run_loops_aux


def _daemon() -> SimpleNamespace:
    return SimpleNamespace(
        _affordance_pipeline=SimpleNamespace(
            record_outcome=mock.Mock(),
            add_inhibition=mock.Mock(),
        )
    )


def _candidate() -> SimpleNamespace:
    return SimpleNamespace(
        capability_name="narration.autonomous_first_system",
        combined=0.72,
        payload={},
    )


def _drive_impingement(*, content: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id="impulse-conative-1",
        source="endogenous.narrative_drive",
        strength=0.55,
        content={"drive": "narration", **content},
    )


def test_autonomous_narration_does_not_speak_raw_drive_text() -> None:
    emitted: list[str] = []
    imp = _drive_impingement(
        content={
            "narrative": "RAW DRIVE TEXT MUST NOT BE SPOKEN",
            "content_summary": "A bounded impulse exists.",
            "action_tendency": "speak",
            "speech_act_candidate": "autonomous_narrative",
            "strength_posterior": 0.55,
            "wcs_snapshot_ref": "wcs:audio.broadcast_voice:voice-output-witness",
            "route_evidence_ref": "route:audio.broadcast_voice:health_witness_required",
            "public_claim_evidence_ref": "claim_posture:bounded_nonassertive_narration",
        }
    )

    with (
        mock.patch(
            "agents.hapax_daimonion.autonomous_narrative.state_readers.assemble_context",
            return_value=SimpleNamespace(programme=None, stimmung_tone="ambient"),
        ),
        mock.patch(
            "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative",
            return_value="COMPOSED SAFE NARRATION",
        ),
        mock.patch(
            "agents.hapax_daimonion.autonomous_narrative.emit.emit_narrative",
            side_effect=lambda text, **_kwargs: (
                emitted.append(text) or SimpleNamespace(partial_success=False)
            ),
        ),
        mock.patch("agents.hapax_daimonion.autonomous_narrative.emit.record_metric"),
        mock.patch(
            "agents.hapax_daimonion.voice_output_witness.record_composed_autonomous_narrative"
        ),
        mock.patch.object(run_loops_aux, "_publish_recruitment_log"),
    ):
        run_loops_aux._dispatch_autonomous_narration(_daemon(), imp, _candidate())

    assert emitted == ["COMPOSED SAFE NARRATION"]
    assert "RAW DRIVE TEXT" not in emitted[0]


def test_missing_execution_evidence_inhibits_without_compose_or_emit() -> None:
    daemon = _daemon()
    imp = _drive_impingement(
        content={
            "narrative": "RAW DRIVE TEXT MUST NOT BE SPOKEN",
            "action_tendency": "speak",
            "speech_act_candidate": "autonomous_narrative",
            "strength_posterior": 0.55,
        }
    )

    with (
        mock.patch(
            "agents.hapax_daimonion.autonomous_narrative.compose.compose_narrative"
        ) as compose,
        mock.patch("agents.hapax_daimonion.autonomous_narrative.emit.emit_narrative") as emit,
        mock.patch("agents.hapax_daimonion.voice_output_witness.record_narration_drive") as drive,
        mock.patch("agents.hapax_daimonion.voice_output_witness.record_drop") as drop,
    ):
        run_loops_aux._dispatch_autonomous_narration(daemon, imp, _candidate())

    compose.assert_not_called()
    emit.assert_not_called()
    drive.assert_called_once()
    drop.assert_called_once()
    assert drop.call_args.kwargs["terminal_state"] == "inhibited"
    assert "wcs_snapshot_ref_missing" in drop.call_args.kwargs["reason"]
    assert "route_evidence_ref_missing" in drop.call_args.kwargs["reason"]
    assert "public_claim_evidence_ref_missing" in drop.call_args.kwargs["reason"]
    daemon._affordance_pipeline.record_outcome.assert_called_once()
