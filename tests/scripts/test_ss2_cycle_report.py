"""Tests for scripts/ss2-cycle-report.py."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.chronicle import ChronicleEvent, record
from shared.operator_quality_feedback import (
    append_operator_quality_rating,
    build_operator_quality_rating,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ss2-cycle-report.py"


def _write_event(path: Path) -> None:
    record(
        ChronicleEvent(
            ts=120.0,
            trace_id="1" * 32,
            span_id="2" * 16,
            parent_span_id=None,
            source="self_authored_narrative",
            event_type="narrative.emitted",
            payload={
                "narrative": "Hapax grounded the emission in the cycle report fixture.",
                "programme_id": "prog-cli",
                "speech_event_id": "speech-cli",
                "grounding_provenance": ["fixture:vault"],
            },
            event_id="ev-cli",
        ),
        path=path,
    )


def _write_axis_ratings(path: Path) -> None:
    occurred_at = datetime.fromtimestamp(100.0, UTC) + timedelta(seconds=1)
    for axis in (
        "substantive",
        "grounded",
        "stimmung_coherence",
        "programme_respecting",
        "listenable",
    ):
        append_operator_quality_rating(
            build_operator_quality_rating(
                rating=5,
                rating_axis=axis,
                occurred_at=occurred_at,
                programme_id="prog-cli",
            ),
            path=path,
        )


def test_script_outputs_json_report_without_text(tmp_path: Path) -> None:
    chronicle = tmp_path / "events.jsonl"
    ratings = tmp_path / "ratings.jsonl"
    _write_event(chronicle)
    _write_axis_ratings(ratings)

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--cycle-id",
            "cycle-cli",
            "--since",
            "1970-01-01T00:01:40+00:00",
            "--until",
            "1970-01-01T00:03:20+00:00",
            "--sample-size",
            "1",
            "--chronicle-path",
            str(chronicle),
            "--ratings-path",
            str(ratings),
            "--programme-id",
            "prog-cli",
            "--format",
            "json",
            "--no-text",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["cycle_id"] == "cycle-cli"
    assert payload["verdict"] == "hold"
    assert payload["samples"][0]["narrative_text"] is None


def test_script_requires_since_or_hours(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--chronicle-path",
            str(tmp_path / "events.jsonl"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "--since is required unless --hours is supplied" in proc.stderr
