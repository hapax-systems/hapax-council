"""Tests for programme-sequence compositor grounding."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.content_programmer.grounding_runner import (
    CompositorOutputWitness,
    CompositorTransitionResult,
    GroundingProgrammeSequence,
    GroundingProgrammeStep,
    ProgrammeSequenceGroundingRunner,
    ResolvedContent,
    WardStateUpdate,
)

NOW = datetime(2026, 5, 10, 21, 45, tzinfo=UTC)


def _sequence() -> GroundingProgrammeSequence:
    return GroundingProgrammeSequence(
        sequence_id="sequence:content-programming-grounding",
        programme_id="programme:grounded-demo",
        format_id="watch_along",
        grounding_question="Can the programme sequence ground actual compositor output?",
        steps=(
            GroundingProgrammeStep(
                step_id="step-a",
                content_ref="content:archive:alpha",
                transition="push_featured_slot",
                ward_id="ward:programme-state",
                ward_state={"slot": "featured", "state": "resolving"},
                expected_output_ref="frame:step-a",
            ),
            GroundingProgrammeStep(
                step_id="step-b",
                content_ref="content:archive:beta",
                transition="crossfade_to_detail",
                ward_id="ward:programme-state",
                ward_state={"slot": "detail", "state": "grounded"},
                expected_output_ref="frame:step-b",
            ),
        ),
    )


def test_programme_steps_resolve_content_trigger_transitions_update_ward_state() -> None:
    calls: list[tuple[str, str]] = []

    def resolve_content(step: GroundingProgrammeStep) -> ResolvedContent:
        calls.append(("resolve", step.step_id))
        return ResolvedContent(
            step_id=step.step_id,
            content_ref=step.content_ref,
            resolved_ref=f"resolved:{step.step_id}",
            evidence_refs=(f"resolver:{step.content_ref}",),
        )

    def trigger_transition(
        step: GroundingProgrammeStep, resolved: ResolvedContent
    ) -> CompositorTransitionResult:
        calls.append(("transition", step.step_id))
        return CompositorTransitionResult(
            step_id=step.step_id,
            transition_id=f"transition:{step.step_id}",
            command_ref=f"compositor-command:{step.transition}:{resolved.resolved_ref}",
            applied=True,
            response_ref=f"compositor-response:{step.step_id}",
            evidence_refs=(f"transition-evidence:{step.step_id}",),
        )

    def update_ward_state(
        step: GroundingProgrammeStep,
        resolved: ResolvedContent,
        transition: CompositorTransitionResult,
    ) -> WardStateUpdate:
        calls.append(("ward", step.step_id))
        return WardStateUpdate(
            step_id=step.step_id,
            ward_id=step.ward_id,
            state_ref=f"ward-state:{step.step_id}",
            applied=transition.applied,
            state={**step.ward_state, "resolved_ref": resolved.resolved_ref},
            evidence_refs=(f"ward-evidence:{step.step_id}",),
        )

    def observe_compositor_output(
        step: GroundingProgrammeStep,
        resolved: ResolvedContent,
        transition: CompositorTransitionResult,
        ward_update: WardStateUpdate,
    ) -> CompositorOutputWitness:
        calls.append(("witness", step.step_id))
        assert resolved.resolved_ref.endswith(step.step_id)
        assert transition.applied
        assert ward_update.applied
        return CompositorOutputWitness(
            step_id=step.step_id,
            frame_ref=step.expected_output_ref or f"frame:{step.step_id}",
            captured_at=NOW,
            changed=True,
            nonblank=True,
            evidence_refs=(
                step.expected_output_ref or f"frame:{step.step_id}",
                f"shm-snapshot:{step.step_id}",
            ),
        )

    result = ProgrammeSequenceGroundingRunner(
        resolve_content=resolve_content,
        trigger_transition=trigger_transition,
        update_ward_state=update_ward_state,
        observe_compositor_output=observe_compositor_output,
    ).run_sequence(_sequence(), now=NOW)

    assert result.final_status == "completed"
    assert calls == [
        ("resolve", "step-a"),
        ("transition", "step-a"),
        ("ward", "step-a"),
        ("witness", "step-a"),
        ("resolve", "step-b"),
        ("transition", "step-b"),
        ("ward", "step-b"),
        ("witness", "step-b"),
    ]
    assert result.resolved_content_refs == ("resolved:step-a", "resolved:step-b")
    assert result.transition_refs == ("transition:step-a", "transition:step-b")
    assert result.ward_state_refs == ("ward-state:step-a", "ward-state:step-b")
    assert result.output_witness_refs == ("frame:step-a", "frame:step-b")
    assert result.actual_outputs == (
        "content:resolved:step-a",
        "transition:transition:step-a",
        "ward_state:ward-state:step-a",
        "compositor_output:frame:step-a",
        "content:resolved:step-b",
        "transition:transition:step-b",
        "ward_state:ward-state:step-b",
        "compositor_output:frame:step-b",
    )
    assert result.step_results[1].ward_update is not None
    assert result.step_results[1].ward_update.state["state"] == "grounded"


def test_sequence_blocks_when_compositor_output_is_not_witnessed() -> None:
    calls: list[tuple[str, str]] = []

    def resolve_content(step: GroundingProgrammeStep) -> ResolvedContent:
        calls.append(("resolve", step.step_id))
        return ResolvedContent(
            step_id=step.step_id,
            content_ref=step.content_ref,
            resolved_ref=f"resolved:{step.step_id}",
            evidence_refs=(f"resolver:{step.content_ref}",),
        )

    def trigger_transition(
        step: GroundingProgrammeStep, resolved: ResolvedContent
    ) -> CompositorTransitionResult:
        calls.append(("transition", step.step_id))
        return CompositorTransitionResult(
            step_id=step.step_id,
            transition_id=f"transition:{step.step_id}",
            command_ref=f"compositor-command:{resolved.resolved_ref}",
            applied=True,
            evidence_refs=(f"transition-evidence:{step.step_id}",),
        )

    def update_ward_state(
        step: GroundingProgrammeStep,
        _resolved: ResolvedContent,
        transition: CompositorTransitionResult,
    ) -> WardStateUpdate:
        calls.append(("ward", step.step_id))
        return WardStateUpdate(
            step_id=step.step_id,
            ward_id=step.ward_id,
            state_ref=f"ward-state:{step.step_id}",
            applied=transition.applied,
            state=step.ward_state,
            evidence_refs=(f"ward-evidence:{step.step_id}",),
        )

    def observe_compositor_output(
        step: GroundingProgrammeStep,
        _resolved: ResolvedContent,
        _transition: CompositorTransitionResult,
        _ward_update: WardStateUpdate,
    ) -> CompositorOutputWitness:
        calls.append(("witness", step.step_id))
        return CompositorOutputWitness(
            step_id=step.step_id,
            frame_ref=step.expected_output_ref or f"frame:{step.step_id}",
            captured_at=NOW,
            changed=False,
            nonblank=True,
            evidence_refs=(step.expected_output_ref or f"frame:{step.step_id}",),
        )

    result = ProgrammeSequenceGroundingRunner(
        resolve_content=resolve_content,
        trigger_transition=trigger_transition,
        update_ward_state=update_ward_state,
        observe_compositor_output=observe_compositor_output,
    ).run_sequence(_sequence(), now=NOW)

    assert result.final_status == "blocked"
    assert result.actual_outputs == ()
    assert result.unavailable_reasons == ("compositor_output_not_changed",)
    assert result.step_results[0].status == "blocked"
    assert result.step_results[0].output_witness is not None
    assert result.step_results[0].output_witness.frame_ref == "frame:step-a"
    assert calls == [
        ("resolve", "step-a"),
        ("transition", "step-a"),
        ("ward", "step-a"),
        ("witness", "step-a"),
    ]
