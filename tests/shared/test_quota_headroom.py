"""M1 acceptance tests, using redacted local-source shapes and no provider probes."""

from __future__ import annotations

import json
import os
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    PlatformCapabilityRegistry,
)
from shared.quota_headroom import (
    TraceReadError,
    claude_rate_limit_windows,
    collect_measurements,
    enrich_ledger,
    freeze_predicate,
    operator_report,
    read_claude_wall_and_spend,
    read_codex_token_count,
    read_kimi_403_signal,
    read_other_family,
    read_receipt_measurements,
    wall_is_live,
)
from shared.quota_spend_ledger import (
    QuotaSpendLedger,
    load_quota_spend_ledger,
    subscription_quota_state_for_route,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hapax-quota-telemetry-writer"
NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


def write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


def token_event(at="2026-09-19T07:50:00Z", used=100, balance="4593.2239900000", total=100):
    # Provider rate_limits fields copied from the named rollout; no prompts or account id.
    return {
        "timestamp": at,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": {"total_tokens": total}},
            "rate_limits": {
                "primary": {"used_percent": used, "window_minutes": 10080, "resets_at": 1789805412},
                "credits": {"balance": balance},
            },
        },
    }


def jsonl(path: Path, *events):
    return write(path, "".join(json.dumps(event) + "\n" for event in events))


def codex(tmp_path, *events):
    jsonl(tmp_path / "rollout-fixture.jsonl", *(events or [token_event()]))
    return read_codex_token_count(tmp_path)


def registry():
    return PlatformCapabilityRegistry.model_validate(
        json.loads(PLATFORM_CAPABILITY_REGISTRY.read_text())
    )


def enriched(tmp_path, readings=None):
    return enrich_ledger(
        load_quota_spend_ledger(),
        readings
        if readings is not None
        else collect_measurements(tmp_path, tmp_path / "receipts", now=NOW),
        registry=registry(),
        now=NOW,
    )


def test_codex_reader_uses_latest_token_count_not_mtime(tmp_path):
    older = jsonl(tmp_path / "rollout-a.jsonl", token_event(at="2026-09-19T07:00:00Z", used=10))
    newer = jsonl(tmp_path / "rollout-b.jsonl", token_event())
    os.utime(older, (2000000000, 2000000000))
    os.utime(newer, (1, 1))
    assert read_codex_token_count(tmp_path)[0].quantity == 100


def test_codex_reader_maps_resets_at_unix_to_iso_z(tmp_path):
    assert codex(tmp_path)[0].model_dump(mode="json")["resets_at"] == "2026-09-19T08:10:12Z"


def test_codex_reader_parses_credits_balance_decimal_string(tmp_path):
    assert codex(tmp_path)[1].quantity == pytest.approx(4593.22399)
    assert codex(tmp_path)[1].label == "observed"


def test_codex_reader_missing_events_is_unobserved(tmp_path):
    row = read_codex_token_count(tmp_path)[0]
    assert row.label == "unobserved"
    assert row.reason_code == "no_token_count_event"
    assert row.quantity is None


def test_claude_admission_yaml_is_not_weekly_headroom(tmp_path):
    write(
        tmp_path / "claude-subscription-quota-admission-test.yaml",
        "status: quota_available\nobserved_at: 2026-09-19T07:55:00Z\nused_percent: 12\n",
    )
    rows = read_claude_wall_and_spend(tmp_path, tmp_path / "transcripts", now=NOW)
    assert rows[0].label == "unobserved"
    assert not any(row.unit == "percent_used" for row in rows)


def test_claude_wall_yaml_records_resets_at_without_implying_available(tmp_path):
    write(
        tmp_path / "claude-subscription-weekly-limit-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-17T19:40:00Z\nresets_at: 2026-09-18T22:00:00Z\n",
    )
    rows = read_claude_wall_and_spend(tmp_path, tmp_path / "transcripts", now=NOW)
    assert rows[0].quantity is None and rows[0].label == "unobserved"
    wall = rows[1]
    assert wall.label == "wall-signal"
    assert wall.resets_at == datetime(2026, 9, 18, 22, tzinfo=UTC)
    assert not wall.measurement_is_fresh(NOW)


def kimi_fixture(tmp_path):
    sessions = tmp_path / "sessions"
    write(
        sessions / "a/b/logs/kimi-code.log",
        "2026-09-19T07:00:00Z HTTP 403 weekly (7-day) usage limit\n"
        "2026-09-19T07:05:00Z HTTP 403 weekly (7-day) usage limit\n",
    )
    write(sessions / "c/d/logs/kimi-code.log", "2026-09-19T07:00:00Z HTTP 200\n")
    write(tmp_path / "logs/kimi-code.log", "global no limits\n")
    return sessions


def test_kimi_403_is_wall_signal_not_fraction(tmp_path):
    row = read_kimi_403_signal(kimi_fixture(tmp_path))[0]
    assert row.label == "wall-signal" and row.quantity is None and row.unit == "refusal"
    assert row.details["files_with_hit"] == 1 and row.details["hit_count"] == 2
    assert row.details["first_seen_at"] == "2026-09-19T07:00:00+00:00"


def test_kimi_global_log_counted_separately(tmp_path):
    sessions = kimi_fixture(tmp_path)
    row = read_kimi_403_signal(sessions)[0]
    assert row.details["global_log_hits"] == 0 and row.details["hit_count"] == 2
    write(
        tmp_path / "logs/kimi-code.log",
        "2026-09-19T07:05:00Z HTTP 403 weekly (7-day) usage limit\n",
    )
    row = read_kimi_403_signal(sessions)[0]
    assert row.details["global_log_hits"] == 1 and row.details["hit_count"] == 2


def test_ledger_always_has_codex_claude_kimi_rows(tmp_path):
    rows = enriched(tmp_path).quota_snapshots
    assert {
        "codex",
        "claude",
        "kimi",
        "grok",
        "muse",
        "agy",
        "vibe",
        "qwencloud",
        "fugu",
        "aperture",
        "glm",
        "local",
        "api",
    } <= {r.family for r in rows}
    assert all(r.label == "unobserved" for r in rows)


def test_freeze_active_when_codex_used_percent_100_and_before_reset(tmp_path):
    freeze = freeze_predicate(codex(tmp_path), now=NOW)
    assert freeze["active"] and freeze["families"] == ["codex"]
    assert freeze["until"] == "2026-09-19T08:10:12Z"


def test_freeze_inactive_after_resets_at(tmp_path):
    assert not freeze_predicate(codex(tmp_path), now=NOW + timedelta(hours=1))["active"]


def test_write_is_atomic(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(SCRIPT))
    out = write(tmp_path / "ledger.json", '{"previous":"intact"}\n')

    def crash(*args):
        raise OSError("crash before replace")

    monkeypatch.setattr(namespace["os"], "replace", crash)
    with pytest.raises(OSError):
        namespace["write_ledger_atomic"](enriched(tmp_path), out)
    assert json.loads(out.read_text()) == {"previous": "intact"}
    assert list(tmp_path.glob(".ledger.json.*.tmp")) == []


def test_check_does_not_write(tmp_path, monkeypatch, capsys):
    namespace = runpy.run_path(str(SCRIPT))

    def forbidden(*args, **kwargs):
        raise AssertionError("--check must never probe, refresh, mint or write")

    monkeypatch.setattr(namespace["subprocess"], "run", forbidden)
    monkeypatch.setattr(namespace["os"], "replace", forbidden)
    out = tmp_path / "out/ledger.json"
    assert (
        namespace["main"](
            [
                "--check",
                "--out",
                str(out),
                "--trace-home",
                str(tmp_path),
                "--relay-receipt-dir",
                str(tmp_path / "receipts"),
                "--now",
                NOW.isoformat(),
            ]
        )
        == 0
    )
    assert not out.parent.exists()
    assert json.loads(capsys.readouterr().out)["schema_version"] == 2


def test_stale_event_never_reported_fresh(tmp_path):
    rows = codex(tmp_path, token_event(at="2026-09-18T23:00:00Z"))
    result = enriched(tmp_path, {"codex": rows})
    row = next(r for r in result.quota_snapshots if r.family == "codex")
    assert row.label == "observed" and not row.measurement_is_fresh(NOW)
    assert row.observed_at == datetime(2026, 9, 18, 23, tzinfo=UTC)
    assert row.stage == "declared-unmeasured"


def claude_message(at="2026-09-19T07:30:00Z", output=5, msg_id="fixture-id"):
    return {
        "timestamp": at,
        "type": "assistant",
        "message": {
            "id": msg_id,
            "role": "assistant",
            "usage": {"input_tokens": 10, "output_tokens": output},
        },
    }


def test_derived_is_never_promoted_to_observed(tmp_path):
    jsonl(tmp_path / "transcripts/a.jsonl", claude_message(output=1), claude_message())
    jsonl(
        tmp_path / "transcripts/b.jsonl",
        claude_message(),
        claude_message(at="2026-09-19T01:00:00Z", msg_id="older"),
    )
    rows = read_claude_wall_and_spend(tmp_path, tmp_path / "transcripts", now=NOW)
    spend = {r.capacity_id: r for r in rows if r.capacity_id.startswith("claude.spend")}
    assert spend["claude.spend.5h"].quantity == 15
    assert spend["claude.spend.day"].quantity == 30
    assert spend["claude.spend.5h"].details["message_id_count"] == 1
    assert all(r.label == "derived" for r in spend.values())
    projected = next(
        r for r in enriched(tmp_path, {"claude": rows}).quota_snapshots if r.family == "claude"
    )
    assert projected.label == "unobserved"
    assert all(r.label == "derived" for r in projected.measurements if r.unit == "tokens")


def test_wall_without_reset_is_not_headroom(tmp_path):
    wall = read_kimi_403_signal(kimi_fixture(tmp_path))[0]
    result = enriched(tmp_path, {"kimi": [wall]})
    row = next(r for r in result.quota_snapshots if r.family == "kimi")
    assert row.resets_at is None and row.quantity is None and row.label == "wall-signal"
    assert row.subscription_quota_state == "unknown"
    assert row.stage == "declared-unmeasured"


def test_unattributed_consumption_detector(tmp_path):
    events = [token_event(balance="100"), token_event(at="2026-09-19T07:55:00Z", balance="90")]
    rows = codex(tmp_path, *events)
    delta = [r for r in rows if r.capacity_id.endswith("unattributed_consumption")]
    assert len(delta) == 1 and delta[0].quantity == 10 and delta[0].label == "derived"
    # Activity in a different rollout must suppress attribution too.
    activity = token_event(at="2026-09-19T07:52:00Z", balance="100", total=20)
    activity["payload"]["rate_limits"] = None
    jsonl(tmp_path / "rollout-other.jsonl", activity)
    assert not any(
        r.capacity_id.endswith("unattributed_consumption") for r in read_codex_token_count(tmp_path)
    )


@pytest.mark.parametrize("family", ["glm", "agy"])
def test_receipt_family_source(tmp_path, family):
    prefix = "glmcp" if family == "glm" else family
    write(
        tmp_path / f"{prefix}-quota-admission.yaml",
        "status: quota_available\nobserved_at: 2026-09-19T07:55:00Z\n",
    )
    row = read_receipt_measurements(tmp_path, family)[0]
    assert row.label == "unobserved" and row.quantity is None
    assert row.reason_code == "admission_witness_has_no_quantity"
    write(
        tmp_path / f"{prefix}-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-19T07:55:00Z\n",
    )
    assert any(r.label == "wall-signal" for r in read_receipt_measurements(tmp_path, family))


@pytest.mark.parametrize(
    "family,relative",
    [
        ("grok", ".grok/sessions/a/events.jsonl"),
        ("muse", ".local/share/muse/a/session.jsonl"),
        ("qwencloud", ".qwencloud/logs/usage.jsonl"),
        ("vibe", ".vibe/logs/session/a/meta.json"),
    ],
)
def test_other_family_source(tmp_path, family, relative):
    event = {
        "timestamp": "2026-09-19T07:50:00Z",
        "rate_limits": {"used_percent": 3, "window_minutes": 10080},
    }
    jsonl(tmp_path / relative, event)
    row = read_other_family(tmp_path, family)[0]
    assert row.quantity == 3 and row.label == "observed"
    assert row.observed_at == datetime(2026, 9, 19, 7, 50, tzinfo=UTC)
    # User text containing fake numbers is never recognized as telemetry.
    jsonl(tmp_path / relative, {"content": event})
    assert read_other_family(tmp_path, family)[0].label == "unobserved"


def test_vibe_api_binding_and_undeclared_routes(tmp_path):
    write(
        tmp_path / ".vibe/whoami_cache.json",
        json.dumps(
            {
                "private-account-hash": {
                    "payload": {"plan_type": "api", "email": "private@example.invalid"}
                }
            }
        ),
    )
    result = enriched(tmp_path)
    rows = {r.family: r for r in result.quota_snapshots}
    assert rows["vibe"].stage == "unusable" and rows["vibe"].owner == "operator"
    assert rows["grok"].route_id is None and rows["grok"].stage == "usable-undeclared"
    assert rows["aperture"].route_id is None and rows["aperture"].stage == "unusable"
    assert (
        "private-account" not in result.model_dump_json()
        and "private@example" not in result.model_dump_json()
    )


def test_operator_report_is_refused_while_the_live_ledger_is_schema_1(tmp_path, monkeypatch):
    monkeypatch.delenv("HAPAX_QUOTA_LEDGER_LIVE_SCHEMA", raising=False)
    namespace = runpy.run_path(str(SCRIPT))
    out = tmp_path / "ledger.json"
    namespace["write_ledger_atomic"](enriched(tmp_path), out, schema_version=1)
    before = out.read_bytes()
    argv = [
        "operator-report",
        "--family",
        "kimi",
        "--reset",
        "x",
        "--quote",
        "q",
        "--out",
        str(out),
    ]
    assert namespace["main"](argv) == 1
    assert out.read_bytes() == before


def test_operator_report_preserves_ambiguous_reset_and_append(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HAPAX_QUOTA_LEDGER_LIVE_SCHEMA", "2")
    report = operator_report(
        family="glm",
        reset="2026-09-19 22:36",
        quote="Weekly 100%; console timezone unspecified",
        at=NOW,
    )
    assert report.label == "operator-reported" and report.resets_at is None
    assert report.details["reset_as_reported"] == "2026-09-19 22:36"
    namespace = runpy.run_path(str(SCRIPT))
    out = tmp_path / "ledger.json"
    namespace["write_ledger_atomic"](enriched(tmp_path), out)
    assert (
        namespace["main"](
            [
                "operator-report",
                "--family",
                "kimi",
                "--reset",
                "2026-09-23 19:57",
                "--quote",
                "Operator reported reset",
                "--at",
                NOW.isoformat(),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    loaded = load_quota_spend_ledger(out)
    assert (
        len(loaded.operator_reports) == 1
        and loaded.operator_reports[0].label == "operator-reported"
    )
    with pytest.raises(ValueError):
        operator_report(family="kimi", reset="unknown", quote="api_key=sk-test-secret", at=NOW)


def test_schema_v1_migration_and_old_reader_projection(tmp_path):
    base = load_quota_spend_ledger()
    v2 = enriched(tmp_path)
    assert v2.schema_version == 2
    v1 = v2.schema_v1_payload()
    assert v1["schema_version"] == 1 and "freeze" not in v1 and "operator_reports" not in v1
    assert len(v1["quota_snapshots"]) == len(base.quota_snapshots)
    expected = {
        "quota_snapshot_schema",
        "snapshot_id",
        "captured_at",
        "fresh_until",
        "route_id",
        "provider",
        "capacity_pool",
        "subscription_quota_state",
        "evidence_refs",
        "operator_visible_reason",
    }
    assert all(
        set(row) == expected and row["quota_snapshot_schema"] == 1 for row in v1["quota_snapshots"]
    )
    restored = QuotaSpendLedger.model_validate(v1)
    for row in base.quota_snapshots:
        assert subscription_quota_state_for_route(
            restored, row.route_id, now=NOW
        ) == subscription_quota_state_for_route(base, row.route_id, now=NOW)
        assert subscription_quota_state_for_route(
            v2, row.route_id, now=NOW
        ) == subscription_quota_state_for_route(base, row.route_id, now=NOW)


def test_corrupt_existing_source_fails_without_leaking_contents(tmp_path):
    write(tmp_path / "rollout-bad.jsonl", '"token_count" secret-material malformed\n')
    with pytest.raises(TraceReadError) as error:
        read_codex_token_count(tmp_path)
    assert "secret-material" not in str(error.value)


@pytest.mark.parametrize(
    "family,reason",
    [
        ("fugu", "no_existing_local_usage_capture"),
        ("aperture", "no_reachable_local_resource_capture"),
    ],
)
def test_capacity_without_source_is_explicit(tmp_path, family, reason):
    row = read_other_family(tmp_path, family)[0]
    assert row.label == "unobserved" and row.quantity is None and row.reason_code == reason


def test_muse_actual_journal_usage_source(tmp_path):
    jsonl(
        tmp_path / ".local/share/muse/a/session.jsonl",
        {
            "payload_type": "runtime.session",
            "recorded_at": 1789829322283803,
            "payload": {
                "event": {
                    "kind": "model_completed",
                    "usage": {
                        "input_tokens": 17,
                        "output_tokens": 4,
                    },
                }
            },
        },
    )
    rows = read_other_family(tmp_path, "muse")
    assert rows[0].label == "unobserved" and rows[0].quantity is None
    usage = {row.capacity_id: row for row in rows[1:]}
    assert set(usage) == {"muse.usage.input_tokens", "muse.usage.output_tokens"}
    assert usage["muse.usage.input_tokens"].quantity == 17
    assert usage["muse.usage.output_tokens"].quantity == 4
    assert all(
        row.label == "observed" and row.window == "last_model_completion" for row in rows[1:]
    )


def test_vibe_actual_session_stats_source(tmp_path):
    jsonl(
        tmp_path / ".vibe/logs/session/a/meta.json",
        {
            "end_time": "2026-09-19T07:50:00Z",
            "username": "must-not-escape",
            "stats": {"session_total_llm_tokens": 21, "session_cost": 0.002},
        },
    )
    rows = read_other_family(tmp_path, "vibe")
    assert rows[0].label == "unobserved"
    usage = {row.capacity_id: row for row in rows[1:]}
    assert usage["vibe.usage.session_total_llm_tokens"].quantity == 21
    assert usage["vibe.usage.session_cost"].quantity == 0.002
    assert all(row.label == "derived" for row in rows[1:])
    assert "must-not-escape" not in str(rows)


def test_claude_harness_notice_source(tmp_path):
    jsonl(
        tmp_path / "a.jsonl",
        {
            "timestamp": "2026-09-19T07:50:00Z",
            "isApiErrorMessage": True,
            "message": {"content": "You've hit your limit; resets 2026-09-19T09:00:00Z"},
        },
    )
    rows = read_claude_wall_and_spend(tmp_path, tmp_path, now=NOW)
    wall = next(row for row in rows if row.capacity_id.endswith("harness_wall"))
    assert wall.label == "wall-signal" and wall.quantity is None
    assert wall.resets_at == datetime(2026, 9, 19, 9, tzinfo=UTC)


def test_every_registry_family_is_projected(tmp_path):
    reg = registry()
    # Unknown future platform names must also remain visible; no closed hardcoded family set.
    from shared.quota_headroom import FAMILY_ALIASES

    # With no family facts the stage check must not elevate it; use a blocked existing route's facts.
    extra = reg.routes[0].model_copy(
        update={"platform": "fixture_future", "route_id": "fixture.future"}
    )
    reg = reg.model_copy(update={"routes": [*reg.routes, extra]})
    result = enrich_ledger(load_quota_spend_ledger(), {}, registry=reg, now=NOW)
    assert {FAMILY_ALIASES.get(str(r.platform), str(r.platform)) for r in reg.routes} <= {
        r.family for r in result.quota_snapshots
    }


# The Claude subscription windows are provider-reported quantities. Record shapes are copied
# from local CLI stream-json output with identifiers replaced; no prompt or response content.
A1_NOW = datetime(2026, 9, 24, 18, 30, tzinfo=UTC)
RESET_5H = 1790285400  # 2026-09-24T21:30:00Z
RESET_7D = 1790373600  # 2026-09-25T22:00:00Z


def unified_info(five=0.08, seven=0.09):
    return {
        "status": "allowed",
        "resetsAt": RESET_5H,
        "rateLimitType": "five_hour",
        "overageStatus": "rejected",
        "overageDisabledReason": "out_of_credits",
        "isUsingOverage": False,
        "unifiedWindows": {
            "five_hour": {"utilization": five, "resetsAt": RESET_5H},
            "seven_day": {"utilization": seven, "resetsAt": RESET_7D},
        },
    }


def rate_limit_event(info, session="fixture-session"):
    return {"type": "rate_limit_event", "rate_limit_info": info, "uuid": "u", "session_id": session}


def stream_init(session="fixture-session", model="claude-opus-5-5", auth_source="none"):
    return {
        "type": "system",
        "subtype": "init",
        "session_id": session,
        "model": model,
        "apiKeySource": auth_source,
    }


def stream_dated(at, session="fixture-session"):
    return {"type": "user", "session_id": session, "timestamp": at, "message": {"role": "user"}}


def claude_stream(tmp_path, *records, lane="lane"):
    return jsonl(tmp_path / "claude-headless" / lane / "output.jsonl", *records)


def claude_rows(tmp_path, now=A1_NOW):
    return read_claude_wall_and_spend(
        tmp_path / "receipts",
        tmp_path / "transcripts",
        now=now,
        stream_root=tmp_path / "claude-headless",
    )


def by_id(rows):
    return {row.capacity_id: row for row in rows}


def enriched_at(readings, now=A1_NOW):
    return enrich_ledger(load_quota_spend_ledger(), readings, registry=registry(), now=now)


def probe_receipt(tmp_path, *, at="2026-09-24T18:00:00Z", seven=9.0, five=8.0, **overrides):
    """A receipt as the admission writer renders it for a probe that saw both windows."""
    fields = {
        "schema": "hapax.claude_quota_admission.v1",
        "status": "quota_available",
        "provider": "anthropic-claude-subscription",
        "route_id": "claude.headless.full",
        "capacity_pool": "subscription_quota",
        "auth_surface": "subscription",
        "observation": "subscription_quota_headroom_observed",
        "probe_environment_scrubbed": (
            "ANTHROPIC_BASE_URL,ANTHROPIC_AUTH_TOKEN,ANTHROPIC_API_KEY,ANTHROPIC_MODEL"
        ),
        "observed_at": at,
        "stale_after_seconds": 1800,
        "evidence_ref": "claude-subscription-headroom-observed-20260924t180000z",
        "secret_source": "claude:operator-session-subscription",  # pragma: allowlist secret
        "secret_value_persisted": "false",  # pragma: allowlist secret
        "prompt_or_output_persisted": "false",
        "billing_mode": "operator_session_subscription",
        "account_live_quota_observed": "true",
        "lane_presence_used_as_quota_evidence": "false",
        "positive_admission": "true",
        "five_hour_used_percent": five,
        "five_hour_resets_at": "2026-09-24T21:30:00Z",
        "seven_day_used_percent": seven,
        "seven_day_resets_at": "2026-09-25T22:00:00Z",
    }
    fields.update(overrides)
    stamp = at.replace("-", "").replace(":", "").lower()
    return write(
        tmp_path
        / f"receipts/claude-subscription-quota-admission-claude-headless-full-{stamp}.yaml",
        "".join(f"{key}: {value}\n" for key, value in fields.items() if value is not None),
    )


def test_claude_unified_windows_are_observed_fractions(tmp_path):
    claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T18:20:00Z"),
        rate_limit_event(unified_info()),
    )
    rows = claude_rows(tmp_path)
    assert {"claude.subscription.weekly", "claude.subscription.five_hour"} <= set(by_id(rows))
    weekly, five_hour = rows[0], by_id(rows)["claude.subscription.five_hour"]
    assert weekly.capacity_id == "claude.subscription.weekly"
    assert (weekly.label, weekly.quantity, weekly.unit) == ("observed", 9.0, "percent_used")
    assert (weekly.window, five_hour.window) == ("10080m", "300m")
    assert weekly.resets_at == datetime(2026, 9, 25, 22, tzinfo=UTC)
    assert five_hour.quantity == 8.0
    assert five_hour.resets_at == datetime(2026, 9, 24, 21, 30, tzinfo=UTC)
    assert weekly.observed_at == datetime(2026, 9, 24, 18, 20, tzinfo=UTC)
    assert weekly.measurement_is_fresh(A1_NOW)


def test_claude_legacy_single_window_event_is_read(tmp_path):
    legacy = {
        "status": "allowed_warning",
        "resetsAt": RESET_7D,
        "rateLimitType": "seven_day",
        "utilization": 0.99,
        "isUsingOverage": False,
        "surpassedThreshold": 0.75,
    }
    assert claude_rate_limit_windows(legacy) == {
        "seven_day": (99.0, datetime(2026, 9, 25, 22, tzinfo=UTC))
    }
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:20:00Z"), rate_limit_event(legacy)
    )
    rows = by_id(claude_rows(tmp_path))
    assert rows["claude.subscription.weekly"].quantity == 99.0
    assert "claude.subscription.five_hour" not in rows


@pytest.mark.parametrize(
    "info",
    [
        {"status": "allowed", "isUsingOverage": False},
        {"status": "allowed", "rateLimitType": "five_hour", "resetsAt": RESET_5H},
        unified_info(five=None, seven=True),
        unified_info(five="0.5", seven=float("nan")),
        {
            "status": "allowed",
            "unifiedWindows": {
                "five_hour": {"utilization": -0.01, "resetsAt": RESET_5H},
                "seven_day": {"utilization": 0.2},
            },
        },
        {
            "status": "allowed_warning",
            "rateLimitType": "seven_day_overage_included",
            "utilization": 0.5,
            "resetsAt": RESET_7D,
        },
    ],
)
def test_claude_window_without_a_numeric_reading_is_absent_never_zero(tmp_path, info):
    assert claude_rate_limit_windows(info) == {}
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:20:00Z"), rate_limit_event(info)
    )
    rows = claude_rows(tmp_path)
    assert rows[0].label == "unobserved" and rows[0].quantity is None
    assert rows[0].reason_code == "no_claude_rate_limit_window_observed"
    assert not any(row.unit == "percent_used" for row in rows)


def test_claude_stream_event_is_never_dated_by_file_mtime(tmp_path):
    # Nothing dated precedes the event, so nothing supplies its time: not evidence.
    stream = claude_stream(tmp_path, stream_init(), rate_limit_event(unified_info()))
    os.utime(stream, (A1_NOW.timestamp(), A1_NOW.timestamp()))
    assert claude_rows(tmp_path)[0].label == "unobserved"
    # An earlier dated record bounds the event; the fresh mtime never does.
    claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T10:00:00Z"),
        rate_limit_event(unified_info()),
    )
    os.utime(stream, (A1_NOW.timestamp(), A1_NOW.timestamp()))
    weekly = claude_rows(tmp_path)[0]
    assert weekly.observed_at == datetime(2026, 9, 24, 10, tzinfo=UTC)
    assert not weekly.measurement_is_fresh(A1_NOW)


def test_claude_reading_dated_after_now_is_ignored(tmp_path):
    claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T19:00:00Z"),
        rate_limit_event(unified_info()),
    )
    assert claude_rows(tmp_path)[0].label == "unobserved"


def test_claude_stream_older_than_any_open_window_is_not_read(tmp_path):
    stream = claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T18:20:00Z"),
        rate_limit_event(unified_info()),
    )
    old = (A1_NOW - timedelta(days=9)).timestamp()
    os.utime(stream, (old, old))
    assert claude_rows(tmp_path)[0].label == "unobserved"


@pytest.mark.parametrize(
    "init",
    [
        None,
        stream_init(model="glm-5.3"),
        stream_init(model="<synthetic>"),
        stream_init(auth_source="ANTHROPIC_API_KEY"),
        stream_init(session="another-session"),
    ],
)
def test_claude_stream_outside_a_subscription_session_is_not_the_subscription(tmp_path, init):
    records = [stream_dated("2026-09-24T18:20:00Z"), rate_limit_event(unified_info())]
    claude_stream(tmp_path, *([init] if init else []), *records)
    rows = claude_rows(tmp_path)
    assert rows[0].label == "unobserved"
    assert not any(row.unit == "percent_used" for row in rows)


def test_claude_newest_reading_wins_across_streams_and_probe_receipts(tmp_path):
    older = claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T17:00:00Z"),
        rate_limit_event(unified_info(seven=0.5)),
        lane="a",
    )
    probe_receipt(tmp_path, at="2026-09-24T18:00:00Z", seven=60.0)
    os.utime(older, (A1_NOW.timestamp(), A1_NOW.timestamp()))
    weekly = claude_rows(tmp_path)[0]
    assert weekly.quantity == 60.0
    assert weekly.observed_at == datetime(2026, 9, 24, 18, tzinfo=UTC)
    claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T18:10:00Z"),
        rate_limit_event(unified_info(seven=0.7)),
        lane="b",
    )
    assert claude_rows(tmp_path)[0].quantity == 70.0


def test_claude_probe_receipt_is_read(tmp_path):
    probe_receipt(tmp_path)
    rows = by_id(claude_rows(tmp_path))
    weekly = rows["claude.subscription.weekly"]
    assert (weekly.label, weekly.quantity, weekly.window) == ("observed", 9.0, "10080m")
    assert weekly.observed_at == datetime(2026, 9, 24, 18, tzinfo=UTC)
    assert rows["claude.subscription.five_hour"].quantity == 8.0
    assert weekly.source.startswith("local-trace:claude_probe_admission_receipt:")


@pytest.mark.parametrize(
    "overrides",
    [
        {"observation": "operator_confirmed_subscription_headroom"},
        {"probe_environment_scrubbed": None},
        {"schema": "hapax.claude_quota_admission.v0"},
        {"status": "quota_blocked"},
        {"auth_surface": "api"},
        {"seven_day_used_percent": "-1", "five_hour_used_percent": "nan"},
        {
            "seven_day_resets_at": "2026-09-24T17:00:00Z",
            "five_hour_resets_at": "2026-09-24T17:00:00Z",
        },
    ],
)
def test_claude_receipt_fraction_requires_a_probe_backed_subscription_receipt(tmp_path, overrides):
    probe_receipt(tmp_path, **overrides)
    rows = claude_rows(tmp_path)
    assert rows[0].label == "unobserved"
    assert not any(row.unit == "percent_used" for row in rows)


def test_claude_rejected_window_is_a_wall_with_its_reset(tmp_path):
    rejected = {
        "status": "rejected",
        "resetsAt": RESET_7D,
        "rateLimitType": "seven_day",
        "overageStatus": "rejected",
        "isUsingOverage": False,
    }
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:20:00Z"), rate_limit_event(rejected)
    )
    rows = claude_rows(tmp_path)
    assert "claude.subscription.rate_limit_rejected" in by_id(rows)
    wall = by_id(rows)["claude.subscription.rate_limit_rejected"]
    assert (wall.label, wall.quantity, wall.window) == ("wall-signal", None, "10080m")
    assert wall.resets_at == datetime(2026, 9, 25, 22, tzinfo=UTC)
    assert freeze_predicate(rows, now=A1_NOW)["families"] == ["claude"]


def test_claude_overage_refusal_alone_is_not_a_wall(tmp_path):
    claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T18:20:00Z"),
        rate_limit_event(unified_info()),
    )
    rows = claude_rows(tmp_path)
    assert not any(row.label == "wall-signal" for row in rows)
    assert not freeze_predicate(rows, now=A1_NOW)["active"]


def test_wall_stands_until_a_newer_provider_observation(tmp_path):
    write(
        tmp_path / "receipts/claude-weekly-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-24T18:00:00Z\n"
        "resets_at: 2026-09-25T22:00:00Z\n",
    )
    older = [stream_init(), stream_dated("2026-09-24T17:50:00Z"), rate_limit_event(unified_info())]
    claude_stream(tmp_path, *older)
    rows = claude_rows(tmp_path)
    assert wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW)
    assert freeze_predicate(rows, now=A1_NOW)["active"]
    snapshot = next(
        r for r in enriched_at({"claude": rows}).quota_snapshots if r.family == "claude"
    )
    assert "post-wall" in snapshot.next_act

    claude_stream(
        tmp_path, *older, stream_dated("2026-09-24T18:10:00Z"), rate_limit_event(unified_info())
    )
    rows = claude_rows(tmp_path)
    assert not wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW)
    assert not freeze_predicate(rows, now=A1_NOW)["active"]
    snapshot = next(
        r for r in enriched_at({"claude": rows}).quota_snapshots if r.family == "claude"
    )
    assert "post-wall" not in snapshot.next_act


def test_transcript_spend_never_supersedes_a_wall(tmp_path):
    # Transcripts also hold other providers speaking the Claude wire format.
    write(
        tmp_path / "receipts/claude-weekly-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-24T18:00:00Z\n",
    )
    jsonl(tmp_path / "transcripts/a.jsonl", claude_message(at="2026-09-24T18:20:00Z"))
    rows = claude_rows(tmp_path)
    assert any(row.label == "derived" for row in rows)
    assert wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW)


def test_window_scoped_wall_needs_a_reading_of_the_same_window(tmp_path):
    rejected = {"status": "rejected", "resetsAt": RESET_7D, "rateLimitType": "seven_day"}
    five_only = {
        "status": "allowed_warning",
        "resetsAt": RESET_5H,
        "rateLimitType": "five_hour",
        "utilization": 0.9,
        "isUsingOverage": False,  # a witnessed serve, so only the window clause can hold the wall
    }
    claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T18:00:00Z"),
        rate_limit_event(rejected),
        stream_dated("2026-09-24T18:05:00Z"),  # dates the wall late: 18:05
        stream_dated("2026-09-24T18:10:00Z"),
        rate_limit_event(five_only),  # served, newer (18:10), but another window
    )
    rows = claude_rows(tmp_path)
    wall = by_id(rows)["claude.subscription.rate_limit_rejected"]
    reading = by_id(rows)["claude.subscription.five_hour"]
    assert wall.observed_at < reading.observed_at  # only the window keeps it standing
    assert wall_is_live(wall, rows, now=A1_NOW)


def test_kimi_response_is_a_served_turn_but_never_lifts_the_wall(tmp_path):
    # Kimi can serve from a paid booster wallet after its weekly quota (E0 census), so a served
    # response does not witness subscription quota. It is still the last served turn.
    sessions = kimi_fixture(tmp_path)
    write(
        sessions / "e/f/logs/kimi-code.log",
        "2026-09-19T07:30:00.209Z INFO  llm response  turnStep=0.40 ttftMs=4014 "
        "outputTokens=487 serverDecodeMs=1\n",
    )
    rows = read_kimi_403_signal(sessions)
    assert "kimi.usage.last_response" in by_id(rows)
    served = by_id(rows)["kimi.usage.last_response"]
    assert (served.label, served.quantity, served.unit) == ("observed", 487, "tokens")
    assert served.observed_at == datetime(2026, 9, 19, 7, 30, 0, 209000, tzinfo=UTC)
    assert rows[0].label == "wall-signal"
    assert wall_is_live(rows[0], rows, now=NOW)


def test_a_windowless_wall_without_a_reset_binds_no_longer_than_its_window(tmp_path):
    # The 403 names a weekly (7-day) limit: it cannot bind past a week after it, with no
    # reset invented for the row itself.
    rows = read_kimi_403_signal(kimi_fixture(tmp_path))  # newest 403 at 2026-09-19T07:05Z
    assert rows[0].resets_at is None
    assert wall_is_live(rows[0], rows, now=datetime(2026, 9, 26, 7, 4, tzinfo=UTC))
    assert not wall_is_live(rows[0], rows, now=datetime(2026, 9, 26, 7, 6, tzinfo=UTC))


@pytest.mark.parametrize(
    "line",
    [
        "2026-09-19T07:30:00Z INFO  llm response  turnStep=0.1 outputTokens=0\n",
        "2026-09-19T07:30:00Z INFO  llm request  turnStep=0.1\n",
        "note: 2026-09-19T07:30:00Z INFO  llm response outputTokens=487\n",
    ],
)
def test_kimi_non_responses_are_not_served_turns(tmp_path, line):
    sessions = kimi_fixture(tmp_path)
    write(sessions / "e/f/logs/kimi-code.log", line)
    assert "kimi.usage.last_response" not in by_id(read_kimi_403_signal(sessions))


def test_derived_evidence_never_lifts_a_wall_even_if_it_claims_a_serve():
    # Defence in depth under the witness rule: the label is checked on its own, so a derived
    # row that somehow carried the witness still lifts nothing.
    from shared.quota_headroom import evidence

    wall = evidence(
        "claude.subscription.wall",
        at=datetime(2026, 9, 24, 18, tzinfo=UTC),
        label="wall-signal",
        unit="refusal",
        source="fixture",
        reason_code="fixture_wall",
    )
    derived = evidence(
        "claude.spend.5h",
        at=datetime(2026, 9, 24, 18, 10, tzinfo=UTC),
        quantity=5,
        unit="tokens",
        label="derived",
        source="fixture",
        details={"subscription_served": 1},
    )
    assert wall_is_live(wall, [wall, derived], now=A1_NOW)


def test_a_reading_without_a_subscription_witness_never_lifts_a_wall(tmp_path):
    # Rows that do not say the subscription served them (other families' usage, derived
    # spend) never lift a wall: parity with the Claude refusal/overage rule.
    from shared.quota_headroom import evidence

    wall = read_kimi_403_signal(kimi_fixture(tmp_path))[0]
    later = evidence(
        "kimi.subscription.usage",
        at=datetime(2026, 9, 19, 7, 30, tzinfo=UTC),
        quantity=3,
        unit="percent_used",
        label="observed",
        source="fixture",
    )
    assert wall_is_live(wall, [wall, later], now=NOW)


def test_any_failure_in_one_family_stays_in_that_family(tmp_path, monkeypatch):
    import shared.quota_headroom as quota_headroom

    def broken(*args, **kwargs):
        raise ValueError("unexpected shape")

    monkeypatch.setattr(quota_headroom, "read_kimi_403_signal", broken)
    jsonl(tmp_path / ".codex/sessions/rollout-a.jsonl", token_event())
    try:
        readings = collect_measurements(tmp_path, tmp_path / "receipts", now=NOW)
    except ValueError:
        readings = None
    assert readings is not None, "one family's failure stopped every family"
    assert readings["codex"][0].label == "observed"
    assert readings["kimi"][0].reason_code == "reader_error"


@pytest.mark.parametrize("flag", [1, "true", "yes"])
def test_any_truthy_overage_flag_is_overage(tmp_path, flag):
    write(
        tmp_path / "receipts/claude-weekly-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-24T18:00:00Z\n",
    )
    info = unified_info() | {"isUsingOverage": flag}
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:10:00Z"), rate_limit_event(info)
    )
    rows = claude_rows(tmp_path)
    assert wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW)


def test_the_ledger_writer_defaults_to_the_live_schema(tmp_path):
    namespace = runpy.run_path(str(SCRIPT))
    out = tmp_path / "ledger.json"
    namespace["write_ledger_atomic"](enriched(tmp_path), out)
    assert json.loads(out.read_text())["schema_version"] == 1


def test_collect_reads_claude_headless_streams_into_the_ledger(tmp_path):
    jsonl(
        tmp_path / ".cache/hapax/claude-headless/lane/output.jsonl",
        stream_init(),
        stream_dated("2026-09-24T18:20:00Z"),
        rate_limit_event(unified_info()),
    )
    readings = collect_measurements(tmp_path, tmp_path / "receipts", now=A1_NOW)
    snapshot = next(r for r in enriched_at(readings).quota_snapshots if r.family == "claude")
    assert (snapshot.capacity_id, snapshot.label, snapshot.quantity) == (
        "claude.subscription.weekly",
        "observed",
        9.0,
    )
    assert snapshot.stage in {"declared-measured", "routable"}


# H1 #3: burn per hour, derived from two readings of the same window.


def weekly_readings(tmp_path, *points, reset=RESET_7D, prefix="l"):
    """Stream readings of the seven-day window at (time, utilization) points, one lane each."""
    for index, (at, utilization) in enumerate(points):
        info = {"status": "allowed", "unifiedWindows": {}}
        info["unifiedWindows"]["seven_day"] = {"utilization": utilization, "resetsAt": reset}
        claude_stream(
            tmp_path,
            stream_init(),
            stream_dated(at),
            rate_limit_event(info),
            lane=f"{prefix}{index}",
        )


def burn(rows):
    return by_id(rows).get("claude.subscription.weekly.burn")


def test_burn_is_derived_from_two_readings_of_the_same_window(tmp_path):
    weekly_readings(tmp_path, ("2026-09-24T17:20:00Z", 0.05), ("2026-09-24T18:20:00Z", 0.08))
    row = burn(claude_rows(tmp_path))
    assert row is not None
    assert (row.label, row.unit, row.quantity) == ("derived", "percent_used_per_hour", 3.0)
    assert row.observed_at == datetime(2026, 9, 24, 18, 20, tzinfo=UTC)
    assert row.details["from_percent"] == 5.0 and row.details["to_percent"] == 8.0


def test_burn_pairs_the_oldest_reading_inside_the_span(tmp_path):
    weekly_readings(
        tmp_path,
        ("2026-09-24T11:00:00Z", 0.01),  # more than six hours before the newest
        ("2026-09-24T15:20:00Z", 0.02),
        ("2026-09-24T17:20:00Z", 0.05),
        ("2026-09-24T18:20:00Z", 0.08),
    )
    row = burn(claude_rows(tmp_path))
    assert row is not None and row.quantity == 2.0


@pytest.mark.parametrize(
    "points",
    [
        # A reset between the readings: their difference measures nothing.
        "reset",
        # Too close together: the rate is noise.
        (("2026-09-24T18:10:00Z", 0.05), ("2026-09-24T18:20:00Z", 0.08)),
        # A falling reading is not a burn.
        (("2026-09-24T17:20:00Z", 0.08), ("2026-09-24T18:20:00Z", 0.05)),
        # One reading is not a rate.
        (("2026-09-24T18:20:00Z", 0.08),),
    ],
)
def test_no_burn_without_a_valid_pair(tmp_path, points):
    if points == "reset":
        weekly_readings(tmp_path, ("2026-09-24T17:20:00Z", 0.05), reset=RESET_5H, prefix="a")
        weekly_readings(tmp_path, ("2026-09-24T18:20:00Z", 0.08), prefix="b")
    else:
        weekly_readings(tmp_path, *points)
    assert burn(claude_rows(tmp_path)) is None


def test_burn_never_freezes_or_supersedes(tmp_path):
    weekly_readings(tmp_path, ("2026-09-24T17:20:00Z", 0.05), ("2026-09-24T18:20:00Z", 5.05))
    rows = claude_rows(tmp_path)
    assert burn(rows) is not None and burn(rows).quantity == 500.0
    frozen = freeze_predicate(
        [row for row in rows if row.capacity_id.endswith(".burn")], now=A1_NOW
    )
    assert not frozen["active"]


def test_codex_burn_from_two_token_counts_in_one_window(tmp_path):
    rows = codex(
        tmp_path,
        token_event(at="2026-09-19T05:50:00Z", used=10),
        token_event(at="2026-09-19T07:50:00Z", used=14),
    )
    row = by_id(rows).get("codex.subscription.weekly.burn")
    assert row is not None
    assert (row.label, row.unit, row.quantity) == ("derived", "percent_used_per_hour", 2.0)


# PR #4728 review round 1 (Muse, Gemini, Mistral, CodeRabbit): each reproduced here first.

REJECTED_7D = {"status": "rejected", "resetsAt": RESET_7D, "rateLimitType": "seven_day"}


def test_stream_wall_is_dated_no_earlier_than_the_next_record(tmp_path):
    # The event sits between 18:00 and 18:20; a reading at 18:10 must not lift it.
    claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T18:00:00Z"),
        rate_limit_event(REJECTED_7D),
        stream_dated("2026-09-24T18:20:00Z"),
        lane="w",
    )
    probe_receipt(tmp_path, at="2026-09-24T18:10:00Z")
    rows = claude_rows(tmp_path)
    assert "claude.subscription.rate_limit_rejected" in by_id(rows)
    wall = by_id(rows)["claude.subscription.rate_limit_rejected"]
    assert wall.observed_at == datetime(2026, 9, 24, 18, 20, tzinfo=UTC)
    assert wall.details["earliest_at"] == "2026-09-24T18:00:00+00:00"
    assert wall_is_live(wall, rows, now=A1_NOW)


@pytest.mark.parametrize(
    "mtime,expected",
    [
        (datetime(2026, 9, 24, 18, 25, tzinfo=UTC), datetime(2026, 9, 24, 18, 25, tzinfo=UTC)),
        (A1_NOW + timedelta(hours=1), A1_NOW),
    ],
)
def test_a_last_stream_wall_is_dated_by_the_file_mtime_clamped_to_now(tmp_path, mtime, expected):
    stream = claude_stream(
        tmp_path,
        stream_init(),
        stream_dated("2026-09-24T18:00:00Z"),
        rate_limit_event(REJECTED_7D),
        lane="w",
    )
    os.utime(stream, (mtime.timestamp(), mtime.timestamp()))
    probe_receipt(tmp_path, at="2026-09-24T18:10:00Z")
    rows = claude_rows(tmp_path)
    assert "claude.subscription.rate_limit_rejected" in by_id(rows)
    wall = by_id(rows)["claude.subscription.rate_limit_rejected"]
    assert wall.observed_at == expected
    assert wall_is_live(wall, rows, now=A1_NOW)
    assert freeze_predicate(rows, now=A1_NOW)["active"]


def test_every_live_harness_wall_is_kept(tmp_path):
    notice = {"isApiErrorMessage": True}
    jsonl(
        tmp_path / "transcripts/a.jsonl",
        notice
        | {
            "timestamp": "2026-09-24T17:00:00Z",
            "message": {"content": "You've hit your weekly limit; resets 2026-09-25T22:00:00Z"},
        },
        notice
        | {
            "timestamp": "2026-09-24T18:00:00Z",
            "message": {"content": "Claude usage limit reached; resets 2026-09-24T19:00:00Z"},
        },
    )
    rows = claude_rows(tmp_path)
    resets = sorted(r.resets_at for r in rows if r.capacity_id.endswith("harness_wall"))
    assert resets == [
        datetime(2026, 9, 24, 19, tzinfo=UTC),
        datetime(2026, 9, 25, 22, tzinfo=UTC),
    ]


@pytest.mark.parametrize(
    "info",
    [
        # The subscription refused the request; its windows describe a refusal. The overage
        # flag is explicitly false, so the refusal alone is what stops the lift.
        {
            "status": "rejected",
            "rateLimitType": "five_hour",
            "resetsAt": RESET_5H,
            "isUsingOverage": False,
            "unifiedWindows": {
                "five_hour": {"utilization": 0.3, "resetsAt": RESET_5H},
                "seven_day": {"utilization": 0.5, "resetsAt": RESET_7D},
            },
        },
        # Served from overage, not from the subscription window.
        unified_info() | {"isUsingOverage": True},
    ],
)
def test_a_reading_the_subscription_did_not_serve_never_lifts_a_wall(tmp_path, info):
    write(
        tmp_path / "receipts/claude-weekly-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-24T18:00:00Z\n"
        "resets_at: 2026-09-25T22:00:00Z\n",
    )
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:10:00Z"), rate_limit_event(info)
    )
    rows = claude_rows(tmp_path)
    assert wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW)


def test_a_served_reading_of_any_window_lifts_a_windowless_wall(tmp_path):
    # A request the subscription served, whichever window it reports, means no window was binding.
    write(
        tmp_path / "receipts/claude-weekly-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-24T18:00:00Z\n",
    )
    five_only = {
        "status": "allowed_warning",
        "resetsAt": RESET_5H,
        "rateLimitType": "five_hour",
        "utilization": 0.9,
        "isUsingOverage": False,  # every recorded event carries it (423/423)
    }
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:10:00Z"), rate_limit_event(five_only)
    )
    rows = claude_rows(tmp_path)
    assert not wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW)


def test_codex_reader_ignores_token_counts_dated_after_now(tmp_path):
    jsonl(
        tmp_path / "rollout-a.jsonl",
        token_event(at="2026-09-19T07:50:00Z", used=40),
        token_event(at="2026-09-19T09:00:00Z", used=99),
    )
    assert read_codex_token_count(tmp_path, now=NOW)[0].quantity == 40


def test_claude_lane_wall_receipts_named_by_role_are_read(tmp_path):
    lane = "status: quota_blocked\ndetected_at: 2026-09-19T07:40:00Z\nresets_at: unknown\n"
    write(tmp_path / "beta-quota-wall.yaml", "role: beta\n" + lane)
    write(
        tmp_path / "alpha-quota-wall.yaml", "role: alpha\nroute_id: claude.headless.full\n" + lane
    )
    write(tmp_path / "cx-red-quota-wall.yaml", "role: cx-red\n" + lane)
    write(
        tmp_path / "glm-coding-plan-weekly-limit-quota-wall.yaml",
        "provider: zai-glm-coding-plan\nstatus: quota_blocked\nobserved_at: 2026-09-19T07:40:00Z\n",
    )
    rows = read_claude_wall_and_spend(tmp_path, tmp_path / "transcripts", now=NOW)
    walls = [row for row in rows if row.label == "wall-signal"]
    assert len(walls) == 2


def test_claude_one_million_context_alias_is_a_subscription_session(tmp_path):
    claude_stream(
        tmp_path,
        stream_init(model="claude-opus-5[1m]"),
        stream_dated("2026-09-24T18:20:00Z"),
        rate_limit_event(unified_info()),
    )
    assert claude_rows(tmp_path)[0].label == "observed"


def test_one_corrupt_family_source_never_stops_the_others(tmp_path):
    jsonl(tmp_path / ".codex/sessions/rollout-a.jsonl", token_event())
    log = tmp_path / ".kimi-code/sessions/a/b/logs/kimi-code.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"\xff\xfe 403 weekly usage limit\n")
    try:
        readings = collect_measurements(tmp_path, tmp_path / "receipts", now=NOW)
    except TraceReadError:
        readings = None
    assert readings is not None, "one family's unreadable source stopped every family"
    assert readings["codex"][0].label == "observed"
    assert readings["kimi"][0].label == "unobserved"
    assert readings["kimi"][0].reason_code == "corrupt_or_unreadable_source"


def test_a_partial_last_line_of_a_live_trace_is_not_corruption(tmp_path):
    path = jsonl(tmp_path / "rollout-a.jsonl", token_event())
    with path.open("a") as stream:
        stream.write('{"timestamp": "2026-09-19T07:55:00Z", "payload": {"type": "token_count"')
    try:
        rows = read_codex_token_count(tmp_path)
    except TraceReadError:
        rows = None
    assert rows is not None, "a live writer's unfinished last line was read as corruption"
    assert rows[0].quantity == 100
    # Once the malformed line is followed by another, it is corruption again.
    with path.open("a") as stream:
        stream.write("\n" + json.dumps(token_event()) + "\n")
    with pytest.raises(TraceReadError):
        read_codex_token_count(tmp_path)


def test_a_transcript_untouched_longer_than_any_window_is_not_scanned(tmp_path):
    path = jsonl(tmp_path / "transcripts/a.jsonl", claude_message(at="2026-09-24T18:00:00Z"))
    old = (A1_NOW - timedelta(days=9)).timestamp()
    os.utime(path, (old, old))
    assert by_id(claude_rows(tmp_path))["claude.spend.5h"].label == "unobserved"
    os.utime(path, (A1_NOW.timestamp(), A1_NOW.timestamp()))
    assert by_id(claude_rows(tmp_path))["claude.spend.5h"].label == "derived"


def test_codex_burn_names_both_readings_sources(tmp_path):
    jsonl(tmp_path / "rollout-a.jsonl", token_event(at="2026-09-19T05:50:00Z", used=10))
    jsonl(tmp_path / "rollout-b.jsonl", token_event(at="2026-09-19T07:50:00Z", used=14))
    rows = read_codex_token_count(tmp_path)
    assert "codex.subscription.weekly.burn" in by_id(rows)
    row = by_id(rows)["codex.subscription.weekly.burn"]
    assert row.details["from_source"] != row.source
    assert row.source == by_id(rows)["codex.subscription.weekly"].source


# PR #4728 review round 3.

A_WEEK_LATER = datetime(2026, 10, 1, 18, tzinfo=UTC)


def claude_wall_at_18(tmp_path):
    write(
        tmp_path / "receipts/claude-weekly-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-24T18:00:00Z\n",
    )


def test_a_reading_without_an_overage_field_never_lifts_a_wall(tmp_path):
    # Absent means "not established": only an explicit non-overage serve is a witness.
    claude_wall_at_18(tmp_path)
    info = unified_info()
    del info["isUsingOverage"]
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:10:00Z"), rate_limit_event(info)
    )
    rows = claude_rows(tmp_path)
    assert wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW)


@pytest.mark.parametrize("flag", [False, 0, 0.0, "false", "0", "0.0"])
def test_explicit_non_overage_values_are_not_overage(tmp_path, flag):
    claude_wall_at_18(tmp_path)
    info = unified_info() | {"isUsingOverage": flag}
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:10:00Z"), rate_limit_event(info)
    )
    rows = claude_rows(tmp_path)
    assert not wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW)


@pytest.mark.parametrize("witnessed,live", [(None, True), ("true", False)])
def test_a_probe_receipt_lifts_a_wall_only_when_it_recorded_the_serve(tmp_path, witnessed, live):
    claude_wall_at_18(tmp_path)
    probe_receipt(tmp_path, at="2026-09-24T18:10:00Z", subscription_served=witnessed)
    rows = claude_rows(tmp_path)
    assert "claude.subscription.wall" in by_id(rows)
    assert wall_is_live(by_id(rows)["claude.subscription.wall"], rows, now=A1_NOW) is live


@pytest.mark.parametrize(
    "text,bound_hours",
    [
        ("You've hit your weekly limit · resets Sep 26, 5pm (America/Chicago)", 168),
        ("You've hit your session limit · resets 11pm (America/Chicago)", 5),
        # Names no window: still a Claude limit, and Claude's windows are five_hour and
        # seven_day only (the provider's unifiedWindows keys), so it binds at most 168 h.
        ("Claude usage limit reached", 168),
    ],
)
def test_a_harness_wall_is_bounded_only_by_the_window_it_names(tmp_path, text, bound_hours):
    jsonl(
        tmp_path / "transcripts/a.jsonl",
        {
            "timestamp": "2026-09-24T18:00:00Z",
            "isApiErrorMessage": True,
            "message": {"content": text},
        },
    )
    rows = claude_rows(tmp_path)
    assert "claude.subscription.harness_wall" in by_id(rows)
    wall = by_id(rows)["claude.subscription.harness_wall"]
    assert wall.resets_at is None
    assert wall.details.get("binds_at_most_hours") == bound_hours
    for hours, expected in ((1, True), (200, bound_hours is None)):
        assert wall_is_live(wall, rows, now=wall.observed_at + timedelta(hours=hours)) is expected


@pytest.mark.parametrize("limit,bound_hours", [("seven_day", 168), ("five_hour", 5), (None, 168)])
def test_a_receipt_wall_is_bounded_by_its_recorded_window(tmp_path, limit, bound_hours):
    body = (
        "role: beta\nstatus: quota_blocked\ndetected_at: 2026-09-24T18:00:00Z\nresets_at: unknown\n"
    )
    if limit:
        body += f"rate_limit_type: {limit}\n"
    write(tmp_path / "beta-quota-wall.yaml", body)
    wall = next(
        r
        for r in read_claude_wall_and_spend(tmp_path, tmp_path / "t", now=A1_NOW)
        if r.label == "wall-signal"
    )
    assert wall.details.get("binds_at_most_hours") == bound_hours
    assert wall_is_live(wall, [wall], now=A_WEEK_LATER) is (bound_hours is None)


def test_a_wall_naming_no_window_binds_until_its_reset_or_a_witnessed_serve(tmp_path):
    write(
        tmp_path / "glmcp-other-quota-wall.yaml",
        "status: quota_blocked\nobserved_at: 2026-09-24T18:00:00Z\n",
    )
    wall = read_receipt_measurements(tmp_path, "glm")[0]
    assert wall.label == "wall-signal" and wall.resets_at is None
    assert wall_is_live(wall, [wall], now=datetime(2026, 12, 24, tzinfo=UTC))


def test_any_exception_in_one_family_stays_in_that_family(tmp_path, monkeypatch):
    import shared.quota_headroom as quota_headroom

    def broken(*args, **kwargs):
        raise KeyError("shape")

    monkeypatch.setattr(quota_headroom, "read_kimi_403_signal", broken)
    jsonl(tmp_path / ".codex/sessions/rollout-a.jsonl", token_event())
    try:
        readings = collect_measurements(tmp_path, tmp_path / "receipts", now=NOW)
    except KeyError:
        readings = None
    assert readings is not None, "one family's failure stopped every family"
    assert readings["kimi"][0].details == {"error": "KeyError"}


def test_an_old_transcript_never_holds_a_live_subscription_wall(tmp_path):
    # A notice in a file untouched for nine days is at least nine days old; every Claude
    # subscription window is at most seven days (unifiedWindows keys; rateLimitType census), so
    # a reset still ahead is not a subscription window's. The skip loses no live subscription wall.
    path = jsonl(
        tmp_path / "transcripts/old.jsonl",
        {
            "timestamp": "2026-09-15T18:00:00Z",
            "isApiErrorMessage": True,
            "message": {"content": "You've hit your limit; resets 2026-09-26T18:00:00Z"},
        },
    )
    old = (A1_NOW - timedelta(days=9)).timestamp()
    os.utime(path, (old, old))
    assert not any(r.capacity_id.endswith("harness_wall") for r in claude_rows(tmp_path))


CLAUDE_NOTICES = [
    "You've hit your weekly limit · resets Sep 26, 5pm (America/Chicago)",
    "You've hit your session limit · resets 11pm (America/Chicago)",
    "Claude usage limit reached",
    "You've hit your limit; resets 2026-09-26T18:00:00Z",  # a stated reset past any window
]


@pytest.mark.parametrize("text", CLAUDE_NOTICES)
def test_the_transcript_skip_never_changes_which_walls_are_live(tmp_path, text):
    # Round 4: the skip is sound only if no Claude wall outlives the horizon. Read the same
    # nine-day-old notice with the file fresh (read) and old (skipped): the live walls agree.
    notice_at = A1_NOW - timedelta(days=9)
    record = {"timestamp": notice_at.isoformat(), "isApiErrorMessage": True}
    path = jsonl(tmp_path / "transcripts/old.jsonl", record | {"message": {"content": text}})

    def live_walls():
        rows = claude_rows(tmp_path)
        return [
            r.capacity_id
            for r in rows
            if r.label == "wall-signal" and wall_is_live(r, rows, now=A1_NOW)
        ]

    os.utime(path, (A1_NOW.timestamp(), A1_NOW.timestamp()))
    read = live_walls()
    os.utime(path, (notice_at.timestamp(), notice_at.timestamp()))
    assert read == live_walls() == []


def test_a_stream_refusal_of_an_unrecognized_window_binds_at_most_a_week(tmp_path):
    rejected = {"status": "rejected", "rateLimitType": "seven_day_overage_included"}
    claude_stream(
        tmp_path, stream_init(), stream_dated("2026-09-24T18:00:00Z"), rate_limit_event(rejected)
    )
    rows = claude_rows(tmp_path)
    assert "claude.subscription.rate_limit_rejected" in by_id(rows)
    wall = by_id(rows)["claude.subscription.rate_limit_rejected"]
    assert wall.details["binds_at_most_hours"] == 168
    assert not wall_is_live(wall, rows, now=wall.observed_at + timedelta(hours=168))


def test_an_old_transcript_with_a_still_live_wall_is_read_and_walled(tmp_path):
    # The seat's case: an old transcript whose only record is a wall naming no window, no later
    # serve. Within Claude's longest window it is still read, and still binds.
    notice_at = A1_NOW - timedelta(days=6)
    record = {"timestamp": notice_at.isoformat(), "isApiErrorMessage": True}
    path = jsonl(
        tmp_path / "transcripts/old.jsonl",
        record | {"message": {"content": "Claude usage limit reached"}},
    )
    os.utime(path, (notice_at.timestamp(), notice_at.timestamp()))
    rows = claude_rows(tmp_path)
    assert "claude.subscription.harness_wall" in by_id(rows)
    assert wall_is_live(by_id(rows)["claude.subscription.harness_wall"], rows, now=A1_NOW)
    assert freeze_predicate(rows, now=A1_NOW)["active"] is False  # no reset: live, not frozen


def test_an_undated_refusal_is_dated_late_and_an_undated_reading_is_not_evidence(tmp_path):
    # Nothing dated precedes either event; a record after them dates the refusal only.
    claude_stream(
        tmp_path,
        stream_init(),
        rate_limit_event(REJECTED_7D | {"unifiedWindows": unified_info()["unifiedWindows"]}),
        stream_dated("2026-09-24T18:20:00Z"),
    )
    rows = claude_rows(tmp_path)
    assert "claude.subscription.rate_limit_rejected" in by_id(rows), "the undated refusal was lost"
    wall = by_id(rows)["claude.subscription.rate_limit_rejected"]
    assert wall.observed_at == datetime(2026, 9, 24, 18, 20, tzinfo=UTC)
    assert wall.details["earliest_at"] is None
    assert rows[0].label == "unobserved"  # the refusal's readings had nothing dated before them


def test_routable_comes_from_this_ledgers_own_fresh_admission():
    # The strict receipt-applied registry read is confined to reporting by the agentic-trust
    # boundary, so the stage reads the admission this tick already produced instead.
    base = load_quota_spend_ledger()
    payload = base.model_dump(mode="json")
    for row in payload["quota_snapshots"]:
        if row["route_id"] == "claude.headless.full":
            row["subscription_quota_state"] = "fresh"
            row["fresh_until"] = (NOW + timedelta(minutes=10)).isoformat()
    fresh = QuotaSpendLedger.model_validate(payload)

    def claude_stage(ledger, now):
        result = enrich_ledger(ledger, {}, registry=registry(), now=now)
        return next(r.stage for r in result.quota_snapshots if r.family == "claude")

    assert claude_stage(fresh, NOW) == "routable"
    assert claude_stage(fresh, NOW + timedelta(minutes=20)) != "routable"  # admission expired
    assert claude_stage(base, NOW) != "routable"  # the fixture's claude.headless.full is exhausted
