from __future__ import annotations

import json
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


def _run(prep_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--prep-dir", str(prep_dir), "--date", DAY, "--now", NOW, "--json", *extra],
        text=True,
        capture_output=True,
        check=False,
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


def test_emit_health_fails_missing_status(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.returncode == 1
    payload = _json(result)
    assert payload["reason"] == "missing_status"
    assert payload["status_path"].endswith(f"{DAY}/prep-status.json")


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
            "updated_at": "2026-06-18T06:10:00Z",
        },
    )

    result = _run(tmp_path, "--max-in-progress-age-s", "3600")

    assert result.returncode == 0, result.stderr
    payload = _json(result)
    assert payload["reason"] == "run_in_progress"
    assert payload["age_s"] == 1200.0


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


def test_emit_health_fails_unreadable_status(tmp_path: Path) -> None:
    status = tmp_path / DAY / "prep-status.json"
    status.parent.mkdir(parents=True)
    status.write_text("{not json", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert _json(result)["reason"] == "unreadable_status"


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
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status_path"].endswith(f"{DAY}/prep-status.json")
