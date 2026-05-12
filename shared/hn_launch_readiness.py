"""HN launch readiness checks for the public studio surface.

The task is intentionally broader than a smoke test: it asks whether the system
is demonstrably ready for a Show HN launch. This module keeps the answer
deterministic by reading the existing runtime truth surfaces instead of
attempting repair or inferring public state from logs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class ReadinessStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


LOGOS_API_WARNING_CLASSIFICATION = "non_blocking_hn_launch_warning"
LOGOS_API_WARNING_RATIONALE = (
    "HN launch requires logos-api liveness plus ready/ok SHM health; failed aggregate "
    "/api/health sub-checks are recorded as non-launch-critical platform posture debt."
)


@dataclass(frozen=True)
class CheckResult:
    id: str
    label: str
    status: ReadinessStatus
    summary: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status.value,
            "summary": self.summary,
            "evidence": _jsonable(self.evidence),
        }


@dataclass(frozen=True)
class ReadinessReport:
    checked_at_epoch: float
    checks: tuple[CheckResult, ...]
    soak_samples: tuple[ReadinessReport, ...] = ()

    @property
    def ready(self) -> bool:
        return not any(check.status is ReadinessStatus.FAIL for check in self.checks)

    @property
    def status(self) -> ReadinessStatus:
        if any(check.status is ReadinessStatus.FAIL for check in self.checks):
            return ReadinessStatus.FAIL
        if any(check.status is ReadinessStatus.WARN for check in self.checks):
            return ReadinessStatus.WARN
        return ReadinessStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        failures = [check.id for check in self.checks if check.status is ReadinessStatus.FAIL]
        warnings = [check.id for check in self.checks if check.status is ReadinessStatus.WARN]
        payload: dict[str, Any] = {
            "checked_at_epoch": round(self.checked_at_epoch, 3),
            "status": self.status.value,
            "ready": self.ready,
            "failures": failures,
            "warnings": warnings,
            "checks": [check.to_dict() for check in self.checks],
        }
        if self.soak_samples:
            payload["soak_samples"] = [sample.to_dict() for sample in self.soak_samples]
        return payload


@dataclass(frozen=True)
class ReadinessConfig:
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    shm_root: Path = Path("/dev/shm")
    logos_base_url: str = "http://127.0.0.1:8051"
    weblog_rss_url: str = "https://hapax.weblog.lol/rss.xml"
    frame_max_age_s: float = 30.0
    runtime_json_max_age_s: float = 120.0
    voice_witness_max_age_s: float = 180.0
    logos_health_max_age_s: float = 120.0
    youtube_id_max_age_s: float = 300.0
    min_camera_count: int = 6
    expected_timer_count: int = 87
    max_failed_user_units: int = 2
    obs_loopback_device: Path = Path("/dev/video42")

    @property
    def compositor_root(self) -> Path:
        return self.shm_root / "hapax-compositor"

    @property
    def imagination_root(self) -> Path:
        return self.shm_root / "hapax-imagination"

    @property
    def daimonion_root(self) -> Path:
        return self.shm_root / "hapax-daimonion"

    @property
    def logos_root(self) -> Path:
        return self.shm_root / "hapax-logos"

    @property
    def visual_root(self) -> Path:
        return self.shm_root / "hapax-visual"


class CommandRunner(Protocol):
    def __call__(
        self, args: Sequence[str], *, timeout: float = 5.0
    ) -> subprocess.CompletedProcess[str]: ...


class JsonGetter(Protocol):
    def __call__(self, url: str, *, timeout: float = 5.0) -> Mapping[str, Any]: ...


class TextGetter(Protocol):
    def __call__(self, url: str, *, timeout: float = 5.0) -> str: ...


@dataclass(frozen=True)
class _CheckContext:
    config: ReadinessConfig
    now_epoch: float
    runner: CommandRunner
    json_getter: JsonGetter
    text_getter: TextGetter


def collect_hn_launch_readiness(
    config: ReadinessConfig | None = None,
    *,
    runner: CommandRunner | None = None,
    json_getter: JsonGetter | None = None,
    text_getter: TextGetter | None = None,
    now_epoch: float | None = None,
) -> ReadinessReport:
    """Collect the ten HN launch checklist checks."""

    resolved_config = config or ReadinessConfig()
    context = _CheckContext(
        config=resolved_config,
        now_epoch=now_epoch if now_epoch is not None else time.time(),
        runner=runner or _run_command,
        json_getter=json_getter or _get_json,
        text_getter=text_getter or _get_text,
    )
    checks = (
        _check_compositor_visual_surface(context),
        _check_programme_segments(context),
        _check_daimonion_voice(context),
        _check_reverie_visual_surface(context),
        _check_logos_api(context),
        _check_github_readme(context),
        _check_omg_weblog(context),
        _check_youtube_livestream(context),
        _check_obs_clean_feed(context),
        _check_timer_and_failure_budget(context),
    )
    return ReadinessReport(checked_at_epoch=context.now_epoch, checks=checks)


def soak_hn_launch_readiness(
    *,
    duration_s: float,
    interval_s: float,
    config: ReadinessConfig | None = None,
    runner: CommandRunner | None = None,
    json_getter: JsonGetter | None = None,
    text_getter: TextGetter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    now: Callable[[], float] = time.time,
) -> ReadinessReport:
    """Run repeated readiness samples and return an aggregate soak result."""

    if duration_s <= 0:
        return collect_hn_launch_readiness(
            config,
            runner=runner or _run_command,
            json_getter=json_getter or _get_json,
            text_getter=text_getter or _get_text,
            now_epoch=now(),
        )

    samples: list[ReadinessReport] = []
    deadline = monotonic() + duration_s
    while True:
        samples.append(
            collect_hn_launch_readiness(
                config,
                runner=runner or _run_command,
                json_getter=json_getter or _get_json,
                text_getter=text_getter or _get_text,
                now_epoch=now(),
            )
        )
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(interval_s, remaining))

    failed_samples = [
        {"sample_index": index, "failures": sample.to_dict()["failures"]}
        for index, sample in enumerate(samples)
        if sample.status is ReadinessStatus.FAIL
    ]
    soak_check = CheckResult(
        id="thirty_minute_soak",
        label="30-minute soak",
        status=ReadinessStatus.FAIL if failed_samples else ReadinessStatus.PASS,
        summary=(
            f"{len(failed_samples)} of {len(samples)} samples failed"
            if failed_samples
            else f"{len(samples)} samples passed"
        ),
        evidence={
            "duration_s": duration_s,
            "interval_s": interval_s,
            "failed_samples": failed_samples,
        },
    )
    return ReadinessReport(
        checked_at_epoch=now(),
        checks=(*samples[-1].checks, soak_check),
        soak_samples=tuple(samples),
    )


def _check_compositor_visual_surface(context: _CheckContext) -> CheckResult:
    config = context.config
    service_results = {
        unit: _service_is_active(unit, context.runner)
        for unit in ("studio-compositor", "hapax-imagination")
    }
    file_results = {
        "preview_frame": _probe_file(
            config.visual_root / "frame.jpg", context.now_epoch, config.frame_max_age_s
        ),
        "snapshot": _probe_file(
            config.compositor_root / "snapshot.jpg", context.now_epoch, config.frame_max_age_s
        ),
        "fx_snapshot": _probe_file(
            config.compositor_root / "fx-snapshot.jpg", context.now_epoch, config.frame_max_age_s
        ),
        "active_wards": _probe_json_file(
            config.compositor_root / "active_wards.json",
            context.now_epoch,
            config.runtime_json_max_age_s,
        ),
        "current_layout_state": _probe_json_file(
            config.compositor_root / "current-layout-state.json",
            context.now_epoch,
            config.runtime_json_max_age_s,
        ),
        "ward_properties": _probe_json_file(
            config.compositor_root / "ward-properties.json",
            context.now_epoch,
            config.runtime_json_max_age_s,
        ),
    }
    egress = _get_json_safe(context.json_getter, f"{config.logos_base_url}/api/studio/egress/state")
    compositor_evidence = _compact_egress_evidence(
        _egress_evidence(egress.get("data"), "compositor")
    )
    active_cameras = _nested_get(compositor_evidence, ("observed", "active_cameras"))

    active_wards = _json_payload(file_results["active_wards"])
    ward_ids = active_wards.get("ward_ids") if isinstance(active_wards, Mapping) else None
    has_wards = isinstance(ward_ids, Sequence) and not isinstance(ward_ids, str) and bool(ward_ids)
    layout_state = _json_payload(file_results["current_layout_state"])
    layout_mode_value = (
        layout_state.get("layout_mode") if isinstance(layout_state, Mapping) else None
    )
    layout_mode = layout_mode_value if isinstance(layout_mode_value, str) else ""
    has_sierpinski = layout_mode == "sierpinski"

    failed_reasons: list[str] = []
    if not all(result["active"] for result in service_results.values()):
        failed_reasons.append("required compositor services are not active")
    if not all(result["ok"] for result in file_results.values()):
        failed_reasons.append("visual/compositor truth files are missing, empty, or stale")
    if not isinstance(active_cameras, int) or active_cameras < config.min_camera_count:
        failed_reasons.append(
            f"active cameras below threshold ({active_cameras!r} < {config.min_camera_count})"
        )
    if not has_wards:
        failed_reasons.append("active ward list is empty or malformed")
    if not has_sierpinski:
        failed_reasons.append("layout mode is not sierpinski")

    status = ReadinessStatus.FAIL if failed_reasons else ReadinessStatus.PASS
    return CheckResult(
        id="compositor_visual_surface",
        label="Compositor cameras, Sierpinski, wards",
        status=status,
        summary="; ".join(failed_reasons) if failed_reasons else "compositor surface is live",
        evidence={
            "services": service_results,
            "files": file_results,
            "active_cameras": active_cameras,
            "layout_mode": layout_mode or None,
            "current_layout_state": layout_state if isinstance(layout_state, Mapping) else None,
            "ward_count": len(ward_ids) if isinstance(ward_ids, Sequence) else 0,
            "egress_compositor": compositor_evidence,
            "egress_error": egress.get("error"),
        },
    )


def _check_programme_segments(context: _CheckContext) -> CheckResult:
    segment = _probe_json_file(
        context.config.compositor_root / "active-segment.json",
        context.now_epoch,
        context.config.runtime_json_max_age_s,
    )
    payload = _json_payload(segment)
    if not isinstance(payload, Mapping):
        return CheckResult(
            id="programme_segments",
            label="Programme segments delivering",
            status=ReadinessStatus.FAIL,
            summary="active segment payload is missing or malformed",
            evidence={"active_segment": segment},
        )

    required_fields = ("programme_id", "role", "topic", "segment_beats", "current_beat_index")
    missing_fields = [field_name for field_name in required_fields if field_name not in payload]
    beats = payload.get("segment_beats")
    has_beats = isinstance(beats, Sequence) and not isinstance(beats, str) and bool(beats)
    status = (
        ReadinessStatus.PASS
        if segment["ok"] and not missing_fields and has_beats
        else ReadinessStatus.FAIL
    )
    summary = (
        "programme segment is fresh and populated"
        if status is ReadinessStatus.PASS
        else "active programme segment is stale, incomplete, or empty"
    )
    return CheckResult(
        id="programme_segments",
        label="Programme segments delivering",
        status=status,
        summary=summary,
        evidence={
            "active_segment": segment,
            "missing_fields": missing_fields,
            "beat_count": len(beats)
            if isinstance(beats, Sequence) and not isinstance(beats, str)
            else 0,
            "programme_id": payload.get("programme_id"),
            "role": payload.get("role"),
            "current_beat_index": payload.get("current_beat_index"),
        },
    )


def _check_daimonion_voice(context: _CheckContext) -> CheckResult:
    service = _service_is_active("hapax-daimonion", context.runner)
    witness = _probe_json_file(
        context.config.daimonion_root / "voice-output-witness.json",
        context.now_epoch,
        context.config.voice_witness_max_age_s,
    )
    payload = _json_payload(witness)
    last_success = payload.get("last_successful_playback") if isinstance(payload, Mapping) else None
    last_playback = payload.get("last_playback") if isinstance(payload, Mapping) else None
    status_value = payload.get("status") if isinstance(payload, Mapping) else None
    successful = status_value == "playback_completed" or _playback_completed(last_success)
    if not successful and _playback_completed(last_playback):
        successful = True

    failed_reasons: list[str] = []
    if not service["active"]:
        failed_reasons.append("hapax-daimonion is not active")
    if not witness["ok"]:
        failed_reasons.append("voice output witness is missing, stale, or malformed")
    if not successful:
        failed_reasons.append("no completed playback is recorded in voice-output-witness")

    return CheckResult(
        id="daimonion_voice_segments",
        label="Daimonion voice speaking segments",
        status=ReadinessStatus.FAIL if failed_reasons else ReadinessStatus.PASS,
        summary="; ".join(failed_reasons)
        if failed_reasons
        else "voice path has completed playback",
        evidence={
            "service": service,
            "voice_output_witness": witness,
            "witness_status": status_value,
            "last_successful_playback": last_success,
            "last_playback": last_playback,
            "last_destination_decision": payload.get("last_destination_decision")
            if isinstance(payload, Mapping)
            else None,
        },
    )


def _check_reverie_visual_surface(context: _CheckContext) -> CheckResult:
    services = {
        unit: _service_is_active(unit, context.runner)
        for unit in ("hapax-reverie", "hapax-imagination")
    }
    files = {
        "imagination_current": _probe_json_file(
            context.config.imagination_root / "current.json",
            context.now_epoch,
            context.config.runtime_json_max_age_s,
        ),
        "imagination_health": _probe_json_file(
            context.config.imagination_root / "health.json",
            context.now_epoch,
            context.config.runtime_json_max_age_s,
        ),
    }
    failed_reasons: list[str] = []
    if not all(result["active"] for result in services.values()):
        failed_reasons.append("reverie/imagination services are not active")
    if not all(result["ok"] for result in files.values()):
        failed_reasons.append("imagination truth files are missing, empty, or stale")

    current_payload = _json_payload(files["imagination_current"])
    has_reactive_payload = isinstance(current_payload, Mapping) and bool(current_payload)
    if not has_reactive_payload:
        failed_reasons.append("imagination current payload is empty or malformed")

    return CheckResult(
        id="reverie_visual_surface",
        label="Reverie surface responding",
        status=ReadinessStatus.FAIL if failed_reasons else ReadinessStatus.PASS,
        summary="; ".join(failed_reasons)
        if failed_reasons
        else "reverie/imagination surface is fresh",
        evidence={
            "services": services,
            "files": files,
            "current_keys": sorted(current_payload) if isinstance(current_payload, Mapping) else [],
        },
    )


def _check_logos_api(context: _CheckContext) -> CheckResult:
    service = _service_is_active("logos-api", context.runner)
    shm_health = _probe_json_file(
        context.config.logos_root / "health.json",
        context.now_epoch,
        context.config.logos_health_max_age_s,
    )
    shm_payload = _json_payload(shm_health)
    api_health = _get_json_safe(context.json_getter, f"{context.config.logos_base_url}/api/health")
    api_payload = api_health.get("data")
    api_overall_status = None
    api_failed_checks: list[str] = []

    failed_reasons: list[str] = []
    warning_reasons: list[str] = []
    if not service["active"]:
        failed_reasons.append("logos-api service is not active")
    if not shm_health["ok"]:
        failed_reasons.append("logos shm health file is missing, empty, or stale")
    if isinstance(shm_payload, Mapping) and (
        shm_payload.get("ready") is not True or shm_payload.get("status") not in {"ok", "healthy"}
    ):
        failed_reasons.append("logos shm health does not report ready/ok")
    if api_health.get("error"):
        failed_reasons.append("logos API health endpoint is unreachable")
    elif isinstance(api_payload, Mapping):
        api_overall_status = api_payload.get("overall_status") or api_payload.get("status")
        api_failed_checks = _string_list(api_payload.get("failed_checks"))
        if api_overall_status not in {"healthy", "ok"}:
            failed_checks_summary = (
                f"; failed health checks: {', '.join(api_failed_checks)}"
                if api_failed_checks
                else ""
            )
            warning_reasons.append(
                f"logos API overall status is {api_overall_status!r}"
                f"; classified as {LOGOS_API_WARNING_CLASSIFICATION}"
                f"{failed_checks_summary}"
            )

    if failed_reasons:
        status = ReadinessStatus.FAIL
    elif warning_reasons:
        status = ReadinessStatus.WARN
    else:
        status = ReadinessStatus.PASS

    return CheckResult(
        id="logos_api",
        label="Logos API healthy and serving",
        status=status,
        summary=(
            "; ".join(failed_reasons or warning_reasons)
            if failed_reasons or warning_reasons
            else "logos-api is active and serving health"
        ),
        evidence={
            "service": service,
            "shm_health": shm_health,
            "shm_ready": shm_payload.get("ready") if isinstance(shm_payload, Mapping) else None,
            "shm_status": shm_payload.get("status") if isinstance(shm_payload, Mapping) else None,
            "api_health": api_payload,
            "api_overall_status": api_overall_status,
            "api_failed_checks": api_failed_checks,
            "api_error": api_health.get("error"),
            "warning_classification": LOGOS_API_WARNING_CLASSIFICATION if warning_reasons else None,
            "warning_rationale": LOGOS_API_WARNING_RATIONALE if warning_reasons else None,
        },
    )


def _check_github_readme(context: _CheckContext) -> CheckResult:
    readme = context.config.repo_root / "README.md"
    file_probe = _probe_file(readme, context.now_epoch, max_age_s=None)
    git_status = _run_safe(
        context.runner,
        ["git", "-C", str(context.config.repo_root), "status", "--porcelain", "--", "README.md"],
    )
    text = _read_text_file(readme)
    lower_text = text.lower()
    required_terms = ("agentgov", "support", "sponsor")
    missing_terms = [term for term in required_terms if term not in lower_text]
    dirty = bool(git_status["stdout"].strip())

    failed_reasons: list[str] = []
    warning_reasons: list[str] = []
    if not file_probe["ok"]:
        failed_reasons.append("README.md is missing or empty")
    if git_status["returncode"] != 0:
        warning_reasons.append("could not inspect README git status")
    elif dirty:
        failed_reasons.append("README.md has uncommitted changes")
    if missing_terms:
        failed_reasons.append(f"README.md missing launch terms: {', '.join(missing_terms)}")

    if failed_reasons:
        status = ReadinessStatus.FAIL
    elif warning_reasons:
        status = ReadinessStatus.WARN
    else:
        status = ReadinessStatus.PASS

    return CheckResult(
        id="github_readme",
        label="GitHub README current",
        status=status,
        summary=(
            "; ".join(failed_reasons or warning_reasons)
            if failed_reasons or warning_reasons
            else "README.md exists, is clean, and covers launch terms"
        ),
        evidence={
            "readme": file_probe,
            "git_status": git_status,
            "missing_terms": missing_terms,
            "dirty": dirty,
        },
    )


def _check_omg_weblog(context: _CheckContext) -> CheckResult:
    producer = _service_is_active("hapax-weblog-publish-public-event-producer", context.runner)
    rss = _get_text_safe(context.text_getter, context.config.weblog_rss_url)
    failed_reasons: list[str] = []
    warning_reasons: list[str] = []
    item_count = 0
    broken_items: list[str] = []

    if not producer["active"]:
        warning_reasons.append("weblog public event producer is not active")
    if rss.get("error"):
        failed_reasons.append("weblog RSS feed is unreachable")
    else:
        try:
            root = ET.fromstring(rss["text"])
            items = root.findall(".//item")
            item_count = len(items)
            for item in items[:20]:
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                candidate = f"{title} {link}".lower()
                if "broken" in candidate or "404" in candidate:
                    broken_items.append(title or link)
        except ET.ParseError as exc:
            failed_reasons.append(f"weblog RSS feed is malformed: {exc}")
    if item_count <= 0 and not rss.get("error"):
        failed_reasons.append("weblog RSS feed contains no posts")
    if broken_items:
        failed_reasons.append("weblog RSS contains broken-post markers")

    if failed_reasons:
        status = ReadinessStatus.FAIL
    elif warning_reasons:
        status = ReadinessStatus.WARN
    else:
        status = ReadinessStatus.PASS

    return CheckResult(
        id="omg_weblog",
        label="omg.lol weblog current",
        status=status,
        summary=(
            "; ".join(failed_reasons or warning_reasons)
            if failed_reasons or warning_reasons
            else "weblog RSS feed is reachable with posts and no broken markers"
        ),
        evidence={
            "producer_service": producer,
            "rss_url": context.config.weblog_rss_url,
            "rss_error": rss.get("error"),
            "item_count": item_count,
            "broken_items": broken_items,
        },
    )


def _check_youtube_livestream(context: _CheckContext) -> CheckResult:
    services = {
        unit: _service_is_active(unit, context.runner)
        for unit in ("hapax-youtube-video-id", "hapax-youtube-viewer-count")
    }
    video_id = _probe_file(
        context.config.compositor_root / "youtube-video-id.txt",
        context.now_epoch,
        context.config.youtube_id_max_age_s,
    )
    video_id_text = _read_text_file(Path(video_id["path"])).strip()
    viewer_count = _probe_file(
        context.config.compositor_root / "youtube-viewer-count.txt",
        context.now_epoch,
        context.config.youtube_id_max_age_s,
        min_size=0,
    )
    quota_state = _probe_json_file(
        context.config.compositor_root / "youtube-quota.json",
        context.now_epoch,
        max_age_s=None,
    )
    quota_payload = _json_payload(quota_state)
    quota_exhausted = False
    if isinstance(quota_payload, Mapping):
        quota_exhausted = bool(
            quota_payload.get("quota_exhausted") or quota_payload.get("description_quota_exhausted")
        )

    failed_reasons: list[str] = []
    warning_reasons: list[str] = []
    if not all(result["active"] for result in services.values()):
        failed_reasons.append("YouTube id/viewer services are not active")
    if not video_id["ok"] or not video_id_text:
        failed_reasons.append("YouTube livestream video id is missing, empty, or stale")
    if not viewer_count["exists"] or not viewer_count["fresh"]:
        failed_reasons.append("YouTube viewer count truth file is missing or stale")
    if quota_exhausted:
        failed_reasons.append("YouTube description quota is exhausted")
    if not quota_state["exists"]:
        warning_reasons.append("YouTube quota/description state file is absent")

    if failed_reasons:
        status = ReadinessStatus.FAIL
    elif warning_reasons:
        status = ReadinessStatus.WARN
    else:
        status = ReadinessStatus.PASS

    return CheckResult(
        id="youtube_livestream",
        label="YouTube livestream active",
        status=status,
        summary=(
            "; ".join(failed_reasons or warning_reasons)
            if failed_reasons or warning_reasons
            else "YouTube livestream id, viewer count, and quota state are ready"
        ),
        evidence={
            "services": services,
            "video_id_file": video_id,
            "video_id_present": bool(video_id_text),
            "viewer_count_file": viewer_count,
            "quota_state": quota_state,
            "quota_exhausted": quota_exhausted,
        },
    )


def _check_obs_clean_feed(context: _CheckContext) -> CheckResult:
    service = _service_is_active("hapax-obs-livestream", context.runner)
    loopback = _probe_file(
        context.config.obs_loopback_device, context.now_epoch, max_age_s=None, min_size=0
    )
    egress = _get_json_safe(
        context.json_getter, f"{context.config.logos_base_url}/api/studio/egress/state"
    )
    payload = egress.get("data")
    evidence = {
        source: _compact_egress_evidence(_egress_evidence(payload, source))
        for source in (
            "rtmp_output",
            "mediamtx_hls",
            "hls_playlist",
            "audio_floor",
            "privacy_floor",
        )
    }
    public_claim_allowed = (
        payload.get("public_claim_allowed") if isinstance(payload, Mapping) else None
    )
    failing_evidence = [
        source
        for source, source_evidence in evidence.items()
        if source_evidence.get("status") != "pass"
    ]

    failed_reasons: list[str] = []
    if not service["active"]:
        failed_reasons.append("hapax-obs-livestream is not active")
    if not loopback["exists"]:
        failed_reasons.append(f"{context.config.obs_loopback_device} loopback device is missing")
    if public_claim_allowed is not True:
        failed_reasons.append("egress state does not allow a public live claim")
    if failing_evidence:
        failed_reasons.append(f"egress evidence failing: {', '.join(failing_evidence)}")

    return CheckResult(
        id="obs_clean_feed",
        label="OBS broadcasting clean feed",
        status=ReadinessStatus.FAIL if failed_reasons else ReadinessStatus.PASS,
        summary="; ".join(failed_reasons) if failed_reasons else "OBS public feed is clean",
        evidence={
            "service": service,
            "loopback": loopback,
            "public_claim_allowed": public_claim_allowed,
            "egress_error": egress.get("error"),
            "egress_evidence": evidence,
        },
    )


def _check_timer_and_failure_budget(context: _CheckContext) -> CheckResult:
    timers = _run_safe(
        context.runner,
        ["systemctl", "--user", "list-timers", "--all", "--no-legend", "--plain"],
        timeout=10.0,
    )
    failed_units = _run_safe(
        context.runner,
        ["systemctl", "--user", "--failed", "--no-legend", "--plain"],
        timeout=10.0,
    )
    timer_lines = [line for line in timers["stdout"].splitlines() if line.strip()]
    failed_lines = [line for line in failed_units["stdout"].splitlines() if line.strip()]
    failed_unit_names = [line.split()[0] for line in failed_lines if line.split()]

    failed_reasons: list[str] = []
    if timers["returncode"] != 0:
        failed_reasons.append("could not list user timers")
    if failed_units["returncode"] != 0:
        failed_reasons.append("could not list failed user units")
    if len(timer_lines) < context.config.expected_timer_count:
        failed_reasons.append(
            f"only {len(timer_lines)} timers found; expected at least "
            f"{context.config.expected_timer_count}"
        )
    if len(failed_unit_names) > context.config.max_failed_user_units:
        failed_reasons.append(
            f"{len(failed_unit_names)} failed user units exceeds budget "
            f"{context.config.max_failed_user_units}"
        )

    return CheckResult(
        id="systemd_timer_failed_unit_budget",
        label="87 timers running, <=2 failed units",
        status=ReadinessStatus.FAIL if failed_reasons else ReadinessStatus.PASS,
        summary="; ".join(failed_reasons)
        if failed_reasons
        else "timer and failed-unit budget is met",
        evidence={
            "timer_count": len(timer_lines),
            "expected_timer_count": context.config.expected_timer_count,
            "failed_unit_count": len(failed_unit_names),
            "max_failed_user_units": context.config.max_failed_user_units,
            "failed_units": failed_unit_names,
            "timer_command": timers,
            "failed_units_command": failed_units,
        },
    )


def _service_is_active(unit: str, runner: CommandRunner) -> dict[str, Any]:
    result = _run_safe(runner, ["systemctl", "--user", "is-active", unit])
    state = result["stdout"].strip()
    return {
        "unit": unit,
        "active": result["returncode"] == 0 and state == "active",
        "state": state or None,
        "returncode": result["returncode"],
        "stderr": result["stderr"],
    }


def _run_command(args: Sequence[str], *, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _run_safe(
    runner: CommandRunner, args: Sequence[str], *, timeout: float = 5.0
) -> dict[str, Any]:
    try:
        result = runner(args, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "args": list(args),
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "args": list(args),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _get_json(url: str, *, timeout: float = 5.0) -> Mapping[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{url} did not return a JSON object")
    return payload


def _get_text(url: str, *, timeout: float = 5.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _get_json_safe(json_getter: JsonGetter, url: str) -> dict[str, Any]:
    try:
        return {"data": json_getter(url, timeout=5.0), "error": None}
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return {"data": {}, "error": str(exc)}


def _get_text_safe(text_getter: TextGetter, url: str) -> dict[str, Any]:
    try:
        return {"text": text_getter(url, timeout=5.0), "error": None}
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return {"text": "", "error": str(exc)}


def _probe_file(
    path: Path,
    now_epoch: float,
    max_age_s: float | None,
    *,
    min_size: int = 1,
) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError as exc:
        return {
            "path": str(path),
            "exists": False,
            "size": None,
            "age_s": None,
            "fresh": False,
            "nonempty": False,
            "ok": False,
            "error": str(exc),
        }
    age_s = max(0.0, now_epoch - stat.st_mtime)
    fresh = max_age_s is None or age_s <= max_age_s
    nonempty = stat.st_size >= min_size
    return {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "age_s": round(age_s, 3),
        "fresh": fresh,
        "nonempty": nonempty,
        "ok": fresh and nonempty,
        "error": None,
    }


def _probe_json_file(
    path: Path,
    now_epoch: float,
    max_age_s: float | None,
    *,
    min_size: int = 1,
) -> dict[str, Any]:
    probe = _probe_file(path, now_epoch, max_age_s, min_size=min_size)
    if not probe["exists"] or not probe["nonempty"]:
        return {**probe, "json": None, "json_error": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**probe, "ok": False, "json": None, "json_error": str(exc)}
    return {**probe, "json": payload, "json_error": None}


def _json_payload(probe: Mapping[str, Any]) -> Any:
    return probe.get("json")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    return [item for item in value if isinstance(item, str)]


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _egress_evidence(payload: Any, source: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    evidence = payload.get("evidence")
    if isinstance(evidence, Mapping):
        candidate = evidence.get(source)
        return dict(candidate) if isinstance(candidate, Mapping) else {}
    if isinstance(evidence, Sequence) and not isinstance(evidence, str):
        for row in evidence:
            if isinstance(row, Mapping) and row.get("source") == source:
                return dict(row)
    return {}


def _compact_egress_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if not evidence:
        return {}
    observed = evidence.get("observed")
    compact_observed: Any = observed
    if evidence.get("source") == "audio_floor" and isinstance(observed, Mapping):
        audio_state = observed.get("audio_safe_for_broadcast")
        compact_observed = {
            "audio_safe": _nested_get(audio_state, ("safe",))
            if isinstance(audio_state, Mapping)
            else None,
            "audio_status": _nested_get(audio_state, ("status",))
            if isinstance(audio_state, Mapping)
            else None,
            "blocking_reason_codes": [
                reason.get("code")
                for reason in audio_state.get("blocking_reasons", [])
                if isinstance(reason, Mapping)
            ]
            if isinstance(audio_state, Mapping)
            else [],
        }
    return {
        "source": evidence.get("source"),
        "status": evidence.get("status"),
        "summary": evidence.get("summary"),
        "observed": compact_observed,
        "age_s": evidence.get("age_s"),
        "stale": evidence.get("stale"),
        "timestamp": evidence.get("timestamp"),
    }


def _nested_get(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = payload
    for segment in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    return current


def _playback_completed(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    status = payload.get("status")
    return (
        status in {"completed", "playback_completed", "success"} or payload.get("completed") is True
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, ReadinessStatus):
        return value.value
    return value


def _format_text_report(report: ReadinessReport) -> str:
    lines = [f"HN launch readiness: {report.status.value}"]
    for check in report.checks:
        lines.append(f"{check.status.value.upper():4} {check.id}: {check.summary}")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check HN launch readiness across studio, publication, and systemd surfaces."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--soak-minutes",
        type=float,
        default=0.0,
        help="Run repeated samples for this many minutes before returning.",
    )
    parser.add_argument(
        "--soak-interval-seconds",
        type=float,
        default=60.0,
        help="Interval between soak samples.",
    )
    parser.add_argument(
        "--logos-base-url",
        default="http://127.0.0.1:8051",
        help="Base URL for the council Logos API.",
    )
    parser.add_argument(
        "--weblog-rss-url",
        default="https://hapax.weblog.lol/rss.xml",
        help="RSS URL for the omg.lol weblog.",
    )
    parser.add_argument(
        "--expected-timers",
        type=int,
        default=87,
        help="Minimum expected user timer count.",
    )
    parser.add_argument(
        "--max-failed-user-units",
        type=int,
        default=2,
        help="Maximum failed user units allowed.",
    )
    parser.add_argument(
        "--min-cameras",
        type=int,
        default=6,
        help="Minimum active camera count expected from egress evidence.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = ReadinessConfig(
        logos_base_url=args.logos_base_url.rstrip("/"),
        weblog_rss_url=args.weblog_rss_url,
        expected_timer_count=args.expected_timers,
        max_failed_user_units=args.max_failed_user_units,
        min_camera_count=args.min_cameras,
    )
    if args.soak_minutes > 0:
        report = soak_hn_launch_readiness(
            duration_s=args.soak_minutes * 60.0,
            interval_s=args.soak_interval_seconds,
            config=config,
        )
    else:
        report = collect_hn_launch_readiness(config)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_format_text_report(report))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
