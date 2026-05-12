"""Tests for programme-beat to compositor control binding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.studio_compositor.director_segment_runner import (
    DirectorSegmentCommand,
    DirectorSegmentRunner,
    render_director_segment_binding_prompt,
)
from agents.studio_compositor.layout_state import LayoutState
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)


def _layout(name: str, source_id: str) -> Layout:
    return Layout(
        name=name,
        sources=[
            SourceSchema(
                id=source_id,
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            )
        ],
        surfaces=[
            SurfaceSchema(
                id=f"{source_id}-surface",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=100, h=100),
                z_order=10,
            )
        ],
        assignments=[Assignment(source=source_id, surface=f"{source_id}-surface")],
    )


def _active_segment_payload(
    *,
    programme_id: str = "prog-manual",
    beat_index: int = 0,
    need_kind: str = "tier",
    need_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    need = {
        "kind": need_kind,
        "evidence_refs": ["source:manual-segment"],
        "expected_effects": ["ward:tier-panel" if need_kind == "tier" else "ward:compare-panel"],
    }
    if need_extra:
        need.update(need_extra)
    return {
        "programme_id": programme_id,
        "role": "tier_list",
        "topic": "Manual runner test",
        "current_beat_index": beat_index,
        "hosting_context": {"mode": "responsible_hosting"},
        "prepared_artifact_ref": {"artifact_sha256": "abc123"},
        "current_beat_layout_intents": [
            {
                "beat_index": beat_index,
                "needs": [need],
            }
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_runner_emits_layout_activate_command_for_manual_segment(tmp_path: Path) -> None:
    default = _layout("default", "default-panel")
    tier = _layout("segment-tier", "tier-panel")
    layouts = {"default": default, "segment-tier": tier}
    state = LayoutState(default)
    segment_path = tmp_path / "active-segment.json"
    receipt_path = tmp_path / "receipt.json"
    binding_path = tmp_path / "binding.json"
    command_log = tmp_path / "commands.jsonl"
    _write_json(segment_path, _active_segment_payload())
    commands: list[DirectorSegmentCommand] = []

    def _sink(command: DirectorSegmentCommand) -> dict[str, Any]:
        commands.append(command)
        state.mutate(lambda _previous: layouts[command.args["layout_name"]])
        return {"status": "ok", "layout_name": command.args["layout_name"]}

    runner = DirectorSegmentRunner(
        layout_state=state,
        available_layouts=lambda: layouts.keys(),
        command_sink=_sink,
        segment_state_path=segment_path,
        receipt_path=receipt_path,
        prompt_binding_path=binding_path,
        command_jsonl_path=command_log,
    )

    receipt = runner.process_once(now=1000.0)

    assert receipt is not None
    assert state.get().name == "segment-tier"
    assert [command.command for command in commands] == ["compositor.layout.activate"]
    assert commands[0].args["layout_name"] == "segment-tier"
    assert commands[0].args["authority"] == "runtime_layout_responsibility"
    saved = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert saved["command_result"]["status"] == "ok"
    assert saved["binding_contract"]["prepared_layout_intents_are_authority"] is False
    assert json.loads(command_log.read_text(encoding="utf-8"))["result"]["status"] == "ok"

    prompt_lines = render_director_segment_binding_prompt(path=binding_path, now=1001.0)
    assert "## Segment director binding" in prompt_lines
    assert any("segment-tier" in line for line in prompt_lines)


def test_runner_refuses_layout_authority_fields_without_command(tmp_path: Path) -> None:
    default = _layout("default", "default-panel")
    state = LayoutState(default)
    segment_path = tmp_path / "active-segment.json"
    receipt_path = tmp_path / "receipt.json"
    binding_path = tmp_path / "binding.json"
    command_log = tmp_path / "commands.jsonl"
    _write_json(
        segment_path,
        _active_segment_payload(need_extra={"layout": "segment-tier"}),
    )
    commands: list[DirectorSegmentCommand] = []
    runner = DirectorSegmentRunner(
        layout_state=state,
        available_layouts=lambda: ["default", "segment-tier"],
        command_sink=lambda command: commands.append(command) or {"status": "ok"},
        segment_state_path=segment_path,
        receipt_path=receipt_path,
        prompt_binding_path=binding_path,
        command_jsonl_path=command_log,
    )

    receipt = runner.process_once(now=1000.0)

    assert receipt is not None
    assert commands == []
    assert state.get().name == "default"
    saved = json.loads(receipt_path.read_text(encoding="utf-8"))
    refusals = saved["refusal"]["proposal_refusals"]
    assert refusals[0]["reason"] == "forbidden_segment_layout_authority_field"
    assert refusals[0]["forbidden_fields"] == ["layout"]
    assert not command_log.exists()


def test_runner_dispatches_again_on_beat_change(tmp_path: Path) -> None:
    default = _layout("default", "default-panel")
    tier = _layout("segment-tier", "tier-panel")
    compare = _layout("segment-compare", "compare-panel")
    layouts = {"default": default, "segment-tier": tier, "segment-compare": compare}
    state = LayoutState(default)
    segment_path = tmp_path / "active-segment.json"
    commands: list[DirectorSegmentCommand] = []

    def _sink(command: DirectorSegmentCommand) -> dict[str, Any]:
        commands.append(command)
        state.mutate(lambda _previous: layouts[command.args["layout_name"]])
        return {"status": "ok", "layout_name": command.args["layout_name"]}

    runner = DirectorSegmentRunner(
        layout_state=state,
        available_layouts=lambda: layouts.keys(),
        command_sink=_sink,
        segment_state_path=segment_path,
        receipt_path=tmp_path / "receipt.json",
        prompt_binding_path=tmp_path / "binding.json",
        command_jsonl_path=tmp_path / "commands.jsonl",
        hysteresis_s=0.0,
    )

    _write_json(segment_path, _active_segment_payload(beat_index=0, need_kind="tier"))
    runner.process_once(now=1000.0)
    _write_json(segment_path, _active_segment_payload(beat_index=1, need_kind="comparison"))
    runner.process_once(now=1001.0)

    assert [command.args["layout_name"] for command in commands] == [
        "segment-tier",
        "segment-compare",
    ]
    assert state.get().name == "segment-compare"


def test_segment_binding_prompt_ignores_stale_receipt(tmp_path: Path) -> None:
    binding = tmp_path / "binding.json"
    _write_json(
        binding,
        {
            "observed_at": 1000.0,
            "programme_id": "prog",
            "beat_index": 1,
            "status": "held",
            "reason": "rendered_readback_mismatch",
            "selected_layout": "segment-tier",
        },
    )

    assert render_director_segment_binding_prompt(path=binding, now=1010.0, ttl_s=15.0)
    assert render_director_segment_binding_prompt(path=binding, now=1020.0, ttl_s=15.0) == []
