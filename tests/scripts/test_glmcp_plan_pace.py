"""Plan-meter to lane-admission contract; all credentials and HTTP are synthetic."""

from __future__ import annotations

import copy
import importlib.machinery
import importlib.util
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from shared import quota_headroom as headroom
from shared import quota_spend_ledger as ledger
from shared.platform_capability_registry import PlatformCapabilityRegistry

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 12, 3, 30, tzinfo=UTC)
WEEK_RESET = NOW + timedelta(hours=144, milliseconds=984)
HOUR_RESET = NOW + timedelta(hours=1, milliseconds=379)
ROUTE = "glmcp.interactive.lane"


def payload(weekly=59, five_hour=14):
    return {
        "success": True,
        "code": 200,
        "data": {
            "limits": [
                {"type": "TIME_LIMIT", "unit": 5, "number": 1, "percentage": 0},
                {
                    "type": "TOKENS_LIMIT",
                    "unit": 3,
                    "number": 5,
                    "percentage": five_hour,
                    "nextResetTime": int(HOUR_RESET.timestamp() * 1000),
                },
                {
                    "type": "TOKENS_LIMIT",
                    "unit": 6,
                    "number": 1,
                    "percentage": weekly,
                    "nextResetTime": int(WEEK_RESET.timestamp() * 1000),
                },
            ]
        },
    }


@pytest.fixture
def producer(monkeypatch):
    loader = importlib.machinery.SourceFileLoader(
        "glmcp_plan_test_producer", str(ROOT / "scripts/hapax-glmcp-quota-admission")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    monkeypatch.setattr(module, "_launch_now", lambda: NOW, raising=False)
    return module


def readings(weekly=59, five_hour=14):
    return headroom.glmcp_plan_measurements(
        payload(weekly, five_hour), at=NOW, source="local-trace:glmcp_plan_usage:test"
    )


def test_monitor_parses_millisecond_resets_and_both_token_windows():
    rows = {r.capacity_id: r for r in readings()}
    week = rows["glm.subscription.weekly"]
    hour = rows["glm.subscription.five_hour"]
    assert week.quantity == 59 and week.resets_at == WEEK_RESET
    assert hour.quantity == 14 and hour.resets_at == HOUR_RESET
    assert week.measurement_fresh_until == NOW + timedelta(minutes=15)
    line = rows["glm.subscription.weekly.even_pace"]
    assert line.label == "derived"
    assert line.quantity == pytest.approx(100 * (24 * 3600 - 0.984) / (168 * 3600))


@pytest.mark.parametrize("weekly,expected", [(59, "exhausted"), (10, "fresh")])
def test_over_line_holds_route_admission_at_ledger_boundary(weekly, expected):
    snapshot = ledger.glmcp_lane_quota_snapshot(readings(weekly), now=NOW)
    base = ledger.load_quota_spend_ledger()
    live = base.model_copy(update={"quota_snapshots": (snapshot,), "captured_at": NOW})
    state, refs = ledger.subscription_quota_state_for_route(live, ROUTE, now=NOW)
    assert state.value == expected
    assert snapshot.subscription_quota_state.value == expected
    assert refs
    assert snapshot.quantity == weekly


@pytest.mark.parametrize("bad", [None, True, -1, float("nan"), 1792294584, "unparseable"])
def test_invalid_reset_cannot_admit(bad):
    data = payload(10)
    data["data"]["limits"][2]["nextResetTime"] = bad
    with pytest.raises(ValueError):
        headroom.glmcp_plan_measurements(data, at=NOW, source="test")


def test_missing_or_stale_or_future_measurement_holds():
    assert ledger.glmcp_lane_quota_snapshot([], now=NOW).subscription_quota_state == "unknown"
    for at in (NOW - timedelta(seconds=1), NOW + timedelta(minutes=15)):
        snapshot = ledger.glmcp_lane_quota_snapshot(readings(10), now=at)
        assert snapshot.subscription_quota_state != "fresh"
    assert (
        ledger.glmcp_lane_quota_snapshot(readings(10, 100), now=NOW).subscription_quota_state
        == "exhausted"
    )


def test_lane_snapshot_without_plan_evidence_cannot_admit():
    snapshot = ledger.glmcp_lane_quota_snapshot(readings(10), now=NOW)
    snapshot = snapshot.model_copy(update={"evidence_refs": ("unrelated-observation",)})
    live = ledger.load_quota_spend_ledger().model_copy(update={"quota_snapshots": (snapshot,)})
    state, _ = ledger.subscription_quota_state_for_route(live, ROUTE, now=NOW)
    assert state == "unknown"


def test_receipt_round_trip_enriches_existing_ledger(producer, tmp_path, monkeypatch):
    monkeypatch.setattr(producer, "fetch_plan_usage", lambda: payload())
    assert (
        producer.main(["--receipt-dir", str(tmp_path), "--now", NOW.isoformat(), "observe-plan"])
        == 0
    )
    rows = headroom.read_receipt_measurements(tmp_path, "glm")
    registry = PlatformCapabilityRegistry.model_validate_json(
        (ROOT / "config/platform-capability-registry.json").read_text()
    )
    enriched = headroom.enrich_ledger(
        ledger.load_quota_spend_ledger(), {"glm": rows}, registry=registry, now=NOW
    )
    snapshot = next(s for s in enriched.quota_snapshots if s.route_id == ROUTE)
    assert snapshot.subscription_quota_state == "exhausted"
    assert {m.capacity_id for m in snapshot.measurements} >= {
        "glm.subscription.five_hour",
        "glm.subscription.weekly.even_pace",
    }
    assert snapshot.resets_at == WEEK_RESET


@pytest.mark.parametrize("failure", [False, True])
def test_no_key_in_output_receipts_or_error(producer, tmp_path, monkeypatch, capsys, failure):
    # Generate a throwaway value; never use or store a real credential in a fixture.
    credential = secrets.token_urlsafe(32)
    monkeypatch.setattr(producer, "get_secret", lambda name: credential)

    def respond(request):
        assert request.url == httpx.URL("https://api.z.ai/api/monitor/usage/quota/limit")
        assert request.headers["Authorization"] == credential
        if failure:
            raise httpx.ReadError(credential, request=request)
        data = payload(10)
        data["untrusted_provider_text"] = credential
        return httpx.Response(200, json=data)

    real_client = httpx.Client
    monkeypatch.setattr(
        producer.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = producer.main(
        ["--receipt-dir", str(tmp_path), "--now", NOW.isoformat(), "--json", "observe-plan"]
    )
    captured = capsys.readouterr()
    persisted = "".join(p.read_text() for p in tmp_path.iterdir() if p.is_file())
    assert credential not in captured.out + captured.err + persisted
    assert result == (1 if failure else 0)
    if failure:
        assert "plan_usage_unavailable" in persisted


def test_failed_refresh_replaces_previous_positive_reading(producer, tmp_path, monkeypatch):
    monkeypatch.setattr(producer, "fetch_plan_usage", lambda: payload(10))
    args = ["--receipt-dir", str(tmp_path), "--now", NOW.isoformat()]
    assert producer.main([*args, "observe-plan"]) == 0
    assert producer.main([*args, "check-launch"]) == 0

    def fail():
        raise RuntimeError("untrusted detail")

    monkeypatch.setattr(producer, "fetch_plan_usage", fail)
    assert producer.main([*args, "observe-plan"]) == 1
    assert producer.main([*args, "check-launch"]) != 0


def test_launch_hold_does_not_invoke_launcher(producer, tmp_path, monkeypatch):
    monkeypatch.setattr(producer, "fetch_plan_usage", lambda: payload())
    args = ["--receipt-dir", str(tmp_path), "--now", NOW.isoformat()]
    assert producer.main([*args, "observe-plan"]) == 0
    calls = []
    monkeypatch.setattr(producer.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    assert producer.main([*args, "launch", "glm-test"]) != 0
    assert calls == []


def test_route_is_declared_without_invented_runtime_acceptance():
    registry = PlatformCapabilityRegistry.model_validate_json(
        (ROOT / "config/platform-capability-registry.json").read_text()
    )
    route = next(r for r in registry.routes if r.route_id == ROUTE)
    assert route.platform == "glmcp" and route.mode == "interactive"
    assert route.capacity_pool == "subscription_quota"
    assert route.authority_ceiling == "frontier_review_required"
    assert route.execution_descriptor.model_id == "z_ai-glm-5.3"
    assert "scripts/hapax-glmcp" in route.launcher
    assert "model" in route.notes and "wire" in route.notes
    assert route.route_state == "blocked"


def test_malformed_and_duplicate_windows_fail_closed():
    for key, value in (("percentage", True), ("percentage", -1), ("percentage", 101)):
        data = payload()
        data["data"]["limits"][2][key] = value
        with pytest.raises(ValueError):
            headroom.glmcp_plan_measurements(data, at=NOW, source="test")
    data = payload()
    data["data"]["limits"].append(copy.deepcopy(data["data"]["limits"][2]))
    with pytest.raises(ValueError):
        headroom.glmcp_plan_measurements(data, at=NOW, source="test")


def test_scheduled_refresh_runs_only_monitor_and_keeps_check_offline(tmp_path, monkeypatch):
    import runpy

    ns = runpy.run_path(str(ROOT / "scripts/hapax-quota-telemetry-writer"))
    refresh = ns["refresh_glmcp_plan_usage"]
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ns["subprocess"], "run", run)
    refresh(SimpleNamespace(check=True, skip_receipts=False, relay_receipt_dir=tmp_path))
    refresh(SimpleNamespace(check=False, skip_receipts=True, relay_receipt_dir=tmp_path))
    refresh(
        SimpleNamespace(
            check=False, skip_receipts=False, now=NOW.isoformat(), relay_receipt_dir=tmp_path
        )
    )
    assert calls == []
    refresh(SimpleNamespace(check=False, skip_receipts=False, relay_receipt_dir=tmp_path))
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv[-1] == "observe-plan"
    assert Path(argv[1]).name == "hapax-glmcp-quota-admission"
    assert options["timeout"] <= 30
    assert "launch" not in argv and "observe-success" not in argv


def test_platform_path_advertises_pace_gated_launcher():
    import runpy

    ns = runpy.run_path(str(ROOT / "scripts/hapax-methodology-dispatch"))
    path = ns["route_for"]("glmcp", "interactive", "lane")
    assert path is not None
    assert "hapax-glmcp-quota-admission launch" in path.launcher
    assert "scripts/hapax-glmcp" in path.notes


@pytest.mark.parametrize("timed_out", [False, True])
def test_scheduled_refresh_failure_invalidates_old_admission(
    producer, tmp_path, monkeypatch, timed_out
):
    import runpy

    monkeypatch.setattr(producer, "fetch_plan_usage", lambda: payload(10))
    args = ["--receipt-dir", str(tmp_path), "--now", NOW.isoformat()]
    assert producer.main([*args, "observe-plan"]) == 0
    ns = runpy.run_path(str(ROOT / "scripts/hapax-quota-telemetry-writer"))

    def fail(*args, **kwargs):
        if timed_out:
            raise ns["subprocess"].TimeoutExpired("synthetic-monitor", 25)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(ns["subprocess"], "run", fail)
    assert (
        ns["refresh_glmcp_plan_usage"](
            SimpleNamespace(check=False, skip_receipts=False, relay_receipt_dir=tmp_path)
        )
        is False
    )
    assert producer.main([*args, "check-launch"]) != 0


def test_admitted_launch_pins_coding_plan_and_model(producer, tmp_path, monkeypatch):
    monkeypatch.setattr(producer, "fetch_plan_usage", lambda: payload(10))
    args = ["--receipt-dir", str(tmp_path), "--now", NOW.isoformat()]
    assert producer.main([*args, "observe-plan"]) == 0
    monkeypatch.setenv("HAPAX_GLMCP_MODEL", "alternate-model")
    monkeypatch.setenv("HAPAX_GLMCP_OPENAI_BASE_URL", "https://api.z.ai/api/paas/v4")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(producer.subprocess, "run", run)
    assert producer.main([*args, "launch", "glm-test"]) == 0
    argv, kwargs = calls[0]
    assert argv == [str(ROOT / "scripts/hapax-glmcp"), "glm-test", "--terminal", "tmux"]
    assert kwargs["env"]["HAPAX_GLMCP_MODEL"] == "glm-5.3"
    assert kwargs["env"]["HAPAX_GLMCP_OPENAI_BASE_URL"] == "https://api.z.ai/api/coding/paas/v4"


def test_launch_clock_cannot_be_backdated_with_observation_override(tmp_path):
    import subprocess

    data = {
        "schema": "hapax.glmcp_quota_admission.v1",
        "provider": "z_ai-glm-coding-plan",
        "route_id": ROUTE,
        "capacity_pool": "subscription_quota",
        "billing_mode": "coding_plan_subscription",
        "payg_fallback": False,
        "secret_value_persisted": False,
        "status": "plan_usage_observed",
        "supported_tool": "hapax-glmcp-quota-admission",
        "endpoint": "https://api.z.ai/api/monitor/usage/quota/limit",
        "observed_at": "2020-01-02T00:00:00Z",
        "weekly_used_percent": 0,
        "five_hour_used_percent": 0,
        "weekly_resets_at": "2020-01-08T00:00:00Z",
        "five_hour_resets_at": "2020-01-02T01:00:00Z",
    }
    import yaml

    (tmp_path / "glmcp-plan-usage.yaml").write_text(yaml.safe_dump(data))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/hapax-glmcp-quota-admission"),
            "--receipt-dir",
            str(tmp_path),
            "--now",
            data["observed_at"],
            "check-launch",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 3
    assert '"admitted": false' in result.stdout
