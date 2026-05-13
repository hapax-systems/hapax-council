from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path

from tests.operator_current_state.test_collector import NOW, _mk_required, _paths


def test_cli_one_shot_writes_private_outputs(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    state_path = tmp_path / "operator-state.json"
    page_path = tmp_path / "operator-now.md"

    result = subprocess.run(
        [
            "python",
            "-m",
            "agents.operator_current_state",
            "--once",
            "--state-path",
            str(state_path),
            "--page-path",
            str(page_path),
            "--planning-feed",
            str(paths.planning_feed),
            "--requests-dir",
            str(paths.requests_dir),
            "--cc-tasks-dir",
            str(paths.cc_tasks_dir),
            "--claims-dir",
            str(paths.claims_dir),
            "--relay-dir",
            str(paths.relay_dir),
            "--awareness-state",
            str(paths.awareness_state),
            "--operator-now-seed",
            str(paths.operator_now_seed),
            "--cc-operator-blocking",
            str(paths.cc_operator_blocking),
            "--hn-receipts-dir",
            str(paths.hn_receipts_dir),
            "--now",
            NOW.isoformat(),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    loaded = json.loads(state_path.read_text(encoding="utf-8"))
    assert loaded["privacy_filter"]["public_projection_authorized"] is False
    assert page_path.exists()


def test_verified_no_action_not_emitted_when_planning_feed_stale(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    paths.planning_feed.write_text(
        json.dumps(
            {
                "generated_at": (NOW - timedelta(minutes=30)).isoformat(),
                "attention_required": [],
                "requests": [],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python",
            "-m",
            "agents.operator_current_state",
            "--state-path",
            str(tmp_path / "state.json"),
            "--page-path",
            str(tmp_path / "operator-now.md"),
            "--planning-feed",
            str(paths.planning_feed),
            "--requests-dir",
            str(paths.requests_dir),
            "--cc-tasks-dir",
            str(paths.cc_tasks_dir),
            "--claims-dir",
            str(paths.claims_dir),
            "--relay-dir",
            str(paths.relay_dir),
            "--now",
            NOW.isoformat(),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    rendered = (tmp_path / "operator-now.md").read_text(encoding="utf-8")
    assert "No verified operator action" not in rendered
    assert "Unknown because required source freshness failed." in rendered
