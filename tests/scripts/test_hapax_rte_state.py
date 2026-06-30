"""Tests for hapax-rte-state warning fields."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-rte-state"
ASSIGN_RTE = REPO_ROOT / "scripts" / "assign-rte"
CAPACITY_ROUTING_NOW = "2026-05-17T08:00:00Z"


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
                "generated_at": CAPACITY_ROUTING_NOW,
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


def _write_assignment(
    relay: Path,
    *,
    rte: str = "beta",
    originator: str = "alpha",
    assigned_at: str = "2026-05-17T07:00:00Z",
    expires_at: str = "2026-05-18T07:00:00Z",
    protocol_exception: bool = False,
) -> None:
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "rte-assignment.yaml").write_text(
        f"""rte: {rte}
originator: {originator}
assigned_at: '{assigned_at}'
expires_at: '{expires_at}'
algorithm: test
protocol_exception: {str(protocol_exception).lower()}
""",
        encoding="utf-8",
    )


def _write_lane(relay: Path, lane: str, updated: str = CAPACITY_ROUTING_NOW) -> None:
    relay.mkdir(parents=True, exist_ok=True)
    (relay / f"{lane}.yaml").write_text(
        f"""session: {lane}
updated: '{updated}'
session_status: active
""",
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
        "HAPAX_CAPACITY_ROUTING_NOW": CAPACITY_ROUTING_NOW,
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


def _run_assign_rte(
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    relay = tmp_path / "relay"
    env = {
        **os.environ,
        "HAPAX_RELAY_DIR": str(relay),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(ASSIGN_RTE), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _run_without_fixed_clock(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    relay = tmp_path / "relay"
    feed = tmp_path / "planning-feed-state.json"
    env = {
        **os.environ,
        "HAPAX_RELAY_DIR": str(relay),
        "HAPAX_PLANNING_FEED_STATE": str(feed),
    }
    env.pop("HAPAX_RTE_NOW", None)
    env.pop("HAPAX_CAPACITY_ROUTING_NOW", None)
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
    route_ledger.write_text(
        json.dumps(
            {
                "decision_id": "rd-20260509T210000Z-rollback-test-aaaaaaaaaaaa",
                "created_at": CAPACITY_ROUTING_NOW,
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
        extra_env={"HAPAX_ROUTE_DECISION_LEDGER": str(route_ledger)},
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


def test_active_assignment_without_tick_is_reported_but_state_stays_unknown(
    tmp_path: Path,
) -> None:
    _write_assignment(tmp_path / "relay")
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run(tmp_path, "--json")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "unknown"
    assert payload["tick_fresh"] is False
    assert payload["assignment"]["status"] == "active"
    assert payload["assignment"]["rte"] == "beta"


def test_expired_assignment_fail_closes_even_with_fresh_green_tick(tmp_path: Path) -> None:
    _write_tick(tmp_path / "relay", "green")
    _write_assignment(
        tmp_path / "relay",
        assigned_at="2026-05-15T07:00:00Z",
        expires_at="2026-05-16T07:00:00Z",
    )
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run(tmp_path, "--json")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "unknown"
    assert payload["assignment"]["status"] == "expired"
    assert "RTE assignment expired" in payload["reasons"][0]


def test_malformed_assignment_timestamp_fail_closes(tmp_path: Path) -> None:
    _write_tick(tmp_path / "relay", "green")
    _write_assignment(tmp_path / "relay", expires_at="not-a-date")
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run(tmp_path, "--json")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "unknown"
    assert payload["assignment"]["status"] == "invalid"
    assert "invalid expires_at" in payload["reasons"][0]


def test_restricted_assignment_requires_protocol_exception(tmp_path: Path) -> None:
    _write_tick(tmp_path / "relay", "green")
    _write_assignment(tmp_path / "relay", rte="gemini-1")
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run(tmp_path, "--json")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["assignment"]["status"] == "invalid"
    assert "restricted RTE lane requires protocol_exception" in payload["reasons"][0]


def test_protocol_exception_restricted_assignment_can_be_active(tmp_path: Path) -> None:
    _write_tick(tmp_path / "relay", "green")
    _write_assignment(tmp_path / "relay", rte="gemini-1", protocol_exception=True)
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run(tmp_path, "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "green"
    assert payload["assignment"]["status"] == "active"
    assert payload["assignment"]["protocol_exception"] is True


def test_assignment_expiry_fallback_clock_uses_runtime_utc(tmp_path: Path) -> None:
    _write_tick(tmp_path / "relay", "green")
    _write_assignment(tmp_path / "relay", expires_at="2099-05-18T07:00:00Z")
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run_without_fixed_clock(tmp_path, "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "green"
    assert payload["assignment"]["status"] == "active"


def test_assign_rte_auto_writes_assignment_and_bootstrap_tick(tmp_path: Path) -> None:
    relay = tmp_path / "relay"
    _write_lane(relay, "alpha")
    _write_lane(relay, "beta")
    _write_planning_feed(tmp_path / "planning-feed-state.json")

    result = _run_assign_rte(
        tmp_path,
        "--auto",
        "--originator",
        "alpha",
        "--json",
        "--write-tick",
        extra_env={"HAPAX_RTE_STALE_HOURS": "9000"},
    )

    assert result.returncode == 0
    assigned = json.loads(result.stdout)
    assert assigned["rte"] == "beta"
    assert Path(assigned["assignment"]).is_file()
    assert Path(assigned["tick"]).is_file()

    state = _run(tmp_path, "--json")
    assert state.returncode == 0
    payload = json.loads(state.stdout)
    assert payload["status"] == "yellow"
    assert payload["tick_fresh"] is True
    assert payload["rte"] == "beta"
    assert payload["assignment"]["status"] == "active"


def test_assign_rte_auto_returns_distinct_failure_when_no_candidate_exists(
    tmp_path: Path,
) -> None:
    result = _run_assign_rte(tmp_path, "--auto", "--originator", "alpha")

    assert result.returncode == 5
    assert "no eligible RTE candidate found" in result.stderr
    assert not (tmp_path / "relay" / "rte-assignment.yaml").exists()


def test_assign_rte_refuses_originator_as_rte(tmp_path: Path) -> None:
    result = _run_assign_rte(tmp_path, "--rte", "alpha", "--originator", "alpha")

    assert result.returncode == 4
    assert "RTE cannot be the originator" in result.stderr
    assert not (tmp_path / "relay" / "rte-assignment.yaml").exists()


def test_assign_rte_refuses_restricted_explicit_lane_without_exception(tmp_path: Path) -> None:
    result = _run_assign_rte(tmp_path, "--rte", "antigrav", "--originator", "alpha")

    assert result.returncode == 4
    assert "protocol-exception" in result.stderr
    assert not (tmp_path / "relay" / "rte-assignment.yaml").exists()


def test_assign_rte_show_and_clear_modes(tmp_path: Path) -> None:
    relay = tmp_path / "relay"
    _write_assignment(relay, expires_at="2099-05-18T07:00:00Z")

    show = _run_assign_rte(tmp_path, "--show", "--json")
    assert show.returncode == 0
    shown = json.loads(show.stdout)
    assert shown["status"] == "active"
    assert shown["rte"] == "beta"

    clear = _run_assign_rte(tmp_path, "--clear")
    assert clear.returncode == 0
    assert not (relay / "rte-assignment.yaml").exists()

    missing = _run_assign_rte(tmp_path, "--show", "--json")
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["status"] == "missing"


def test_assign_rte_show_expired_returns_distinct_exit(tmp_path: Path) -> None:
    _write_assignment(tmp_path / "relay", expires_at="2000-05-18T07:00:00Z")

    result = _run_assign_rte(tmp_path, "--show", "--json")

    assert result.returncode == 6
    assert json.loads(result.stdout)["status"] == "expired"


def test_assign_rte_rejects_invalid_tick_status_at_cli_boundary(tmp_path: Path) -> None:
    result = _run_assign_rte(
        tmp_path,
        "--rte",
        "beta",
        "--originator",
        "alpha",
        "--write-tick",
        "--tick-status",
        "unknown",
    )

    assert result.returncode == 2
    assert "invalid choice" in result.stderr
