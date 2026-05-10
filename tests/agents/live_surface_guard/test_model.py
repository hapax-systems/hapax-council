from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agents.live_surface_guard.model import (
    IncidentLedger,
    RemediationAction,
    RemediationBudget,
    RemediationController,
    action_for_assessment,
    emit_contract_textfile,
    sample_obs_decoder,
)
from shared.live_surface_truth import (
    LiveSurfaceSnapshot,
    LiveSurfaceState,
    V4l2EgressMode,
    assess_live_surface,
)

ONE_PIXEL_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeObs:
    def __init__(self, image_data: str = ONE_PIXEL_PNG) -> None:
        self.image_data = image_data

    def get_source_active(self, *, source_name: str):
        return SimpleNamespace(video_active=True)

    def get_stream_status(self):
        return SimpleNamespace(output_active=True)

    def get_source_screenshot(self, **_kwargs):
        return SimpleNamespace(image_data=self.image_data)


class FakeExecutor:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.rollbacks: list[str] = []

    def perform(self, action: RemediationAction) -> str:
        self.actions.append(action.value)
        return "ok"

    def rollback(self, action: RemediationAction) -> str:
        self.rollbacks.append(action.value)
        return "rollback_ok"


def _direct_snapshot(**overrides) -> LiveSurfaceSnapshot:
    data = {
        "service_active": True,
        "bridge_active": True,
        "cameras_total": 6,
        "cameras_healthy": 6,
        "v4l2_frames_total": 100,
        "v4l2_last_frame_age_seconds": 0.2,
        "final_egress_snapshot_frames_total": 10,
        "final_egress_snapshot_last_frame_age_seconds": 0.2,
    }
    data.update(overrides)
    return LiveSurfaceSnapshot(**data)


def _bridge_snapshot(**overrides) -> LiveSurfaceSnapshot:
    data = {
        "service_active": True,
        "bridge_active": True,
        "cameras_total": 6,
        "cameras_healthy": 6,
        "v4l2_egress_mode": V4l2EgressMode.BRIDGE,
        "shmsink_frames_total": 100,
        "shmsink_last_frame_age_seconds": 0.2,
        "bridge_write_frames_total": 90,
        "bridge_write_bytes_total": 90_000,
        "bridge_write_errors_total": 0,
        "bridge_heartbeat_age_seconds": 0.3,
        "decoded_video42_frames_total": 80,
        "decoded_video42_last_frame_age_seconds": 0.3,
    }
    data.update(overrides)
    return LiveSurfaceSnapshot(**data)


def test_sample_obs_decoder_needs_hash_motion_not_playing_alone() -> None:
    first = sample_obs_decoder(FakeObs(), "StudioCompositor", now=1000.0)
    second = sample_obs_decoder(
        FakeObs(),
        "StudioCompositor",
        previous_hash=first.screenshot_hash,
        now=1001.0,
    )

    assert first.source_active is True
    assert first.playing is True
    assert first.screenshot_changed is False
    assert first.screenshot_flat is True
    assert second.screenshot_changed is False


def test_stale_obs_frame_plans_bounded_direct_remediation_with_receipt(tmp_path: Path) -> None:
    before = _direct_snapshot(
        obs_source_active=True,
        obs_playing=True,
        obs_screenshot_age_seconds=0.2,
        obs_screenshot_changed=False,
        obs_screenshot_flat=True,
    )
    before_assessment = assess_live_surface(before, require_obs_decoder=True)
    after = _direct_snapshot(
        obs_source_active=True,
        obs_playing=True,
        obs_screenshot_age_seconds=0.2,
        obs_screenshot_changed=True,
        obs_screenshot_flat=False,
    )
    after_assessment = assess_live_surface(after, require_obs_decoder=True)
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    executor = FakeExecutor()
    controller = RemediationController(
        budget=RemediationBudget(max_attempts=1, cooldown_seconds=60.0),
        executor=executor,
        ledger=ledger,
        clock=lambda: 10.0,
    )

    action = action_for_assessment(before, before_assessment)
    assert action is RemediationAction.OBS_CACHE_BUST_REBIND
    receipt = controller.run(
        action,
        before_snapshot=before,
        before_assessment=before_assessment,
        collect_after=lambda: (after, after_assessment),
    )
    skipped = controller.run(
        action,
        before_snapshot=before,
        before_assessment=before_assessment,
        collect_after=lambda: (after, after_assessment),
    )

    assert receipt.final_outcome == "restored"
    assert receipt.rollback_outcome == "not_needed"
    assert skipped.final_outcome == "skipped_budget"
    assert executor.actions == ["obs_cache_bust_rebind"]
    ledger_row = json.loads(ledger.path.read_text(encoding="utf-8").splitlines()[0])
    payload = ledger_row["payload"]
    assert payload["before_evidence"]["state"] == LiveSurfaceState.DEGRADED_CONTAINMENT.value
    assert payload["after_evidence"]["state"] == LiveSurfaceState.HEALTHY.value
    assert "rollback_outcome" in payload


def test_bridge_obs_stall_uses_bridge_specific_action() -> None:
    snapshot = _bridge_snapshot(
        obs_source_active=True,
        obs_playing=True,
        obs_screenshot_age_seconds=0.2,
        obs_screenshot_changed=False,
        obs_screenshot_flat=False,
    )
    assessment = assess_live_surface(snapshot, require_obs_decoder=True)

    assert action_for_assessment(snapshot, assessment) is (
        RemediationAction.BRIDGE_RECONNECT_OBS_REBIND
    )


def test_contract_textfile_exposes_mode_reasons_and_obs_metrics(tmp_path: Path) -> None:
    snapshot = _direct_snapshot(
        obs_source_active=True,
        obs_playing=True,
        obs_screenshot_age_seconds=0.2,
        obs_screenshot_changed=False,
        obs_screenshot_flat=True,
        public_output_live=False,
    )
    assessment = assess_live_surface(
        snapshot,
        require_obs_decoder=True,
        require_public_output=True,
    )
    path = tmp_path / "live_surface.prom"

    emit_contract_textfile(path, snapshot=snapshot, assessment=assessment, receipts_total=2)

    text = path.read_text(encoding="utf-8")
    assert 'hapax_live_surface_v4l2_egress_mode{mode="direct_v4l2"} 1' in text
    assert 'hapax_live_surface_reason{reason="obs_screenshot_flat"} 1' in text
    assert "hapax_obs_decoder_playing 1" in text
    assert "hapax_public_output_live 0" in text
    assert "hapax_live_surface_remediation_receipts_total 2" in text
