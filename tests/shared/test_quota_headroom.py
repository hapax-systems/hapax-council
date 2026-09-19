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
    collect_measurements,
    enrich_ledger,
    freeze_predicate,
    operator_report,
    read_claude_wall_and_spend,
    read_codex_token_count,
    read_kimi_403_signal,
    read_other_family,
    read_receipt_measurements,
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


def test_operator_report_preserves_ambiguous_reset_and_append(tmp_path, capsys):
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
