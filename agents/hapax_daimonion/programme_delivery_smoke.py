"""Deterministic end-to-end programme delivery smoke harness."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.hapax_daimonion.autonomous_narrative.compose import check_beat_transition
from agents.hapax_daimonion.programme_loop import _active_segment_payload
from agents.studio_compositor.director_segment_runner import (
    DirectorSegmentCommand,
    DirectorSegmentRunner,
)
from agents.studio_compositor.layout_state import LayoutState
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)
from shared.programme import (
    Programme,
    ProgrammeContent,
    ProgrammeRole,
    segmented_content_format_spec,
)
from shared.programme_store import ProgrammePlanStore

_BEATS = (
    "hook: frame why the launch smoke matters",
    "rank: compare the required delivery surfaces",
    "close: confirm the broadcast-visible receipt",
)
_PREPARED_SCRIPT = (
    "The smoke begins with a sourced launch segment and visible comparison ward.",
    "The middle beat ranks the delivery surfaces and confirms the layout switch.",
    "The close records the broadcast receipt and leaves the compositor in a verified state.",
)
_LAYOUT_INTENTS: tuple[dict[str, Any], ...] = (
    {
        "beat_id": "hook",
        "parent_beat_index": 0,
        "action_intent_kinds": ["show_evidence"],
        "needs": ["source_visible"],
        "proposed_postures": ["comparison"],
        "expected_effects": ["source_context_legible"],
        "evidence_refs": ["source:programme-delivery-smoke"],
        "source_affordances": ["source_card"],
        "priority": 100,
    },
    {
        "beat_id": "rank",
        "parent_beat_index": 1,
        "action_intent_kinds": ["demonstrate_action"],
        "needs": ["ranked_list_visible"],
        "proposed_postures": ["ranked_visual"],
        "expected_effects": ["ranked_list_legible"],
        "evidence_refs": ["source:programme-delivery-smoke"],
        "source_affordances": ["tier_chart"],
        "priority": 100,
    },
    {
        "beat_id": "close",
        "parent_beat_index": 2,
        "action_intent_kinds": ["read_detail"],
        "needs": ["readability_held"],
        "proposed_postures": ["depth_visual"],
        "expected_effects": ["detail_readable"],
        "evidence_refs": ["source:programme-delivery-smoke"],
        "source_affordances": ["detail_card"],
        "priority": 100,
    },
)
_LAYOUT_WARDS = {
    "segment-compare": "compare-panel",
    "segment-list": "ranked-list-panel",
    "segment-detail": "artifact-detail-panel",
    "segment-poll": "audience-poll-panel",
    "segment-receipt": "world-receipt-panel",
    "segment-programme-context": "programme-context",
    "segment-tier": "tier-panel",
    "segment-chat": "chat-panel",
}


@dataclass(frozen=True)
class SmokeResult:
    receipt_path: Path
    output_dir: Path
    receipt: dict[str, Any]


def run_smoke(
    *,
    output_dir: Path,
    programme_id: str = "programme-delivery-smoke",
    write_screenshots: bool = True,
) -> SmokeResult:
    output_dir = Path(output_dir)
    shm_dir = output_dir / "shm"
    active_segment_path = shm_dir / "active-segment.json"
    runner_receipt_path = shm_dir / "director-segment-runner-receipt.json"
    runner_prompt_binding_path = shm_dir / "director-segment-binding.json"
    runner_command_log_path = output_dir / "director-segment-runner-commands.jsonl"
    runner_receipts_path = output_dir / "director-segment-runner-process-receipts.jsonl"
    tts_receipts_path = output_dir / "tts-delivery.jsonl"
    screenshots_dir = output_dir / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in (
        active_segment_path,
        runner_receipt_path,
        runner_prompt_binding_path,
        runner_command_log_path,
        runner_receipts_path,
        tts_receipts_path,
        output_dir / "programme-delivery-smoke-receipt.json",
    ):
        stale.unlink(missing_ok=True)

    programme = _build_programme(programme_id)
    prep_artifact, manifest_path = _write_prep_manifest(output_dir, programme)
    store = ProgrammePlanStore(output_dir / "programmes.jsonl")
    store.add(programme)
    active = store.activate(programme.programme_id, now=time.time())
    loaded = store.active_programme()
    if loaded is None or loaded.programme_id != programme.programme_id:
        raise RuntimeError("programme store did not load and activate smoke segment")

    screenshots: list[str] = []
    if write_screenshots:
        screenshots.append(
            str(
                _write_screenshot(
                    screenshots_dir / "01-before.png",
                    stage="before",
                    programme=programme,
                    beat_index=None,
                    layout="default",
                )
            )
        )

    transition_count = 0
    accepted_layouts: list[str] = []
    observed_layout = "default"
    durations = [15.0, 15.0, 15.0]
    layout_state = LayoutState(_layout("default", "default-panel"))
    layouts = _smoke_layouts()
    command_sink = _RecordingLayoutCommandSink(layout_state=layout_state, layouts=layouts)
    runner = DirectorSegmentRunner(
        layout_state=layout_state,
        available_layouts=lambda: layouts.keys(),
        command_sink=command_sink,
        segment_state_path=active_segment_path,
        receipt_path=runner_receipt_path,
        prompt_binding_path=runner_prompt_binding_path,
        command_jsonl_path=runner_command_log_path,
        hysteresis_s=0.0,
    )
    _clear_smoke_blit_readbacks()

    for beat_index, line in enumerate(_PREPARED_SCRIPT):
        elapsed = sum(durations[:beat_index]) + 0.25
        beat_active = active.model_copy(update={"actual_started_at": time.time() - elapsed})
        changed, current_beat = check_beat_transition(beat_active)
        if changed:
            transition_count += 1
        segment_payload = _active_segment_payload(beat_active, programme.role.value, current_beat)
        _write_json(active_segment_path, segment_payload)

        pre_result = runner.process_once(now=time.time())
        if pre_result is None:
            raise RuntimeError(f"beat {beat_index} did not produce a runner receipt")
        _append_jsonl(runner_receipts_path, pre_result)
        selected_layout = pre_result.get("selected_layout")
        if selected_layout is None:
            raise RuntimeError(f"beat {beat_index} did not select a layout")
        observed_layout = selected_layout
        _record_smoke_blit_readback(selected_layout)
        accepted_result = runner.process_once(now=time.time())
        if accepted_result is None:
            raise RuntimeError(f"beat {beat_index} did not produce an accepted receipt")
        _append_jsonl(runner_receipts_path, accepted_result)
        if accepted_result.get("status") != "accepted":
            raise RuntimeError(
                f"beat {beat_index} layout was not accepted: {accepted_result.get('reason')}"
            )
        accepted_layouts.append(selected_layout)
        _append_jsonl(
            tts_receipts_path,
            {
                "programme_id": programme.programme_id,
                "beat_index": beat_index,
                "status": "delivered",
                "surface": "tts",
                "delivery_mode": "smoke_tts_handoff",
                "text": line,
                "delivered_at": time.time(),
            },
        )
        if write_screenshots and beat_index == 1:
            screenshots.append(
                str(
                    _write_screenshot(
                        screenshots_dir / "02-during.png",
                        stage="during",
                        programme=programme,
                        beat_index=beat_index,
                        layout=selected_layout,
                    )
                )
            )

    active_segment_path.unlink(missing_ok=True)
    if write_screenshots:
        screenshots.append(
            str(
                _write_screenshot(
                    screenshots_dir / "03-after.png",
                    stage="after",
                    programme=programme,
                    beat_index=None,
                    layout=observed_layout,
                )
            )
        )

    receipt = {
        "ok": True,
        "programme_id": programme.programme_id,
        "prep_manifest_path": str(manifest_path),
        "prep_artifact_path": str(prep_artifact),
        "prep_manifest_ok": _manifest_lists_artifact(manifest_path, prep_artifact.name),
        "programme_loaded": loaded.programme_id == programme.programme_id,
        "beat_transition_count": transition_count,
        "director_command_count": len(command_sink.commands),
        "accepted_layouts": accepted_layouts,
        "tts_delivered_count": _jsonl_count(tts_receipts_path),
        "screenshot_paths": screenshots,
        "runner_receipts_path": str(runner_receipts_path),
        "runner_latest_receipt_path": str(runner_receipt_path),
        "runner_command_log_path": str(runner_command_log_path),
        "tts_receipts_path": str(tts_receipts_path),
    }
    receipt["ok"] = (
        receipt["prep_manifest_ok"]
        and receipt["programme_loaded"]
        and receipt["beat_transition_count"] >= len(_BEATS)
        and receipt["director_command_count"] >= len(_BEATS)
        and len(receipt["accepted_layouts"]) >= len(_BEATS)
        and receipt["tts_delivered_count"] >= len(_BEATS)
        and (not write_screenshots or len(receipt["screenshot_paths"]) == 3)
    )
    receipt_path = output_dir / "programme-delivery-smoke-receipt.json"
    _write_json(receipt_path, receipt)
    return SmokeResult(receipt_path=receipt_path, output_dir=output_dir, receipt=receipt)


def _build_programme(programme_id: str) -> Programme:
    spec = segmented_content_format_spec(ProgrammeRole.TIER_LIST)
    if spec is None:
        raise RuntimeError("tier_list programme spec is unavailable")
    content = ProgrammeContent(
        declared_topic="programme delivery smoke",
        source_uri="file://programme-delivery-smoke",
        subject="HN launch programme path",
        narrative_beat=spec.narrative_beat_template.format(topic="programme delivery smoke"),
        source_refs=["source:programme-delivery-smoke"],
        evidence_refs=["source:programme-delivery-smoke"],
        role_contract={
            "role": spec.role.value,
            "asset_requirements": list(spec.asset_requirements),
            "ward_profile": spec.ward_profile,
        },
        segment_beats=list(_BEATS),
        hosting_context="responsible_hosting",
        authority="smoke:evidence-receipt",
        beat_layout_intents=[dict(item) for item in _LAYOUT_INTENTS],
        delivery_mode="live_prior",
        segment_beat_durations=[15.0, 15.0, 15.0],
        prepared_script=list(_PREPARED_SCRIPT),
    )
    return Programme(
        programme_id=programme_id,
        role=ProgrammeRole.TIER_LIST,
        planned_duration_s=300.0,
        content=content,
        parent_show_id="show-programme-delivery-smoke",
    )


def _write_prep_manifest(output_dir: Path, programme: Programme) -> tuple[Path, Path]:
    today = output_dir / "prep" / dt.date.today().isoformat()
    today.mkdir(parents=True, exist_ok=True)
    artifact = today / f"{programme.programme_id}.json"
    payload = {
        "programme_id": programme.programme_id,
        "role": programme.role.value,
        "topic": programme.content.declared_topic,
        "accepted": True,
        "prepared_script": programme.content.prepared_script,
        "segment_beats": programme.content.segment_beats,
        "beat_layout_intents": programme.content.beat_layout_intents,
        "smoke_authority": "deterministic programme delivery smoke",
    }
    _write_json(artifact, payload)
    manifest = today / "manifest.json"
    _write_json(
        manifest,
        {
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "smoke": True,
            "programmes": [artifact.name],
        },
    )
    return artifact, manifest


def _write_screenshot(
    path: Path,
    *,
    stage: str,
    programme: Programme,
    beat_index: int | None,
    layout: str,
) -> Path:
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1280, 720), (20, 24, 28))
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 70, 1220, 650), outline=(130, 180, 210), width=4)
    draw.rectangle((120, 130, 1160, 590), fill=(32, 40, 48), outline=(220, 210, 150), width=3)
    draw.text((150, 155), f"Programme delivery smoke: {stage}", fill=(235, 235, 225))
    draw.text((150, 205), f"Programme: {programme.programme_id}", fill=(190, 220, 230))
    draw.text((150, 255), f"Layout: {layout}", fill=(240, 215, 155))
    if beat_index is not None:
        draw.text((150, 305), f"Beat {beat_index + 1}: {_BEATS[beat_index]}", fill=(220, 220, 220))
        draw.text((150, 355), _PREPARED_SCRIPT[beat_index], fill=(210, 225, 210))
    else:
        draw.text(
            (150, 305),
            "No active beat" if stage != "after" else "Segment completed",
            fill=(220, 220, 220),
        )
    image.save(path)
    return path


class _RecordingLayoutCommandSink:
    def __init__(self, *, layout_state: LayoutState, layouts: dict[str, Layout]) -> None:
        self.layout_state = layout_state
        self.layouts = layouts
        self.commands: list[DirectorSegmentCommand] = []

    def __call__(self, command: DirectorSegmentCommand) -> dict[str, Any]:
        layout_name = command.args.get("layout_name")
        if not isinstance(layout_name, str) or layout_name not in self.layouts:
            return {"status": "error", "reason": "unknown_layout", "layout_name": layout_name}
        self.commands.append(command)
        self.layout_state.mutate(lambda _previous: self.layouts[layout_name])
        return {"status": "ok", "layout_name": layout_name}


def _smoke_layouts() -> dict[str, Layout]:
    segment_layouts = {
        layout_name: _layout(layout_name, ward_id) for layout_name, ward_id in _LAYOUT_WARDS.items()
    }
    return {
        "default": _layout("default", "default-panel"),
        **segment_layouts,
    }


def _layout(name: str, ward_id: str) -> Layout:
    surface_id = f"{ward_id}-surface"
    return Layout(
        name=name,
        sources=[
            SourceSchema(
                id=ward_id,
                kind="cairo",
                backend="cairo",
                params={"class_name": "ProgrammeDeliverySmokeWard"},
            )
        ],
        surfaces=[
            SurfaceSchema(
                id=surface_id,
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=1280, h=720),
                z_order=10,
            )
        ],
        assignments=[Assignment(source=ward_id, surface=surface_id)],
    )


def _clear_smoke_blit_readbacks() -> None:
    try:
        from agents.studio_compositor.fx_chain import clear_blit_readbacks

        clear_blit_readbacks()
    except Exception:
        pass


def _record_smoke_blit_readback(layout_name: str) -> None:
    ward_id = _LAYOUT_WARDS[layout_name]
    try:
        import cairo

        from agents.studio_compositor.fx_chain import _record_blit_observability

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
        geometry = SurfaceGeometry(kind="rect", x=0, y=0, w=1280, h=720)
        _record_blit_observability(ward_id, surface, geometry, 1.0)
    except Exception as exc:
        raise RuntimeError(f"could not record smoke blit readback for {ward_id}") from exc


def _manifest_lists_artifact(manifest_path: Path, artifact_name: str) -> bool:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    programmes = manifest.get("programmes") if isinstance(manifest, dict) else None
    return isinstance(programmes, list) and artifact_name in programmes


def _jsonl_count(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/tmp") / f"hapax-programme-delivery-smoke-{int(time.time())}",
    )
    parser.add_argument("--programme-id", default="programme-delivery-smoke")
    parser.add_argument("--skip-screenshots", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_smoke(
        output_dir=args.out_dir,
        programme_id=args.programme_id,
        write_screenshots=not args.skip_screenshots,
    )
    print(json.dumps({"ok": result.receipt["ok"], "receipt_path": str(result.receipt_path)}))
    return 0 if result.receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
