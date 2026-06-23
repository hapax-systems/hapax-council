from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-segment-prep-emit-health"
DAY = "2026-06-18"
NOW = "2026-06-18T06:30:00Z"


def _write_status(prep_dir: Path, payload: dict[str, object], *, day: str = DAY) -> Path:
    path = prep_dir / day / "prep-status.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(
    prep_dir: Path, *extra: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HAPAX_SEGMENT_PREP_AUTHORITY_MODE"] = "open"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(SCRIPT), "--prep-dir", str(prep_dir), "--date", DAY, "--now", NOW, "--json", *extra],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)


def test_emit_health_passes_when_run_saved_segments(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed",
            "phase": "completed",
            "saved_count": 1,
            "run_saved_programmes": ["segment-01.json"],
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = _json(result)
    assert payload["ok"] is True
    assert payload["reason"] == "emitted_segments"


def test_emit_health_fails_completed_no_segments_even_with_old_release_pool(
    tmp_path: Path,
) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed_no_segments_saved",
            "phase": "completed_no_segments_saved",
            "saved_count": 0,
            "run_saved_programmes": [],
            "selected_release": {"ok": True, "selected_count": 3},
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    payload = _json(result)
    assert payload["ok"] is False
    assert payload["reason"] == "zero_emit"
    assert payload["selected_release_ok"] is True
    assert payload["selected_release_count"] == 3


def test_emit_health_fails_completed_no_programmes(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed_no_programmes",
            "phase": "completed_no_programmes",
            "saved_count": 0,
            "run_saved_programmes": [],
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "zero_emit"


def test_emit_health_passes_honest_no_eligible_pool(tmp_path: Path) -> None:
    # The producer ran end-to-end; the deterministic release/eligibility gate was
    # simply not cleared today (no_eligible_pool). This is the documented
    # SUCCESSFUL no-release outcome of select_release_pool and must NOT trip the
    # systemd OnFailure -> P0 path.
    _write_status(
        tmp_path,
        {
            "status": "completed_no_segments_saved",
            "phase": "completed_no_segments_saved",
            "saved_count": 0,
            "run_saved_programmes": [],
            "selected_release": {
                "ok": False,
                "reason": "no_eligible_pool",
                "selected_count": 0,
                "eligible_artifact_count": 0,
            },
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = _json(result)
    assert payload["ok"] is True
    assert payload["reason"] == "honest_no_release"
    assert payload["selected_release_ok"] is False
    assert payload["selected_release_reason"] == "no_eligible_pool"
    assert payload["next_action"] is None


def test_emit_health_passes_honest_review_not_ok(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed_no_segments_saved",
            "phase": "completed_no_segments_saved",
            "saved_count": 0,
            "run_saved_programmes": [],
            "selected_release": {"ok": False, "reason": "review_not_ok", "selected_count": 0},
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _json(result)["reason"] == "honest_no_release"


def test_emit_health_passes_honest_authority_gate_no_release(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed_no_segments_saved",
            "phase": "completed_no_segments_saved",
            "saved_count": 0,
            "run_saved_programmes": [],
            "selected_release": {
                "ok": False,
                "reason": "segment_prep_authority_gate",
                "selected_count": 0,
            },
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _json(result)["reason"] == "honest_no_release"


def test_emit_health_fails_zero_emit_without_selected_release(tmp_path: Path) -> None:
    # No selected_release verdict at all -> we cannot prove the run reached the
    # release gate honestly, so fail closed.
    _write_status(
        tmp_path,
        {
            "status": "completed_no_segments_saved",
            "phase": "completed_no_segments_saved",
            "saved_count": 0,
            "run_saved_programmes": [],
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "zero_emit"


def test_emit_health_fails_zero_emit_when_selected_release_ok_missing(
    tmp_path: Path,
) -> None:
    # A recognized reason is not sufficient by itself. The producer must also
    # explicitly record an unsuccessful selected-release verdict; missing verdict
    # fields fail closed.
    _write_status(
        tmp_path,
        {
            "status": "completed_no_segments_saved",
            "phase": "completed_no_segments_saved",
            "saved_count": 0,
            "run_saved_programmes": [],
            "selected_release": {"reason": "no_eligible_pool", "selected_count": 0},
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "zero_emit"


def test_emit_health_fails_publication_blocked_no_release(tmp_path: Path) -> None:
    # Publication-blocked means a selected release existed but could not be
    # republished/load-verified consistently, which is still a source/runtime
    # anomaly for this heartbeat and must fail closed.
    _write_status(
        tmp_path,
        {
            "status": "completed_no_segments_saved",
            "phase": "completed_no_segments_saved",
            "saved_count": 0,
            "run_saved_programmes": [],
            "selected_release": {
                "ok": False,
                "reason": "selected_release_publication_blocked",
            },
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "zero_emit"


def test_emit_health_fails_zero_emit_anomalous_selected_release_reason(
    tmp_path: Path,
) -> None:
    # A selected_release reason that is NOT a recognised honest no-release reason
    # (e.g. an internal anomaly) must still fail closed rather than be silenced.
    _write_status(
        tmp_path,
        {
            "status": "completed_no_segments_saved",
            "phase": "completed_no_segments_saved",
            "saved_count": 0,
            "run_saved_programmes": [],
            "selected_release": {"ok": False, "reason": "internal_writer_crash"},
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "zero_emit"


def test_emit_health_fails_missing_status(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.returncode == 1
    payload = _json(result)
    assert payload["reason"] == "missing_status"
    assert payload["status_path"].endswith(f"{DAY}/prep-status.json")
    assert "producer" in str(payload["next_action"])


def test_emit_health_allows_missing_status_when_authority_paused(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        extra_env={
            "HAPAX_SEGMENT_PREP_AUTHORITY_MODE": "paused",
            "HAPAX_SEGMENT_PREP_AUTHORITY_REASON": "operator hold",
        },
    )

    assert result.returncode == 0, result.stderr
    payload = _json(result)
    assert payload["reason"] == "paused_authority"
    assert payload["status"] == "paused"
    assert payload["phase"] == "segment_prep_authority_paused"
    assert payload["next_action"] is None


def test_emit_health_fails_missing_status_when_pause_state_unreadable(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        extra_env={"HAPAX_SEGMENT_PREP_AUTHORITY_MODE": "not-a-real-mode"},
    )

    assert result.returncode == 1
    payload = _json(result)
    assert payload["reason"] == "pause_state_unreadable"


def test_emit_health_allows_deliberate_pause(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "paused",
            "phase": "segment_prep_authority_paused",
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _json(result)["reason"] == "paused_authority"


def test_emit_health_allows_fresh_in_progress_run(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "in_progress",
            "phase": "compose_segment_in_progress",
            "started_at": "2026-06-18T06:00:00Z",
            "updated_at": "2026-06-18T06:10:00Z",
            "pid": os.getpid(),
        },
    )

    result = _run(tmp_path, "--max-in-progress-age-s", "3600")

    assert result.returncode == 0, result.stderr
    payload = _json(result)
    assert payload["reason"] == "run_in_progress"
    assert payload["age_s"] == 1200.0
    assert payload["run_age_s"] == 1800.0
    assert payload["process_alive"] is True


def test_emit_health_fails_stale_in_progress_run(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "in_progress",
            "phase": "compose_segment_in_progress",
            "updated_at": "2026-06-18T04:00:00Z",
        },
    )

    result = _run(tmp_path, "--max-in-progress-age-s", "3600")

    assert result.returncode == 1
    payload = _json(result)
    assert payload["reason"] == "stale_in_progress"
    assert payload["age_s"] == 9000.0


def test_emit_health_fails_production_timeout_boundary(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "in_progress",
            "phase": "compose_segment_in_progress",
            "started_at": "2026-06-18T04:05:00Z",
            "updated_at": "2026-06-18T06:04:00Z",
            "pid": os.getpid(),
        },
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--prep-dir",
            str(tmp_path),
            "--date",
            DAY,
            "--now",
            "2026-06-18T06:20:00Z",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HAPAX_SEGMENT_PREP_AUTHORITY_MODE": "open"},
    )

    assert result.returncode == 1
    payload = _json(result)
    assert payload["reason"] == "timed_out_in_progress"
    assert payload["age_s"] == 960.0
    assert payload["run_age_s"] == 8100.0
    assert payload["process_alive"] is True


def test_emit_health_fails_dead_in_progress_process(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "in_progress",
            "phase": "compose_segment_in_progress",
            "started_at": "2026-06-18T06:00:00Z",
            "updated_at": "2026-06-18T06:10:00Z",
            "pid": 999999999,
        },
    )

    result = _run(tmp_path, "--max-in-progress-age-s", "3600")

    assert result.returncode == 1
    payload = _json(result)
    assert payload["reason"] == "dead_in_progress_process"
    assert payload["age_s"] == 1200.0
    assert payload["run_age_s"] == 1800.0
    assert payload["process_alive"] is False


def test_emit_health_fails_unreadable_status(tmp_path: Path) -> None:
    status = tmp_path / DAY / "prep-status.json"
    status.parent.mkdir(parents=True)
    status.write_text("{not json", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "unreadable_status"


def test_emit_health_fails_invalid_status_payload(tmp_path: Path) -> None:
    status = tmp_path / DAY / "prep-status.json"
    status.parent.mkdir(parents=True)
    status.write_text("[]", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "invalid_status_payload"


def test_emit_health_fails_in_progress_without_updated_at(tmp_path: Path) -> None:
    _write_status(tmp_path, {"status": "in_progress", "phase": "compose_segment_in_progress"})

    result = _run(tmp_path, "--max-in-progress-age-s", "3600")

    assert result.returncode == 1
    assert _json(result)["reason"] == "in_progress_missing_updated_at"


def test_emit_health_fails_blocked_status(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "blocked",
            "phase": "source_selection_blocked",
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "blocked_no_emit"


def test_emit_health_fails_failed_status(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "compose_failed",
            "phase": "compose_segment_failed",
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "prep_failed"


def test_emit_health_fails_completed_zero_emit(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed",
            "phase": "completed",
            "saved_count": 0,
            "run_saved_programmes": [],
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "completed_zero_emit"


def test_emit_health_fails_unknown_zero_emit_status(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed_unknown",
            "phase": "completed_unknown",
            "saved_count": 0,
            "run_saved_programmes": [],
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "unknown_zero_emit_status"


def test_emit_health_default_date_uses_utc_now(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed",
            "phase": "completed",
            "saved_count": 1,
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = subprocess.run(
        [str(SCRIPT), "--prep-dir", str(tmp_path), "--now", NOW, "--json"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HAPAX_SEGMENT_PREP_AUTHORITY_MODE": "open"},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status_path"].endswith(f"{DAY}/prep-status.json")


def test_emit_health_default_prep_dir_uses_environment(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        {
            "status": "completed",
            "phase": "completed",
            "saved_count": 1,
            "updated_at": "2026-06-18T04:20:00Z",
        },
    )

    result = subprocess.run(
        [str(SCRIPT), "--date", DAY, "--now", NOW, "--json"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_SEGMENT_PREP_AUTHORITY_MODE": "open",
            "HAPAX_SEGMENT_PREP_DIR": str(tmp_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status_path"].startswith(str(tmp_path))


def test_emit_health_human_failure_output_includes_next_action(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(SCRIPT), "--prep-dir", str(tmp_path), "--date", DAY, "--now", NOW],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HAPAX_SEGMENT_PREP_AUTHORITY_MODE": "open"},
    )

    assert result.returncode == 1
    assert "next_action=" in result.stdout
