"""Capacity-gap v1 contracts. These are stamped before the producer exists."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import capacity_gap_signal as gap

NOW = datetime(2026, 9, 28, 20, 0, tzinfo=UTC)


def test_observer_importer_retains_window_and_rejects_stale(tmp_path: Path) -> None:
    source = tmp_path / "capacity-observations.jsonl"
    source.write_text(
        '{"ts":"2026-09-28T19:20:00Z","fleet_memory":{"gx10-b941":{"total_mb":124546,"avail_mb":15800}},"gpus":["GPU, 24576 MiB, 0 MiB"]}\n'
        '{"ts":"2026-09-28T19:40:00Z","fleet_memory":{"gx10-b941":{"total_mb":124546,"avail_mb":15800}},"gpus":["GPU, 24576 MiB, 0 MiB"]}\n'
    )
    observations = gap.load_observations(source, NOW)
    assert len(observations) == 2
    assert observations[-1]["fleet_memory"]["gx10-b941"]["avail_mb"] == 15800
    assert gap.observer_stale(observations, NOW) is False
    assert gap.observer_stale(observations, NOW + timedelta(minutes=45)) is True


def test_tp_member_not_declared_idle_or_lost_and_idle_uses_request_window() -> None:
    samples = [
        {"ts": "2026-09-28T19:20:00Z", "gpus": ["GPU, 24576 MiB, 0 MiB"]},
        {"ts": "2026-09-28T19:40:00Z", "gpus": ["GPU, 24576 MiB, 0 MiB"]},
    ]
    members = {"spark-01df:8000": {"spark-01df", "gx10-b941"}}
    endpoints = {
        "spark-01df:8000": {
            "answering": True,
            "models": ["qwen3.8-flash-next"],
            "requests": [(NOW - timedelta(minutes=30), 10), (NOW, 10)],
        }
    }
    states = gap.classify_local(samples, members, endpoints, NOW)
    assert states["spark-01df:8000"] == "idle"
    assert "gx10-b941" not in states
    demand = gap.waiting_demand([{"task_id": "waiting", "status": "offered"}], set())
    assert gap.judge_gaps(states, demand, set()) == {
        "IDLE_WITH_DEMAND:spark-01df:8000:waiting=1:fit=unmeasured"
    }
    endpoints["spark-01df:8000"]["requests"][-1] = (NOW, 11)
    assert gap.classify_local(samples, members, endpoints, NOW)["spark-01df:8000"] == "busy"
    endpoints["spark-01df:8000"]["requests"] = []
    assert gap.classify_local(samples, members, endpoints, NOW)["spark-01df:8000"] == "unknown"


def test_fugu_wall_keeps_assigned_rows_in_demand() -> None:
    rows = [
        {"task_id": f"fugu-{i}", "status": "claimed", "assigned_to": "fugu-dev"} for i in range(31)
    ]
    demand = gap.waiting_demand(rows, walled_families={"fugu"})
    assert len(demand.walled_rows["fugu"]) == 31
    assert any("31" in item for item in gap.judge_gaps({"fugu": "walled"}, demand, set()))


def test_new_jetson_on_tailnet_is_unregistered() -> None:
    discovered = {"jetson-new", "spark-01df"}
    registered = {"spark-01df"}
    assert gap.registration_gaps(discovered, registered, answering=discovered) == {
        "UNREGISTERED:jetson-new"
    }


def test_tailnet_importer_detects_new_jetson(monkeypatch) -> None:
    monkeypatch.setattr(
        gap,
        "run",
        lambda *_args, **_kwargs: (
            '{"Self":{"HostName":"spark-01df","Online":true},"Peer":{"j":{"HostName":"jetson-new","Online":true},"off":{"HostName":"old","Online":false}}}'
        ),
    )
    online, all_hosts = gap.tailnet_devices()
    assert online == {"spark-01df", "jetson-new"}
    assert all_hosts == {"spark-01df", "jetson-new", "old"}


def test_changed_persistent_and_clear_delivery(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    inbox = tmp_path / "dev1"
    assert gap.deliver({"idle:qwen"}, state, inbox, NOW) is True
    assert len(list(inbox.glob("*.md"))) == 1
    assert gap.deliver({"idle:qwen"}, state, inbox, NOW + timedelta(minutes=15)) is False
    assert gap.deliver({"idle:qwen"}, state, inbox, NOW + timedelta(minutes=31)) is True
    assert gap.deliver(set(), state, inbox, NOW + timedelta(minutes=32)) is False
    assert len(list(inbox.glob("*.md"))) == 2


def test_seat_role_is_read_from_section_zero_each_send(tmp_path: Path) -> None:
    seat = tmp_path / "COORDINATOR-SEAT.md"
    seat.write_text(
        "## 0. Incumbent and lease\n| incumbent | role `dev1-seat-codex`. |\n"
        "| inbox | `lanebus/dev1/` is declared. |\n## 1. History\n"
    )
    assert gap.seat_role(seat) == ("dev1-seat-codex", "dev1")
    seat.write_text(
        "## 0. Incumbent and lease\n| incumbent | role `grok-owedset`. |\n"
        "| inbox | `lanebus/grok/` is declared. |\n## 1. History\n"
    )
    assert gap.seat_role(seat) == ("grok-owedset", "grok")


@pytest.mark.parametrize("inbox", ["", "lanebus/../", "lanebus/dev1/` and `lanebus/other/"])
def test_seat_role_refuses_missing_escaping_or_ambiguous_inbox(tmp_path: Path, inbox: str) -> None:
    seat = tmp_path / "COORDINATOR-SEAT.md"
    seat.write_text(
        "## 0. Incumbent and lease\n| incumbent | role `dev1-seat-codex`. |\n"
        f"| inbox | `{inbox}` |\n## 1. History\n"
    )
    with pytest.raises(ValueError):
        gap.seat_role(seat)


def test_lost_gaps_emit_across_tailnet_loss() -> None:
    # Major 1: LOST even when the host has left the tailnet, plus a reason gap.
    gaps = gap.lost_gaps({"spark-01df:8000", "gx10-b941:9000"}, {"spark-01df:8000"}, {"spark-01df"})
    assert gaps == {"LOST:gx10-b941:9000", "LOST_HOST_OFFLINE:gx10-b941"}


def test_resolve_seat_degrades_on_malformed_document(tmp_path: Path) -> None:
    # Major 3: a malformed seat degrades to the default inbox with a gap, not a crash.
    bad = tmp_path / "COORDINATOR-SEAT.md"
    bad.write_text("## 0. Incumbent and lease\n(garbled: no role or inbox row)\n## 1. History\n")
    assert gap.resolve_seat(bad) == ("dev1-seat", "dev1", {"INPUT_STALE:seat-document"})
    good = tmp_path / "good.md"
    good.write_text(
        "## 0. Incumbent and lease\n| incumbent | role `dev1-seat`. |\n"
        "| inbox | `lanebus/dev1/` is declared. |\n## 1. History\n"
    )
    assert gap.resolve_seat(good) == ("dev1-seat", "dev1", set())


def test_capacity_gap_units_are_parked_against_auto_activation() -> None:
    # A new unmarked timer is `enable --now`'d by hapax-post-merge-deploy; the
    # Hapax-Parked marker makes it disable-on-deploy so activation stays the seat's act.
    root = Path(__file__).resolve().parents[2]
    marker = re.compile(r"(?mi)^[#;][ \t]*Hapax-Parked:[ \t]*(?:true|yes|1)[ \t]*$")
    for unit in ("hapax-capacity-gap-signal.service", "hapax-capacity-gap-signal.timer"):
        text = (root / "systemd" / "units" / unit).read_text(encoding="utf-8")
        assert marker.search(text), unit


def test_waiting_demand_counts_claimed_and_unserved_not_only_offered() -> None:
    # glm major: claimed / in_progress rows are unserved demand, not just offered/assigned.
    rows = [
        {"task_id": "offered", "status": "offered"},
        {"task_id": "claimed", "status": "claimed", "assigned_to": "fugu-dev"},
        {"task_id": "running", "status": "in_progress", "assigned_to": "x"},
        {"task_id": "done", "status": "done"},
    ]
    demand = gap.waiting_demand(rows, set())
    assert set(demand.waiting_rows) == {"offered", "claimed", "running"}


def test_observer_stale_tolerates_one_skipped_observer_tick() -> None:
    # glm major: a skipped observer tick (40 min) plus signal sampling slack must not
    # read as stale; 50 min is within tolerance (the old 40-min threshold would fail it).
    tolerated = [{"ts": gap.stamp(NOW - timedelta(minutes=50))}]
    assert gap.observer_stale(tolerated, NOW) is False
    dead = [{"ts": gap.stamp(NOW - timedelta(minutes=70))}]
    assert gap.observer_stale(dead, NOW) is True
