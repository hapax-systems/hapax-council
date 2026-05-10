"""Pure contract pieces for live-surface egress observability.

The guard separates evidence collection, classification, and remediation.
OBS ``PLAYING`` or a running bridge process can appear in the evidence, but
neither is treated as output truth without decoded-frame or screenshot motion.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from shared.live_surface_truth import (
    LiveSurfaceAssessment,
    LiveSurfaceSnapshot,
    V4l2EgressMode,
)


class RemediationAction(StrEnum):
    OBS_CACHE_BUST_REBIND = "obs_cache_bust_rebind"
    BRIDGE_RECONNECT_OBS_REBIND = "bridge_reconnect_obs_rebind"
    HLS_CACHE_BUST = "hls_cache_bust"
    AUTO_PRIVATE_ESCALATE = "auto_private_escalate"


@dataclass(frozen=True)
class ObsDecoderEvidence:
    source_active: bool | None
    playing: bool | None
    screenshot_hash: str | None
    screenshot_changed: bool | None
    screenshot_flat: bool | None
    screenshot_age_seconds: float | None
    captured_at: float
    error: str | None = None


@dataclass
class RemediationBudget:
    max_attempts: int = 3
    cooldown_seconds: float = 60.0
    attempts: dict[str, int] = field(default_factory=dict)
    last_attempt_monotonic: dict[str, float] = field(default_factory=dict)

    def can_attempt(self, action: RemediationAction, *, now: float) -> bool:
        key = action.value
        if self.attempts.get(key, 0) >= self.max_attempts:
            return False
        last = self.last_attempt_monotonic.get(key)
        return last is None or now - last >= self.cooldown_seconds

    def record_attempt(self, action: RemediationAction, *, now: float) -> int:
        key = action.value
        count = self.attempts.get(key, 0) + 1
        self.attempts[key] = count
        self.last_attempt_monotonic[key] = now
        return count


class RemediationExecutor(Protocol):
    def perform(self, action: RemediationAction) -> str:
        """Run one bounded remediation action and return an outcome code."""

    def rollback(self, action: RemediationAction) -> str:
        """Attempt rollback after a failed after-check."""


class NoopRemediationExecutor:
    def perform(self, action: RemediationAction) -> str:
        return f"dry_run:{action.value}"

    def rollback(self, action: RemediationAction) -> str:
        return "not_needed"


@dataclass(frozen=True)
class RemediationReceipt:
    action: str
    attempt_number: int
    started_at: float
    before_evidence: Mapping[str, Any]
    perform_outcome: str
    after_evidence: Mapping[str, Any]
    rollback_outcome: str
    final_outcome: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "action": self.action,
                "attempt_number": self.attempt_number,
                "started_at": self.started_at,
                "before_evidence": dict(self.before_evidence),
                "perform_outcome": self.perform_outcome,
                "after_evidence": dict(self.after_evidence),
                "rollback_outcome": self.rollback_outcome,
                "final_outcome": self.final_outcome,
            },
            sort_keys=True,
        )


class IncidentLedger:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_type": event_type,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload": payload,
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")

    def append_receipt(self, receipt: RemediationReceipt) -> None:
        self.append("remediation", json.loads(receipt.to_json()))


class RemediationController:
    def __init__(
        self,
        *,
        budget: RemediationBudget | None = None,
        executor: RemediationExecutor | None = None,
        ledger: IncidentLedger | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._budget = budget or RemediationBudget()
        self._executor = executor or NoopRemediationExecutor()
        self._ledger = ledger
        self._clock = clock
        self._lock = threading.Lock()

    def run(
        self,
        action: RemediationAction,
        *,
        before_snapshot: LiveSurfaceSnapshot,
        before_assessment: LiveSurfaceAssessment,
        collect_after: Callable[[], tuple[LiveSurfaceSnapshot, LiveSurfaceAssessment]],
    ) -> RemediationReceipt:
        now = self._clock()
        before = surface_evidence(before_snapshot, before_assessment)
        if not self._budget.can_attempt(action, now=now):
            receipt = RemediationReceipt(
                action=action.value,
                attempt_number=self._budget.attempts.get(action.value, 0),
                started_at=now,
                before_evidence=before,
                perform_outcome="skipped_budget",
                after_evidence=before,
                rollback_outcome="not_started",
                final_outcome="skipped_budget",
            )
            if self._ledger is not None:
                self._ledger.append_receipt(receipt)
            return receipt

        if not self._lock.acquire(blocking=False):
            receipt = RemediationReceipt(
                action=action.value,
                attempt_number=self._budget.attempts.get(action.value, 0),
                started_at=now,
                before_evidence=before,
                perform_outcome="skipped_single_flight",
                after_evidence=before,
                rollback_outcome="not_started",
                final_outcome="skipped_single_flight",
            )
            if self._ledger is not None:
                self._ledger.append_receipt(receipt)
            return receipt

        try:
            attempt = self._budget.record_attempt(action, now=now)
            perform_outcome = self._executor.perform(action)
            after_snapshot, after_assessment = collect_after()
            after = surface_evidence(after_snapshot, after_assessment)
            if after_assessment.restored:
                rollback_outcome = "not_needed"
                final_outcome = "restored"
            else:
                rollback_outcome = self._executor.rollback(action)
                final_outcome = "after_still_degraded"
            receipt = RemediationReceipt(
                action=action.value,
                attempt_number=attempt,
                started_at=now,
                before_evidence=before,
                perform_outcome=perform_outcome,
                after_evidence=after,
                rollback_outcome=rollback_outcome,
                final_outcome=final_outcome,
            )
            if self._ledger is not None:
                self._ledger.append_receipt(receipt)
            return receipt
        finally:
            self._lock.release()


def _resp_bool(resp: Any, *names: str) -> bool | None:
    for name in names:
        if hasattr(resp, name):
            return bool(getattr(resp, name))
    if isinstance(resp, Mapping):
        for name in names:
            if name in resp:
                return bool(resp[name])
    return None


def _obs_image_data(resp: Any) -> str | None:
    if hasattr(resp, "image_data"):
        return str(resp.image_data)
    if isinstance(resp, Mapping) and "image_data" in resp:
        return str(resp["image_data"])
    return None


def _decode_image_data(image_data: str) -> bytes:
    raw = image_data.split(",", 1)[1] if image_data.startswith("data:") else image_data
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        return image_data.encode("utf-8", "replace")


def _flat_image_data(image_data: str) -> bool:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(_decode_image_data(image_data))) as image:
            extrema = image.convert("RGB").getextrema()
        return all(low == high for low, high in extrema)
    except Exception:
        return False


def sample_obs_decoder(
    client: Any,
    source_name: str,
    *,
    previous_hash: str | None = None,
    now: float | None = None,
) -> ObsDecoderEvidence:
    captured_at = time.time() if now is None else now
    source_active: bool | None = None
    playing: bool | None = None
    try:
        source_active = _resp_bool(
            client.get_source_active(source_name=source_name),
            "video_active",
            "active",
        )
    except Exception:
        source_active = False

    try:
        playing = _resp_bool(
            client.get_stream_status(),
            "output_active",
            "stream_active",
            "active",
        )
    except Exception:
        playing = None

    try:
        resp = client.get_source_screenshot(
            source_name=source_name,
            image_format="png",
            image_width=16,
            image_height=16,
        )
        image_data = _obs_image_data(resp)
        if image_data is None:
            raise RuntimeError("OBS screenshot response did not include image_data")
        digest = hashlib.sha256(image_data.encode("utf-8", "replace")).hexdigest()
        return ObsDecoderEvidence(
            source_active=source_active,
            playing=playing,
            screenshot_hash=digest,
            screenshot_changed=previous_hash is not None and digest != previous_hash,
            screenshot_flat=_flat_image_data(image_data),
            screenshot_age_seconds=0.0,
            captured_at=captured_at,
        )
    except Exception as exc:
        return ObsDecoderEvidence(
            source_active=source_active,
            playing=playing,
            screenshot_hash=None,
            screenshot_changed=None,
            screenshot_flat=None,
            screenshot_age_seconds=None,
            captured_at=captured_at,
            error=f"{type(exc).__name__}: {exc}",
        )


def action_for_assessment(
    snapshot: LiveSurfaceSnapshot,
    assessment: LiveSurfaceAssessment,
) -> RemediationAction | None:
    reasons = set(assessment.reasons)
    obs_reasons = {
        "obs_source_inactive",
        "obs_screenshot_missing",
        "obs_playing_without_decoder_motion",
        "obs_decoder_stale_hash",
        "obs_screenshot_flat",
        "obs_screenshot_stale",
    }
    if reasons & obs_reasons:
        if snapshot.v4l2_egress_mode is V4l2EgressMode.BRIDGE:
            return RemediationAction.BRIDGE_RECONNECT_OBS_REBIND
        return RemediationAction.OBS_CACHE_BUST_REBIND
    if "hls_playlist_stale" in reasons or "hls_playlist_malformed_target_duration" in reasons:
        return RemediationAction.HLS_CACHE_BUST
    if "public_output_unverified" in reasons:
        return RemediationAction.AUTO_PRIVATE_ESCALATE
    return None


def surface_evidence(
    snapshot: LiveSurfaceSnapshot,
    assessment: LiveSurfaceAssessment,
) -> dict[str, Any]:
    return {
        "state": assessment.state.value,
        "restored": assessment.restored,
        "reasons": list(assessment.reasons),
        "camera_last_frame_age_seconds": dict(snapshot.camera_last_frame_age_seconds),
        "v4l2_egress_mode": snapshot.v4l2_egress_mode.value,
        "hls_active": snapshot.hls_active,
        "hls_playlist_age_seconds": snapshot.hls_playlist_age_seconds,
        "rtmp_connected": snapshot.rtmp_connected,
        "rtmp_bytes_total": snapshot.rtmp_bytes_total,
        "obs_source_active": snapshot.obs_source_active,
        "obs_playing": snapshot.obs_playing,
        "obs_screenshot_changed": snapshot.obs_screenshot_changed,
        "obs_screenshot_flat": snapshot.obs_screenshot_flat,
        "obs_screenshot_age_seconds": snapshot.obs_screenshot_age_seconds,
        "public_output_live": snapshot.public_output_live,
        "bridge_write_frames_total": snapshot.bridge_write_frames_total,
        "bridge_write_bytes_total": snapshot.bridge_write_bytes_total,
        "bridge_write_errors_total": snapshot.bridge_write_errors_total,
        "decoded_video42_frames_total": snapshot.decoded_video42_frames_total,
        "decoded_video42_last_frame_age_seconds": (snapshot.decoded_video42_last_frame_age_seconds),
        "director_last_intent_age_seconds": snapshot.director_last_intent_age_seconds,
        "containment_flags": dict(snapshot.containment_flags),
    }


def _label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _optional_bool(value: bool | None) -> str | None:
    if value is None:
        return None
    return "1" if value else "0"


def _optional_float(value: float | None) -> str | None:
    if value is None:
        return None
    return str(float(value))


def emit_contract_textfile(
    path: Path,
    *,
    snapshot: LiveSurfaceSnapshot,
    assessment: LiveSurfaceAssessment,
    receipts_total: int = 0,
) -> None:
    lines = [
        "# HELP hapax_live_surface_state Live surface state as one-hot gauges",
        "# TYPE hapax_live_surface_state gauge",
    ]
    for state in ("healthy", "degraded_containment", "failed"):
        lines.append(
            f'hapax_live_surface_state{{state="{state}"}} '
            f"{1 if assessment.state.value == state else 0}"
        )

    lines.extend(
        [
            "# HELP hapax_live_surface_v4l2_egress_mode Active v4l2 egress mode",
            "# TYPE hapax_live_surface_v4l2_egress_mode gauge",
        ]
    )
    for mode in V4l2EgressMode:
        lines.append(
            f'hapax_live_surface_v4l2_egress_mode{{mode="{mode.value}"}} '
            f"{1 if snapshot.v4l2_egress_mode is mode else 0}"
        )

    optional_samples = {
        "hapax_obs_decoder_source_active": _optional_bool(snapshot.obs_source_active),
        "hapax_obs_decoder_playing": _optional_bool(snapshot.obs_playing),
        "hapax_obs_decoder_frame_hash_changed": _optional_bool(snapshot.obs_screenshot_changed),
        "hapax_obs_decoder_frame_flat": _optional_bool(snapshot.obs_screenshot_flat),
        "hapax_obs_decoder_screenshot_seconds_ago": _optional_float(
            snapshot.obs_screenshot_age_seconds
        ),
        "hapax_public_output_live": _optional_bool(snapshot.public_output_live),
        "hapax_v4l2_bridge_write_frames_total": _optional_float(snapshot.bridge_write_frames_total),
        "hapax_v4l2_bridge_write_bytes_total": _optional_float(snapshot.bridge_write_bytes_total),
        "hapax_v4l2_bridge_write_errors_total": _optional_float(snapshot.bridge_write_errors_total),
        "hapax_v4l2_bridge_heartbeat_seconds_ago": _optional_float(
            snapshot.bridge_heartbeat_age_seconds
        ),
        "hapax_video42_decoded_frames_total": _optional_float(
            snapshot.decoded_video42_frames_total
        ),
        "hapax_video42_decoded_last_frame_seconds_ago": _optional_float(
            snapshot.decoded_video42_last_frame_age_seconds
        ),
    }
    for name, value in optional_samples.items():
        if value is not None:
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")

    lines.extend(
        [
            "# HELP hapax_live_surface_reason Active degraded or failed reason",
            "# TYPE hapax_live_surface_reason gauge",
        ]
    )
    for reason in assessment.reasons:
        lines.append(f'hapax_live_surface_reason{{reason="{_label_value(reason)}"}} 1')

    lines.extend(
        [
            "# HELP hapax_live_surface_remediation_receipts_total Recorded remediation receipts",
            "# TYPE hapax_live_surface_remediation_receipts_total counter",
            f"hapax_live_surface_remediation_receipts_total {receipts_total}",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
