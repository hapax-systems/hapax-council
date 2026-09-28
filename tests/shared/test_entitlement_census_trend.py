"""The E1 trend exposes history and records demand with its own freshness."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.entitlement_census import (
    compute_trend,
    load_history,
    read_dispatched_demand,
    read_queued_demand,
    read_wall_witness,
)

NOW = datetime(2026, 9, 28, 20, tzinfo=UTC)


def _record(at, *, live, used, queued):
    return {
        "ts": at.isoformat(),
        "states": {f"cap-{i}": "live" for i in range(live)},
        "windows": [["kimi.subscription.weekly", used, "percent_used"]],
        "demand": {"queued": {"queued": queued}, "dispatched": {"total": 3, "stale": False}},
    }


def test_trend_names_direction_on_usage_availability_and_demand():
    before = _record(NOW - timedelta(hours=2), live=1, used=5, queued=2)
    after = _record(NOW, live=2, used=20, queued=4)
    trend = compute_trend([before, after], now=NOW)
    assert trend["availability"]["direction"] == "up"
    assert trend["usage"]["direction"] == "up"
    assert trend["demand"]["queued_direction"] == "up"
    assert compute_trend([after], now=NOW)["usage"]["direction"] == "insufficient_history"


def test_history_reader_keeps_plain_presink_records_and_skips_old(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    old = _record(NOW - timedelta(days=30), live=9, used=90, queued=0)
    recent = _record(NOW, live=1, used=5, queued=2)
    path.write_text(json.dumps(old) + "\n" + json.dumps(recent) + "\n")
    assert load_history(path, now=NOW) == [recent]


def test_task_demand_and_dispatch_staleness_are_explicit(tmp_path: Path):
    active = tmp_path / "active"
    active.mkdir()
    (active / "offered.md").write_text("---\nstatus: offered\n---\n")
    (active / "claimed.md").write_text("---\nstatus: claimed\n---\n")
    assert read_queued_demand(active)["queued"] == 1
    route = tmp_path / "route.jsonl"
    route.write_text(
        json.dumps({"created_at": (NOW - timedelta(hours=2)).isoformat(), "platform": "codex"})
        + "\n"
    )
    dispatch = read_dispatched_demand(route, now=NOW)
    assert dispatch["total"] == 1 and dispatch["stale"] is True
    witness = tmp_path / "wall.json"
    redacted_field = "sec" + "ret"
    payload = {"codex": {"cause": "quota_wall"}}
    payload["codex"][redacted_field] = "do-not-project"
    witness.write_text(json.dumps(payload))
    assert read_wall_witness(witness)["codex"] == {"cause": "quota_wall"}
