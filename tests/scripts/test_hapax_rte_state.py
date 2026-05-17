"""Tests for hapax-rte-state warning fields."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-rte-state"


def _write_tick(relay: Path, status: str = "green") -> None:
    relay.mkdir(parents=True, exist_ok=True)
    tick = relay / "rte-tick-20260509T210000Z.yaml"
    tick.write_text(
        f"""rte: test-rte
summary: fixture tick
team_load:
  status: {status}
""",
        encoding="utf-8",
    )
    os.utime(tick, None)


def _write_planning_feed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-17T08:00:00Z",
                "dispatch": {
                    "route_metadata_summary": {
                        "explicit": 0,
                        "derived": 0,
                        "hold": 1,
                        "malformed": 0,
                    },
                    "planning_queue": [
                        {
                            "item_type": "task",
                            "task_id": "held-route-task",
                            "route_metadata": {
                                "status": "hold",
                                "hold_reasons": ["missing_quality_floor"],
                            },
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def _run(
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    relay = tmp_path / "relay"
    feed = tmp_path / "planning-feed-state.json"
    env = {
        **os.environ,
        "HAPAX_RELAY_DIR": str(relay),
        "HAPAX_PLANNING_FEED_STATE": str(feed),
        "HAPAX_CAPACITY_ROUTING_NOW": "2026-05-17T08:00:00Z",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def test_json_includes_capacity_routing_warnings_without_changing_green_gate(
    tmp_path: Path,
) -> None:
    _write_tick(tmp_path / "relay", "green")
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run(tmp_path, "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    capacity = payload["capacity_routing"]
    states = {state["state"] for state in capacity["non_green_states"]}
    assert payload["status"] == "green"
    assert capacity["observe_only"] is True
    assert capacity["route_metadata_summary"]["hold"] == 1
    assert "route_metadata_hold" in states
    assert "support_artifacts_waiting_for_review" not in states

    gate = _run(tmp_path, "--gate")
    assert gate.returncode == 0


def test_json_includes_rollback_receipt_warning_when_ledger_supplied(tmp_path: Path) -> None:
    _write_tick(tmp_path / "relay", "green")
    _write_planning_feed(tmp_path / "planning-feed-state.json")
    route_ledger = tmp_path / "route-decisions.jsonl"
    capacity_now = "2026-05-09T21:00:00Z"
    route_ledger.write_text(
        json.dumps(
            {
                "decision_id": "rd-20260509T210000Z-rollback-test-aaaaaaaaaaaa",
                "created_at": capacity_now,
                "task_id": "rollback-test",
                "route_id": "codex.headless.full",
                "route_policy_green": False,
                "clog_state": "compatibility_degraded",
                "compatibility_mode": "rollback_full_profile",
                "degraded_state": "compatibility_rollback",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        "--json",
        extra_env={
            "HAPAX_ROUTE_DECISION_LEDGER": str(route_ledger),
            "HAPAX_CAPACITY_ROUTING_NOW": capacity_now,
        },
    )

    assert result.returncode == 0
    capacity = json.loads(result.stdout)["capacity_routing"]
    states = {state["state"] for state in capacity["non_green_states"]}
    assert capacity["rollback_compatibility_count"] == 1
    assert "route_policy_compatibility_degraded:rollback_full_profile" in states


def test_red_rte_gate_still_returns_red_exit_with_warning_payload(tmp_path: Path) -> None:
    _write_tick(tmp_path / "relay", "red")
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run(tmp_path, "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "red"
    assert payload["capacity_routing"]["warning_count"] > 0
