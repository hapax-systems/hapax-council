"""Utilization uses observed windows and the declared provider-call stream."""

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.durable_jsonl_sink import DurableJsonlSink
from shared.entitlement_census import (
    CensusConfig,
    HostHoldings,
    read_provider_calls,
    render_markdown,
    render_view,
    run_census,
)

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def _config(*, ledger: bool = False, slots: int | None = None, cost: float = 200):
    return CensusConfig.model_validate(
        {
            "schema": "hapax.entitlement_census.v1",
            "hosts": [{"host_id": "appendix", "transport": "local"}],
            "entitlements": [
                {
                    "entitlement_id": "sample",
                    "provider": "sample",
                    "kind": "cognition",
                    "cost_class": "subscription",
                    "monthly_cost_usd": cost,
                    "usage_ledger": ledger,
                    "renewal_day": 19 if ledger else None,
                    "concurrency_slots": slots,
                }
            ],
        }
    )


def _run(config, *, provider_calls=None):
    return run_census(
        config,
        now=NOW,
        holdings=[HostHoldings(host_id="appendix", reachable=True, observed_at=NOW)],
        registry={},
        inventory_dispositions={},
        ledger=None,
        prior_view=None,
        resolve_secret=lambda _: None,
        http_get=lambda *_: (_ for _ in ()).throw(AssertionError("no network")),
        read_home_file=lambda _: None,
        provider_calls=provider_calls,
    )


def _call(sink: DurableJsonlSink, *, call_id: str, phase: str, start: str, end=None, tokens=None):
    sink.append(
        stream_id="provider-calls",
        data_class="provider_call",
        source_receipt_ref="fixture-run",
        payload={
            "provider": "sample",
            "entitlement_id": "sample",
            "route_id": "sample.route",
            "call_id": call_id,
            "phase": phase,
            "started_at": start,
            "ended_at": end,
            "status": "ok" if phase == "final" else None,
            "http_status": 200 if phase == "final" else None,
            "tokens_in": tokens,
            "tokens_out": tokens,
            "model": "sample-model",
            "prompt": "must never enter census output",
        },
    )


def test_unreadable_or_missing_call_stream_is_unjudged_not_zero(tmp_path: Path):
    config = _config(ledger=True)
    assert read_provider_calls(tmp_path / "absent.jsonl") is None
    row = _run(config, provider_calls=None).rows[0]
    assert row.utilization["basis"] == "none"
    assert row.utilization["underuse"] is None
    assert "unreadable" in row.utilization["reason"]
    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"bad":true}\n')
    assert read_provider_calls(broken) is None


def test_readable_empty_stream_reports_zero_recorded_calls_in_paid_period(tmp_path: Path):
    stream = tmp_path / "provider-calls.jsonl"
    stream.write_text("")
    rows = read_provider_calls(stream)
    assert rows == []
    row = _run(_config(ledger=True), provider_calls=rows).rows[0]
    assert row.utilization["basis"] == "per_call_ledger"
    assert row.utilization["calls"] == 0
    assert row.utilization["underuse"] is True
    assert "zero recorded calls" in row.utilization["reason"]


def test_pair_counts_once_and_unfinished_attempt_counts_with_unknown_tokens(tmp_path: Path):
    sink = DurableJsonlSink(tmp_path)
    start = "2026-09-25T00:00:00Z"
    _call(sink, call_id="a", phase="attempted", start=start)
    _call(sink, call_id="a", phase="final", start=start, end="2026-09-25T01:00:00Z", tokens=12)
    _call(sink, call_id="b", phase="attempted", start="2026-09-26T00:00:00Z")
    rows = read_provider_calls(sink.path_for_stream("provider-calls"))
    row = _run(_config(ledger=True, slots=2), provider_calls=rows).rows[0]
    assert row.utilization["calls"] == 2
    assert row.utilization["unknown_tokens_calls"] == 1
    assert row.utilization["underuse"] is None  # unresolved duration cannot prove low occupancy
    assert "must never enter census output" not in json.dumps(
        render_view(_run(_config(ledger=True, slots=2), provider_calls=rows), now=NOW)
    )


def test_complete_slot_duration_below_five_percent_is_ranked(tmp_path: Path):
    sink = DurableJsonlSink(tmp_path)
    start = "2026-09-25T00:00:00Z"
    _call(sink, call_id="a", phase="attempted", start=start)
    _call(sink, call_id="a", phase="final", start=start, end="2026-09-25T01:00:00Z")
    rows = read_provider_calls(sink.path_for_stream("provider-calls"))
    run = _run(_config(ledger=True, slots=2, cost=269), provider_calls=rows)
    utilization = run.rows[0].utilization
    assert utilization["basis"] == "per_call_ledger"
    assert utilization["used_pct"] < 5
    assert utilization["underuse"] is True
    assert render_view(run, now=NOW)["underuse"][0]["monthly_cost_usd"] == 269


def test_provider_mismatch_cannot_be_counted_as_this_entitlement():
    record = {
        "entitlement_id": "sample",
        "provider": "someone_else",
        "call_id": "a",
        "phase": "attempted",
        "started_at": "2026-09-25T00:00:00Z",
    }
    row = _run(_config(ledger=True), provider_calls=[record]).rows[0]
    assert row.utilization["underuse"] is None
    assert row.utilization["basis"] == "none"


def test_underuse_is_ordered_by_declared_monthly_cost():
    config = _config(ledger=True)
    cheap = config.entitlements[0].model_copy(
        update={"entitlement_id": "cheap", "monthly_cost_usd": 20}
    )
    expensive = config.entitlements[0].model_copy(
        update={"entitlement_id": "expensive", "monthly_cost_usd": 269}
    )
    config = config.model_copy(update={"entitlements": (cheap, expensive)})
    run = _run(config, provider_calls=[])
    assert [item["entitlement_id"] for item in render_view(run, now=NOW)["underuse"]] == [
        "expensive",
        "cheap",
    ]


def test_paid_unjudged_row_with_unknown_cost_is_named():
    config = _config(cost=200)
    unknown_cost = config.entitlements[0].model_copy(update={"monthly_cost_usd": None})
    config = config.model_copy(update={"entitlements": (unknown_cost,)})
    view = render_view(_run(config), now=NOW)
    assert view["paid_unjudged"][0]["entitlement_id"] == "sample"
    assert view["paid_unjudged"][0]["monthly_cost_usd"] is None
    assert "monthly cost not declared" in view["paid_unjudged"][0]["reason"]
    assert "sample ($unknown/month)" in render_markdown(view)


def test_stale_window_never_judges_healthy_or_underused():
    run = _run(_config())
    run.rows[0].measurements = (
        {
            "capacity_id": "sample.week",
            "quantity": 10,
            "unit": "percent_used",
            "window": "10080m",
            "resets_at": "2026-09-29T00:00:00Z",
            "measurement_fresh_until": "2026-09-28T11:00:00Z",
        },
    )
    # Re-run through the calculation entrypoint after replacing the fixture measurement.
    from shared.entitlement_census import utilization_for_row

    assert (
        utilization_for_row(run.config.entitlements[0], run.rows[0], now=NOW, provider_calls=None)[
            "underuse"
        ]
        is None
    )


def test_fresh_window_below_half_pace_is_underused():
    run = _run(_config())
    run.rows[0].measurements = (
        {
            "capacity_id": "sample.week",
            "quantity": 10,
            "unit": "percent_used",
            "window": "10080m",
            "resets_at": "2026-10-02T00:00:00Z",
            "measurement_fresh_until": "2026-09-28T13:00:00Z",
        },
    )
    from shared.entitlement_census import utilization_for_row

    utilization = utilization_for_row(
        run.config.entitlements[0], run.rows[0], now=NOW, provider_calls=None
    )
    assert utilization["basis"] == "window_pace"
    assert utilization["pace_ratio"] < 0.5
    assert utilization["underuse"] is True
