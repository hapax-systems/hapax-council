"""Capacity-gap v1 contracts. These are stamped before the producer exists."""

import argparse
import json
import re
import types
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


def test_service_membership_comes_from_both_host_processes() -> None:
    runtime = {
        "spark-01df": "vllm serve /models/qwen38fn --port 8000 --tensor-parallel-size 2",
        "gx10-b941": "ray::worker /models/qwen38fn TP rank 1",
    }
    assert gap.runtime_membership(runtime, {"spark-01df:8000"}) == {
        "spark-01df:8000": {"spark-01df", "gx10-b941"}
    }


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


# Importer tests moved from #4915 to keep that PR under the review size limit.
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


def _wire_cycle(
    tmp_path: Path,
    monkeypatch,
    *,
    online: set[str],
    tailnet: set[str],
    probes: dict[str, dict],
    stale: bool,
    state_seed: dict | None = None,
) -> tuple[argparse.Namespace, Path]:
    """Drive cycle() with fakes for every environment-touching helper."""
    state = tmp_path / "state.json"
    state.write_text(json.dumps(state_seed or {}))
    seat = tmp_path / "COORDINATOR-SEAT.md"
    seat.write_text(
        "## 0. Incumbent and lease\n| incumbent | role `dev1-seat`. |\n"
        "| inbox | `lanebus/dev1/` is declared. |\n## 1. History\n"
    )
    args = argparse.Namespace(
        repo=tmp_path,
        observer=tmp_path / "observer.jsonl",
        state=state,
        routing=tmp_path / "routing.md",
        quota_ledger=tmp_path / "quota.json",
        codex_sessions=tmp_path / "sessions",
        tasks=tmp_path / "tasks",
        lanebus=tmp_path / "lanebus",
        seat_document=seat,
    )
    monkeypatch.setattr(gap, "load_observations", lambda *_a: [])
    monkeypatch.setattr(gap, "observer_stale", lambda *_a: stale)
    monkeypatch.setattr(
        gap,
        "inventory_repo",
        lambda *_a: types.SimpleNamespace(ports={8000}, sources=[], parallel_sizes={}),
    )
    monkeypatch.setattr(gap, "tailnet_devices", lambda: (online, tailnet))
    monkeypatch.setattr(gap, "host_runtime", lambda *_a: "")
    monkeypatch.setattr(
        gap,
        "probe_endpoint",
        lambda host, port: (f"{host}:{port}", probes.get(f"{host}:{port}", {"answering": False})),
    )
    monkeypatch.setattr(gap, "_subscribed_state", lambda *_a: {})
    monkeypatch.setattr(gap, "codex_headroom", lambda *_a: ("unknown", "codex unknown"))
    monkeypatch.setattr(gap, "read_tasks", lambda *_a: [])
    monkeypatch.setattr(gap, "_pr_demand", lambda: (0, 0))
    monkeypatch.setattr(gap, "_appliance_demand", lambda *_a: 0)
    monkeypatch.setattr(gap, "_claude_pace", lambda *_a: None)
    return args, state


def test_cycle_emits_lost_unregistered_and_tracks_counters(tmp_path, monkeypatch) -> None:
    # Major 2: cycle() end to end wires LOST (incl. tailnet loss), UNREGISTERED and
    # the request-counter branch together on real orchestration.
    args, state = _wire_cycle(
        tmp_path,
        monkeypatch,
        online={"spark-01df"},
        tailnet={"spark-01df"},
        probes={"spark-01df:8000": {"answering": True, "models": ["qwen3.8-unreg"], "counter": 11}},
        stale=False,
        state_seed={
            "known_endpoints": ["spark-01df:8000", "gx10-b941:9000"],
            "request_counters": {"spark-01df:8000": [gap.stamp(NOW - timedelta(minutes=30)), 10]},
        },
    )
    gaps = gap.cycle(args, NOW)
    assert "LOST:gx10-b941:9000" in gaps
    assert "LOST_HOST_OFFLINE:gx10-b941" in gaps
    assert "UNREGISTERED:spark-01df:8000:qwen3.8-unreg" in gaps
    persisted = json.loads(state.read_text())["request_counters"]
    assert persisted["spark-01df:8000"] == [gap.stamp(NOW), 11]
    assert list((args.lanebus / "dev1").glob("*.md"))


def test_cycle_fails_loud_on_stale_inputs(tmp_path, monkeypatch) -> None:
    # Major 4 (clause 5): a stale observer input is reported, not swallowed.
    args, _state = _wire_cycle(
        tmp_path,
        monkeypatch,
        online={"spark-01df"},
        tailnet={"spark-01df"},
        probes={"spark-01df:8000": {"answering": True, "models": [], "counter": 1}},
        stale=True,
        state_seed={"known_endpoints": ["spark-01df:8000"]},
    )
    gaps = gap.cycle(args, NOW)
    assert "INPUT_STALE:capacity-observer" in gaps
    assert list((args.lanebus / "dev1").glob("*.md"))


def test_cycle_seeds_known_endpoints_from_routing_for_lost_after_state_loss(
    tmp_path, monkeypatch
) -> None:
    # Re-round: with an empty state (state loss / rename / first deploy), a registered
    # endpoint that was never seen answering must still emit LOST, by seeding known
    # endpoints from the routing table.
    args, _state = _wire_cycle(
        tmp_path,
        monkeypatch,
        online=set(),
        tailnet={"spark-01df"},
        probes={},
        stale=False,
        state_seed={},
    )
    args.routing.write_text("| spark | `http://spark-01df:8000/v1` |\n")
    gaps = gap.cycle(args, NOW)
    assert "LOST:spark-01df:8000" in gaps
    assert "LOST_HOST_OFFLINE:spark-01df" in gaps


def test_subscribed_state_maps_quota_and_handles_staleness(tmp_path: Path) -> None:
    ledger = tmp_path / "quota.json"
    assert gap._subscribed_state(ledger, NOW) == {}  # missing file
    ledger.write_text(
        json.dumps(
            {
                "captured_at": gap.stamp(NOW),
                "quota_snapshots": [
                    {"route_id": "glmcp.x", "subscription_quota_state": "exhausted"},
                    {
                        "route_id": "kimi.y",
                        "subscription_quota_state": "active",
                        "fresh_until": gap.stamp(NOW - timedelta(minutes=1)),
                    },
                    {"route_id": "muse.z", "subscription_quota_state": "active"},
                ],
            }
        )
    )
    assert gap._subscribed_state(ledger, NOW) == {
        "glmcp": "walled",
        "kimi": "unknown",
        "muse": "available",
    }
    ledger.write_text(
        json.dumps(
            {
                "captured_at": gap.stamp(NOW - timedelta(hours=1)),
                "quota_snapshots": [{"route_id": "a.b", "subscription_quota_state": "exhausted"}],
            }
        )
    )
    assert gap._subscribed_state(ledger, NOW) == {}  # stale capture
    ledger.write_text("{not json")
    assert gap._subscribed_state(ledger, NOW) == {}  # unparseable


def test_pr_demand_counts_review_and_dirty_and_survives_bad_output(monkeypatch) -> None:
    monkeypatch.setattr(
        gap,
        "run",
        lambda *_a, **_k: json.dumps(
            [
                {
                    "isDraft": False,
                    "reviewDecision": "REVIEW_REQUIRED",
                    "mergeStateStatus": "CLEAN",
                },
                {"isDraft": True, "reviewDecision": None, "mergeStateStatus": "DIRTY"},
                {"isDraft": False, "reviewDecision": "APPROVED", "mergeStateStatus": "DIRTY"},
            ]
        ),
    )
    assert gap._pr_demand() == (1, 2)
    monkeypatch.setattr(gap, "run", lambda *_a, **_k: "not json")
    assert gap._pr_demand() == (0, 0)


def test_codex_headroom_walls_and_reports_unknown_without_transcripts(tmp_path: Path) -> None:
    assert gap.codex_headroom(tmp_path, NOW) == ("unknown", "codex headroom=unknown")
    day = tmp_path / "2026/09/28"
    day.mkdir(parents=True)
    (day / "rollout-wall.jsonl").write_text(
        json.dumps(
            {
                "payload": {
                    "rate_limits": {
                        "primary": {"used_percent": 100, "resets_at": 1791046721},
                        "rate_limit_reached_type": "primary",
                    }
                }
            }
        )
        + "\n"
    )
    state, _detail = gap.codex_headroom(tmp_path, NOW)
    assert state == "walled"


def test_claude_pace_returns_none_on_non_json_or_within_line(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gap, "run", lambda *_a, **_k: "not json")
    assert gap._claude_pace(tmp_path) is None
    monkeypatch.setattr(gap, "run", lambda *_a, **_k: '{"over_line":false}')
    assert gap._claude_pace(tmp_path) is None


def test_appliance_demand_falls_back_to_unread_mimo_inbox(tmp_path: Path) -> None:
    inbox = tmp_path / "mimo"
    (inbox / "read").mkdir(parents=True)
    (inbox / "a.md").write_text("x")
    (inbox / "b.md").write_text("y")
    (inbox / "read" / "a.md").write_text("x")
    assert gap._appliance_demand(tmp_path) == 1  # only b.md is unread


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


def test_probe_endpoint_reports_models_counter_and_handles_failure(monkeypatch) -> None:
    class _Resp:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *_a) -> bool:
            return False

        def read(self, *_a) -> bytes:
            return self._body

    def ok(url, timeout=2):
        if url.endswith("/v1/models"):
            return _Resp(json.dumps({"data": [{"id": "qwen3.8-flash"}]}).encode())
        return _Resp(b"vllm:request_success_total 5.0\n")

    monkeypatch.setattr(gap.urllib.request, "urlopen", ok)
    key, info = gap.probe_endpoint("spark-01df", 8000)
    assert key == "spark-01df:8000"
    assert info["answering"] and info["models"] == ["qwen3.8-flash"] and info["counter"] == 5.0

    def boom(url, timeout=2):
        raise OSError("down")

    monkeypatch.setattr(gap.urllib.request, "urlopen", boom)
    _key, down = gap.probe_endpoint("h", 9000)
    assert down["answering"] is False


def test_host_runtime_runs_probe_and_rejects_bad_host(monkeypatch) -> None:
    monkeypatch.setattr(gap, "run", lambda *_a, **_k: "vllm serve /models/x --port 8000")
    assert "vllm serve" in gap.host_runtime("spark-01df")
    assert gap.host_runtime("bad host!") == ""


def test_read_tasks_parses_only_cc_task_frontmatter(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("---\ntype: cc-task\ntask_id: t1\nstatus: offered\n---\nbody\n")
    (tmp_path / "b.md").write_text("---\ntype: note\n---\nx\n")
    (tmp_path / "c.md").write_text("no frontmatter\n")
    rows = gap.read_tasks(tmp_path)
    assert [r["task_id"] for r in rows] == ["t1"]
