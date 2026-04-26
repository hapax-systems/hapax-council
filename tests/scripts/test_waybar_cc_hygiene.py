"""Smoke tests for scripts/waybar/hapax-waybar-cc-hygiene.

Validates the bash widget that renders the cc-hygiene state spine
into a 4-dot waybar payload. The widget is read-only (no click
handlers, no IPC) so the contract is purely the JSON payload shape.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WIDGET = REPO_ROOT / "scripts" / "waybar" / "hapax-waybar-cc-hygiene"


def _run(state_path: Path | None) -> dict:
    env = os.environ.copy()
    if state_path is not None:
        env["HAPAX_CC_HYGIENE_STATE"] = str(state_path)
    else:
        env["HAPAX_CC_HYGIENE_STATE"] = "/nonexistent/path"
    result = subprocess.run(
        ["bash", str(WIDGET)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _write_state(tmp: Path, state: dict) -> Path:
    p = tmp / "state.json"
    p.write_text(json.dumps(state))
    return p


def test_missing_state_emits_stale() -> None:
    payload = _run(None)
    assert payload["class"] == "stale"
    assert "cc --" in payload["text"]


def test_renders_four_dots_with_in_progress() -> None:
    with tempfile.TemporaryDirectory() as d:
        state_path = _write_state(
            Path(d),
            {
                "schema_version": 1,
                "sweep_timestamp": "2026-04-26T12:34:00Z",
                "sweep_duration_ms": 50,
                "killswitch_active": False,
                "sessions": [
                    {
                        "role": "alpha",
                        "current_claim": "task-a",
                        "in_progress_count": 1,
                        "relay_updated": None,
                    },
                    {
                        "role": "beta",
                        "current_claim": None,
                        "in_progress_count": 0,
                        "relay_updated": None,
                    },
                ],
                "check_summaries": [],
                "events": [],
            },
        )
        payload = _run(state_path)
        # alpha=●, beta=○, delta missing → ○, epsilon missing → ○
        assert payload["text"] == "cc ●○○○ 0f"
        assert payload["class"] == ""


def test_fired_checks_count_and_class() -> None:
    with tempfile.TemporaryDirectory() as d:
        state_path = _write_state(
            Path(d),
            {
                "schema_version": 1,
                "sweep_timestamp": "2026-04-26T12:34:00Z",
                "sweep_duration_ms": 50,
                "killswitch_active": False,
                "sessions": [],
                "check_summaries": [
                    {"check_id": "stale_in_progress", "fired": 3},
                    {"check_id": "ghost_claimed", "fired": 0},
                    {"check_id": "duplicate_claim", "fired": 1},
                ],
                "events": [],
            },
        )
        payload = _run(state_path)
        assert "2f" in payload["text"]  # 2 distinct check_ids fired
        assert payload["class"] == "degraded"


def test_killswitch_marker() -> None:
    with tempfile.TemporaryDirectory() as d:
        state_path = _write_state(
            Path(d),
            {
                "schema_version": 1,
                "sweep_timestamp": "2026-04-26T12:34:00Z",
                "sweep_duration_ms": 50,
                "killswitch_active": True,
                "sessions": [],
                "check_summaries": [],
                "events": [],
            },
        )
        payload = _run(state_path)
        assert "KS" in payload["text"]
        assert payload["class"] == "degraded"


def test_claimed_but_no_in_progress_dot() -> None:
    with tempfile.TemporaryDirectory() as d:
        state_path = _write_state(
            Path(d),
            {
                "schema_version": 1,
                "sweep_timestamp": "2026-04-26T12:34:00Z",
                "sweep_duration_ms": 50,
                "killswitch_active": False,
                "sessions": [
                    {
                        "role": "delta",
                        "current_claim": "claimed-not-yet-edited",
                        "in_progress_count": 0,
                        "relay_updated": None,
                    },
                ],
                "check_summaries": [],
                "events": [],
            },
        )
        payload = _run(state_path)
        # delta should render ◐ (claimed but not in_progress)
        assert "◐" in payload["text"]
