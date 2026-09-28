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
    demand = gap.waiting_demand([{"task_id": "waiting", "status": "offered"}], set())
    assert gap.judge_gaps(states, demand, set()) == {
        "IDLE_WITH_DEMAND:spark-01df:8000:waiting=1:fit=unmeasured"
    }
    endpoints["spark-01df:8000"]["requests"][-1] = (NOW, 11)
    assert gap.classify_local(samples, members, endpoints, NOW)["spark-01df:8000"] == "busy"
    endpoints["spark-01df:8000"]["requests"] = []
    assert gap.classify_local(samples, members, endpoints, NOW)["spark-01df:8000"] == "unknown"


def test_zero_percent_unserved_gpu_and_waiting_row_is_gap_but_tp_member_is_not() -> None:
    samples = [
        {
            "ts": "2026-09-28T19:20:00Z",
            "fleet_memory": {"gx10-b941": {"total_mb": 124546, "avail_mb": 124000}},
        },
        {
            "ts": "2026-09-28T19:40:00Z",
            "fleet_memory": {"gx10-b941": {"total_mb": 124546, "avail_mb": 124000}},
        },
    ]
    runtime = {"gx10-b941": "NVIDIA GB10, 124546 MiB, 0 MiB"}
    demand = gap.waiting_demand([{"task_id": "waiting", "status": "offered"}], set())
    hosts = gap.unserved_metal(samples, runtime, {}, NOW)
    assert hosts == {"gx10-b941"}
    assert gap.judge_gaps({host: "unserved" for host in hosts}, demand, set()) == {
        "UNSERVED_METAL_WITH_DEMAND:gx10-b941:waiting=1:fit=unmeasured"
    }
    assert (
        gap.unserved_metal(samples, runtime, {"spark-01df:8000": {"spark-01df", "gx10-b941"}}, NOW)
        == set()
    )


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
        "## 0. Incumbent and lease\n| incumbent | dev1-seat, role `dev1-seat`. |\n## 1. History\n"
    )
    assert gap.seat_role(seat) == ("dev1-seat", "dev1")
    seat.write_text(
        "## 0. Incumbent and lease\n| incumbent | grok-owedset, role `grok-owedset`. |\n## 1. History\n"
    )
    assert gap.seat_role(seat) == ("grok-owedset", "grok-owedset")


def test_service_membership_comes_from_both_host_processes() -> None:
    runtime = {
        "spark-01df": "vllm serve /models/qwen38fn --port 8000 --tensor-parallel-size 2",
        "gx10-b941": "ray::worker /models/qwen38fn TP rank 1",
    }
    assert gap.runtime_membership(runtime, {"spark-01df:8000"}) == {
        "spark-01df:8000": {"spark-01df", "gx10-b941"}
    }


def test_over_pace_status_output_survives_nonzero_decision_code(monkeypatch) -> None:
    class Result:
        returncode = 3
        stdout = '{"over_line":true}'

    monkeypatch.setattr(gap.subprocess, "run", lambda *_args, **_kwargs: Result())
    assert gap.run(["status"]) == '{"over_line":true}'


def test_pacing_gap_identity_does_not_change_with_line_drift(monkeypatch, tmp_path: Path) -> None:
    current = '{"over_line":true,"weekly_used_percent":81,"line_percent":44.1}'
    monkeypatch.setattr(gap, "run", lambda *_args, **_kwargs: current)
    first = gap._claude_pace(tmp_path)
    current = '{"over_line":true,"weekly_used_percent":81,"line_percent":44.2}'
    second = gap._claude_pace(tmp_path)
    assert first is not None and second is not None
    assert first[0] == second[0] == "OVER_PACE:claude"
    assert first[1] != second[1]


def test_codex_rate_limit_importer_reports_headroom_and_reset(tmp_path: Path) -> None:
    day = tmp_path / "2026/09/28"
    day.mkdir(parents=True)
    (day / "rollout-test.jsonl").write_text(
        '{"payload":{"rate_limits":{"primary":{"used_percent":38,"resets_at":1791046721},"rate_limit_reached_type":null}}}\n'
    )
    state, detail = gap.codex_headroom(tmp_path, NOW)
    assert state == "available"
    assert "headroom=62.0%" in detail
    assert "reset=" in detail


def test_mimo_manifest_minus_ledger_done_is_queued_work(tmp_path: Path) -> None:
    kit = tmp_path / "mimo-talus/kit"
    kit.mkdir(parents=True)
    (kit / "MANIFEST-v2.json").write_text('{"count":3}')
    (kit / "LEDGER-v2.md").write_text(
        "| Task | Status |\n|---|---|\n| 001 | DONE |\n| 002 | QUEUED |\n"
    )
    assert gap._appliance_demand(tmp_path) == 2


def test_catalogue_importers_require_exact_zero_price_and_featherless_data() -> None:
    catalogues = {
        "https://openrouter.ai/api/v1/models": {
            "data": [
                {"id": "stealth/space-bunny-alpha", "pricing": {"prompt": "0", "completion": "0"}}
            ]
        },
        "https://api.featherless.ai/v1/models": {"data": [{"id": "model-a"}, {"id": "model-b"}]},
    }
    states = gap.catalogue_capabilities(catalogues)
    assert states == {"space-bunny": "price0", "featherless": "available:2"}
    catalogues["https://openrouter.ai/api/v1/models"]["data"][0]["pricing"]["completion"] = (
        "0.000001"
    )
    assert gap.catalogue_capabilities(catalogues)["space-bunny"] == "priced"


def test_fugu_wall_importer_uses_live_pane_reset_and_expires() -> None:
    pane = "■ You’ve hit your usage limit. Try again at Oct 4th, 2026 7:00 PM.\n› Ask Codex"
    assert gap.fugu_wall({"hapax-fugu-ci": pane}, NOW) == ("walled", "2026-10-05T00:00:00Z")
    assert (
        gap.fugu_wall({"hapax-fugu-ci": pane}, datetime(2026, 10, 5, 0, 1, tzinfo=UTC))[0]
        == "unknown"
    )


def test_missing_live_probe_fails_loud_after_two_cycles_and_recovers() -> None:
    state = {}
    health = {"provider-catalogues": False, "quota-ledger": True}
    assert gap.input_staleness(state, health) == set()
    assert gap.input_staleness(state, health) == {"INPUT_STALE:provider-catalogues"}
    health["provider-catalogues"] = True
    assert gap.input_staleness(state, health) == set()
