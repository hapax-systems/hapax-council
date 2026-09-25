"""Tests for ``scripts/hapax-claude-pool-pace`` — the 7-day pool pacing governor.

Red-first pins (the row's exit predicate, part 4): an overshoot refuses a launch; a probe
failure refuses rather than releases (fail narrow); no probe runs without a ledger line.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import shared.durable_jsonl_sink as sink_mod

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-pool-pace"
ADMISSION = REPO_ROOT / "scripts" / "hapax-claude-subscription-quota-admission"
HEADLESS_GLOB = str(Path.home() / ".cache" / "hapax" / "claude-headless" / "*" / "output.jsonl")

NOW = datetime(2026, 9, 25, 23, 0, 0, tzinfo=UTC)
WINDOW_START = NOW - timedelta(hours=24)          # 24 h into the 7-day window
WEEKLY_RESET = WINDOW_START + timedelta(hours=168)
LINE_AT_NOW = 2.0 + 0.6 * 24.0                    # = 16.4 % (2 % start + 0.6 %/h)


def _load(name: str, path: Path) -> ModuleType:
    loader = SourceFileLoader(name, str(path))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def _pace() -> ModuleType:
    return _load("hapax_claude_pool_pace_under_test", SCRIPT)


def _sink_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    monkeypatch.setenv(sink_mod.DEFAULT_ROOT_ENV, str(root))
    return root


def _window_receipts(tmp_path: Path, *, weekly_used: float, weekly_reset: datetime,
                     five_used: float = 1.0, five_reset: datetime | None = None,
                     observed_at: datetime = NOW) -> Path:
    """A probe-backed admission receipt carrying both windows, as the probe mints them."""
    receipts = tmp_path / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    five_reset = five_reset or (observed_at + timedelta(hours=3))
    stamp = observed_at.strftime("%Y%m%dt%H%M%Sz")
    (receipts / f"claude-subscription-quota-admission-claude-headless-full-{stamp}.yaml").write_text(
        "\n".join(
            [
                "schema: hapax.claude_quota_admission.v1",
                "status: quota_available",
                "provider: anthropic-claude-subscription",
                "route_id: claude.headless.full",
                "capacity_pool: subscription_quota",
                "auth_surface: subscription",
                "observation: subscription_quota_headroom_observed",
                f"observed_at: {observed_at.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "stale_after_seconds: 1800",
                f"evidence_ref: claude-subscription-headroom-observed-{stamp}",
                "secret_source: claude:operator-session-subscription",
                "secret_value_persisted: false",
                "prompt_or_output_persisted: false",
                "billing_mode: operator_session_subscription",
                "account_live_quota_observed: true",
                "lane_presence_used_as_quota_evidence: false",
                "positive_admission: true",
                "probe_environment_scrubbed: true",
                "subscription_served: true",
                f"seven_day_used_percent: {weekly_used}",
                f"seven_day_resets_at: {weekly_reset.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                f"five_hour_used_percent: {five_used}",
                f"five_hour_resets_at: {five_reset.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return receipts


def _run(argv: list[str]) -> int:
    return _pace().main(argv)


def _base_args(tmp_path: Path, receipts: Path) -> list[str]:
    return ["--now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "--receipt-dir", str(receipts),
            "--headless-glob", str(tmp_path / "no-headless" / "*" / "output.jsonl")]


def test_overshoot_refuses_a_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # noqa: ANN001
    _sink_root(tmp_path, monkeypatch)
    receipts = _window_receipts(tmp_path, weekly_used=40.0, weekly_reset=WEEKLY_RESET)
    args = [*_base_args(tmp_path, receipts), "--json"]
    assert _run(["record", *args]) == 0
    capsys.readouterr()

    rc = _run(["check", *args])
    payload = json.loads(capsys.readouterr().out)

    assert rc == _pace().EXIT_REFUSE_OVER_PACE
    assert payload["decision"] == "refuse"
    assert payload["reason"] == "pace_line_exceeded"
    assert payload["weekly_used_percent"] == pytest.approx(40.0)
    assert payload["line_percent"] == pytest.approx(LINE_AT_NOW, abs=0.01)
    assert payload["over_line"] is True


def test_at_or_under_the_line_allows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # noqa: ANN001
    _sink_root(tmp_path, monkeypatch)
    receipts = _window_receipts(tmp_path, weekly_used=5.0, weekly_reset=WEEKLY_RESET)
    args = [*_base_args(tmp_path, receipts), "--json"]
    assert _run(["record", *args]) == 0
    capsys.readouterr()

    rc = _run(["check", *args])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["decision"] == "allow"
    assert payload["over_line"] is False


def test_five_hour_ceiling_refuses_even_under_the_weekly_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    _sink_root(tmp_path, monkeypatch)
    receipts = _window_receipts(tmp_path, weekly_used=2.0, weekly_reset=WEEKLY_RESET, five_used=95.0)
    args = [*_base_args(tmp_path, receipts), "--json"]
    assert _run(["record", *args]) == 0
    capsys.readouterr()

    rc = _run(["check", *args])
    payload = json.loads(capsys.readouterr().out)

    assert rc == _pace().EXIT_REFUSE_OVER_PACE
    assert payload["reason"] == "five_hour_ceiling_exceeded"


def test_a_probe_failure_refuses_rather_than_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    """No reading, a stale reading, and an unledgered reading all refuse (fail narrow)."""
    _sink_root(tmp_path, monkeypatch)
    empty = tmp_path / "empty-receipts"
    empty.mkdir()

    rc = _run(["check", *_base_args(tmp_path, empty), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == _pace().EXIT_REFUSE_UNKNOWN
    assert payload["reason"] == "no_claude_window_reading"
    assert payload["decision"] == "refuse"

    stale_at = NOW - timedelta(hours=2)
    stale = _window_receipts(tmp_path / "stale", weekly_used=5.0,
                             weekly_reset=stale_at + timedelta(hours=168), observed_at=stale_at)
    rc = _run(["check", *_base_args(tmp_path, stale), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == _pace().EXIT_REFUSE_UNKNOWN
    assert payload["reason"] == "reading_stale"

    # A fresh reading that no ledger row covers is not yet evidence.
    fresh = _window_receipts(tmp_path, weekly_used=5.0, weekly_reset=WEEKLY_RESET)
    rc = _run(["check", *_base_args(tmp_path, fresh), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == _pace().EXIT_REFUSE_UNKNOWN
    assert payload["reason"] == "pace_reading_not_ledgered"


def test_no_probe_runs_without_a_ledger_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``record`` ledgers the reading and never makes a provider call itself."""
    root = _sink_root(tmp_path, monkeypatch)
    receipts = _window_receipts(tmp_path, weekly_used=5.0, weekly_reset=WEEKLY_RESET)

    def _forbidden(*_args: Any, **_kwargs: Any):  # noqa: ANN401
        raise AssertionError("the pacing recorder must never call a provider")

    monkeypatch.setattr("subprocess.run", _forbidden)
    monkeypatch.setattr("subprocess.Popen", _forbidden)

    assert _run(["record", *_base_args(tmp_path, receipts), "--json"]) == 0

    rows = [
        json.loads(line)
        for line in (root / "claude-pool.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["stream_id"] == "claude-pool"
    assert row["data_class"] == "claude_pool_pace_reading"
    assert row["payload"]["weekly_used_percent"] == pytest.approx(5.0)
    assert row["payload"]["over_line"] is False
    assert row["prior_hash"] == sink_mod.GENESIS_HASH


def test_record_fails_closed_when_it_cannot_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    missing = tmp_path / "absent-root"
    monkeypatch.setenv(sink_mod.DEFAULT_ROOT_ENV, str(missing))
    receipts = _window_receipts(tmp_path, weekly_used=5.0, weekly_reset=WEEKLY_RESET)

    rc = _run(["record", *_base_args(tmp_path, receipts), "--json"])
    captured = capsys.readouterr()
    out = captured.out + captured.err

    assert rc == _pace().EXIT_REFUSE_UNKNOWN
    assert "ledger" in out
    assert not (missing / "claude-pool.jsonl").exists()


def test_status_reports_utilization_against_the_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    _sink_root(tmp_path, monkeypatch)
    receipts = _window_receipts(tmp_path, weekly_used=40.0, weekly_reset=WEEKLY_RESET)
    args = [*_base_args(tmp_path, receipts), "--json"]
    assert _run(["record", *args]) == 0
    capsys.readouterr()

    rc = _run(["status", *args])
    payload = json.loads(capsys.readouterr().out)
    assert rc == _pace().EXIT_REFUSE_OVER_PACE  # over the line: the read reports the refusal
    assert set(payload) >= {
        "now", "line_percent", "weekly_used_percent", "five_hour_used_percent",
        "over_line", "decision", "reason", "reading_age_seconds", "ledgered",
    }
    assert payload["line_percent"] == pytest.approx(LINE_AT_NOW, abs=0.01)
    assert payload["weekly_used_percent"] == pytest.approx(40.0)
    assert payload["ledgered"] is True


def test_the_admission_receipt_is_pace_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    """The Claude route's only quota-freshness producer refuses above the line."""
    _sink_root(tmp_path, monkeypatch)
    receipts = _window_receipts(tmp_path, weekly_used=40.0, weekly_reset=WEEKLY_RESET)
    assert _run(["record", *_base_args(tmp_path, receipts), "--json"]) == 0
    capsys.readouterr()

    receipt_dir = tmp_path / "minted"
    writer = _load("hapax_claude_subscription_quota_admission_pace_gate", ADMISSION)
    rc = writer.main(
        [
            "--receipt-dir", str(receipt_dir),
            "--now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "--evidence-ref", "claude-subscription-headroom-observed-20260925t2300z",
            "--observation", "subscription_quota_headroom_observed",
            "--stale-after-seconds", "900",
            "--pace-now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "--pace-receipt-dir", str(receipts),
            "--pace-headless-glob", str(tmp_path / "no-headless" / "*" / "output.jsonl"),
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert rc != 0
    assert "pace" in (out.out + out.err).lower()
    assert not list(receipt_dir.glob("*.yaml"))


def test_startup_tolerance_is_two_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # noqa: ANN001
    """The seat's ruling: 1.9 % at 0 h passes, 2.1 % at 0 h refuses, 2.5 % at 1 h passes."""
    _sink_root(tmp_path, monkeypatch)

    at_reset = tmp_path / "at-reset"
    receipts = _window_receipts(at_reset, weekly_used=1.9, weekly_reset=NOW + timedelta(hours=168))
    args = [*_base_args(at_reset, receipts), "--json"]
    assert _run(["record", *args]) == 0
    capsys.readouterr()
    assert _run(["check", *args]) == 0
    assert json.loads(capsys.readouterr().out)["line_percent"] == pytest.approx(2.0)

    over_at_reset = tmp_path / "over-at-reset"
    receipts = _window_receipts(over_at_reset, weekly_used=2.1,
                                weekly_reset=NOW + timedelta(hours=168))
    args = [*_base_args(over_at_reset, receipts), "--json"]
    assert _run(["record", *args]) == 0
    capsys.readouterr()
    rc = _run(["check", *args])
    payload = json.loads(capsys.readouterr().out)
    assert rc == _pace().EXIT_REFUSE_OVER_PACE
    assert payload["reason"] == "pace_line_exceeded"

    one_hour_in = tmp_path / "one-hour-in"
    receipts = _window_receipts(one_hour_in, weekly_used=2.5,
                                weekly_reset=NOW + timedelta(hours=167))
    args = [*_base_args(one_hour_in, receipts), "--json"]
    assert _run(["record", *args]) == 0
    capsys.readouterr()
    rc = _run(["check", *args])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["line_percent"] == pytest.approx(2.6)
