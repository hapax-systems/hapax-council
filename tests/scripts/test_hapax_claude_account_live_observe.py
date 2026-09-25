"""The account-live probe keeps the subscription windows it sees.

The probe already makes a real subscription request every time it runs, and the provider
reports both windows on it (``rate_limit_event.rate_limit_info.unifiedWindows``). Before this,
the probe asked for the single-object ``json`` reply, which carries no window, and its receipt
said only ``quota_available: true``. Dispatch cannot pace on a bit. These tests pin the
producer-to-consumer boundary: probe stdout -> observation -> admission receipt written by the
real writer -> ledger reader.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.quota_headroom import read_claude_wall_and_spend

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-account-live-observe"
_WRITER = REPO_ROOT / "scripts" / "hapax-claude-subscription-quota-admission"
_spec = importlib.util.spec_from_file_location(
    "hapax_claude_account_live_observe_windows",
    _SCRIPT,
    loader=importlib.machinery.SourceFileLoader(
        "hapax_claude_account_live_observe_windows", str(_SCRIPT)
    ),
)
assert _spec and _spec.loader
obs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(obs)

NOW = datetime(2026, 9, 24, 18, 6, 36, tzinfo=UTC)
RESET_5H = 1790285400  # 2026-09-24T21:30:00Z
RESET_7D = 1790373600  # 2026-09-25T22:00:00Z


def info(status="allowed", five=0.08, seven=0.09, overage_status="rejected"):
    return {
        "status": status,
        "resetsAt": RESET_5H,
        "rateLimitType": "five_hour",
        "overageStatus": overage_status,
        "overageDisabledReason": "out_of_credits",
        "isUsingOverage": False,
        "unifiedWindows": {
            "five_hour": {"utilization": five, "resetsAt": RESET_5H},
            "seven_day": {"utilization": seven, "resetsAt": RESET_7D},
        },
    }


# The CLI's init record for a subscription session; the field name is the CLI's, the value "none".
SUBSCRIPTION_INIT = {
    "type": "system",
    "subtype": "init",
    "model": "claude-opus-5",
    "apiKeySource": "none",  # pragma: allowlist secret
}


def served_result(model="claude-opus-5"):
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "usage": {"input_tokens": 5, "output_tokens": 9},
        "modelUsage": {model: {"inputTokens": 5}},
    }


def stream(*records):
    return "".join(json.dumps(record) + "\n" for record in records)


def fake_run(stdout: str):
    class Completed:
        returncode = 0
        stderr = ""

    Completed.stdout = stdout
    return lambda *args, **kwargs: Completed()


@pytest.fixture(autouse=True)
def _scrub(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(obs.PROBE_ENV_SCRUBBED) + ["ANTHROPIC_MODEL"]:
        monkeypatch.delenv(name, raising=False)


def probe_stream(monkeypatch, *records):
    monkeypatch.setattr(obs.subprocess, "run", fake_run(stream(*records)))
    return obs.probe(NOW)


def test_probe_asks_for_the_stream_that_carries_the_windows() -> None:
    argv = list(obs.PROBE_ARGV)
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    # The CLI refuses stream-json in print mode without --verbose.
    assert "--verbose" in argv


def test_probe_keeps_the_windows_it_sees(monkeypatch: pytest.MonkeyPatch) -> None:
    event = probe_stream(
        monkeypatch,
        SUBSCRIPTION_INIT,
        {"type": "rate_limit_event", "rate_limit_info": info()},
        served_result(),
    )
    assert event is not None and event.kind == "served" and event.model == "claude-opus-5"
    assert event.windows == {
        "five_hour": (8.0, datetime(2026, 9, 24, 21, 30, tzinfo=UTC)),
        "seven_day": (9.0, datetime(2026, 9, 25, 22, tzinfo=UTC)),
    }


def test_probe_rejected_window_is_a_wall_even_when_the_result_was_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A served result after a subscription refusal came from somewhere other than the
    # subscription window; it must never mint subscription headroom.
    event = probe_stream(
        monkeypatch,
        {"type": "rate_limit_event", "rate_limit_info": info(status="rejected")},
        served_result(),
    )
    assert event is not None and event.kind == "wall"


def test_probe_overage_refusal_alone_is_not_a_wall(monkeypatch: pytest.MonkeyPatch) -> None:
    event = probe_stream(
        monkeypatch,
        {"type": "rate_limit_event", "rate_limit_info": info(overage_status="rejected")},
        served_result(),
    )
    assert event is not None and event.kind == "served"


def test_probe_still_reads_a_single_json_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs.subprocess, "run", fake_run(json.dumps(served_result())))
    event = obs.probe(NOW)
    assert event is not None and event.kind == "served" and event.windows == {}


def test_probe_stream_without_a_result_is_not_a_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every stream names "rate_limit_event"; that word is not a refusal.
    event = probe_stream(monkeypatch, {"type": "rate_limit_event", "rate_limit_info": info()})
    assert event is None


@pytest.mark.parametrize(
    "stdout,stderr",
    [
        ("Claude AI usage limit reached|1790373600", ""),
        (stream({"type": "rate_limit_event", "rate_limit_info": info()}), "usage limit reached"),
    ],
)
def test_probe_refusal_printed_outside_the_stream_is_still_a_wall(
    monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str
) -> None:
    completed = fake_run(stdout)()
    completed.stderr = stderr
    monkeypatch.setattr(obs.subprocess, "run", lambda *a, **k: completed)
    event = obs.probe(NOW)
    assert event is not None and event.kind == "wall"


def mint(event, tmp_path: Path, *, route_ids=("claude.headless.full",)):
    return obs.mint(
        event,
        now=NOW,
        route_ids=route_ids,
        stale_after_seconds=1800,
        receipt_dir=tmp_path,
        dry_run=False,
    )


def test_probe_windows_reach_the_ledger_reader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    event = probe_stream(
        monkeypatch, {"type": "rate_limit_event", "rate_limit_info": info()}, served_result()
    )
    monkeypatch.undo()  # the writer must really run
    receipts = mint(event, tmp_path, route_ids=obs.DEFAULT_ROUTE_IDS)
    assert all(r["returncode"] == 0 for r in receipts), receipts
    rows = {
        row.capacity_id: row
        for row in read_claude_wall_and_spend(
            tmp_path, tmp_path / "transcripts", now=NOW, stream_root=tmp_path / "streams"
        )
    }
    weekly = rows["claude.subscription.weekly"]
    assert (weekly.label, weekly.quantity, weekly.window) == ("observed", 9.0, "10080m")
    assert weekly.observed_at == NOW.replace(microsecond=0)
    assert weekly.resets_at == datetime(2026, 9, 25, 22, tzinfo=UTC)
    assert rows["claude.subscription.five_hour"].quantity == 8.0


def test_a_passive_serve_mints_no_numbers(tmp_path: Path) -> None:
    passive = obs.Observation("served", NOW, "session-transcript", model="claude-opus-5-5")
    receipts = mint(passive, tmp_path)
    assert receipts[0]["returncode"] == 0, receipts
    text = next(tmp_path.glob("*.yaml")).read_text(encoding="utf-8")
    assert "used_percent" not in text and "resets_at" not in text


def run_writer(
    tmp_path: Path, *extra: str, now: str = "2026-09-24T18:06:36Z"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_WRITER),
            "--receipt-dir",
            str(tmp_path),
            "--now",
            now,
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260924t180636z",  # pragma: allowlist secret
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_writer_records_probe_windows(tmp_path: Path) -> None:
    result = run_writer(
        tmp_path,
        "--probe-environment-scrubbed",
        "--seven-day-used-percent",
        "9",
        "--seven-day-resets-at",
        "2026-09-25T22:00:00Z",
    )
    assert result.returncode == 0, result.stderr
    text = next(tmp_path.glob("*.yaml")).read_text(encoding="utf-8")
    assert "seven_day_used_percent: 9.0\n" in text
    assert "seven_day_resets_at: 2026-09-25T22:00:00Z\n" in text
    assert "five_hour" not in text


@pytest.mark.parametrize(
    "extra",
    [
        # Numbers only ever come from the scrubbed probe's own reply.
        ("--seven-day-used-percent", "9", "--seven-day-resets-at", "2026-09-25T22:00:00Z"),
        (
            "--probe-environment-scrubbed",
            "--observation",
            "operator_confirmed_subscription_headroom",
            "--evidence-ref",
            "claude-operator-confirmed-subscription-headroom-20260924t180636z",  # pragma: allowlist secret
            "--seven-day-used-percent",
            "9",
            "--seven-day-resets-at",
            "2026-09-25T22:00:00Z",
        ),
        # The serve witness, like the numbers, comes only from the scrubbed probe.
        ("--subscription-served",),
        # A window is a pair; half of one is not a reading.
        ("--probe-environment-scrubbed", "--seven-day-used-percent", "9"),
        ("--probe-environment-scrubbed", "--five-hour-resets-at", "2026-09-24T21:30:00Z"),
        (
            "--probe-environment-scrubbed",
            "--seven-day-used-percent",
            "-1",
            "--seven-day-resets-at",
            "2026-09-25T22:00:00Z",
        ),
        (
            "--probe-environment-scrubbed",
            "--seven-day-used-percent",
            "nan",
            "--seven-day-resets-at",
            "2026-09-25T22:00:00Z",
        ),
        # A window that had already reset when observed is not the current window.
        (
            "--probe-environment-scrubbed",
            "--seven-day-used-percent",
            "9",
            "--seven-day-resets-at",
            "2026-09-24T18:00:00Z",
        ),
        (
            "--probe-environment-scrubbed",
            "--seven-day-used-percent",
            "9",
            "--seven-day-resets-at",
            "next tuesday",
        ),
    ],
)
def test_writer_refuses_a_window_it_cannot_vouch_for(
    tmp_path: Path, extra: tuple[str, ...]
) -> None:
    result = run_writer(tmp_path, *extra)
    assert result.returncode != 0
    assert list(tmp_path.glob("*.yaml")) == []
    assert "next action" in result.stderr


# H1 #15: read the quantity before probing for it; probe only when it is stale.


def iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def passive_serve(tmp_path: Path, at: datetime) -> None:
    """A transcript serve by a model that witnesses both default routes."""
    path = tmp_path / "projects/proj/session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "assistant",
        "timestamp": iso(at),
        "message": {"model": "claude-opus-5", "usage": {"input_tokens": 3, "output_tokens": 4}},
    }
    path.write_text(json.dumps(record) + "\n")


def window_receipt(tmp_path: Path, at: datetime, reset: str = "2026-09-25T22:00:00Z") -> None:
    result = run_writer(
        tmp_path / "receipts",
        "--probe-environment-scrubbed",
        "--seven-day-used-percent",
        "9",
        "--seven-day-resets-at",
        reset,
        now=iso(at),
    )
    assert result.returncode == 0, result.stderr


def run_main(monkeypatch, tmp_path: Path, capsys, *extra: str, probe_result=None):
    calls: list[datetime] = []

    def fake_probe(now: datetime):
        calls.append(now)
        return probe_result

    monkeypatch.setattr(obs, "probe", fake_probe)
    rc = obs.main(
        [
            "--transcript-glob",
            str(tmp_path / "projects" / "*" / "*.jsonl"),
            "--headless-glob",
            str(tmp_path / "headless" / "*" / "output.jsonl"),
            "--receipt-dir",
            str(tmp_path / "receipts"),
            "--now",
            iso(NOW),
            "--max-age-seconds",
            "1800",
            "--json",
            *extra,
        ]
    )
    return rc, json.loads(capsys.readouterr().out), calls


def test_a_fresh_quantity_is_not_probed_again(monkeypatch, tmp_path: Path, capsys) -> None:
    window_receipt(tmp_path, NOW - timedelta(minutes=10))
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys)
    assert rc == 0 and calls == []
    assert payload["quantity"]["stale"] is False
    assert payload["quantity"]["newest_reading_at"] == iso(NOW - timedelta(minutes=10))


@pytest.mark.parametrize("reading_age", [timedelta(minutes=50), None])
def test_a_stale_or_missing_quantity_is_probed_and_the_receipt_keeps_it(
    monkeypatch, tmp_path: Path, capsys, reading_age
) -> None:
    if reading_age is not None:
        window_receipt(tmp_path, NOW - reading_age)
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    probed = obs.Observation(
        "served",
        NOW,
        "active-probe",
        model="claude-opus-5",
        scrubbed_env=obs.PROBE_ENV_SCRUBBED,
        windows={"seven_day": (11.0, datetime(2026, 9, 25, 22, tzinfo=UTC))},
    )
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys, probe_result=probed)
    assert rc == 0 and calls == [NOW]
    assert payload["probe"]["requested_for_routes"] == []
    assert payload["probe"]["quantity"]["stale"] is True
    newest = read_claude_wall_and_spend(
        tmp_path / "receipts", tmp_path / "none", now=NOW, stream_root=tmp_path / "none"
    )[0]
    assert (newest.quantity, newest.observed_at) == (11.0, NOW.replace(microsecond=0))


def test_an_unreadable_quantity_source_never_triggers_a_probe(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "claude-subscription-quota-admission-claude-headless-full-x.yaml").write_text(
        "seven_day_used_percent: [unclosed\n"
    )
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys)
    assert calls == []
    assert payload["quantity"]["read_error"] == "corrupt_or_unreadable_quantity_source"
    assert payload["quantity"]["stale"] is False


def test_a_walled_account_is_not_probed_for_its_quantity(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    passive_serve(tmp_path, NOW - timedelta(minutes=5))
    wall = {
        "type": "assistant",
        "timestamp": iso(NOW - timedelta(minutes=1)),
        "message": {"model": "claude-opus-5", "error": "rate_limit"},
        "error": "rate_limit",
    }
    with (tmp_path / "projects/proj/session.jsonl").open("a") as stream:
        stream.write(json.dumps(wall) + "\n")
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys)
    assert payload["verdict"] == "walled" and calls == []


def test_no_probe_means_no_quantity_probe(monkeypatch, tmp_path: Path, capsys) -> None:
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys, "--no-probe")
    assert calls == [] and payload["quantity"]["stale"] is True


# PR #4728 review round 1: each reproduced here first.


def minted(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in (tmp_path / "receipts").glob("*admission*.yaml"))


def test_a_quantity_probe_that_hits_a_wall_holds_the_route(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    wall = obs.Observation("wall", NOW, "active-probe", "provider-quota-refusal")
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys, probe_result=wall)
    assert calls == [NOW]
    assert (payload["verdict"], rc) == ("walled", 3)
    assert minted(tmp_path) == []


def test_a_failed_quantity_probe_keeps_the_passive_admission(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    # The passive admission is minted; the broken instrument still surfaces (exit 7).
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    broken = obs.Observation("probe_failed", NOW, "active-probe", "TimeoutExpired")
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys, probe_result=broken)
    assert calls == [NOW]
    assert (payload["verdict"], rc) == ("served", 7)
    assert payload["probe"]["outcome"] == "probe_failed"
    assert len(minted(tmp_path)) == 2


def test_a_failed_probe_still_mints_the_routes_passive_evidence_covers(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    # A Fable serve witnesses headless.full but not review.opus, so the probe runs for opus.
    path = tmp_path / "projects/proj/session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "assistant",
        "timestamp": iso(NOW - timedelta(minutes=1)),
        "message": {"model": "claude-fable-5-1", "usage": {"input_tokens": 3, "output_tokens": 4}},
    }
    path.write_text(json.dumps(record) + "\n")
    broken = obs.Observation("probe_failed", NOW, "active-probe", "TimeoutExpired")
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys, probe_result=broken)
    assert calls == [NOW] and rc == 7
    assert payload["probe"]["requested_for_routes"] == ["claude.review.opus"]
    assert minted(tmp_path) and all("headless-full" in name for name in minted(tmp_path))


def test_a_refused_requests_reading_is_still_the_current_quantity(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    # The quantity is the provider's number whether or not it served that request; a fresh one
    # is not re-bought. Admission is decided by walls and serves, not by this check.
    stream = tmp_path / "headless/lane/output.jsonl"
    stream.parent.mkdir(parents=True)
    records = [
        {"type": "system", "subtype": "init", "session_id": "s", "model": "claude-opus-5"}
        | {"apiKeySource": "none"},  # pragma: allowlist secret
        {"type": "user", "session_id": "s", "timestamp": iso(NOW - timedelta(minutes=5))},
        {
            "type": "rate_limit_event",
            "session_id": "s",
            "rate_limit_info": info(status="rejected", seven=1.0),
        },
    ]
    stream.write_text("".join(json.dumps(r) + "\n" for r in records))
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys)
    assert payload["quantity"]["stale"] is False and calls == []


@pytest.mark.parametrize(
    "windows",
    [
        {"five_hour": (8.0, datetime(2026, 9, 24, 21, 30, tzinfo=UTC))},
        {"seven_day": (9.0, NOW - timedelta(minutes=1))},
    ],
)
def test_a_probe_without_a_live_weekly_window_witnesses_only_missing_routes(
    monkeypatch, tmp_path: Path, capsys, windows
) -> None:
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    by_route: dict[str, object] = {}

    def fake_mint(evidence, **kwargs):
        by_route.update(kwargs["evidence_by_route"])
        return [{"route_id": route_id, "returncode": 0} for route_id in kwargs["route_ids"]]

    monkeypatch.setattr(obs, "mint", fake_mint)
    probed = obs.Observation("served", NOW, "active-probe", model="claude-opus-5", windows=windows)
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys, probe_result=probed)
    assert calls == [NOW] and by_route
    assert all(evidence.source == "session-transcript" for evidence in by_route.values())


def test_a_reading_whose_window_has_reset_is_stale(monkeypatch, tmp_path: Path, capsys) -> None:
    window_receipt(tmp_path, NOW - timedelta(minutes=10), reset=iso(NOW - timedelta(minutes=5)))
    passive_serve(tmp_path, NOW - timedelta(minutes=1))
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys)
    assert payload["quantity"]["stale"] is True and calls == [NOW]


def test_an_expired_probe_window_never_costs_the_receipt(tmp_path: Path) -> None:
    probed = obs.Observation(
        "served",
        NOW,
        "active-probe",
        model="claude-opus-5",
        scrubbed_env=obs.PROBE_ENV_SCRUBBED,
        windows={
            "seven_day": (9.0, NOW - timedelta(seconds=1)),
            "five_hour": (8.0, datetime(2026, 9, 24, 21, 30, tzinfo=UTC)),
        },
    )
    receipts = mint(probed, tmp_path)
    assert receipts[0]["returncode"] == 0, receipts
    text = next(tmp_path.glob("*.yaml")).read_text(encoding="utf-8")
    assert "seven_day" not in text and "five_hour_used_percent: 8.0" in text


@pytest.mark.parametrize("flag", [True, 1, "true"])
def test_a_probe_served_from_overage_is_a_wall(monkeypatch: pytest.MonkeyPatch, flag) -> None:
    # Recorded samples carry a JSON boolean; anything but an explicit false-y value fails closed.
    overage = info() | {"isUsingOverage": flag}
    event = probe_stream(
        monkeypatch, {"type": "rate_limit_event", "rate_limit_info": overage}, served_result()
    )
    assert event is not None and event.kind == "wall"


# PR #4728 review round 3.


def test_a_probe_witnesses_the_subscription_only_on_an_explicit_non_overage_serve(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    unknown = info()
    del unknown["isUsingOverage"]
    for rate_info, witnessed in ((info(), True), (unknown, False)):
        event = probe_stream(
            monkeypatch, {"type": "rate_limit_event", "rate_limit_info": rate_info}, served_result()
        )
        assert event is not None and event.kind == "served"
        assert event.subscription_served is witnessed
    monkeypatch.undo()
    for witnessed in (True, False):
        receipts = tmp_path / str(witnessed)
        event = obs.Observation(
            "served",
            NOW,
            "active-probe",
            model="claude-opus-5",
            scrubbed_env=obs.PROBE_ENV_SCRUBBED,
            windows={"seven_day": (9.0, datetime(2026, 9, 25, 22, tzinfo=UTC))},
            subscription_served=witnessed,
        )
        assert mint(event, receipts)[0]["returncode"] == 0
        text = next(receipts.glob("*.yaml")).read_text(encoding="utf-8")
        assert ("subscription_served: true" in text) is witnessed


def test_a_failed_probe_mints_exactly_what_passive_evidence_alone_would(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    # The probe failing is an instrument fault, not evidence against the account: the routes it
    # leaves minted are the ones a run that never probes would mint from the same serves.
    path = tmp_path / "projects/proj/session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "assistant",
        "timestamp": iso(NOW - timedelta(minutes=1)),
        "message": {"model": "claude-fable-5-1", "usage": {"input_tokens": 3, "output_tokens": 4}},
    }
    path.write_text(json.dumps(record) + "\n")
    broken = obs.Observation("probe_failed", NOW, "active-probe", "TimeoutExpired")
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys, probe_result=broken)
    with_failed_probe = minted(tmp_path)
    for receipt in (tmp_path / "receipts").glob("*.yaml"):
        receipt.unlink()
    rc_passive, _, _ = run_main(monkeypatch, tmp_path, capsys, "--no-probe")
    assert rc == 7 and rc_passive == 0
    assert with_failed_probe and with_failed_probe == minted(tmp_path)


def test_a_refused_reading_never_suppresses_a_route_probe(monkeypatch, tmp_path: Path, capsys):
    # The suppression in N1 is confined to the quantity trigger: with no passive serve, the
    # route-driven probe still runs.
    stream = tmp_path / "headless/lane/output.jsonl"
    stream.parent.mkdir(parents=True)
    records = [
        {"type": "system", "subtype": "init", "session_id": "s", "model": "claude-opus-5"}
        | {"apiKeySource": "none"},  # pragma: allowlist secret
        {"type": "user", "session_id": "s", "timestamp": iso(NOW - timedelta(minutes=5))},
        {
            "type": "rate_limit_event",
            "session_id": "s",
            "rate_limit_info": info(status="rejected", seven=1.0),
        },
    ]
    stream.write_text("".join(json.dumps(r) + "\n" for r in records))
    rc, payload, calls = run_main(monkeypatch, tmp_path, capsys)
    assert payload["quantity"]["stale"] is False and calls == [NOW]
