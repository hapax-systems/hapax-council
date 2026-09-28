"""Capacity-gap v1 contracts. These are stamped before the producer exists."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

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


def test_repo_wide_inventory_finds_nested_units_and_compose_members(tmp_path: Path) -> None:
    (tmp_path / "systemd/units/deep").mkdir(parents=True)
    (tmp_path / "systemd/units/deep/qwen.service").write_text(
        "[Service]\nExecStart=vllm serve /models/qwen --port 8000 --tensor-parallel-size 2\n"
    )
    (tmp_path / "fleet/deep").mkdir(parents=True)
    (tmp_path / "fleet/deep/compose.yaml").write_text(
        "services:\n  qwen:\n    image: vllm/vllm-openai\n    ports: ['8000:8000']\n    environment:\n      VLLM_TENSOR_PARALLEL_SIZE: '2'\n"
    )
    inventory = gap.inventory_repo(tmp_path)
    assert 8000 in inventory.ports
    assert any("deep/qwen.service" in item for item in inventory.sources)
    assert any("fleet/deep/compose.yaml" in item for item in inventory.sources)
    assert inventory.parallel_sizes["qwen"] == 2


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


def test_changed_persistent_and_clear_delivery(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    inbox = tmp_path / "dev1"
    assert gap.deliver({"idle:qwen"}, state, inbox, NOW) is True
    assert len(list(inbox.glob("*.md"))) == 1
    assert gap.deliver({"idle:qwen"}, state, inbox, NOW + timedelta(minutes=15)) is False
    assert gap.deliver({"idle:qwen"}, state, inbox, NOW + timedelta(minutes=31)) is True
    assert gap.deliver(set(), state, inbox, NOW + timedelta(minutes=32)) is False
    assert len(list(inbox.glob("*.md"))) == 2
