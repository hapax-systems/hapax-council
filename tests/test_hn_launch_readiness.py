from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from shared.hn_launch_readiness import (
    ReadinessConfig,
    collect_hn_launch_readiness,
    soak_hn_launch_readiness,
)

NOW = 1_778_512_400.0
CURRENT_SHA = "a" * 40


class FakeRunner:
    def __init__(
        self,
        *,
        active_units: set[str] | None = None,
        timer_count: int = 87,
        failed_units: tuple[str, ...] = (),
        readme_status: str = "",
        current_sha: str | None = None,
    ) -> None:
        self.active_units = active_units or set()
        self.timer_count = timer_count
        self.failed_units = failed_units
        self.readme_status = readme_status
        self.current_sha = current_sha

    def __call__(
        self, args: list[str] | tuple[str, ...], *, timeout: float = 5.0
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        if list(args[:3]) == ["systemctl", "--user", "is-active"]:
            unit = args[3]
            state = "active" if unit in self.active_units else "inactive"
            return subprocess.CompletedProcess(args, 0 if state == "active" else 3, state, "")
        if list(args[:3]) == ["systemctl", "--user", "list-timers"]:
            stdout = "\n".join(
                f"timer-{index}.timer next left last passed unit"
                for index in range(self.timer_count)
            )
            return subprocess.CompletedProcess(args, 0, stdout, "")
        if list(args[:3]) == ["systemctl", "--user", "--failed"]:
            stdout = "\n".join(
                f"{unit} loaded failed failed fixture failure" for unit in self.failed_units
            )
            return subprocess.CompletedProcess(args, 0, stdout, "")
        if args[0] == "git" and "rev-parse" in args:
            if self.current_sha:
                return subprocess.CompletedProcess(args, 0, f"{self.current_sha}\n", "")
            return subprocess.CompletedProcess(args, 1, "", "missing origin/main")
        if args[0] == "git" and "status" in args:
            return subprocess.CompletedProcess(args, 0, self.readme_status, "")
        return subprocess.CompletedProcess(args, 127, "", "unexpected command")


class FlakyObsRunner(FakeRunner):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sample_index = 0

    def __call__(
        self, args: list[str] | tuple[str, ...], *, timeout: float = 5.0
    ) -> subprocess.CompletedProcess[str]:
        if list(args[:4]) == ["systemctl", "--user", "is-active", "hapax-obs-livestream"]:
            if self.sample_index >= 1:
                return subprocess.CompletedProcess(args, 3, "inactive", "")
        result = super().__call__(args, timeout=timeout)
        if list(args[:3]) == ["systemctl", "--user", "--failed"]:
            self.sample_index += 1
        return result


def test_hn_launch_readiness_passes_when_all_truth_surfaces_are_green(tmp_path: Path) -> None:
    config = _ready_fixture(tmp_path)
    report = collect_hn_launch_readiness(
        config,
        runner=FakeRunner(active_units=_all_active_units()),
        json_getter=_json_getter_ready,
        text_getter=_text_getter_ready,
        now_epoch=NOW,
    )

    assert report.ready is True
    assert [check.status.value for check in report.checks] == ["pass"] * 10


def test_hn_launch_readiness_warnings_do_not_block_ready(tmp_path: Path) -> None:
    config = _ready_fixture(tmp_path)

    def degraded_logos_getter(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
        if url.endswith("/api/health"):
            return {"overall_status": "failed", "failed_checks": ["connectivity.phone"]}
        return _json_getter_ready(url, timeout=timeout)

    report = collect_hn_launch_readiness(
        config,
        runner=FakeRunner(active_units=_all_active_units()),
        json_getter=degraded_logos_getter,
        text_getter=_text_getter_ready,
        now_epoch=NOW,
    )

    checks = {check.id: check for check in report.checks}
    assert report.status.value == "warn"
    assert report.ready is True
    assert checks["logos_api"].status.value == "warn"
    assert checks["logos_api"].evidence["api_failed_checks"] == ["connectivity.phone"]
    assert (
        checks["logos_api"].evidence["warning_classification"] == "non_blocking_hn_launch_warning"
    )
    assert "connectivity.phone" in checks["logos_api"].summary
    assert report.to_dict()["failures"] == []
    assert report.to_dict()["warnings"] == ["logos_api"]


def test_hn_launch_readiness_flags_private_voice_obs_youtube_and_failed_units(
    tmp_path: Path,
) -> None:
    config = _ready_fixture(tmp_path)
    _write_text(config.compositor_root / "youtube-video-id.txt", "", NOW)
    _write_json(
        config.daimonion_root / "voice-output-witness.json",
        {
            "status": "drop_recorded",
            "last_successful_playback": None,
            "last_destination_decision": {
                "destination": "private",
                "reason": "mpc_private_monitor_target_absent",
            },
        },
        NOW,
    )
    active_units = _all_active_units() - {"hapax-obs-livestream"}
    report = collect_hn_launch_readiness(
        config,
        runner=FakeRunner(
            active_units=active_units,
            failed_units=(
                "hapax-rebuild-services.service",
                "hapax-request-intake-consumer.service",
                "hapax-wiring-audit.service",
            ),
        ),
        json_getter=_json_getter_private_egress,
        text_getter=_text_getter_ready,
        now_epoch=NOW,
    )

    checks = {check.id: check for check in report.checks}
    assert report.ready is False
    assert checks["daimonion_voice_segments"].status.value == "fail"
    assert checks["youtube_livestream"].status.value == "fail"
    assert checks["obs_clean_feed"].status.value == "fail"
    assert checks["systemd_timer_failed_unit_budget"].status.value == "fail"
    assert "mpc_private_monitor_target_absent" in json.dumps(
        checks["daimonion_voice_segments"].to_dict()
    )


def test_hn_launch_readiness_clears_fresh_current_rebuild_late_active_false_red(
    tmp_path: Path,
) -> None:
    config = _ready_fixture(tmp_path)
    _write_rebuild_outcome(
        config,
        sha_key="imagination",
        current_sha=CURRENT_SHA,
        outcome="restart_timeout_late_active",
        timestamp="2026-05-11T15:13:20Z",
    )

    report = collect_hn_launch_readiness(
        config,
        runner=FakeRunner(
            active_units=_all_active_units(),
            failed_units=(
                "hapax-rebuild-services.service",
                "hapax-request-intake-consumer.service",
                "hapax-wiring-audit.service",
            ),
            current_sha=CURRENT_SHA,
        ),
        json_getter=_json_getter_ready,
        text_getter=_text_getter_ready,
        now_epoch=NOW,
    )

    checks = {check.id: check for check in report.checks}
    budget = checks["systemd_timer_failed_unit_budget"]
    assert budget.status.value == "pass"
    assert budget.evidence["failed_unit_count"] == 3
    assert budget.evidence["effective_failed_unit_count"] == 2
    assert budget.evidence["cleared_failed_units"] == ["hapax-rebuild-services.service"]


def test_hn_launch_readiness_keeps_stale_or_sha_mismatched_rebuild_evidence_in_budget(
    tmp_path: Path,
) -> None:
    cases = (
        ("stale", CURRENT_SHA, "2026-05-11T14:00:00Z", "outcome timestamp is stale"),
        (
            "sha-mismatch",
            "b" * 40,
            "2026-05-11T15:13:20Z",
            "outcome current_sha does not match origin/main",
        ),
    )
    for case_name, outcome_sha, timestamp, reason in cases:
        config = _ready_fixture(tmp_path / case_name)
        _write_rebuild_outcome(
            config,
            sha_key="imagination",
            current_sha=outcome_sha,
            outcome="restart_timeout_late_active",
            timestamp=timestamp,
        )

        report = collect_hn_launch_readiness(
            config,
            runner=FakeRunner(
                active_units=_all_active_units(),
                failed_units=(
                    "hapax-rebuild-services.service",
                    "hapax-request-intake-consumer.service",
                    "hapax-wiring-audit.service",
                ),
                current_sha=CURRENT_SHA,
            ),
            json_getter=_json_getter_ready,
            text_getter=_text_getter_ready,
            now_epoch=NOW,
        )

        checks = {check.id: check for check in report.checks}
        budget = checks["systemd_timer_failed_unit_budget"]
        assert budget.status.value == "fail"
        assert budget.evidence["effective_failed_unit_count"] == 3
        assert budget.evidence["cleared_failed_units"] == []
        stale_records = budget.evidence["rebuild_outcome_ledger"]["stale_or_unknown_records"]
        assert stale_records[0]["reason"] == reason


def test_hn_launch_readiness_blocks_on_missing_and_unhealthy_rebuild_outcomes(
    tmp_path: Path,
) -> None:
    for outcome in ("missing_unit", "restart_failed_unhealthy"):
        config = _ready_fixture(tmp_path / outcome)
        _write_rebuild_outcome(
            config,
            sha_key="compositor",
            current_sha=CURRENT_SHA,
            outcome=outcome,
            timestamp="2026-05-11T15:13:20Z",
        )

        report = collect_hn_launch_readiness(
            config,
            runner=FakeRunner(
                active_units=_all_active_units(),
                failed_units=("hapax-rebuild-services.service",),
                current_sha=CURRENT_SHA,
            ),
            json_getter=_json_getter_ready,
            text_getter=_text_getter_ready,
            now_epoch=NOW,
        )

        checks = {check.id: check for check in report.checks}
        budget = checks["systemd_timer_failed_unit_budget"]
        assert budget.status.value == "fail"
        assert outcome in budget.summary


def test_compositor_visual_surface_ignores_consumed_layout_mode_mailbox(tmp_path: Path) -> None:
    config = _ready_fixture(tmp_path)
    (config.compositor_root / "current-layout-state.json").unlink()
    _write_text(config.compositor_root / "layout-mode.txt", "sierpinski\n", NOW)

    report = collect_hn_launch_readiness(
        config,
        runner=FakeRunner(active_units=_all_active_units()),
        json_getter=_json_getter_ready,
        text_getter=_text_getter_ready,
        now_epoch=NOW,
    )

    checks = {check.id: check for check in report.checks}
    compositor = checks["compositor_visual_surface"]
    assert compositor.status.value == "fail"
    assert "layout mode is not sierpinski" not in compositor.summary
    assert "current_layout_state" in compositor.evidence["files"]


def test_compositor_visual_surface_accepts_forcefield_when_sierpinski_ward_active(
    tmp_path: Path,
) -> None:
    config = _ready_fixture(tmp_path)
    _write_json(
        config.compositor_root / "current-layout-state.json",
        {
            "layout_name": "default",
            "layout_mode": "forcefield",
            "active_ward_ids": ["programme_banner", "reverie", "sierpinski"],
            "published_t": NOW,
        },
        NOW,
    )

    report = collect_hn_launch_readiness(
        config,
        runner=FakeRunner(active_units=_all_active_units()),
        json_getter=_json_getter_ready,
        text_getter=_text_getter_ready,
        now_epoch=NOW,
    )

    checks = {check.id: check for check in report.checks}
    compositor = checks["compositor_visual_surface"]
    assert compositor.status.value == "pass"
    assert compositor.evidence["layout_mode"] == "forcefield"
    assert compositor.evidence["sierpinski_ward_active"] is True


def test_hn_launch_soak_fails_if_any_sample_fails(tmp_path: Path) -> None:
    config = _ready_fixture(tmp_path)
    clock = {"mono": 0.0}

    def monotonic() -> float:
        return clock["mono"]

    def sleep(seconds: float) -> None:
        clock["mono"] += seconds

    def now() -> float:
        return NOW + clock["mono"]

    report = soak_hn_launch_readiness(
        duration_s=1.0,
        interval_s=1.0,
        config=config,
        runner=FlakyObsRunner(active_units=_all_active_units()),
        json_getter=_json_getter_ready,
        text_getter=_text_getter_ready,
        sleep=sleep,
        monotonic=monotonic,
        now=now,
    )

    assert report.ready is False
    checks = {check.id: check for check in report.checks}
    assert checks["thirty_minute_soak"].status.value == "fail"
    assert checks["thirty_minute_soak"].evidence["failed_samples"] == [
        {"sample_index": 1, "failures": ["obs_clean_feed"]}
    ]


def _ready_fixture(tmp_path: Path) -> ReadinessConfig:
    repo_root = tmp_path / "repo"
    shm_root = tmp_path / "shm"
    config = ReadinessConfig(
        repo_root=repo_root,
        shm_root=shm_root,
        rebuild_state_dir=tmp_path / "rebuild-state",
        logos_base_url="http://logos.local",
        weblog_rss_url="http://weblog.local/rss.xml",
        obs_loopback_device=tmp_path / "dev-video42",
    )
    _write_text(
        repo_root / "README.md",
        "Hapax Council\n\nagentgov support sponsor launch notes.\n",
        NOW,
    )
    _write_bytes(config.visual_root / "frame.jpg", b"jpg", NOW)
    _write_bytes(config.compositor_root / "snapshot.jpg", b"jpg", NOW)
    _write_bytes(config.compositor_root / "fx-snapshot.jpg", b"jpg", NOW)
    _write_json(
        config.compositor_root / "active_wards.json",
        {"ward_ids": ["programme_banner", "reverie", "sierpinski"], "published_t": NOW},
        NOW,
    )
    _write_json(config.compositor_root / "ward-properties.json", {"wards": {}}, NOW)
    _write_json(
        config.compositor_root / "current-layout-state.json",
        {
            "layout_name": "default",
            "layout_mode": "sierpinski",
            "active_ward_ids": ["programme_banner", "reverie", "sierpinski"],
            "published_t": NOW,
        },
        NOW,
    )
    _write_json(
        config.compositor_root / "active-segment.json",
        {
            "programme_id": "seg-1",
            "role": "tier_list",
            "topic": "Show HN launch",
            "segment_beats": ["hook", "close"],
            "current_beat_index": 1,
        },
        NOW,
    )
    _write_json(
        config.daimonion_root / "voice-output-witness.json",
        {
            "status": "playback_completed",
            "last_successful_playback": {"status": "completed"},
        },
        NOW,
    )
    _write_json(config.imagination_root / "current.json", {"preset": "reverie"}, NOW)
    _write_json(config.imagination_root / "health.json", {"status": "ok"}, NOW)
    _write_json(config.logos_root / "health.json", {"ready": True, "status": "ok"}, NOW)
    _write_text(config.compositor_root / "youtube-video-id.txt", "abc123\n", NOW)
    _write_text(config.compositor_root / "youtube-viewer-count.txt", "0\n", NOW)
    _write_json(config.compositor_root / "youtube-quota.json", {"quota_exhausted": False}, NOW)
    _write_bytes(config.obs_loopback_device, b"", NOW)
    return config


def _all_active_units() -> set[str]:
    return {
        "studio-compositor",
        "hapax-imagination",
        "hapax-daimonion",
        "hapax-reverie",
        "logos-api",
        "hapax-weblog-publish-public-event-producer",
        "hapax-youtube-video-id",
        "hapax-youtube-viewer-count",
        "hapax-obs-livestream",
    }


def _json_getter_ready(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    del timeout
    if url.endswith("/api/studio/egress/state"):
        return {
            "public_claim_allowed": True,
            "evidence": [
                {"source": "compositor", "status": "pass", "observed": {"active_cameras": 6}},
                {"source": "rtmp_output", "status": "pass"},
                {"source": "mediamtx_hls", "status": "pass"},
                {"source": "hls_playlist", "status": "pass"},
                {"source": "audio_floor", "status": "pass"},
                {"source": "privacy_floor", "status": "pass"},
            ],
        }
    if url.endswith("/api/health"):
        return {"overall_status": "healthy"}
    raise ValueError(url)


def _json_getter_private_egress(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    del timeout
    if url.endswith("/api/studio/egress/state"):
        return {
            "public_claim_allowed": False,
            "evidence": [
                {"source": "compositor", "status": "pass", "observed": {"active_cameras": 6}},
                {"source": "rtmp_output", "status": "fail"},
                {"source": "mediamtx_hls", "status": "fail"},
                {"source": "hls_playlist", "status": "fail"},
                {"source": "audio_floor", "status": "fail"},
                {"source": "privacy_floor", "status": "pass"},
            ],
        }
    if url.endswith("/api/health"):
        return {"overall_status": "healthy"}
    raise ValueError(url)


def _text_getter_ready(url: str, *, timeout: float = 5.0) -> str:
    del url, timeout
    return """<?xml version="1.0"?>
    <rss><channel><item><title>Show HN readiness</title><link>https://example.test/post</link></item></channel></rss>
    """


def _write_text(path: Path, value: str, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _write_json(path: Path, value: Any, mtime: float) -> None:
    _write_text(path, json.dumps(value), mtime)


def _write_bytes(path: Path, value: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    os.utime(path, (mtime, mtime))


def _write_rebuild_outcome(
    config: ReadinessConfig,
    *,
    sha_key: str,
    current_sha: str,
    outcome: str,
    timestamp: str,
) -> None:
    payload = {
        "schema_version": 1,
        "timestamp": timestamp,
        "sha_key": sha_key,
        "service": f"hapax-{sha_key}.service",
        "current_sha": current_sha,
        "last_sha": "none",
        "outcome": outcome,
    }
    _write_text(
        config.rebuild_state_dir / f"last-{sha_key}-outcome.json",
        json.dumps(payload),
        NOW,
    )
