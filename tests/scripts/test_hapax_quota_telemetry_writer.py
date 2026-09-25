"""Tests for the live quota/resource telemetry writer (routing Phase 0.4)."""

from __future__ import annotations

import json
import os
import runpy
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-quota-telemetry-writer"
CLAUDE_ADMISSION_SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-subscription-quota-admission"
FIXTURES = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"
NOW = "2026-06-10T00:00:00Z"
PAYG_NOW = "2026-07-06T14:05:00Z"


@pytest.fixture(autouse=True)
def isolate_measurement_traces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_QUOTA_TRACE_HOME", str(tmp_path / "trace-home"))


def _fake_nvidia_smi(tmp_path: Path, body: str) -> Path:
    stub = tmp_path / "fake-nvidia-smi"
    stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _run_writer(
    tmp_path: Path,
    *extra_args: str,
    nvidia_body: str = "echo '1000, 32000'",
    now: str = NOW,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir(exist_ok=True)
    if "--platform-capability-receipt-dir" not in extra_args:
        platform_receipts.mkdir(exist_ok=True)
        _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, nvidia_body)
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR": str(platform_receipts),
        "HAPAX_DISPATCH_HOST": "",
        "HAPAX_DEFAULT_DISPATCH_HOST": "",
    }
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skip-receipts",
            "--now",
            now,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    return result, out


def test_capability_receipt_refresh_preserves_codex_exec_auth_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    calls: list[list[str]] = []
    receipt_dir = tmp_path / "platform-receipts"

    def fake_run(
        argv: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert capture_output is True
        assert text is True
        assert timeout == 36
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)

    assert (
        namespace["refresh_capability_receipts"](
            timeout=12,
            receipt_dir=receipt_dir,
        )
        is True
    )
    assert calls == [
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"),
            "--all",
            "--codex-exec-auth-probe",
            "--timeout",
            "12",
            "--receipt-dir",
            str(receipt_dir),
        ]
    ]


def test_pull_forward_invokes_the_harness_with_bounded_budgets_and_freshness_derived_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The pull goes through the SAME harness (per-producer lock, run-ledger
    gate) with explicitly bounded child budgets, and adds --force exactly when
    the freshness the next write needs demands a mint NOW — never from a
    measured timer phase (critical finding on #4665, round 2)."""
    namespace = runpy.run_path(str(SCRIPT))
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    calls: list[list[str]] = []

    def fake_run(argv, *, capture_output, text, timeout):
        calls.append(argv)
        assert capture_output is True
        assert text is True
        assert timeout == namespace["PULL_FORWARD_TIMEOUT_S"]
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "now": NOW,
                    "ran": [{"producer_id": "agy-review-quota"}],
                    "skipped": [],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    now_dt = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    # No admission receipt at all: the next write embeds nothing — force, with
    # the decision instant attached so the producer lock can revalidate it.
    info = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT, receipt_dir=relay, now=now_dt
    )
    assert calls == [
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "hapax-determine"),
            "--producer",
            "agy-review-quota",
            "--lock-wait",
            str(namespace["PULL_FORWARD_LOCK_WAIT_S"]),
            "--timeout",
            str(int(namespace["PULL_FORWARD_PRODUCER_TIMEOUT_S"])),
            "--force",
            "--force-justified-at",
            NOW,
            "--json",
        ]
    ]
    assert {k: v for k, v in info.items() if k not in {"scan_elapsed_s", "scan_bound_s"}} == {
        "invoked": True,
        "forced": True,
        "ran": ["agy-review-quota"],
        "skipped": [],
        "ok": True,
    }
    # The pre-mint force-decision scan is timed against its own bound
    # (round 5, codex-1 C2): elapsed is measured (real clock here, near
    # zero against an empty receipt dir) and the bound rides along for the
    # summary.
    assert info["scan_bound_s"] == namespace["PRE_MINT_SCAN_BOUND_S"]
    assert info["scan_elapsed_s"] >= 0.0

    # A receipt that comfortably covers the next cycle: plain due-check pull,
    # no --force — the cadence gate alone decides whether a run happens.
    _agy_admission(relay, observed_at=NOW, stale_after_seconds=900)
    calls.clear()
    info = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT, receipt_dir=relay, now=now_dt
    )
    assert info["forced"] is False
    assert "--force" not in calls[0]
    assert info["ok"] is True


def test_pull_forward_force_predicate_matches_freshness_need(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reviewers' exact repro numbers (codex-1, rounds 2 and 3): a 560s-old
    admission on a 900s TTL has 340s left — under the 600s write cadence, the
    receipt lapses mid-cycle and the surface flaps for the difference. A
    280s-old admission (620s left) beat the round-2 615s horizon but NOT the
    round-3 publication-deadline horizon: a +640s slipped fire plus a 27s
    publish overran it by 47s. The predicate must demand a mint in both
    cases; only a receipt that covers the full horizon (FRESHNESS_HORIZON_S) escapes force."""
    namespace = runpy.run_path(str(SCRIPT))
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    now_dt = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    # No subprocess: the decision is pure receipt arithmetic.
    monkeypatch.setattr(
        namespace["subprocess"],
        "run",
        lambda *a, **kw: pytest.fail("the predicate must not spawn the harness"),
    )

    # 560s old, 900s TTL: fresh_until = now + 340s < now + 819 → force.
    _agy_admission(
        relay,
        observed_at=(now_dt - timedelta(seconds=560)).isoformat().replace("+00:00", "Z"),
        stale_after_seconds=900,
    )
    assert namespace["pull_forward_force_needed"](relay, now=now_dt) is True

    # 280s old, 900s TTL: 620s left — beat the round-2 615s horizon, still
    # under the publication-deadline horizon (codex-1 round-3 repro) → force.
    (relay / "agy-quota-admission.yaml").unlink()
    _agy_admission(
        relay,
        observed_at=(now_dt - timedelta(seconds=280)).isoformat().replace("+00:00", "Z"),
        stale_after_seconds=900,
    )
    assert namespace["pull_forward_force_needed"](relay, now=now_dt) is True

    # Fresh mint, full horizon: covers cycle + accuracy + pre-write work →
    # no force.
    (relay / "agy-quota-admission.yaml").unlink()
    _agy_admission(
        relay, observed_at=NOW, stale_after_seconds=int(namespace["FRESHNESS_HORIZON_S"])
    )
    assert namespace["pull_forward_force_needed"](relay, now=now_dt) is False

    # Nothing on disk → force.
    (relay / "agy-quota-admission.yaml").unlink()
    assert namespace["pull_forward_force_needed"](relay, now=now_dt) is True


def test_pull_forward_route_prefix_derivation_is_the_producer_naming_contract() -> None:
    """claude-1 minor (#4665, round 8) + codex-1 D1 (round 10):
    QUOTA_SURFACE_PULL_FORWARD_ROUTE_PREFIXES is derived from the producer ids
    under a naming CONTRACT — every producer id leads with its route
    dot-namespace as the first hyphen token. Pin both halves: the published
    prefixes stay derived (never hand-listed), and each derived prefix must
    match REAL registry route subjects — the witness only widens to routes
    that actually exist, so a renamed or invented namespace fails here
    instead of riding green outside the continuity contract."""
    sys.path.insert(0, str(REPO_ROOT))
    from shared.platform_capability_registry import load_platform_capability_registry_for_dispatch

    namespace = runpy.run_path(str(SCRIPT))
    producers = namespace["QUOTA_SURFACE_PULL_FORWARD_PRODUCER_IDS"]
    prefixes = namespace["QUOTA_SURFACE_PULL_FORWARD_ROUTE_PREFIXES"]

    # Derived, not hand-listed: the constant is exactly the split derivation
    # over the live producer tuple.
    assert prefixes == tuple(pid.split("-", 1)[0] + "." for pid in producers)
    assert "agy." in prefixes

    # D1: every derived prefix names at least one REAL registry route —
    # validated against the static registry's own route subjects, not a
    # hand-copied list that could drift from the registry it vouches for.
    registry, _ = load_platform_capability_registry_for_dispatch(apply_receipts=False)
    route_ids = [route.route_id for route in registry.routes]
    for prefix in prefixes:
        assert any(route_id.startswith(prefix) for route_id in route_ids), (
            f"pull-forward prefix {prefix!r} matches no registry route"
        )

    # The naming contract itself, pinned on a hypothetical second producer:
    # "claude-account-live" (deliberately absent today) must derive "claude.",
    # and claude.* routes exist in the registry, so the day it is added the
    # witness widens to real routes automatically.
    hypothetical = (*producers, "claude-account-live")
    derived = tuple(pid.split("-", 1)[0] + "." for pid in hypothetical)
    assert derived == (*prefixes, "claude.")
    assert any(route_id.startswith("claude.") for route_id in route_ids)

    # The mismatch leg, exercised: a producer whose first token names no route
    # namespace derives a prefix matching zero registry routes — exactly the
    # condition the registry validation above forbids for the live tuple.
    bogus_producer = "notaplatform-review-quota"
    bogus_prefix = bogus_producer.split("-", 1)[0] + "."
    assert not any(route_id.startswith(bogus_prefix) for route_id in route_ids)


def test_pull_forward_degrades_not_aborts_on_failure_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    now_dt = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    outcomes = [
        subprocess.CompletedProcess(["x"], 5, stdout="", stderr="producer failed"),
        subprocess.TimeoutExpired(cmd=["x"], timeout=namespace["PULL_FORWARD_TIMEOUT_S"]),
    ]

    def fake_run(argv, *, capture_output, text, timeout):
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    info1 = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT, receipt_dir=relay, now=now_dt
    )
    info2 = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT, receipt_dir=relay, now=now_dt
    )
    assert not outcomes
    assert info1["ok"] is False and info2["ok"] is False
    stderr = capsys.readouterr().err
    assert "pull-forward failed" in stderr and "rc=5" in stderr
    assert "pull-forward timed out" in stderr


def test_pull_forward_degrades_on_spawn_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    relay = tmp_path / "relay-receipts"
    relay.mkdir()

    def fake_run(argv, *, capture_output, text, timeout):
        raise FileNotFoundError("interpreter vanished")

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    info = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT,
        receipt_dir=relay,
        now=datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    assert info["ok"] is False
    assert "could not run" in capsys.readouterr().err


def test_pull_forward_lock_timeout_is_reported_not_silent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A skip with reason lock_timeout must surface in the returned info and
    on stderr with a next action — never a silent green pull (major finding on
    #4665, round 2)."""
    namespace = runpy.run_path(str(SCRIPT))
    relay = tmp_path / "relay-receipts"
    relay.mkdir()

    def fake_run(argv, *, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "now": NOW,
                    "ran": [],
                    "skipped": [
                        {
                            "producer_id": "agy-review-quota",
                            "reason": "lock_timeout",
                            "waited_s": 90.0,
                        }
                    ],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    info = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT,
        receipt_dir=relay,
        now=datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    assert info["ok"] is True  # the harness exited cleanly; the skip is honest
    assert info["skipped"] == [{"producer_id": "agy-review-quota", "reason": "lock_timeout"}]
    stderr = capsys.readouterr().err
    assert "deferred" in stderr and "lock held" in stderr
    assert "journalctl --user -u hapax-determine.service" in stderr


def test_main_pulls_mints_writes_then_refreshes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The measured flap had three cooperating defects (review on #4665): a
    pull that skipped the producer in the pre-boundary phase, a refresh that
    consumed the PREVIOUS cycle's ledger (clamping a fresh 900s admission to
    the stale ledger's remaining freshness), and tests that replaced both
    operations with constants. The stubs here are behavioral: the pull MINTS
    the receipt a real pull leaves on disk, and the refresh asserts it is
    consuming THIS cycle's ledger before it runs."""
    namespace = runpy.run_path(str(SCRIPT))
    # Patch through main's own globals via monkeypatch.setitem: run_path's
    # returned mapping is not guaranteed to be the dict main resolves names in,
    # and direct assignment would outlive the test (review finding on #4665).
    main_globals = namespace["main"].__globals__
    order: list[str] = []
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def fake_pull(**kw):
        order.append("pull")
        # What the real pull leaves behind: THIS cycle's mint, observed at the
        # tick's re-observation time. A broken pull leaves the previous cycle's
        # receipt (observed_at=NOW-600s) and the assertions below catch it.
        _agy_admission(relay, observed_at=NOW)
        return {
            "invoked": True,
            "forced": True,
            "ran": ["agy-review-quota"],
            "skipped": [],
            "ok": True,
        }

    seen: dict[str, str] = {}

    def fake_refresh(*, timeout, receipt_dir):
        order.append("refresh")
        # Behavioral: the refresh's ledger consumer (_ledger_fresh_routes)
        # validates routes and caps stale_after from the live ledger ON DISK.
        # If the pass-1 write had not landed between pull and refresh, this
        # reads the previous cycle's ledger — the clamping critical.
        payload = json.loads(out.read_text(encoding="utf-8"))
        seen["captured_at_at_refresh"] = payload["captured_at"]
        agy_at_refresh = next(
            s for s in payload["quota_snapshots"] if s["route_id"] == "agy.review.direct"
        )
        seen["agy_fresh_until_at_refresh"] = agy_at_refresh["fresh_until"]
        return True

    monkeypatch.setitem(main_globals, "pull_forward_due_producers", fake_pull)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", fake_refresh)
    # Frozen monotonic clock: the publication instant derives from measured
    # monotonic elapsed, and this test asserts exact freshness numbers — a
    # real clock would make them depend on machine speed (round-4 codex-1).
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    assert order == ["pull", "refresh"]
    # The refresh consumed THIS cycle's ledger: written this tick, embedding
    # the mint the pull just produced (900s TTL from NOW, not from NOW-600s).
    assert seen["captured_at_at_refresh"] == NOW
    assert seen["agy_fresh_until_at_refresh"] == "2026-06-10T00:15:00Z"
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        s for s in payload["quota_snapshots"] if s["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "fresh"
    assert agy_snapshot["fresh_until"] == "2026-06-10T00:15:00Z"
    summary = json.loads(capsys.readouterr().out)
    assert summary["pull_forward"]["forced"] is True
    assert summary["pull_forward"]["ran"] == ["agy-review-quota"]
    assert summary["receipts_refreshed"] is True
    assert summary["ledger_rebuilt_after_refresh"] is False
    # The exit predicate, on the published ledger at the PUBLICATION instant:
    # a fresh 900s mint leaves the full cycle ahead of it — not degraded.
    assert summary["admission_freshness_at_publication_s"] == 900.0
    assert summary["admission_freshness_degraded"] is False
    assert summary["published_at"] == NOW  # zero measured elapsed, pinned now


def test_refreshed_codex_receipts_rebuild_the_published_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The refresh rewrites the receipts only the codex blocker reads; when
    they change the blocker, the published ledger must be rebuilt in the same
    tick or the surface keeps the pre-refresh codex state until the next
    600s cycle (critical #2's write-side counterpart on #4665)."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setenv("HAPAX_DISPATCH_HOST", "")
    monkeypatch.setenv("HAPAX_DEFAULT_DISPATCH_HOST", "")
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    _codex_platform_receipt(
        platform_receipts, reason_code="codex_exec_auth_refresh_token_invalidated"
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    writes: list[str] = []
    real_write = main_globals["write_ledger_atomic"]

    def counting_write(ledger, path, **kwargs):
        writes.append(ledger.captured_at.isoformat())
        real_write(ledger, path, **kwargs)

    def healing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(platform_receipts)
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", healing_refresh)
    monkeypatch.setitem(main_globals, "write_ledger_atomic", counting_write)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    assert len(writes) == 2, writes
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        s for s in payload["quota_snapshots"] if s["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "fresh"
    summary = json.loads(capsys.readouterr().out)
    assert summary["ledger_rebuilt_after_refresh"] is True


def test_unchanged_codex_receipts_write_the_ledger_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The second pass is conditional: an unchanged codex blocker must not
    churn the published ledger every tick."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    writes: list[str] = []
    real_write = main_globals["write_ledger_atomic"]

    def counting_write(ledger, path, **kwargs):
        writes.append(ledger.captured_at.isoformat())
        real_write(ledger, path, **kwargs)

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)
    monkeypatch.setitem(main_globals, "write_ledger_atomic", counting_write)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    assert len(writes) == 1, writes
    summary = json.loads(capsys.readouterr().out)
    assert summary["ledger_rebuilt_after_refresh"] is False


def test_sustained_freshness_across_two_complete_cycles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The sustained-route-freshness proof the round-2 tests stopped short of
    (codex-1 major): run two ticks through the ACTUAL scheduling decision —
    tick A at the phase where the previous mint is 560s old, tick B at the max
    slippage the timer permits (600s cycle + 60s AccuracySec, the codex-1
    round-3 repro) — with the pull stub consulting the receipts on disk and
    minting only what the freshness predicate demands, then assert each
    published ledger's embedded admission covers its full next cycle. The
    round-2 defect class (a 560s-old admission slipping through as 'not due')
    flaps tick B; the force predicate repairs it at any timer phase."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    forced: list[bool] = []

    # Injectable monotonic clock (round-4 codex-1: the publication instant is
    # now MEASURED inside the scan→build→write pass). The first read in a
    # tick anchors the pass start; later reads (the lock deadline, the
    # post-pass publication read) include the modeled publication work — 27s
    # in the codex-1 round-3 repro — with no sleeping and no wall clock.
    class PublicationClock:
        advance = False
        calls = 0

        def __call__(self) -> float:
            self.calls += 1
            return 1000.0 + (publish_work_s if self.advance and self.calls > 1 else 0.0)

    clock = PublicationClock()

    def behavioral_pull(*, repo_root, receipt_dir, now, timeout=None):
        if namespace["pull_forward_force_needed"](receipt_dir, now=now):
            forced.append(True)
            _agy_admission(
                relay,
                observed_at=now.isoformat().replace("+00:00", "Z"),
                stale_after_seconds=900,
            )
            return {
                "invoked": True,
                "forced": True,
                "ran": ["agy-review-quota"],
                "skipped": [],
                "ok": True,
            }
        forced.append(False)
        return {"invoked": True, "forced": False, "ran": [], "skipped": [], "ok": True}

    monkeypatch.setitem(main_globals, "pull_forward_due_producers", behavioral_pull)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)
    monkeypatch.setitem(main_globals, "monotonic_clock", clock)

    # Tick A at T0: the previous cycle's mint is 560s old — the reviewer's
    # exact repro; its publication instant is T0 itself (zero elapsed). Tick
    # B at T0+660: the MAX SLIPPED fire (600s cycle + 60s AccuracySec,
    # codex-1 round-3 repro) — and its scan→build→write pass takes 27s of
    # publication work (advanced into the injectable clock), so tick A's
    # embedded admission had to cover 660+27=687s to keep the surface
    # gapless.
    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    _agy_admission(
        relay,
        observed_at=(t0 - timedelta(seconds=560)).isoformat().replace("+00:00", "Z"),
        stale_after_seconds=900,
    )
    slipped_fire_s = 660.0
    publish_work_s = 27.0
    summaries = []
    for tick, tick_now in enumerate((t0, t0 + timedelta(seconds=slipped_fire_s))):
        out = tmp_path / f"out-{tick}" / "quota-spend-ledger-live.json"
        clock.calls = 0
        clock.advance = bool(tick)  # tick B's in-pass publication work
        rc = namespace["main"](
            [
                "--now",
                tick_now.isoformat().replace("+00:00", "Z"),
                "--out",
                str(out),
                "--relay-receipt-dir",
                str(relay),
                "--platform-capability-receipt-dir",
                str(platform_receipts),
                "--nvidia-smi",
                str(stub),
                "--json",
            ]
        )
        assert rc == 0
        summaries.append(json.loads(capsys.readouterr().out))

    # Both ticks FORCED a mint (560s and 660s old both fail the freshness
    # predicate), every published ledger carried the full horizon ahead at
    # its ACTUAL publication instant, and tick A's embedded admission
    # covered tick B's slipped, slow publication — no stale interval anywhere
    # in the two cycles (codex-1 round-3 C1 repro, judged at the round-4
    # publication instant).
    assert forced == [True, True]
    horizon = namespace["FRESHNESS_HORIZON_S"]
    for summary in summaries:
        assert summary["admission_freshness_degraded"] is False
        assert summary["admission_freshness_at_publication_s"] >= horizon
    # The TRUE no-flap predicate (round-4 codex-2): tick A's embedded
    # admission outlives tick B's measured publication instant — the slipped
    # fire PLUS the 27s of publication work — not merely tick B's captured_at.
    published_b = datetime.fromisoformat(summaries[1]["published_at"].replace("Z", "+00:00"))
    assert published_b == t0 + timedelta(seconds=slipped_fire_s + publish_work_s)
    payload_a = json.loads((tmp_path / "out-0" / "quota-spend-ledger-live.json").read_text())
    fresh_until_a = next(
        s for s in payload_a["quota_snapshots"] if s["route_id"] == "agy.review.direct"
    )["fresh_until"]
    assert datetime.fromisoformat(fresh_until_a.replace("Z", "+00:00")) >= published_b
    # Tick B minted at its fire instant and published 27s later: 900-27=873s
    # of admission freshness remained at the actual publication instant.
    assert summaries[1]["admission_freshness_at_publication_s"] == 873.0


class SequenceClock:
    """Monotonic fake returning scripted values in order, holding the last.

    Scripts the elapsed profile of a tick — invocation anchor, pre-mint scan,
    lock deadline, publication read — with no sleeping and no wall clock."""

    def __init__(self, values: list[float]) -> None:
        self._values = values
        self.calls = 0

    def __call__(self) -> float:
        value = self._values[min(self.calls, len(self._values) - 1)]
        self.calls += 1
        return value


def test_continuity_gap_degrades_even_when_freshness_is_green(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """codex-1 round-5 C2, the consumer leg no remaining-lifetime predicate
    can see: tick B slips past tick A's published promise and THEN mints a
    fresh 2000s admission, so B's own freshness reads 2000s remaining — green —
    while the surface was dead for the 30s between A's expiry and B's
    publication. Only continuity against the promise A actually published
    witnesses the gap. Both ticks write the SAME ledger path, exactly the
    deployed surface."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    def run_tick(tick_now: datetime) -> tuple[int, dict, str]:
        rc = namespace["main"](
            [
                "--now",
                tick_now.isoformat().replace("+00:00", "Z"),
                "--out",
                str(out),
                "--relay-receipt-dir",
                str(relay),
                "--platform-capability-receipt-dir",
                str(platform_receipts),
                "--nvidia-smi",
                str(stub),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        return rc, json.loads(captured.out), captured.err

    # Tick A's mint promises t0+900; tick B slips to t0+930 — past that
    # promise — and mints 2000s, so its own admission is green on arrival.
    mint_stale_after = [900]

    def behavioral_pull(*, repo_root, receipt_dir, now, timeout=None):
        if namespace["pull_forward_force_needed"](receipt_dir, now=now):
            _agy_admission(
                relay,
                observed_at=now.isoformat().replace("+00:00", "Z"),
                stale_after_seconds=mint_stale_after[0],
            )
            return {
                "invoked": True,
                "forced": True,
                "ran": ["agy-review-quota"],
                "skipped": [],
                "ok": True,
            }
        return {"invoked": True, "forced": False, "ran": [], "skipped": [], "ok": True}

    monkeypatch.setitem(main_globals, "pull_forward_due_producers", behavioral_pull)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc_a, summary_a, _ = run_tick(t0)
    assert rc_a == 0  # cold start: no previous promise to be continuous with
    assert summary_a["admission_continuity_gap_s"] is None
    assert summary_a["previous_promise_fresh_until"] is None

    mint_stale_after[0] = 2000
    rc_b, summary_b, err_b = run_tick(t0 + timedelta(seconds=930))
    assert rc_b == 4
    assert "DEGRADED" in err_b and "coverage gap" in err_b
    assert summary_b["admission_freshness_degraded"] is False
    assert summary_b["admission_freshness_at_publication_s"] == 2000.0
    assert summary_b["admission_continuity_degraded"] is True
    assert summary_b["admission_continuity_gap_s"] == 30.0
    assert summary_b["previous_promise_fresh_until"] == (
        (t0 + timedelta(seconds=900)).isoformat().replace("+00:00", "Z")
    )
    assert summary_b["pull_forward"]["forced"] is True


def test_c2_counterexample_slow_pre_mint_scan_publishes_past_previous_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """codex-1 round-5 C2, the producer leg, through the REAL pull-forward:
    the force-decision scan runs before the mint, so neither the mint's anchor
    nor the write-pass measurement can see its duration. Tick B's scan takes
    250s against a 4s bound and its publication lands at t0+930 — 30s past
    tick A's t0+900 promise — while B's own 2000s admission reads green. The
    tick must exit 4 on BOTH witnesses (continuity gap + scan overrun), or a
    horizon derived from an unbounded scan keeps flapping the surface."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    def run_tick(tick_now: datetime, clock_values: list[float]) -> tuple[int, dict, str]:
        monkeypatch.setitem(main_globals, "monotonic_clock", SequenceClock(clock_values))
        rc = namespace["main"](
            [
                "--now",
                tick_now.isoformat().replace("+00:00", "Z"),
                "--out",
                str(out),
                "--relay-receipt-dir",
                str(relay),
                "--platform-capability-receipt-dir",
                str(platform_receipts),
                "--nvidia-smi",
                str(stub),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        return rc, json.loads(captured.out), captured.err

    real_run = subprocess.run
    determine_calls = {"count": 0}

    def routing_run(argv, *args, **kwargs):
        if not any(str(part).endswith("hapax-determine") for part in argv):
            return real_run(argv, *args, **kwargs)
        determine_calls["count"] += 1
        justified = argv[argv.index("--force-justified-at") + 1]
        # The mint the forced determine child would have produced: 900s on
        # tick A (promise t0+900), 2000s on tick B so B's own freshness
        # predicate reads green at its slipped publication.
        _agy_admission(
            relay,
            observed_at=justified,
            stale_after_seconds=900 if determine_calls["count"] == 1 else 2000,
        )
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=json.dumps(
                {
                    "now": justified,
                    "ran": [{"producer_id": "agy-review-quota"}],
                    "skipped": [],
                }
            ),
        )

    monkeypatch.setitem(
        main_globals,
        "subprocess",
        SimpleNamespace(
            run=routing_run,
            TimeoutExpired=subprocess.TimeoutExpired,
            SubprocessError=subprocess.SubprocessError,
        ),
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)

    # Tick A: scan 0s, publication 0s elapsed — published at t0, promise t0+900.
    rc_a, summary_a, _ = run_tick(t0, [0, 0, 0, 0, 0])
    assert rc_a == 0
    assert summary_a["admission_continuity_gap_s"] is None

    # Tick B fires at t0+660 (max slippage): the scan reads 250s elapsed
    # (anchor 0 → scan end 250), the write lands 20s later (read 270), so the
    # ledger publishes at t0+660+270 — the invocation-wide anchor is what
    # makes that arithmetic visible at all.
    rc_b, summary_b, err_b = run_tick(t0 + timedelta(seconds=660), [0, 0, 250, 250, 270])
    assert rc_b == 4
    assert "DEGRADED" in err_b and "coverage gap" in err_b
    assert "DEGRADED" in err_b and "pre-mint force-decision scan" in err_b
    assert summary_b["admission_freshness_degraded"] is False
    assert summary_b["admission_freshness_at_publication_s"] == 1730.0
    assert summary_b["admission_continuity_degraded"] is True
    assert summary_b["admission_continuity_gap_s"] == 30.0
    assert summary_b["pre_mint_scan_elapsed_s"] == 250.0
    assert summary_b["pre_mint_scan_overrun"] is True
    assert summary_b["previous_promise_fresh_until"] == (
        (t0 + timedelta(seconds=900)).isoformat().replace("+00:00", "Z")
    )
    assert summary_b["pull_forward"]["forced"] is True
    assert summary_b["pull_forward"]["ran"] == ["agy-review-quota"]
    assert determine_calls["count"] == 2


def test_continuity_green_when_published_within_promise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The negative leg: a tick that slips but publishes INSIDE the previous
    promise — 20s of write work on a t0+660 fire against a t0+900 promise —
    reports a 0.0 gap and exits 0. Continuity must witness gaps, not flag
    every slow tick."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    def run_tick(tick_now: datetime, clock_values: list[float]) -> tuple[int, dict, str]:
        monkeypatch.setitem(main_globals, "monotonic_clock", SequenceClock(clock_values))
        rc = namespace["main"](
            [
                "--now",
                tick_now.isoformat().replace("+00:00", "Z"),
                "--out",
                str(out),
                "--relay-receipt-dir",
                str(relay),
                "--platform-capability-receipt-dir",
                str(platform_receipts),
                "--nvidia-smi",
                str(stub),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        return rc, json.loads(captured.out), captured.err

    mint_stale_after = [900]

    def behavioral_pull(*, repo_root, receipt_dir, now, timeout=None):
        if namespace["pull_forward_force_needed"](receipt_dir, now=now):
            _agy_admission(
                relay,
                observed_at=now.isoformat().replace("+00:00", "Z"),
                stale_after_seconds=mint_stale_after[0],
            )
            return {
                "invoked": True,
                "forced": True,
                "ran": ["agy-review-quota"],
                "skipped": [],
                "ok": True,
            }
        return {"invoked": True, "forced": False, "ran": [], "skipped": [], "ok": True}

    monkeypatch.setitem(main_globals, "pull_forward_due_producers", behavioral_pull)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)

    rc_a, _, _ = run_tick(t0, [0, 0, 0])
    assert rc_a == 0

    mint_stale_after[0] = 2000
    rc_b, summary_b, err_b = run_tick(t0 + timedelta(seconds=660), [0, 0, 20])
    assert rc_b == 0
    assert "DEGRADED" not in err_b
    assert summary_b["admission_continuity_degraded"] is False
    assert summary_b["admission_continuity_gap_s"] == 0.0
    assert summary_b["admission_freshness_degraded"] is False
    assert summary_b["admission_freshness_at_publication_s"] == 1980.0
    assert summary_b["previous_promise_fresh_until"] == (
        (t0 + timedelta(seconds=900)).isoformat().replace("+00:00", "Z")
    )


def test_degraded_admission_is_reported_not_silent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the pull cannot secure a sufficient receipt (here: a lock_timeout
    skip behind a concurrent winner that leaves the old admission in place),
    the tick still writes its honest ledger — but the degradation is in the
    summary and on stderr, never a silent green pull (major finding on #4665,
    round 2)."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    # The stale admission a lock_timeout leaves behind: 560s old, 340s left.
    _agy_admission(
        relay,
        observed_at=(t0 - timedelta(seconds=560)).isoformat().replace("+00:00", "Z"),
        stale_after_seconds=900,
    )

    def skipping_pull(**kw):
        return {
            "invoked": True,
            "forced": True,
            "ran": [],
            "skipped": [{"producer_id": "agy-review-quota", "reason": "lock_timeout"}],
            "ok": True,
        }

    monkeypatch.setitem(main_globals, "pull_forward_due_producers", skipping_pull)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )
    assert rc == 4  # honest ledger, machine-checkable degradation (not aborted, not green)
    captured = capsys.readouterr()
    assert "DEGRADED" in captured.err
    assert "340" in captured.err
    assert "at publication" in captured.err
    assert "819" in captured.err  # the horizon the admission failed to cover
    assert "Next:" in captured.err
    summary = json.loads(captured.out)
    assert summary["admission_freshness_degraded"] is True
    assert summary["admission_freshness_at_publication_s"] == 340.0
    assert summary["freshness_horizon_s"] == 819.0


def test_publication_work_overrun_degrades_instead_of_reporting_captured_at(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """codex-1 round-4 major, exact repro shape: a 900s admission and 120s of
    publication work inside the scan→build→write pass. Judged at `captured_at`
    — sampled before the work — the tick reported 870-900s remaining and
    exited green while the surface actually published at 780s remaining, under
    the 815s horizon. The exit predicate must evaluate freshness at the
    MEASURED publication instant, so this tick is degraded and machine-
    checkable, not green."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    _agy_admission(relay, observed_at=NOW, stale_after_seconds=900)

    class OverrunClock:
        advance = False
        calls = 0

        def __call__(self) -> float:
            self.calls += 1
            return 1000.0 + (120.0 if self.advance and self.calls > 1 else 0.0)

    clock = OverrunClock()
    clock.advance = True  # every read after the pass anchor includes the overrun

    monkeypatch.setitem(main_globals, "monotonic_clock", clock)
    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {"invoked": True, "forced": False, "ran": [], "skipped": [], "ok": True},
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )
    assert rc == 4
    captured = capsys.readouterr()
    assert "DEGRADED" in captured.err
    assert "780" in captured.err
    assert "at publication" in captured.err
    summary = json.loads(captured.out)
    # 900s of admission freshness minus the 120s the pass actually took.
    assert summary["admission_freshness_at_publication_s"] == 780.0
    assert summary["admission_freshness_degraded"] is True
    assert summary["freshness_horizon_s"] == 819.0
    # The ledger's own captured_at is still the pre-work sampling instant —
    # the summary must not pretend it was the publication instant.
    assert summary["captured_at"] == NOW
    assert summary["published_at"] == "2026-06-10T00:02:00Z"


def test_pull_forward_reports_unparseable_harness_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """codex-2 round-4 test finding: rc=0 with unparseable stdout used to
    leave the pull silently green (ok=True, nothing recorded) — a harness
    whose --json contract broke degraded NOTHING. It must report the
    malformed output and mark the pull not-ok while continuing on existing
    receipts (degrade, never abort)."""
    namespace = runpy.run_path(str(SCRIPT))
    relay = tmp_path / "relay-receipts"
    relay.mkdir()

    def fake_run(argv, *, capture_output, text, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout="not json at all\n", stderr="")

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    info = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT,
        receipt_dir=relay,
        now=datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    assert info["ok"] is False
    assert info["ran"] == [] and info["skipped"] == []
    stderr = capsys.readouterr().err
    assert "not a JSON object" in stderr
    assert "Next:" in stderr
    assert "agy-review-quota" in stderr


def test_pull_forward_reports_parsed_non_object_harness_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """claude-1 round-5 minor: rc=0 with stdout that parses as JSON but is
    not an object (a bare list or string) used to slip past the is-None
    guard and the isinstance-dict reader alike — ok stayed True with nothing
    recorded, the same silently-green case one type away from the round-4
    unparseable finding. Parsed-but-not-an-object must degrade identically."""
    namespace = runpy.run_path(str(SCRIPT))
    relay = tmp_path / "relay-receipts"
    relay.mkdir()

    def fake_run(argv, *, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            argv, 0, stdout='["ran", "but", "no", "object"]\n', stderr=""
        )

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    info = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT,
        receipt_dir=relay,
        now=datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    assert info["ok"] is False
    assert info["ran"] == [] and info["skipped"] == []
    stderr = capsys.readouterr().err
    assert "not a JSON object" in stderr
    assert "Next:" in stderr


def test_receipt_refresh_failure_exits_three(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """rc=3 (receipt refresh failed) had no main-flow coverage: the refresh
    contract is 'degrade, not abort', and the nonzero exit is what makes the
    degradation machine-checkable (round-4 codex-2 test finding)."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    _agy_admission(relay, observed_at=NOW, stale_after_seconds=900)

    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)
    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {"invoked": True, "forced": False, "ran": [], "skipped": [], "ok": True},
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: False)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )
    assert rc == 3  # fresh admission, honest write, refresh failed
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipts_refreshed"] is False
    assert summary["admission_freshness_degraded"] is False


def test_live_ledger_lock_timeout_raises_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """claude-3 (round 4): acquiring the live-ledger lock was the tick's last
    unbounded wait — a holder that never released hung the tick into the
    unit's kill timeout. Bounded acquisition must raise a typed error the
    caller can exit on, mirroring determine's producer lock."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    out.parent.mkdir(parents=True)
    ticks = iter((0.0, 100.0, 200.0, 300.0))
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: next(ticks))
    monkeypatch.setattr(namespace["time"], "sleep", lambda seconds: None)
    with namespace["quota_spend_live_lock"](out, wait_s=150.0):
        with pytest.raises(namespace["LiveLedgerLockTimeout"]):
            with namespace["quota_spend_live_lock"](out, wait_s=150.0):
                pass


def test_live_ledger_lock_contention_exits_two_not_hanging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The main-flow contract for the bounded lock: a tick that cannot
    acquire the live ledger inside the wait writes NOTHING, exits 2 with next
    actions, and leaves the on-disk ledger untouched (claude-3, round 4)."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    # Six clock reads, exactly sized: the outer holder below (1), the
    # invocation anchor (2), the mint anchor for the pre-write diagnostic
    # (3 — round 12), main's lock-deadline base (4), and the two retry
    # comparisons that must first undershoot then overshoot the deadline
    # (5, 6) so the bounded wait expires instead of hanging or succeeding.
    step = iter((0.0, 100.0, 200.0, 300.0, 400.0, 500.0))

    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: next(step))
    monkeypatch.setattr(namespace["time"], "sleep", lambda seconds: None)
    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {"invoked": True, "forced": False, "ran": [], "skipped": [], "ok": True},
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)

    with namespace["quota_spend_live_lock"](out):
        rc = namespace["main"](
            [
                "--now",
                NOW,
                "--out",
                str(out),
                "--relay-receipt-dir",
                str(relay),
                "--platform-capability-receipt-dir",
                str(platform_receipts),
                "--nvidia-smi",
                str(stub),
                "--json",
            ]
        )
    assert rc == 2
    stderr = capsys.readouterr().err
    assert "held longer than" in stderr
    assert "Next:" in stderr
    assert not out.exists()  # nothing was published by the lock-starved tick


def test_pass2_rebuild_failure_fails_the_tick_and_preserves_the_pass1_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A reconciliation failure after a healing refresh must exit nonzero (the
    unit's OnFailure fires) and be distinguishable in the summary from the
    healthy 'blocker unchanged' case, while the pass-1 ledger on disk stays
    intact (major findings on #4665, round 2)."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setenv("HAPAX_DISPATCH_HOST", "")
    monkeypatch.setenv("HAPAX_DEFAULT_DISPATCH_HOST", "")
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(
        platform_receipts, reason_code="codex_exec_auth_refresh_token_invalidated"
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    real_build = main_globals["build_live_ledger"]
    builds: list[int] = []

    def failing_second_build(*a, **kw):
        builds.append(1)
        if len(builds) == 1:
            return real_build(*a, **kw)
        raise main_globals["QuotaSpendLedgerError"]("injected pass-2 validation failure")

    def healing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(platform_receipts)
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", healing_refresh)
    monkeypatch.setitem(main_globals, "build_live_ledger", failing_second_build)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )
    assert rc == 1
    assert len(builds) == 2
    captured = capsys.readouterr()
    assert "invalid after receipt refresh" in captured.err
    summary = json.loads(captured.out)
    assert summary["ledger_rebuilt_after_refresh"] is False
    assert "injected pass-2 validation failure" in summary["ledger_rebuild_after_refresh_error"]
    # The pass-1 ledger survived intact and parses.
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["captured_at"] == NOW


def test_clock_refresh_branch_without_now_uses_post_pull_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The production clock path (no --now): every scan judges receipt
    freshness against the time AFTER the pull child ran, so a mint the pull
    produces mid-tick is never rejected as future-dated (major finding on
    #4665). Round-2 tests only ever passed --now; this exercises main's
    datetime.now branches directly."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    class ControllableDatetime(datetime):
        clock = t0

        @classmethod
        def now(cls, tz=None):
            return cls.clock

    # The pull advances BOTH clocks like a real 27s child would: the wall
    # re-sample below judges receipt freshness post-pull, and the monotonic
    # elapsed carries the pull into the publication instant. A frozen
    # monotonic with an advancing wall is exactly the combination that masked
    # the round-7 M1 double-count, so this test refuses to freeze it.
    mono = {"elapsed": 0.0}

    def timed_pull(*, repo_root, receipt_dir, now, timeout=None):
        ControllableDatetime.clock = t0 + timedelta(seconds=27)
        mono["elapsed"] = 27.0
        _agy_admission(
            relay,
            observed_at=ControllableDatetime.clock.isoformat().replace("+00:00", "Z"),
            stale_after_seconds=900,
        )
        return {
            "invoked": True,
            "forced": True,
            "ran": ["agy-review-quota"],
            "skipped": [],
            "ok": True,
        }

    monkeypatch.setitem(main_globals, "datetime", ControllableDatetime)
    monkeypatch.setitem(main_globals, "pull_forward_due_producers", timed_pull)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: mono["elapsed"])

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["captured_at"] == (t0 + timedelta(seconds=27)).isoformat().replace("+00:00", "Z")
    summary = json.loads(capsys.readouterr().out)
    assert summary["admission_freshness_at_publication_s"] == 900.0


def test_publication_anchor_is_the_invocation_wall_clock_not_the_post_pull_resample(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M1 (#4665, round 7): under a real clock, `now` is re-sampled after the
    pull so the receipt scans judge post-pull freshness — but publication must
    anchor at the IMMUTABLE invocation wall clock, because the invocation-wide
    monotonic elapsed already carries the pull. Anchoring at the re-sample
    counted the pull twice: the reviewer repro (60s pull, publication 80s
    after the invocation) reported T+140, shaving 60s of honest freshness and
    manufacturing a phantom continuity gap into rc=4."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    class ControllableDatetime(datetime):
        clock = t0

        @classmethod
        def now(cls, tz=None):
            return cls.clock

    def timed_pull(*, repo_root, receipt_dir, now, timeout=None):
        # A 60s pull child: the wall moves 60s, the mint lands inside it.
        ControllableDatetime.clock = t0 + timedelta(seconds=60)
        _agy_admission(
            relay,
            observed_at=ControllableDatetime.clock.isoformat().replace("+00:00", "Z"),
            stale_after_seconds=900,
        )
        return {
            "invoked": True,
            "forced": True,
            "ran": ["agy-review-quota"],
            "skipped": [],
            "ok": True,
        }

    monkeypatch.setitem(main_globals, "datetime", ControllableDatetime)
    monkeypatch.setitem(main_globals, "pull_forward_due_producers", timed_pull)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)
    # invocation anchor 0.0 (pre-pull), pass-1 lock deadline 0.0,
    # publication read 80.0: 80s of invocation-wide monotonic elapsed.
    monkeypatch.setitem(main_globals, "monotonic_clock", SequenceClock([0.0, 0.0, 80.0]))

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    # The scans judge post-pull time (captured_at t0+60) while the publication
    # instant is the invocation wall anchor PLUS the measured elapsed (t0+80)
    # — never the post-pull re-sample plus elapsed (t0+140).
    assert payload["captured_at"] == (t0 + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    summary = json.loads(capsys.readouterr().out)
    assert summary["published_at"] == (t0 + timedelta(seconds=80)).isoformat().replace(
        "+00:00", "Z"
    )
    # 900s minted at t0+60, published at t0+80: 880s honestly remaining —
    # the double-counted T+140 would have read 820 and (against a promise
    # near expiry) degraded a healthy tick.
    assert summary["admission_freshness_at_publication_s"] == 880.0
    assert summary["admission_continuity_gap_s"] is None


def test_receipt_surface_gap_degrades_even_when_ledger_witnesses_are_green(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, rounds 8 and 10): the continuity witness measures the LEDGER's
    promise, but quota routing consumes the CAPABILITY RECEIPTS the refresh
    replaces — the reviewer's two-tick repro (900s admissions, ticks at T and
    T+660, a 260s second refresh) had the old receipt surface die at T+900
    with its replacement landing at T+940: a 40s hole both ticks reported as a
    zero gap. This models the second tick through the REAL expiry semantics:
    the predecessor is a 900s OBSERVED quota admission inside a 24h outer
    envelope (the live agy/claude/glmcp shape), so routing's effective expiry
    is the 900s admission — the round-9 witness read the 24h envelope instead
    and reported this exact tick green with a −85000s gap."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    # A fresh agy admission keeps every LEDGER witness green: 900s remaining
    # at publication, no previous promise on disk, no pass-2 continuity gap.
    _agy_admission(relay, observed_at=NOW)
    # The predecessor surface, live-shaped: quota OBSERVED with a 900s
    # admission inside a 24h outer envelope, observed 23:44 -> the quota
    # surface routing consumes died at 23:59; this tick's replacement lands
    # at the publication instant NOW (00:00) — a 60s hole. Under the round-9
    # outer-TTL reading the same predecessor "lived" to next-day 23:44 and
    # the hole read as a −82800s green gap.
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        # What the real refresh leaves behind: a replacement receipt observed
        # now, whose FILE landed at 00:00 — the per-platform publication
        # instant the round-11 witness reads from the file's own mtime
        # (codex-1 M1), pinned onto the frozen timeline here.
        _codex_platform_receipt(platform_receipts)
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    # rc=4 driven ONLY by the receipt-surface witness: the reviewer's
    # condition — every ledger witness green across a dead receipt surface —
    # is now machine-checkable at the routing consumer's effective expiry.
    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["admission_freshness_degraded"] is False
    # The ledger continuity witness is green — 0.0, not None, when the
    # refresh's receipt rewrite forces a pass-2 rebuild judged against the
    # promise pass 1 just published. Green either way: the hole this test
    # pins lives in the RECEIPT surface, which the ledger cannot see.
    assert summary["admission_continuity_degraded"] is False
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 60.0
    assert summary["receipt_publication_at"] == NOW
    # THE C1 pin: the predecessor expiry is the 900s quota admission's death
    # (23:59), never the 24h outer envelope (next-day 23:44).
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-09T23:59:00Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    # THE M1 pin: the landing instant is this platform's own file mtime
    # (00:00), and the loaded-registry flag sits beside the gap witnesses.
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:00:00Z"}
    assert summary["registry_pools_loaded"] is True


def _backup_codex_receipt(
    platform_receipts: Path,
    *,
    observed_at: str,
    outer_stale_after: str = "24h",
    quota_stale_after: str = "900s",
    name: str = "z-codex-backup.json",
) -> None:
    """A same-platform sibling receipt under an alphabetically-later name.

    Round 13's C1 shadow: `z-...` sorts after `codex.json`, so the old
    last-filename-wins scan consumed it even though routing's loader selects
    by greatest observed_at. Round 14's C1 shadows pass extreme stamps or
    short envelopes: a future-dated backup is newest-observed but routing
    REJECTS it, and an expired-newer backup is newest-observed but routing
    retains nothing from it.
    """
    source = platform_receipts.parent / "backup-source"
    _codex_platform_receipt(
        source,
        observed_at=observed_at,
        outer_stale_after=outer_stale_after,
        quota_stale_after=quota_stale_after,
    )
    backup = platform_receipts / name
    backup.write_text((source / "codex.json").read_text(), encoding="utf-8")
    stamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).timestamp()
    os.utime(backup, (stamp, stamp))


def test_receipt_surface_scan_selects_the_newest_observed_receipt_per_platform(
    tmp_path: Path,
) -> None:
    """C1 (#4665, round 13), selection pin: per platform the scan must keep the
    receipt routing's loader would consume — greatest observed_at, exact ties
    keeping the first file in name order — never whichever filename sorts
    last. An older z-codex-backup.json used to overwrite the refreshed
    codex.json's state, so the platform read as not replaced and a real
    continuity gap went unwitnessed."""
    namespace = runpy.run_path(str(SCRIPT))
    receipt_dir = tmp_path / "platform-receipts"
    receipt_dir.mkdir()
    _backup_codex_receipt(receipt_dir, observed_at="2026-06-09T22:00:00Z")
    _codex_platform_receipt(
        receipt_dir,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    _utime_platform_receipt(receipt_dir, "codex", "2026-06-09T23:47:00Z")

    states, no_named_route = namespace["_scan_receipt_surface"](
        receipt_dir, now=datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    )

    assert no_named_route == []
    observed_at, _expiry, published_at = states["codex"]
    # The refreshed receipt wins over the alphabetically-later backup…
    assert observed_at.isoformat() == "2026-06-09T23:44:00+00:00"
    # …so the publication instant is the refreshed file's own mtime, not the
    # backup's.
    assert published_at.isoformat() == "2026-06-09T23:47:00+00:00"


def test_receipt_surface_scan_tie_keeps_first_file_in_name_order(tmp_path: Path) -> None:
    """C1 (#4665, round 13), tie-break pin: routing's loader resolves equal
    observed_at stamps in favor of the first file in name order (strict >
    comparison over a sorted walk); the scan must resolve ties identically or
    the two surfaces can disagree about which file published a platform."""
    namespace = runpy.run_path(str(SCRIPT))
    receipt_dir = tmp_path / "platform-receipts"
    receipt_dir.mkdir()
    _backup_codex_receipt(receipt_dir, observed_at="2026-06-09T23:44:00Z")
    _codex_platform_receipt(
        receipt_dir,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    _utime_platform_receipt(receipt_dir, "codex", "2026-06-09T23:50:00Z")

    states, _ = namespace["_scan_receipt_surface"](
        receipt_dir, now=datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    )

    _observed_at, _expiry, published_at = states["codex"]
    assert published_at.isoformat() == "2026-06-09T23:50:00+00:00"


def test_receipt_surface_backup_receipt_cannot_mask_a_continuity_gap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, round 13), end-to-end: the reviewer's masking repro. Same
    dead-surface tick as the round-8/10 gap test above, plus an older
    z-codex-backup.json in the receipt dir. The last-filename-wins scan
    selected the backup before AND after the refresh, so the platform read as
    unchanged, no replacement was witnessed, and the tick reported rc=0 across
    a 60s hole — while routing still consumed codex.json. With the
    newest-observed selection the backup is inert and every gap assertion
    matches the no-backup tick exactly."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    _backup_codex_receipt(platform_receipts, observed_at="2026-06-09T22:00:00Z")
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(platform_receipts)
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 60.0
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:00:00Z"}


def test_receipt_surface_scan_selection_mirrors_routing_freshness_eligibility(
    tmp_path: Path,
) -> None:
    """C1 (#4665, round 14), eligibility pin: routing's loader consumes only
    receipts passing receipt_is_fresh — a stamp more than one minute into the
    future is rejected, and so is anything past its own stale_after. The scan
    must select among the ELIGIBLE receipts, so a future-dated backup cannot
    out-win the canonical receipt and an expired-newer backup cannot shadow a
    live envelope. Pinned against load_platform_capability_receipts itself
    (codex-1 D1, round 14): whenever the loader vouches for a platform, the
    scan's selected observed_at is the loader's; once nothing is eligible the
    scan falls back to newest-observed, because then routing holds nothing and
    the expired predecessor's evidence is exactly what the witness measures."""
    namespace = runpy.run_path(str(SCRIPT))
    receipt_dir = tmp_path / "platform-receipts"
    receipt_dir.mkdir()
    _codex_platform_receipt(
        receipt_dir,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    # Newest observed of all, but dated 10 minutes into the future: routing
    # rejects it, so the scan must never let it win while it stays future.
    _backup_codex_receipt(
        receipt_dir, observed_at="2026-06-10T00:10:00Z", name="z-codex-backup-future.json"
    )
    # Observed after the canonical receipt but already past its own 5m
    # envelope at NOW: routing retains nothing from it.
    _backup_codex_receipt(
        receipt_dir,
        observed_at="2026-06-09T23:50:00Z",
        outer_stale_after="5m",
        quota_stale_after="5m",
        name="z-codex-backup-expired.json",
    )
    # A plain older eligible sibling: never selected over the canonical.
    _backup_codex_receipt(
        receipt_dir, observed_at="2026-06-09T22:00:00Z", name="z-codex-backup-older.json"
    )
    now = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    states, _no_named_route = namespace["_scan_receipt_surface"](receipt_dir, now=now)
    loaded = namespace["load_platform_capability_receipts"](receipt_dir, now=now)

    assert set(loaded) == {"codex"}
    assert states["codex"][0] == namespace["ensure_utc"](loaded["codex"].observed_at)
    assert states["codex"][0].isoformat() == "2026-06-09T23:44:00+00:00"

    # Nothing eligible a day and an hour later (even the newest backup's own
    # 24h envelope has lapsed): the loader holds nothing, and the scan keeps
    # the newest-observed evidence for the historical-gap measurement.
    later = now + timedelta(days=1, hours=1)
    states_later, _ = namespace["_scan_receipt_surface"](receipt_dir, now=later)
    assert namespace["load_platform_capability_receipts"](receipt_dir, now=later) == {}
    assert states_later["codex"][0].isoformat() == "2026-06-10T00:10:00+00:00"


def test_receipt_surface_future_dated_backup_cannot_mask_a_continuity_gap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, round 14), end-to-end: the reviewer's masking repro. A
    z-codex-backup.json dated 10 minutes into the future won round-13's plain
    newest-observed scan before AND after the refresh, so codex read as
    unchanged, no replacement was witnessed, and the tick reported rc=0 with a
    null gap across a real 60s hole — while routing rejected the backup and
    kept consuming codex.json. Routing's freshness eligibility in the scan
    makes the future-dated backup inert and every gap assertion matches the
    no-backup tick exactly."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    _backup_codex_receipt(platform_receipts, observed_at="2026-06-10T00:10:00Z")
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(platform_receipts)
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 60.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-09T23:59:00Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:00:00Z"}


def test_receipt_surface_expired_newer_backup_cannot_fabricate_a_gap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, round 14), end-to-end: the inverse repro. A backup observed
    AFTER the canonical receipt (23:50) but already past its own 5m envelope at
    NOW won round-13's newest-observed scan, so the predecessor read as a 23:55
    quota-TTL expiry and the 00:00 replacement fabricated a 300s hole (rc=4)
    across a surface routing still accepted at the 24h envelope. Routing
    retains nothing from the expired backup; the scan must not either."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    # Eligible-unobservable canonical receipt: the 24h envelope vouches until
    # next-day 23:44 (codex.headless.full is subscription_quota).
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
    )
    _backup_codex_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:50:00Z",
        outer_stale_after="5m",
        quota_stale_after="5m",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(
            platform_receipts,
            outer_stale_after="24h",
            quota_stale_after="15m",
            quota_status="unobservable",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is False
    assert summary["receipt_continuity_gap_s"] == -85440.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T23:44:00Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]


def test_receipt_surface_future_backup_cannot_mask_a_gap_when_nothing_is_eligible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, round 15), end-to-end: the fallback combination the round-14
    regressions never combined. The canonical receipt's OWN envelope has lapsed
    (23:44 + 15m expired at 23:59) and a backup is stamped 10 minutes into the
    future, so at the 00:00 tick NOTHING is eligible and the historical
    fallback runs. The fallback must keep the expired predecessor's evidence
    while excluding the future-dated backup routing rejects outright: letting
    the backup win credited its 00:25 quota expiry as the predecessor, so the
    00:00 replacement read gap=-1500 and rc=0 across a real 60s hole."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="15m",
        quota_stale_after="900s",
    )
    _backup_codex_receipt(platform_receipts, observed_at="2026-06-10T00:10:00Z")
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(platform_receipts)
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 60.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-09T23:59:00Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:00:00Z"}


def test_receipt_surface_scan_clock_advances_with_publication_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C2 (#4665, round 15), end-to-end WITHOUT --now: each receipt scan must
    sample the wall clock where it runs, because routing judges the receipts
    it consumes with its own clock at that stage. A successor landing 65s into
    a refresh that completes at T+140 is future-dated only against the
    post-pull clock the round-14 scans kept reusing: judged against T, the
    successor scan rejects the replacement and selects the stale backup copy,
    the platform reads as unreplaced, and the tick exits rc=0 across a real
    60s hole. A scripted datetime drives the advancing-clock leg the frozen
    --now regressions cannot reach; routing selection, predecessor expiry,
    the 60s gap, and rc=4 all follow once the successor scan's clock moves
    past the successor's landing."""
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

    class _ScriptedClock(datetime):
        current = t0

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setitem(main_globals, "datetime", _ScriptedClock)
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    # Predecessor canonical: observed a minute before T, quota envelope
    # expiring at T+80 — the 60s hole the refresh's T+140 landing opens.
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:59:00Z",
        outer_stale_after="24h",
        quota_stale_after="140s",
    )
    # A stale same-observed_at copy under a later filename: eligible at every
    # clock here, so only the successor's landing — not the backup — can move
    # the selection once the scan clock advances past it.
    _backup_codex_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:59:00Z",
        outer_stale_after="24h",
        quota_stale_after="140s",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def slow_refresh(*, timeout, receipt_dir):
        _ScriptedClock.current = t0 + timedelta(seconds=65)
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-10T00:01:05Z",
            outer_stale_after="24h",
            quota_stale_after="15m",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:02:20Z")
        _ScriptedClock.current = t0 + timedelta(seconds=140)
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", slow_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 60.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T00:01:20Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:02:20Z"}


def test_receipt_surface_eligibility_transition_cannot_credit_an_old_mtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, round 16), end-to-end: the reviewer's exact repro. An
    untouched backup (observed T+200, mtime T-60) is future-dated at the
    predecessor scan, so the canonical (quota expiring T+80) is the
    predecessor. The refresh lands the canonical successor at T+140 and the
    successor scan's honest clock admits the backup — greatest observed_at —
    so the selection MOVES onto the backup. That move is an eligibility
    transition, not a republication: the backup only starts vouching at
    observed_at - 60s = T+140, and its OLD mtime must not be credited as the
    publication instant — pre-fix the tick read gap=-140 rc=0 across the real
    T+80..T+140 hole; the routable-from instant restores gap=60 rc=4."""
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

    class _ScriptedClock(datetime):
        current = t0

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setitem(main_globals, "datetime", _ScriptedClock)
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:59:00Z",
        outer_stale_after="24h",
        quota_stale_after="140s",
    )
    _backup_codex_receipt(
        platform_receipts,
        observed_at="2026-06-10T00:03:20Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
    )
    # The backup is an OLD file whose stamp is far ahead: pin its mtime a
    # minute before T, as an untouched artifact would carry.
    old_stamp = datetime.fromisoformat("2026-06-09T23:59:00+00:00").timestamp()
    os.utime(platform_receipts / "z-codex-backup.json", (old_stamp, old_stamp))
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _ScriptedClock.current = t0 + timedelta(seconds=140)
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-10T00:00:00Z",
            outer_stale_after="24h",
            quota_stale_after="15m",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:02:20Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 60.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T00:01:20Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:02:20Z"}


def test_receipt_surface_predecessor_scan_samples_the_clock_after_the_ledger_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C2/D1 (#4665, round 16), end-to-end: the missing clock leg — elapsed
    wall time BEFORE the predecessor scan. The canonical receipt is observed
    T+90, so it is future-dated against the post-pull clock T but admissible
    once the ledger pass has burned 70 real seconds and the predecessor scan
    samples its own clock (T+70). Judged against the stale T, the predecessor
    falls back to the long-expired backup (expiry T-300) and the successor
    landing at T+140 fabricated a 440s hole (rc=4); sampled after the ledger
    pass, the predecessor is the canonical (expiry T+170) and the same
    landing is honest uninterrupted coverage (gap=-30, rc=0)."""
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

    class _ScriptedClock(datetime):
        current = t0

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setitem(main_globals, "datetime", _ScriptedClock)
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW, stale_after_seconds=3600)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-10T00:01:30Z",
        outer_stale_after="24h",
        quota_stale_after="80s",
    )
    _backup_codex_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:50:00Z",
        outer_stale_after="5m",
        quota_stale_after="5m",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    original_load = main_globals["load_quota_spend_ledger"]

    def slow_ledger_pass(base):
        _ScriptedClock.current = t0 + timedelta(seconds=70)
        return original_load(base)

    def publishing_refresh(*, timeout, receipt_dir):
        _ScriptedClock.current = t0 + timedelta(seconds=140)
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-10T00:02:30Z",
            outer_stale_after="24h",
            quota_stale_after="15m",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:02:20Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "load_quota_spend_ledger", slow_ledger_pass)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is False
    assert summary["receipt_continuity_gap_s"] == -30.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T00:02:50Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]


def test_receipt_surface_tick_start_anchor_sees_holes_the_post_ledger_scan_masks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, round 17), end-to-end: the predecessor evidence must be the
    TICK-START snapshot, not a post-ledger rescan. The canonical's quota
    envelope dies at T+20; a backup observed T+100 only starts vouching at
    observed_at - 60s = T+40 — a real 20s hole. A 50s ledger pass lets the
    post-ledger rescan select the backup (no longer future-dated at T+50) and
    charge its OWN far-later expiry as the predecessor end, so the round-16
    predicate read rc=0 across the hole. Anchored at tick start, the walk
    from the canonical's T+20 expiry to the replacement's T+60 landing crosses
    the backup's honest T+40 coverage start and the hole is charged: rc=4."""
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

    class _ScriptedClock(datetime):
        current = t0

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setitem(main_globals, "datetime", _ScriptedClock)
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW, stale_after_seconds=3600)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:59:00Z",
        outer_stale_after="24h",
        quota_stale_after="80s",
    )
    # The backup's mtime is pinned to its own observed_at by the helper, so at
    # the T clock its tick-start interval is the skew-dropped honest one
    # [T+40, ...) — predecessor evidence even though selection shadows it.
    _backup_codex_receipt(
        platform_receipts,
        observed_at="2026-06-10T00:01:40Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    original_load = main_globals["load_quota_spend_ledger"]

    def slow_ledger_pass(base):
        _ScriptedClock.current = t0 + timedelta(seconds=50)
        return original_load(base)

    def publishing_refresh(*, timeout, receipt_dir):
        _ScriptedClock.current = t0 + timedelta(seconds=150)
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-10T00:01:00Z",
            outer_stale_after="24h",
            quota_stale_after="15m",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:01:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "load_quota_spend_ledger", slow_ledger_pass)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 20.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T00:00:20Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:01:00Z"}


def test_receipt_surface_maintaining_successor_survives_backup_winning_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M1 (#4665, round 17), end-to-end: when the final selection moves onto a
    backup (observed T+200, mtime pinned T-60), the REPLACEMENT the refresh
    actually wrote (canonical restamped T+40, landed T+40) is the successor
    that binds — not the backup's own routable-from. The successor lands
    inside the tick-begin coverage (canonical expiring T+80), so coverage was
    never interrupted; charging the backup's T+140 routable-from against the
    T+80 predecessor fabricated a 60s hole (rc=4) on uninterrupted coverage.
    The moved-path landing keeps gap=-40 rc=0 while still reporting the
    replacement."""
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

    class _ScriptedClock(datetime):
        current = t0

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setitem(main_globals, "datetime", _ScriptedClock)
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW, stale_after_seconds=3600)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:59:00Z",
        outer_stale_after="24h",
        quota_stale_after="140s",
    )
    _backup_codex_receipt(
        platform_receipts,
        observed_at="2026-06-10T00:03:20Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
    )
    # The backup is an OLD file whose stamp is far ahead: pin its mtime a
    # minute before T, as an untouched artifact would carry.
    old_stamp = datetime.fromisoformat("2026-06-09T23:59:00+00:00").timestamp()
    os.utime(platform_receipts / "z-codex-backup.json", (old_stamp, old_stamp))
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _ScriptedClock.current = t0 + timedelta(seconds=150)
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-10T00:00:40Z",
            outer_stale_after="24h",
            quota_stale_after="15m",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:40Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is False
    assert summary["receipt_continuity_gap_s"] == -40.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T00:01:20Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]


def test_selected_receipt_coverage_ignores_shadowed_longer_ttl() -> None:
    """C1 (#4665, round 18), helper: unioning readable lifetimes is not
    coverage. The older backup expires T+780; routing selects the canonical
    (newer observed) until the outer envelope dies, so coverage ends at the
    canonical quota death T+20."""
    namespace = runpy.run_path(str(SCRIPT))
    evidence = namespace["_ReceiptSurfaceEvidence"]
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)
    canonical = evidence(
        observed_at=t0 - timedelta(seconds=60),
        expiry=t0 + timedelta(seconds=20),
        routable_from=t0 - timedelta(seconds=60),
        path=Path("codex.json"),
        eligible_until=t0 - timedelta(seconds=60) + timedelta(hours=24),
    )
    backup = evidence(
        observed_at=t0 - timedelta(seconds=120),
        expiry=t0 + timedelta(seconds=780),
        routable_from=t0 - timedelta(seconds=120),
        path=Path("z-codex-backup.json"),
        eligible_until=t0 - timedelta(seconds=120) + timedelta(hours=24),
    )
    intervals = namespace["_selected_receipt_coverage_intervals"]([canonical, backup])
    assert intervals == [(canonical.routable_from, canonical.expiry)]
    hole = namespace["_first_uncovered_run_s"](
        intervals, t0 + timedelta(seconds=20), t0 + timedelta(seconds=60)
    )
    assert hole == 40.0


def test_selected_receipt_coverage_follows_selection_transitions() -> None:
    """C1 (#4665, round 18), helper: when a newer backup becomes eligible,
    selection moves onto it and its quota window concatenates. Canonical
    dies T+20; backup admitted T+40 — a 20s hole, not a 40s one."""
    namespace = runpy.run_path(str(SCRIPT))
    evidence = namespace["_ReceiptSurfaceEvidence"]
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)
    canonical = evidence(
        observed_at=t0 - timedelta(seconds=60),
        expiry=t0 + timedelta(seconds=20),
        routable_from=t0 - timedelta(seconds=60),
        path=Path("codex.json"),
        eligible_until=t0 - timedelta(seconds=60) + timedelta(hours=24),
    )
    backup = evidence(
        observed_at=t0 + timedelta(seconds=100),
        expiry=t0 + timedelta(seconds=1000),
        routable_from=t0 + timedelta(seconds=40),
        path=Path("z-codex-backup.json"),
        eligible_until=t0 + timedelta(seconds=100) + timedelta(hours=24),
    )
    intervals = namespace["_selected_receipt_coverage_intervals"]([canonical, backup])
    assert intervals == [
        (canonical.routable_from, canonical.expiry),
        (backup.routable_from, backup.expiry),
    ]
    hole = namespace["_first_uncovered_run_s"](
        intervals, t0 + timedelta(seconds=20), t0 + timedelta(seconds=60)
    )
    assert hole == 20.0


def test_interval_helpers_boundary_branches() -> None:
    """D1 (#4665, round 18): direct pins for merge / covering-end / hole
    helpers — empty, zero-width, adjacent merge, overlap, and the no-hole
    and start-of-window hole branches."""
    namespace = runpy.run_path(str(SCRIPT))
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)
    merge = namespace["_merge_half_open_intervals"]
    covering = namespace["_interval_covering_end"]
    uncovered = namespace["_first_uncovered_run_s"]
    assert merge([]) == []
    assert merge([(t0, t0)]) == []
    assert merge([(t0 + timedelta(seconds=5), t0)]) == []
    a = (t0, t0 + timedelta(seconds=10))
    b = (t0 + timedelta(seconds=10), t0 + timedelta(seconds=20))
    c = (t0 + timedelta(seconds=15), t0 + timedelta(seconds=25))
    assert merge([a, b]) == [(t0, t0 + timedelta(seconds=20))]
    assert merge([a, c]) == [(t0, t0 + timedelta(seconds=10)), c]
    assert covering([a], t0 + timedelta(seconds=5)) == t0 + timedelta(seconds=10)
    assert covering([a], t0 + timedelta(seconds=10)) is None
    assert covering([a], t0 - timedelta(seconds=1)) is None
    assert uncovered([a, b], t0, t0 + timedelta(seconds=20)) is None
    assert uncovered([b], t0, t0 + timedelta(seconds=20)) == 10.0
    assert uncovered([a], t0 + timedelta(seconds=20), t0 + timedelta(seconds=10)) is None


def test_receipt_routable_from_near_future_mtime_is_not_backdated(tmp_path: Path) -> None:
    """C2 (#4665, round 18), unit: a landing 0.7s past a truncated scan clock
    keeps the file stamp. Falling back to observed_at - 60s would manufacture
    T+0 coverage across a real T+20..T+60.7 lapse."""
    namespace = runpy.run_path(str(SCRIPT))
    path = tmp_path / "codex.json"
    path.write_text("{}", encoding="utf-8")
    observed = datetime(2026, 6, 10, 0, 1, 0, tzinfo=UTC)
    landing = observed + timedelta(microseconds=700_000)
    checked_now = observed  # truncated T+60.0 against landing T+60.7
    _utime_platform_receipt(tmp_path, "codex", "2026-06-10T00:01:00.700000Z")
    routable = namespace["_receipt_routable_from"](observed, path, checked_now)
    assert routable == landing
    assert routable != observed - timedelta(minutes=1)


def test_receipt_routable_from_far_future_mtime_uses_admitted_at(tmp_path: Path) -> None:
    """C2 (#4665, round 18), unit: a months-ahead mtime is fixture residue,
    not a near-future truncation, so routable-from stays the admissibility
    bound — the synthetic-fixture shape the round-17 skew guard exists for."""
    namespace = runpy.run_path(str(SCRIPT))
    path = tmp_path / "codex.json"
    path.write_text("{}", encoding="utf-8")
    observed = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)
    _utime_platform_receipt(tmp_path, "codex", "2026-09-10T00:00:00Z")
    routable = namespace["_receipt_routable_from"](observed, path, observed)
    assert routable == observed - timedelta(minutes=1)


def test_receipt_surface_shadowed_older_backup_cannot_mask_a_quota_lapse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, round 18), end-to-end: canonical observed T-60, quota TTL
    80s, expires T+20; an older backup observed T-120, quota TTL 900s,
    expires T+780; both outer envelopes last 24h. Routing keeps selecting
    the canonical until the replacement lands T+60, leaving a 40s quota
    lapse. Unioning readable lifetimes credited the backup (gap=-720 rc=0);
    constructing coverage from the selected receipt reports rc=4 gap=40."""
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

    class _ScriptedClock(datetime):
        current = t0

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setitem(main_globals, "datetime", _ScriptedClock)
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW, stale_after_seconds=3600)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:59:00Z",
        outer_stale_after="24h",
        quota_stale_after="80s",
    )
    _utime_platform_receipt(platform_receipts, "codex", "2026-06-09T23:59:00Z")
    _backup_codex_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:58:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    states, _ = namespace["_scan_receipt_surface"](platform_receipts, now=t0)
    assert states["codex"][0] == t0 - timedelta(seconds=60)
    assert states["codex"][1] == t0 + timedelta(seconds=20)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _ScriptedClock.current = t0 + timedelta(seconds=60)
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-10T00:01:00Z",
            outer_stale_after="24h",
            quota_stale_after="15m",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:01:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 40.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T00:00:20Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:01:00Z"}


def test_receipt_surface_fractional_mtime_does_not_backdate_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C2 (#4665, round 18), end-to-end WITHOUT --now: predecessor expires
    T+20, successor observed T+60 lands T+60.7, final scan T+60.8. Truncating
    the successor scan clock to whole seconds made landing > checked_now and
    the skew guard replaced it with observed_at - 60s, reporting publication
    T, gap=-20 rc=0 across the 40.7s lapse. Keeping precision reports rc=4
    and gap=40.7."""
    t0 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

    class _ScriptedClock(datetime):
        current = t0

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setitem(main_globals, "datetime", _ScriptedClock)
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW, stale_after_seconds=3600)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:59:00Z",
        outer_stale_after="24h",
        quota_stale_after="80s",
    )
    _utime_platform_receipt(platform_receipts, "codex", "2026-06-09T23:59:00Z")
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-10T00:01:00Z",
            outer_stale_after="24h",
            quota_stale_after="15m",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:01:00.700000Z")
        _ScriptedClock.current = t0 + timedelta(seconds=60, microseconds=800_000)
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 40.7
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T00:00:20Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {
        "codex": "2026-06-10T00:01:00.700000Z"
    }


def test_receipt_surface_scan_drops_a_platform_whose_every_receipt_is_future_dated(
    tmp_path: Path,
) -> None:
    """C1 (#4665, round 16), scan-level: the empty-pool branch. When every
    candidate for a platform is future-dated there is no honest evidence —
    not fresh, not expired-predecessor — so the platform appears in NEITHER
    the states mapping NOR the no-named-route list: a silent no-evidence
    state, distinct from both the fresh and the expired-fallback legs, and
    invisible to the gap witnesses by design (fabricating any window from a
    clock-skewed stamp is worse)."""
    namespace = runpy.run_path(str(SCRIPT))
    receipt_dir = tmp_path / "platform-receipts"
    receipt_dir.mkdir()
    _codex_platform_receipt(
        receipt_dir,
        observed_at="2026-06-10T00:10:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
    )
    _backup_codex_receipt(
        receipt_dir, observed_at="2026-06-10T00:05:00Z", name="z-codex-backup.json"
    )
    now = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    states, no_named_route = namespace["_scan_receipt_surface"](receipt_dir, now=now)

    assert states == {}
    assert no_named_route == []


def test_future_dating_tolerance_matches_receipt_is_fresh(
    tmp_path: Path,
) -> None:
    """claude-1 (#4665, round 16): the scan reuses one future-dating window
    for fallback admissibility and the routable-from instant, and the window
    must be receipt_is_fresh's own — pinned at both edges so a drift in
    either place fails here instead of silently disagreeing with routing."""
    namespace = runpy.run_path(str(SCRIPT))
    tolerance = namespace["FUTURE_DATING_TOLERANCE"]
    now = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    at_edge = tmp_path / "edge"
    past_edge = tmp_path / "past-edge"
    at_edge.mkdir()
    past_edge.mkdir()
    _codex_platform_receipt(
        at_edge,
        observed_at=(now + tolerance).strftime("%Y-%m-%dT%H:%M:%SZ"),
        outer_stale_after="24h",
        quota_stale_after="15m",
    )
    _codex_platform_receipt(
        past_edge,
        observed_at=(now + tolerance + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        outer_stale_after="24h",
        quota_stale_after="15m",
    )

    edge_states, _ = namespace["_scan_receipt_surface"](at_edge, now=now)
    past_states, _ = namespace["_scan_receipt_surface"](past_edge, now=now)

    assert namespace["receipt_is_fresh"](
        namespace["load_platform_capability_receipt"](at_edge / "codex.json"), now=now
    ) is (edge_states != {})
    assert namespace["receipt_is_fresh"](
        namespace["load_platform_capability_receipt"](past_edge / "codex.json"), now=now
    ) is (past_states != {})
    assert edge_states != {}
    assert past_states == {}


@pytest.mark.parametrize(
    ("route_wrappers", "expected_expiry"),
    [
        # Unreadable named wrapper: routing recomputes capability BLOCKED, the
        # unobservable-quota envelope leg fails, and the quota TTL binds
        # (23:44 + 15m = 23:59) — the reviewer's round-14 M1 repro shape.
        (
            {
                "codex.headless.full": {
                    "path": "scripts/hapax-codex-headless",
                    "exists": False,
                    "executable": False,
                    "sha256": None,
                }
            },
            "2026-06-09T23:59:00Z",
        ),
        # Readable named wrapper: statuses stay OBSERVED under recomputation
        # and the subscription envelope leg survives (next-day 23:44).
        (
            {
                "codex.headless.full": {
                    "path": "scripts/hapax-codex-headless",
                    "exists": True,
                    "executable": True,
                    "sha256": "0" * 64,
                }
            },
            "2026-06-10T23:44:00Z",
        ),
    ],
)
def test_receipt_surface_expiry_mirrors_route_payload_recomputation(
    tmp_path: Path,
    route_wrappers: dict[str, dict[str, object]],
    expected_expiry: str,
) -> None:
    """M1 (#4665, round 14): routing recomputes per-route capability/resource
    statuses from the receipt's route_wrappers BEFORE the unobservable-quota
    envelope decision, so receipt-level statuses are not what routing consumes.
    The witness's expiry must equal observed_at plus the quota stale_after
    _apply_receipt_to_route_payload — routing's own applier — actually applied
    to the named route (codex-1 D1, round 14), for both the failing and the
    surviving recomputation."""
    namespace = runpy.run_path(str(SCRIPT))
    receipt_dir = tmp_path / "platform-receipts"
    receipt_dir.mkdir()
    _codex_platform_receipt(
        receipt_dir,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
        route_wrappers=route_wrappers,
    )
    from shared.platform_capability_registry import _apply_receipt_to_route_payload

    receipt = namespace["load_platform_capability_receipt"](receipt_dir / "codex.json")
    route_pools = namespace["static_registry_route_pools"]()
    pool, source = route_pools["codex.headless.full"]
    route_payload = {
        "route_id": "codex.headless.full",
        "capacity_pool": pool.value,
        "telemetry": {"quota_source": source.value},
        "freshness": {
            "evidence": {"capability": {}, "resource": {}, "quota": {}, "provider_docs": {}}
        },
    }
    _apply_receipt_to_route_payload(route_payload, receipt)
    applied_expiry = namespace["ensure_utc"](receipt.observed_at) + namespace[
        "parse_duration_spec"
    ](route_payload["freshness"]["quota_stale_after"])

    expiry = namespace["receipt_surface_effective_expiry"](receipt, route_pools)

    assert expiry == applied_expiry
    assert expiry.isoformat().replace("+00:00", "Z") == expected_expiry


def test_receipt_surface_unreadable_route_wrapper_holds_the_quota_ttl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M1 (#4665, round 14), end-to-end: the reviewer's repro. An eligible
    unobservable quota with OBSERVED receipt-level statuses but an UNREADABLE
    named route wrapper: routing recomputes the per-route capability status to
    blocked, fails the nonblocking test, and holds the platform at the quota
    TTL — while the round-13 helper trusted receipt-level statuses, granted
    the 24h envelope, and read a green tick across a real 60s hole."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
        route_wrappers={
            "codex.headless.full": {
                "path": "scripts/hapax-codex-headless",
                "exists": False,
                "executable": False,
                "sha256": None,
            }
        },
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(
            platform_receipts,
            outer_stale_after="24h",
            quota_stale_after="15m",
            quota_status="unobservable",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 60.0
    # The quota TTL binds despite the 24h envelope: routing's per-route
    # recomputation saw the unreadable wrapper.
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-09T23:59:00Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_publication_instants"] == {"codex": "2026-06-10T00:00:00Z"}


def test_receipt_surface_readable_route_wrapper_keeps_the_envelope_leg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M1 (#4665, round 14), positive control: with a READABLE named route
    wrapper the per-route recomputation keeps both statuses OBSERVED, the
    subscription envelope leg survives exactly as the wrapper-less shape
    does, and an uninterrupted surface stays honestly green. Without this
    control, a mirror that held every route_wrappers-bearing receipt at the
    quota TTL would pass the unreadable repro while flapping every live
    envelope."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:30:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
        route_wrappers={
            "codex.headless.full": {
                "path": "scripts/hapax-codex-headless",
                "exists": True,
                "executable": True,
                "sha256": "0" * 64,
            }
        },
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(
            platform_receipts,
            outer_stale_after="24h",
            quota_stale_after="15m",
            quota_status="unobservable",
            route_wrappers={
                "codex.headless.full": {
                    "path": "scripts/hapax-codex-headless",
                    "exists": True,
                    "executable": True,
                    "sha256": "0" * 64,
                }
            },
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is False
    assert summary["receipt_continuity_gap_s"] == -84600.0
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T23:30:00Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]


def test_receipt_surface_outer_ttl_leg_subscription_unobservable_quota(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The other half of the C1 fix (#4665, round 10): quota UNOBSERVABLE for
    exactly the nonblocking reasons, with capability and resource OBSERVED,
    keeps vouching for the OUTER stale_after — the live api/codex shape
    (account_live_quota_receipt_absent, 24h envelope over a 15m quota TTL).
    The witness must read THAT expiry too, or every such platform would flap
    rc=4 on a surface routing still accepts. Route pools come from the REAL
    static registry: codex.headless.full is subscription_quota, which is what
    makes this leg live."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    # Eligible-unobservable predecessor: quota unobservable for exactly
    # account_live_quota_receipt_absent, capability+resource observed, 15m
    # quota TTL inside a 24h outer envelope, observed 23:30 -> routing keeps
    # vouching until NEXT-DAY 23:30. This tick's replacement at 00:00 lands
    # ~23.5h inside the envelope: no hole, honestly green.
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:30:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(
            platform_receipts,
            outer_stale_after="24h",
            quota_stale_after="15m",
            quota_status="unobservable",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is False
    # The outer-envelope leg, pinned: the predecessor expiry is the 24h
    # envelope's far edge (next-day 23:30), not the 15m quota TTL (23:45).
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T23:30:00Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_continuity_gap_s"] == -84600.0


def test_receipt_surface_fail_closed_leg_blocked_capability_holds_quota_ttl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The fail-closed leg of the C1 fix (#4665, round 10), live-shaped after
    vibe (measured 2026-09-12: capability BLOCKED, quota unobservable): an
    unobservable quota whose capability surface is blocked never earns the
    outer envelope, no matter how eligible its reasons and pools are — the
    routing consumer keeps it at the quota TTL, and so must the witness. A
    hole between that quota TTL and the replacement IS a real hole."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    # Blocked-capability predecessor: same eligible reasons and (registry)
    # pools as the outer leg, but capability+resource BLOCKED -> the
    # effective expiry stays at the 15m quota TTL (observed 23:40 -> dies
    # 23:55; replacement lands at 00:00 — a 300s hole).
    _codex_platform_receipt(
        platform_receipts,
        reason_code="codex_exec_auth_blocked",
        observed_at="2026-06-09T23:40:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def publishing_refresh(*, timeout, receipt_dir):
        _codex_platform_receipt(
            platform_receipts,
            reason_code="codex_exec_auth_blocked",
            outer_stale_after="24h",
            quota_stale_after="15m",
            quota_status="unobservable",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", publishing_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is True
    assert summary["receipt_continuity_gap_s"] == 300.0
    # Fail-closed pin: the quota TTL binds (23:55), never the 24h envelope.
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-09T23:55:00Z"
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]


def test_receipt_surface_staggered_replacements_keep_continuous_coverage_green(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M1 (#4665, round 11): each replaced platform is judged by its OWN
    landing instant, never the refresh's completion instant. The refresh
    writes platforms separately — codex replaced at 23:47 (inside its 23:59
    predecessor expiry), claude at 00:03 (inside its 00:05 expiry) — and the
    tick completes at 00:10. The round-10 witness charged every platform the
    whole refresh's tail: 00:10 against the earliest predecessor expiry
    (23:59) read a fictitious 660s hole and flapped rc=4 on uninterrupted
    coverage (the reviewer's T+40/T+200/T+260 repro shape)."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at="2026-06-10T00:10:00Z")
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:44:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    _codex_platform_receipt(
        platform_receipts,
        platform="claude",
        observed_at="2026-06-09T23:50:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def staggered_refresh(*, timeout, receipt_dir):
        # Round-16 semantics: a receipt is routable from
        # max(landing, observed_at - FUTURE_DATING_TOLERANCE), so the fixture
        # must keep the physical ordering the production filesystem guarantees
        # (observed_at <= mtime). The default observed_at (23:59) would pin
        # codex routable at 23:58 against its 23:59 predecessor expiry and
        # shrink the judged margin to 60s of a coverage that physically
        # landed at 23:47.
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-09T23:46:00Z",
            outer_stale_after="24h",
            quota_stale_after="900s",
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-09T23:47:00Z")
        _codex_platform_receipt(
            platform_receipts,
            platform="claude",
            observed_at="2026-06-10T00:02:00Z",
            outer_stale_after="24h",
            quota_stale_after="15m",
        )
        _utime_platform_receipt(platform_receipts, "claude", "2026-06-10T00:03:00Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", staggered_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            "2026-06-10T00:10:00Z",
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_continuity_degraded"] is False
    # The worst platform binds: claude's 00:03 landing against its 00:05
    # predecessor expiry is the tightest coverage, 120s of margin.
    assert summary["receipt_continuity_gap_s"] == -120.0
    assert summary["receipt_surface_replaced_platforms"] == ["claude", "codex"]
    assert summary["receipt_surface_publication_instants"] == {
        "claude": "2026-06-10T00:03:00Z",
        "codex": "2026-06-09T23:47:00Z",
    }
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-09T23:59:00Z"


def test_receipt_surface_expiry_never_outlives_the_outer_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """C1 (#4665, round 12; codex-1 critical, independently confirmed by
    glm-1 and claude-1): routing's loader rejects an expired OUTER envelope
    before applying any quota evidence, so a 900s quota admission inside a
    60s envelope dies WITH the envelope at 23:51 — never at observed+900s
    (00:05). Before the cap the witness vouched 280s past routing's real
    death and the 00:00:20 replacement read green (gap −280) against a
    surface routing had already refused at 23:51; capped, the same tick
    reports the true 560s hole and flaps rc=4."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at="2026-06-10T00:00:30Z")
    # Predecessor: quota OBSERVED with a 900s TTL inside a 60s outer
    # envelope — the reviewer's exact repro shape.
    _codex_platform_receipt(
        platform_receipts,
        observed_at="2026-06-09T23:50:00Z",
        outer_stale_after="60s",
        quota_stale_after="900s",
    )
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def replace_past_the_envelope(*, timeout, receipt_dir):
        # The successor names a route NO registry carries, so its own expiry
        # fails closed to the quota TTL — capped to the same 60s envelope, so
        # the gap math is untouched while the no-named-route key (claude-1
        # minor, #4665 round 12) gets its main-flow leg here.
        _codex_platform_receipt(
            platform_receipts,
            observed_at="2026-06-10T00:00:00Z",
            outer_stale_after="60s",
            quota_stale_after="900s",
            routes=["codex.retired.route"],
        )
        _utime_platform_receipt(platform_receipts, "codex", "2026-06-10T00:00:20Z")
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", replace_past_the_envelope)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            "2026-06-10T00:00:30Z",
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    # The predecessor's effective expiry is the OUTER envelope edge (23:51),
    # not observed+900s (00:05): the envelope cap is the fix under test.
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-09T23:51:00Z"
    assert summary["receipt_continuity_gap_s"] == 560.0
    assert summary["receipt_continuity_degraded"] is True
    # The successor names no registry route: the fail-closed fallback the gap
    # witnesses cannot see is named in the summary, post-refresh state.
    assert summary["receipt_surface_no_named_route_platforms"] == ["codex"]


def test_registry_pools_loaded_flag_witnesses_the_fail_closed_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """claude-1 minor (#4665, round 10): a registry that fails to load fails
    every receipt closed to the quota TTL with only a stderr note. The
    --json summary carries the loaded flag beside the gap witnesses so the
    machine-checkable surface can tell fail-closed-from-failure apart from
    pools-loaded-and-genuinely-tight."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    monkeypatch.setitem(
        main_globals,
        "PLATFORM_CAPABILITY_REGISTRY",
        Path("/nonexistent/hapax-platform-capability-registry.json"),
    )
    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["registry_pools_loaded"] is False
    assert "static capability registry unavailable" in captured.err


POOL_SOURCE_COMBOS = [
    ("subscription_quota", "manual", True),
    ("subscription_quota", "ledger", True),
    ("api_paid_spend", "ledger", True),
    ("bootstrap_budget", "ledger", True),
    ("api_paid_spend", "manual", False),
    ("bootstrap_budget", "cli", False),
    ("local_compute", "cli", False),
]


def _load_written_receipt(receipt_dir: Path):
    sys.path.insert(0, str(REPO_ROOT))
    from shared.platform_capability_receipts import load_platform_capability_receipt

    return load_platform_capability_receipt(receipt_dir / "codex.json")


def test_receipt_surface_effective_expiry_mirrors_the_routing_consumer(
    tmp_path: Path,
) -> None:
    """The C1 pin (#4665, rounds 10 and 14): the writer's expiry helper must
    agree with the routing consumer's own eligibility rule on every
    pool/source combo. Since round 14 the helper mirrors by CALLING the
    registry's private helpers (drift-proof against re-derivation, codex-1
    M1); this test still pins the envelope decision against the registry's
    own nonblocking rule as reference, over wrapper-less receipts where
    routing passes receipt-level statuses through unchanged — the per-route
    wrapper recomputation itself is pinned separately by the round-14
    route_payload_recomputation test."""
    sys.path.insert(0, str(REPO_ROOT))
    import shared.platform_capability_registry as capability_registry

    namespace = runpy.run_path(str(SCRIPT))
    expiry_of = namespace["receipt_surface_effective_expiry"]
    nonblocking_of = capability_registry._quota_unobservable_nonblocking
    observed = datetime.fromisoformat("2026-06-09T23:00:00+00:00")

    def expiry_dt(receipt, pools):
        pool, source = pools
        return expiry_of(
            receipt,
            {
                receipt.routes[0]: (
                    capability_registry.CapacityPool(pool),
                    capability_registry.QuotaSource(source),
                )
            },
        )

    # OBSERVED quota: the admission's own TTL binds on every combo — pools
    # never buy an observed admission the outer envelope.
    _codex_platform_receipt(
        tmp_path,
        observed_at="2026-06-09T23:00:00Z",
        outer_stale_after="24h",
        quota_stale_after="900s",
    )
    observed_receipt = _load_written_receipt(tmp_path)
    for pool, source, _eligible in POOL_SOURCE_COMBOS:
        payload = {"capacity_pool": pool, "telemetry": {"quota_source": source}}
        assert expiry_dt(observed_receipt, (pool, source)) == observed + timedelta(seconds=900)
        assert nonblocking_of(payload, observed_receipt) is False

    # Eligible-unobservable quota: outer envelope exactly where the routing
    # consumer's nonblocking rule says so, quota TTL everywhere else.
    _codex_platform_receipt(
        tmp_path,
        observed_at="2026-06-09T23:00:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
    )
    unobservable_receipt = _load_written_receipt(tmp_path)
    for pool, source, eligible in POOL_SOURCE_COMBOS:
        payload = {"capacity_pool": pool, "telemetry": {"quota_source": source}}
        expected = observed + (timedelta(hours=24) if eligible else timedelta(minutes=15))
        assert expiry_dt(unobservable_receipt, (pool, source)) == expected
        assert (nonblocking_of(payload, unobservable_receipt) is True) is eligible

    # Reasons outside the nonblocking set: fail closed regardless of pool.
    _codex_platform_receipt(
        tmp_path,
        observed_at="2026-06-09T23:00:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
        quota_reason_codes=["account_live_quota_receipt_absent", "provider_api_refused"],
    )
    refused_receipt = _load_written_receipt(tmp_path)
    for pool, source, _eligible in POOL_SOURCE_COMBOS:
        payload = {"capacity_pool": pool, "telemetry": {"quota_source": source}}
        assert expiry_dt(refused_receipt, (pool, source)) == observed + timedelta(minutes=15)
        assert nonblocking_of(payload, refused_receipt) is False

    # Short-envelope legs (#4665 round 12, C1): routing's loader rejects the
    # receipt once the OUTER envelope dies, BEFORE any quota evidence
    # applies — and _quota_unobservable_nonblocking itself does no envelope
    # filtering, so THIS composition must add the cap or the mirror and the
    # writer diverge on short envelopes. Every branch converges at the
    # envelope edge when the quota TTL outlives it; none may vouch past it.
    _codex_platform_receipt(
        tmp_path,
        observed_at="2026-06-09T23:00:00Z",
        outer_stale_after="60s",
        quota_stale_after="900s",
    )
    short_observed = _load_written_receipt(tmp_path)
    for pool, source, _eligible in POOL_SOURCE_COMBOS:
        payload = {"capacity_pool": pool, "telemetry": {"quota_source": source}}
        assert expiry_dt(short_observed, (pool, source)) == observed + timedelta(seconds=60)
        assert nonblocking_of(payload, short_observed) is False

    _codex_platform_receipt(
        tmp_path,
        observed_at="2026-06-09T23:00:00Z",
        outer_stale_after="60s",
        quota_stale_after="900s",
        quota_status="unobservable",
    )
    short_unobservable = _load_written_receipt(tmp_path)
    for pool, source, _eligible in POOL_SOURCE_COMBOS:
        payload = {"capacity_pool": pool, "telemetry": {"quota_source": source}}
        # Eligible pools vouch the envelope itself; every other branch caps
        # the 900s quota TTL at the same 60s edge — converged at 23:01,
        # never at 23:15.
        assert expiry_dt(short_unobservable, (pool, source)) == observed + timedelta(seconds=60)


def test_mixed_named_route_pools_bind_the_platform_at_the_earliest_expiry(
    tmp_path: Path,
) -> None:
    """A receipt naming routes in different pools binds the platform at the
    EARLIEST per-route expiry: one non-qualifying route holds the whole
    platform at the shorter TTL, mirroring the per-route consumer — the
    platform aggregate may never outlive its soonest-dying route."""
    namespace = runpy.run_path(str(SCRIPT))
    expiry_of = namespace["receipt_surface_effective_expiry"]
    observed = datetime.fromisoformat("2026-06-09T23:00:00+00:00")
    _codex_platform_receipt(
        tmp_path,
        observed_at="2026-06-09T23:00:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
        routes=["codex.headless.full", "codex.local.compute"],
    )
    receipt = _load_written_receipt(tmp_path)
    pool_of = namespace["CapacityPool"]
    source_of = namespace["QuotaSource"]
    mixed = {
        "codex.headless.full": (pool_of("subscription_quota"), source_of("manual")),
        "codex.local.compute": (pool_of("local_compute"), source_of("cli")),
    }
    # The local_compute route dies at the 15m quota TTL while the subscription
    # route would carry the 24h envelope: the platform binds at 15m.
    assert expiry_of(receipt, mixed) == observed + timedelta(minutes=15)
    all_eligible = {
        "codex.headless.full": (pool_of("subscription_quota"), source_of("manual")),
        "codex.local.compute": (pool_of("api_paid_spend"), source_of("ledger")),
    }
    assert expiry_of(receipt, all_eligible) == observed + timedelta(hours=24)
    # A receipt naming no registry route at all fails closed to the quota TTL.
    assert (
        expiry_of(receipt, {})
        == expiry_of(receipt, {"some.other.route": ("subscription_quota", "manual")})
        == observed + timedelta(minutes=15)
    )


def test_static_registry_route_pools_pins_the_live_outer_leg_facts() -> None:
    """The outer-envelope leg is only live because the REAL registry pools say
    so: codex routes are subscription_quota and the api gateway routes carry
    api_paid_spend under the ledger quota source (measured 2026-09-12). Pin
    both so a registry edit that silently retires the outer leg fails here
    first, not as a production flap."""
    sys.path.insert(0, str(REPO_ROOT))
    from shared.platform_capability_registry import CapacityPool, QuotaSource

    namespace = runpy.run_path(str(SCRIPT))
    pools_globals = namespace["static_registry_route_pools"].__globals__
    pools_globals["_static_registry_route_pools_cache"] = None
    pools = namespace["static_registry_route_pools"]()
    assert pools["codex.headless.full"] == (CapacityPool.SUBSCRIPTION_QUOTA, QuotaSource.MANUAL)
    gateway = [
        (pool, source) for route_id, (pool, source) in pools.items() if route_id.startswith("api.")
    ]
    assert gateway and (CapacityPool.API_PAID_SPEND, QuotaSource.LEDGER) in gateway


def test_static_registry_failure_fails_closed_to_the_quota_ttl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A registry that cannot load yields no pools — every receipt then fails
    closed to the quota TTL, which can only tighten the witness. The failure
    must be visible on stderr with a next action, not silent."""
    sys.path.insert(0, str(REPO_ROOT))

    namespace = runpy.run_path(str(SCRIPT))

    # runpy.run_path returns a COPY of the module globals — patch the live
    # function globals, the same idiom the main-flow tests use for main().
    pools_globals = namespace["static_registry_route_pools"].__globals__
    monkeypatch.setitem(
        pools_globals,
        "PLATFORM_CAPABILITY_REGISTRY",
        Path("/nonexistent/hapax-platform-capability-registry.json"),
    )
    pools_globals["_static_registry_route_pools_cache"] = None
    assert namespace["static_registry_route_pools"]() == {}
    stderr = capsys.readouterr().err
    assert "static capability registry unavailable" in stderr
    assert "Next:" in stderr

    # And the expiries built from the empty pool map stay at the quota TTL:
    # an outer-envelope receipt degrades to its 15m quota admission.
    _codex_platform_receipt(
        tmp_path,
        observed_at="2026-06-09T23:00:00Z",
        outer_stale_after="24h",
        quota_stale_after="15m",
        quota_status="unobservable",
    )
    expiries = namespace["quota_receipt_surface_expiries"](tmp_path)
    observed = datetime.fromisoformat("2026-06-09T23:00:00+00:00")
    assert expiries["codex"] == (observed, observed + timedelta(minutes=15))


def test_quota_receipt_surface_expiries_skips_unreadable_and_handles_missing_dir(
    tmp_path: Path,
) -> None:
    """The helper's branch coverage (M2, #4665 round 10): a missing receipt
    directory yields {}, an unreadable receipt is skipped rather than raising,
    and a directory with nothing readable yields {} — the tick then asserts no
    receipt-surface witness instead of guessing."""
    namespace = runpy.run_path(str(SCRIPT))
    assert namespace["quota_receipt_surface_expiries"](tmp_path / "no-such-dir") == {}

    _codex_platform_receipt(tmp_path, observed_at="2026-06-09T23:00:00Z")
    (tmp_path / "garbage.json").write_text("{not json", encoding="utf-8")
    expiries = namespace["quota_receipt_surface_expiries"](tmp_path)
    assert sorted(expiries) == ["codex"]

    unreadable_only = tmp_path / "only-garbage"
    unreadable_only.mkdir()
    (unreadable_only / "garbage.json").write_text("[not an object", encoding="utf-8")
    assert namespace["quota_receipt_surface_expiries"](unreadable_only) == {}


def test_lingering_unrefreshed_receipt_is_maintenance_not_a_replacement_hole(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Measured live 2026-09-12 (round 9 of #4665): the real receipt dir holds
    retired gemini/antigrav/grok receipts dead since July that the --all
    refresh never touches. An aggregate receipt-surface witness over every
    published receipt would flap every production tick rc=4 forever. The
    witness must scope to platforms the refresh actually REPLACED (observed_at
    moved); a lingering dead receipt the refresh does not republish is a
    maintenance defect for the capability-surface claim, not a replacement
    hole."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _agy_admission(relay, observed_at=NOW)
    # A live platform the refresh restamps...
    _codex_platform_receipt(platform_receipts)
    # ...and a retired platform's receipt dead since June beside it, which
    # the refresh below deliberately never rewrites.
    retired = json.loads((platform_receipts / "codex.json").read_text(encoding="utf-8"))
    retired["platform"] = "gemini"
    retired["receipt_id"] = "gemini-retired-test"
    retired["routes"] = ["gemini.review.direct"]
    retired["observed_at"] = "2026-06-30T17:05:59Z"
    for section in ("capability", "resource", "quota"):
        retired[section]["observed_at"] = "2026-06-30T17:05:59Z"
    retired["provider_docs"]["fetched_at"] = "2026-06-30T17:05:59Z"
    (platform_receipts / "gemini.json").write_text(json.dumps(retired), encoding="utf-8")
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"

    def codex_only_refresh(*, timeout, receipt_dir):
        # Exactly like the real --all refresh: restamps the platforms it
        # covers, never touches the retired platform's leftover receipt. The
        # restamped file lands at NOW (its mtime is the per-platform
        # publication instant the round-11 witness reads).
        _codex_platform_receipt(platform_receipts, observed_at="2026-06-09T23:59:30Z")
        _utime_platform_receipt(platform_receipts, "codex", NOW)
        return True

    monkeypatch.setitem(
        main_globals,
        "pull_forward_due_producers",
        lambda **kw: {
            "invoked": True,
            "forced": False,
            "ran": [],
            "skipped": [],
            "ok": True,
        },
    )
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", codex_only_refresh)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: 0.0)

    rc = namespace["main"](
        [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )

    # The months-dead gemini receipt does not fire the witness: only codex
    # was republished, and codex's PREDECESSOR (observed 23:59:00, not the
    # restamp) still vouches past the replacement — a negative gap, reported
    # honestly, degraded=False.
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_surface_replaced_platforms"] == ["codex"]
    assert summary["receipt_surface_predecessor_expiry"] == "2026-06-10T00:14:00Z"
    assert summary["receipt_continuity_gap_s"] == -840.0
    assert summary["receipt_continuity_degraded"] is False


def test_rebuild_publication_includes_the_post_refresh_blocker_rescan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M1 (#4665, round 8): without --now, pass2_now was sampled BEFORE the
    post-refresh blocker recompute while the rebuild's monotonic anchor was
    sampled AFTER it, so the rescan's real seconds vanished from published_at
    — the reviewer repro: a 120s blocker rescan published the ledger at T+160
    while reporting T+40, keeping rc green against the 819s horizon the
    surface had already blown through. The rebuild must re-pair the clocks
    AFTER the rescan so its seconds land inside the wall value publication
    anchors on; judged at that honest instant, this tick degrades (rc=4) —
    exactly the false green the round-8 defect manufactured."""
    namespace = runpy.run_path(str(SCRIPT))
    main_globals = namespace["main"].__globals__
    monkeypatch.setenv("HAPAX_DISPATCH_HOST", "")
    monkeypatch.setenv("HAPAX_DEFAULT_DISPATCH_HOST", "")
    relay = tmp_path / "relay-receipts"
    platform_receipts = tmp_path / "platform-receipts"
    relay.mkdir()
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    stub = _fake_nvidia_smi(tmp_path, "echo '1000, 32000'")
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    class ControllableDatetime(datetime):
        clock = t0

        @classmethod
        def now(cls, tz=None):
            return cls.clock

    mono = {"elapsed": 0.0}
    real_blocker = main_globals["codex_saved_login_blocker"]
    blocker_calls = {"n": 0}

    def rescan_advancing_blocker(receipt_dir, *, now):
        blocker_calls["n"] += 1
        if blocker_calls["n"] == 2:
            # The post-refresh recompute is the reviewer's 120s rescan: both
            # clocks advance while it runs, as real receipt-dir probing does.
            ControllableDatetime.clock = t0 + timedelta(seconds=140)
            mono["elapsed"] += 120.0
        return real_blocker(receipt_dir, now=now)

    def timed_pull(*, repo_root, receipt_dir, now, timeout=None):
        ControllableDatetime.clock = t0 + timedelta(seconds=20)
        mono["elapsed"] += 20.0
        _agy_admission(
            relay,
            observed_at=ControllableDatetime.clock.isoformat().replace("+00:00", "Z"),
            stale_after_seconds=900,
        )
        return {
            "invoked": True,
            "forced": True,
            "ran": ["agy-review-quota"],
            "skipped": [],
            "ok": True,
        }

    def healing_refresh(*, timeout, receipt_dir):
        # Rewrites the receipt into a blocked state so the recompute below
        # differs from pass 1 and triggers the rebuild.
        _codex_platform_receipt(
            platform_receipts, reason_code="codex_exec_auth_refresh_token_invalidated"
        )
        return True

    monkeypatch.setitem(main_globals, "datetime", ControllableDatetime)
    monkeypatch.setitem(main_globals, "pull_forward_due_producers", timed_pull)
    monkeypatch.setitem(main_globals, "refresh_capability_receipts", healing_refresh)
    monkeypatch.setitem(main_globals, "codex_saved_login_blocker", rescan_advancing_blocker)
    monkeypatch.setitem(main_globals, "monotonic_clock", lambda: mono["elapsed"])

    rc = namespace["main"](
        [
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
    )
    assert rc == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["ledger_rebuilt_after_refresh"] is True
    # The rebuild's publication instant carries the 120s rescan: pass 1
    # published at t0+20, the rescan ran to t0+140, and pass 2 published AT
    # t0+140 — the round-8 defect would report exactly t0+20, dropping the
    # rescan from the surface's own freshness arithmetic.
    assert summary["published_at"] == (t0 + timedelta(seconds=140)).isoformat().replace(
        "+00:00", "Z"
    )
    # Judged at that honest instant: the t0+20 mint leaves 920-140=780s
    # against the 819s horizon — degraded. The defect claimed 900s of
    # freshness the surface did not have and exited green.
    assert summary["admission_freshness_at_publication_s"] == 780.0
    assert summary["admission_freshness_degraded"] is True
    # The rebuild's own continuity witness stays green: judged against the
    # promise pass 1 just published (0.0, not None — a two-pass tick always
    # reports a per-pass value), never against the pre-tick promise.
    assert summary["admission_continuity_gap_s"] == 0.0
    assert summary["admission_continuity_degraded"] is False
    assert summary["receipt_continuity_degraded"] is False


def test_rebuild_continuity_is_judged_against_the_pass1_promise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M2 (#4665, round 7): a refresh-forced rebuild replaces the ledger a
    SECOND time in one tick, so pass 2's continuity must compare against the
    promise PASS 1 just published — its immediate predecessor — not the
    pre-tick promise pass 1 already covered. Reviewer repro shape: previous
    expiry T+100, pass 1 published inside it covering T+1000, pass 2
    published past T+100 — the pre-tick comparison read a phantom gap and
    failed a tick whose coverage never broke."""

    def seeded_tick_pair(tmp: Path, pass_clock: list[float]) -> tuple[int, dict, str]:
        namespace = runpy.run_path(str(SCRIPT))
        main_globals = namespace["main"].__globals__
        relay = tmp / "relay-receipts"
        platform_receipts = tmp / "platform-receipts"
        tmp.mkdir(parents=True, exist_ok=True)
        relay.mkdir()
        platform_receipts.mkdir()
        _codex_platform_receipt(platform_receipts)
        stub = _fake_nvidia_smi(tmp, "echo '1000, 32000'")
        out = tmp / "out" / "quota-spend-ledger-live.json"
        argv = [
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(stub),
            "--json",
        ]
        mint_stale_after = [100]

        def behavioral_pull(*, repo_root, receipt_dir, now, timeout=None):
            if namespace["pull_forward_force_needed"](receipt_dir, now=now):
                _agy_admission(relay, observed_at=NOW, stale_after_seconds=mint_stale_after[0])
                return {
                    "invoked": True,
                    "forced": True,
                    "ran": ["agy-review-quota"],
                    "skipped": [],
                    "ok": True,
                }
            return {"invoked": True, "forced": False, "ran": [], "skipped": [], "ok": True}

        def run_tick(clock_values: list[float]) -> tuple[int, dict, str]:
            monkeypatch.setitem(main_globals, "monotonic_clock", SequenceClock(clock_values))
            rc = namespace["main"](argv)
            captured = capsys.readouterr()
            return rc, json.loads(captured.out), captured.err

        # Tick A mints a 100s promise (t0+100) — honestly freshness-degraded,
        # cold start on continuity — and publishes the pre-tick ledger.
        monkeypatch.setitem(main_globals, "pull_forward_due_producers", behavioral_pull)
        monkeypatch.setitem(main_globals, "refresh_capability_receipts", lambda **kw: True)
        rc_a, summary_a, _ = run_tick([0, 0, 0])
        assert rc_a == 4  # 100s remaining against an 819s horizon
        assert summary_a["admission_continuity_gap_s"] is None

        # Tick B: a fresh 1000s mint (coverage t0+1020), and the refresh
        # flips the codex blocker so the ledger is rebuilt — a two-pass tick.
        mint_stale_after[0] = 1000
        _codex_platform_receipt(
            platform_receipts, reason_code="codex_exec_auth_refresh_token_invalidated"
        )

        def healing_refresh(*, timeout, receipt_dir):
            _codex_platform_receipt(platform_receipts)
            return True

        monkeypatch.setitem(main_globals, "refresh_capability_receipts", healing_refresh)
        return run_tick(pass_clock)

    t0 = datetime.fromisoformat(NOW.replace("Z", "+00:00"))

    def z(dt: datetime) -> str:
        return dt.isoformat().replace("+00:00", "Z")

    # Pass 1 publishes at t0+5 (well inside the t0+100 promise); the rebuild
    # publishes at t0+120 — 20s past the PRE-TICK promise, fully covered by
    # pass 1's own t0+1000. The phantom-gap repro needs pass-2 elapsed > 100.
    rc, summary, _ = seeded_tick_pair(tmp_path / "pair-no-gap", [0, 0, 5, 5, 5, 120])
    assert rc == 0
    assert summary["ledger_rebuilt_after_refresh"] is True
    assert summary["admission_continuity_gap_s"] == 0.0
    assert summary["admission_continuity_degraded"] is False
    assert summary["previous_promise_fresh_until"] == z(t0 + timedelta(seconds=100))

    # Retention leg: pass 1 itself publishes at t0+110 — 10s PAST the
    # pre-tick promise, a real dead interval — and the continuous rebuild at
    # t0+130 must not erase it. The reported gap stays 10s and cites the
    # pre-tick predecessor.
    rc, summary, err = seeded_tick_pair(tmp_path / "pair-retained-gap", [0, 0, 110, 110, 110, 130])
    assert rc == 4
    assert summary["ledger_rebuilt_after_refresh"] is True
    assert summary["admission_continuity_gap_s"] == 10.0
    assert summary["admission_continuity_degraded"] is True
    assert z(t0 + timedelta(seconds=100)) in err


def test_pre_mint_scan_elapsed_is_scripted_not_wall_assumed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """glm-1 minor (#4665, round 6): the pre-mint scan's elapsed measurement
    is pinned to a scripted monotonic clock, so dropping or re-anchoring the
    sampling fails red instead of riding a near-zero real clock on an empty
    receipt dir."""
    namespace = runpy.run_path(str(SCRIPT))
    relay = tmp_path / "relay-receipts"
    relay.mkdir()

    def fake_run(argv, *, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"now": NOW, "ran": [], "skipped": []}),
            stderr="",
        )

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    monkeypatch.setitem(
        namespace["pull_forward_due_producers"].__globals__,
        "monotonic_clock",
        SequenceClock([100.0, 103.5]),
    )
    info = namespace["pull_forward_due_producers"](
        repo_root=REPO_ROOT,
        receipt_dir=relay,
        now=datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    assert info["scan_elapsed_s"] == 3.5


class TestPullForwardBudgetPins:
    """The child budget arithmetic must reconcile with the systemd units, or a
    drifted constant silently converts a degrade into a guaranteed
    TimeoutExpired (claude-1/glm-1 majors on #4665, round 2). These pins
    re-derive the unit-file numbers the comments cite, so neither side can
    drift alone."""

    SERVICE_UNIT = REPO_ROOT / "systemd/units/hapax-quota-telemetry.service"
    TIMER_UNIT = REPO_ROOT / "systemd/units/hapax-quota-telemetry.timer"

    @staticmethod
    def _unit_seconds(path: Path, key: str) -> float:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.startswith(key + "="):
                value = line.split("=", 1)[1].strip()
                if value.endswith("min"):
                    return float(value[:-3]) * 60.0
                if value.endswith("s"):
                    return float(value[:-1])
                return float(value)
        raise AssertionError(f"{key}= not found in {path}")

    def test_child_worst_case_fits_the_pull_timeout(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        assert (
            namespace["PULL_FORWARD_LOCK_WAIT_S"] + namespace["PULL_FORWARD_PRODUCER_TIMEOUT_S"]
            <= namespace["PULL_FORWARD_TIMEOUT_S"]
        )

    def test_worst_case_tick_stays_under_the_write_cadence(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        cadence = self._unit_seconds(self.TIMER_UNIT, "OnUnitActiveSec")
        assert cadence == namespace["WRITER_CYCLE_S"]
        # refresh outer timeout: max(3x, +15s) over the 120s argparse default
        refresh_outer = max(3 * 120.0, 120.0 + 15.0)
        assert namespace["PULL_FORWARD_TIMEOUT_S"] + refresh_outer < cadence

    def test_kill_bound_covers_a_deferred_cycle(self) -> None:
        cadence = self._unit_seconds(self.TIMER_UNIT, "OnUnitActiveSec")
        kill = self._unit_seconds(self.SERVICE_UNIT, "TimeoutStartSec")
        assert cadence < kill

    def test_horizon_accounts_for_the_timer_accuracy_window(self) -> None:
        namespace = runpy.run_path(str(SCRIPT))
        accuracy = self._unit_seconds(self.TIMER_UNIT, "AccuracySec")
        assert namespace["TIMER_ACCURACY_S"] == accuracy

    def test_freshness_horizon_derives_from_the_next_deadline(self) -> None:
        # codex-1 round-4 critical: the horizon must cover everything between
        # this write and the next one's publication — cycle + timer accuracy +
        # the longer of lock wait vs producer timeout (mutually exclusive once
        # the force revalidation lands) + the bounded pre-write work. The
        # pre-write bound is 65s (glm-1 minor, round 4): the round-4 value of
        # 60 was below its own cited 33s mint + 32s write-side measurement.
        # The pre-mint scan bound (round 5, codex-1 C2) is its own term.
        namespace = runpy.run_path(str(SCRIPT))
        assert (
            namespace["FRESHNESS_HORIZON_S"]
            == namespace["WRITER_CYCLE_S"]
            + namespace["TIMER_ACCURACY_S"]
            + max(
                namespace["PULL_FORWARD_LOCK_WAIT_S"],
                namespace["PULL_FORWARD_PRODUCER_TIMEOUT_S"],
            )
            + namespace["PRE_MINT_SCAN_BOUND_S"]
            + namespace["PRE_WRITE_WORK_BOUND_S"]
            == 819.0
        )

    def test_pre_mint_scan_bound_covers_its_own_cited_measurement(self) -> None:
        # codex-1 critical C2 (round 5): the pre-mint force-decision scan must
        # be a bounded, derivation-visible term. Measured 2026-09-12 against
        # the live receipt dir (3,590 expired + 1 active agy admission
        # receipt): 0.06-0.07s across three runs; the bound must not sit below
        # that measurement, and the steady-state bound it implies
        # (L <= 900 - horizon) must stay at or above the worst observed
        # inflated tick (81s) so receipt-spam inflation degrades via the
        # scan-elapsed signal, not by silently re-tightening the horizon.
        namespace = runpy.run_path(str(SCRIPT))
        assert namespace["PRE_MINT_SCAN_BOUND_S"] >= 0.1
        assert 900.0 - namespace["FRESHNESS_HORIZON_S"] >= 81.0

    def test_pre_write_bound_covers_its_own_cited_measurement(self) -> None:
        # glm-1 minor (round 4): PRE_WRITE_WORK_BOUND_S must not sit below the
        # measurement the comment cites (33s mint + 32s write-side = 65s
        # anchor-to-write, 2026-09-12), and the steady-state bound it implies
        # (L <= 900 - horizon = 85s) must stay above the worst observed
        # inflated tick (81s).
        namespace = runpy.run_path(str(SCRIPT))
        assert namespace["PRE_WRITE_WORK_BOUND_S"] >= 33.0 + 32.0
        assert 900.0 - namespace["FRESHNESS_HORIZON_S"] >= 81.0

    def test_production_execstart_never_skips_receipts(self) -> None:
        # claude-1 minor (round 4): rc=4 suppression under --skip-receipts is
        # one flag away from hiding the exit predicate in production; pin the
        # shipped ExecStart the same way the budget pins bind the constants.
        for raw in self.SERVICE_UNIT.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.startswith("ExecStart="):
                assert "--skip-receipts" not in line
                return
        raise AssertionError(f"ExecStart= not found in {self.SERVICE_UNIT}")

    def test_freshness_horizon_stays_under_the_admission_ttl(self) -> None:
        # The agy admission TTL is 900s. A horizon at or above the TTL would
        # make every tick degrade; at 819 an at-bound tick degrades (by
        # design, visibly) while the steady state stays clean.
        namespace = runpy.run_path(str(SCRIPT))
        assert namespace["FRESHNESS_HORIZON_S"] < 900.0


def _wall_receipt(
    relay: Path,
    role: str,
    resets_at: str,
    *,
    failure_class: str = "quota_exhausted",
    route_id: str | None = None,
    detected_at: str | None = "2026-06-09T23:00:00Z",
) -> None:
    route_line = f"route_id: {route_id}\n" if route_id is not None else ""
    detected_at_line = f"detected_at: {detected_at}\n" if detected_at is not None else ""
    (relay / f"{role}-quota-wall.yaml").write_text(
        f"""role: {role}
status: quota_blocked
{detected_at_line}\
signal_kind: rate_limit_event
failure_class: {failure_class}
rate_limit_type: {failure_class}
{route_line}\
resets_at: {resets_at}
is_overage: False
action: exit_clean_await_restart
""",
        encoding="utf-8",
    )


def _codex_platform_receipt(
    receipt_dir: Path,
    *,
    platform: str = "codex",
    reason_code: str | None = None,
    include_failed_reason: bool = True,
    saved_login_witness: bool = True,
    legacy_exec_auth_witness: bool = False,
    evidence_refs_override: list[str] | None = None,
    observed_at: str = "2026-06-09T23:59:00Z",
    outer_stale_after: str = "15m",
    quota_stale_after: str = "15m",
    quota_status: str = "observed",
    quota_reason_codes: list[str] | None = None,
    routes: list[str] | None = None,
    route_wrappers: dict[str, dict[str, object]] | None = None,
) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    status = "blocked" if reason_code is not None else "observed"
    reason_codes = (
        [
            *(["codex_exec_auth_failed"] if include_failed_reason else []),
            reason_code,
        ]
        if reason_code is not None
        else []
    )
    evidence_refs = evidence_refs_override or (
        []
        if reason_code is not None
        else [
            "local:codex:exec:auth:observed",
            "remote:hapax-appendix:codex:exec:auth:observed",
        ]
        if legacy_exec_auth_witness
        else ["local:codex:cli:available", "local:codex:wrapper:present"]
        if not saved_login_witness
        else ["host:hapax-appendix:codex:exec:auth:saved-login:observed"]
    )
    # Non-observed quota evidence requires reason codes (receipt validation),
    # so an unobservable quota without explicit codes defaults to the live
    # subscription shape the routing consumer treats as expected.
    quota_reasons = quota_reason_codes
    if quota_reasons is None and quota_status != "observed":
        quota_reasons = ["account_live_quota_receipt_absent"]
    payload = {
        "receipt_schema": 1,
        "receipt_id": "codex-auth-blocked-test" if reason_code else "codex-auth-fresh-test",
        "platform": platform,
        "routes": routes or [f"{platform}.headless.full"],
        "observed_at": observed_at,
        "stale_after": outer_stale_after,
        "cli": {"binary": "codex", "available": True, "version": "codex-test"},
        "wrapper": {
            "path": "scripts/hapax-codex-headless",
            "exists": True,
            "executable": True,
            "sha256": None,
        },
        "config_refs": [],
        "tool_state": [],
        "mcp_status": [],
        "capability": {
            "status": status,
            "source": "live",
            "observed_at": observed_at,
            "stale_after": "15m",
            "evidence_refs": evidence_refs,
            "reason_codes": reason_codes,
        },
        "resource": {
            "status": status,
            "source": "live",
            "observed_at": observed_at,
            "stale_after": "15m",
            "evidence_refs": evidence_refs,
            "reason_codes": reason_codes,
        },
        "quota": {
            "status": quota_status,
            "source": "live",
            "observed_at": observed_at,
            "stale_after": quota_stale_after,
            "evidence_refs": ["test:quota:observed"],
            "reason_codes": quota_reasons or [],
        },
        "provider_docs": {
            "refs": ["test:provider-docs"],
            "fetched_at": observed_at,
            "stale_after": "7d",
            "fetch_status": "observed",
        },
        "known_unknowns": [],
    }
    if route_wrappers:
        payload["route_wrappers"] = route_wrappers
    (receipt_dir / f"{platform}.json").write_text(json.dumps(payload), encoding="utf-8")


def _utime_platform_receipt(receipt_dir: Path, platform: str, iso: str) -> None:
    """Pin a receipt file's mtime — the per-platform publication instant.

    The round-11 witness reads each replaced platform's landing instant from
    its own receipt file mtime (codex-1 M1), so tests place successors onto
    the frozen timeline instead of inheriting the real wall clock.
    Nanosecond stamps keep fractional ISO times exact (codex-1 C2, #4665
    round 18).
    """
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = dt - epoch
    ns = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000
    os.utime(receipt_dir / f"{platform}.json", ns=(ns, ns))


def _glmcp_admission(
    relay: Path,
    *,
    observed_at: str,
    stale_after_seconds: int = 900,
    evidence_ref: str = "supported-tool-usage-witness",
    supported_tool: str = "hapax-glmcp-reviewer",
    endpoint: str = "https://api.z.ai/api/coding/paas/v4",
    model: str = "glm-5.2",
    name: str = "glmcp-quota-admission.yaml",
    timestamp_field: str = "observed_at",
    capacity_pool: str | None = None,
    billing_mode: str | None = None,
    payg_fallback: str | None = None,
    primary_error_class: str | None = None,
    quota_wall_evidence_ref: str | None = None,
) -> None:
    if capacity_pool is None:
        capacity_pool = (
            "api_paid_spend" if endpoint == "https://api.z.ai/api/paas/v4" else "subscription_quota"
        )
    if billing_mode is None:
        billing_mode = (
            "api_credit_payg"
            if endpoint == "https://api.z.ai/api/paas/v4"
            else "coding_plan_subscription"
        )
    if payg_fallback is None:
        payg_fallback = "true" if endpoint == "https://api.z.ai/api/paas/v4" else "false"
    extra_payg_fields = ""
    if endpoint == "https://api.z.ai/api/paas/v4":
        if primary_error_class is None:
            primary_error_class = "quota_exhausted"
        if quota_wall_evidence_ref is None:
            quota_wall_evidence_ref = "cx-glmcp-quota-wall.yaml"
        extra_payg_fields = (
            f"primary_error_class: {primary_error_class}\n"
            f"quota_wall_evidence_ref: {quota_wall_evidence_ref}\n"
        )
    (relay / name).write_text(
        f"""schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: {capacity_pool}
route_id: glmcp.review.direct
supported_tool: {supported_tool}
endpoint: {endpoint}
model: {model}
{timestamp_field}: {observed_at}
stale_after_seconds: {stale_after_seconds}
evidence_ref: {evidence_ref}
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: {billing_mode}
payg_fallback: {payg_fallback}
{extra_payg_fields}""",
        encoding="utf-8",
    )


def _agy_admission(
    relay: Path,
    *,
    observed_at: str,
    stale_after_seconds: int = 900,
    evidence_ref: str = "agy-gemini31pro-smoke-witness",
    model: str = "gemini-3.1-pro-preview",
    name: str = "agy-quota-admission.yaml",
    secret_value_persisted: str = "false",
) -> None:
    (relay / name).write_text(
        f"""schema: hapax.agy_quota_admission.v1
status: quota_available
provider: google-antigravity-cli-agy
capacity_pool: subscription_quota
route_id: agy.review.direct
supported_tool: hapax-agy-reviewer
model: {model}
observed_at: {observed_at}
stale_after_seconds: {stale_after_seconds}
evidence_ref: {evidence_ref}
secret_source: agy:operator-session
secret_value_persisted: {secret_value_persisted}
prompt_or_output_persisted: false
billing_mode: operator_session_subscription
smoke_command: scripts/hapax-agy-reviewer
smoke_returncode: 0
smoke_stdout_validated: true
positive_admission: true
""",
        encoding="utf-8",
    )


def _glmcp_payg_spend(
    relay: Path,
    *,
    name: str = "glmcp-payg-spend.yaml",
    spend_id: str = "spend-20260706T140430Z-glmcp-payg-review-test",
    task_id: str = "cc-task-glmcp-review-seat-glm52-model-contract-20260706",
    task_hash: str | None = None,
    created_at: str = "2026-07-06T14:04:30Z",
    reconcile_by: str = "2026-07-07T14:04:30Z",
    estimated_cost_usd: str = "0.05",
    model_or_engine: str = "glm-5.2",
    model_id: str = "z_ai-glm-5.2",
    status: str = "spend_estimated",
    reconciliation_state: str = "pending",
    extra_fields: str = "",
) -> None:
    task_hash_line = f"task_hash: {task_hash}\n" if task_hash is not None else ""
    (relay / name).write_text(
        f"""schema: hapax.glmcp_payg_spend.v1
status: {status}
spend_id: {spend_id}
task_id: {task_id}
{task_hash_line}authority_case: CASE-CAPACITY-ROUTING-GLMCP-PAYG-20260706
route_id: glmcp.review.direct
capacity_pool: api_paid_spend
budget_id: tb-20260706-zai-glmcp-payg-review
provider: z_ai
model_or_engine: {model_or_engine}
model_id: {model_id}
effort: none
quantization: not_applicable
auth_surface: api_key
quality_floor: frontier_review_required
quality_preservation_reason: receipt-bounded GLMCP review fallback after Coding Plan quota wall
spend_reason: quota_exhaustion
estimated_cost_usd: {estimated_cost_usd}
created_at: {created_at}
reconcile_by: {reconcile_by}
reconciliation_state: {reconciliation_state}
support_artifact_authority: none
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/paas/v4
billing_mode: api_credit_payg
payg_fallback: true
primary_error_class: quota_exhausted
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
{extra_fields}
""",
        encoding="utf-8",
    )


def test_glmcp_admission_recheck_command_uses_scanner_glob() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    receipt_glob = namespace["GLMCP_ADMISSION_RECEIPT_GLOB"]

    assert receipt_glob == "*glmcp-quota-admission*.yaml"
    assert f"-name '{receipt_glob}'" in namespace["GLMCP_ADMISSION_RECHECK_COMMAND"]
    assert "receipt_dir.glob(GLMCP_ADMISSION_RECEIPT_GLOB)" in SCRIPT.read_text(encoding="utf-8")


def test_claude_lane_presence_regex_is_consistent_across_receipt_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLAUDE_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import CLAUDE_ADMISSION_LANE_PRESENCE_RE

    assert (
        telemetry_namespace["CLAUDE_ADMISSION_LANE_PRESENCE_RE"].pattern
        == admission_namespace["LANE_PRESENCE_RE"].pattern
        == CLAUDE_ADMISSION_LANE_PRESENCE_RE.pattern
    )


def test_claude_billingish_regex_is_consistent_across_receipt_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLAUDE_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import CLAUDE_ADMISSION_BILLINGISH_RE

    assert (
        telemetry_namespace["CLAUDE_ADMISSION_BILLINGISH_RE"].pattern
        == admission_namespace["BILLINGISH_RE"].pattern
        == CLAUDE_ADMISSION_BILLINGISH_RE.pattern
    )


def test_claude_witness_allowlist_regex_is_consistent_across_receipt_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLAUDE_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE

    assert (
        telemetry_namespace["CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE"].pattern
        == admission_namespace["WITNESS_ALLOWLIST_RE"].pattern
        == CLAUDE_ADMISSION_WITNESS_ALLOWLIST_RE.pattern
    )


def test_claude_secretish_regex_is_consistent_across_receipt_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))
    admission_namespace = runpy.run_path(str(CLAUDE_ADMISSION_SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import CLAUDE_ADMISSION_SECRETISH_RE

    assert (
        telemetry_namespace["CLAUDE_ADMISSION_SECRETISH_RE"].pattern
        == admission_namespace["SECRETISH_RE"].pattern
        == CLAUDE_ADMISSION_SECRETISH_RE.pattern
    )


def test_claude_account_live_quota_suffix_tokens_are_consistent_across_layers() -> None:
    telemetry_namespace = runpy.run_path(str(SCRIPT))

    sys.path.insert(0, str(REPO_ROOT))
    from shared.platform_capability_registry import _ref_tokens
    from shared.quota_spend_ledger import (
        CLAUDE_ADMISSION_ACCOUNT_LIVE_QUOTA_SUFFIX as LEDGER_SUFFIX,
    )

    suffix_tokens = ("account", "live", "quota", "observed")
    assert _ref_tokens(telemetry_namespace["CLAUDE_ADMISSION_ACCOUNT_LIVE_QUOTA_SUFFIX"]) == (
        suffix_tokens
    )
    assert _ref_tokens(LEDGER_SUFFIX) == suffix_tokens


def test_writes_valid_live_ledger_with_fresh_captured_at(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["captured_at"] == NOW
    assert payload["ledger_id"].startswith("quota-spend-ledger-live-")
    assert payload["local_resource_state"] in {"green", "yellow"}

    # The output revalidates through the fail-closed loader.
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import load_quota_spend_ledger

    ledger = load_quota_spend_ledger(out)
    states = {
        snapshot.route_id: snapshot.subscription_quota_state.value
        for snapshot in ledger.quota_snapshots
    }
    # claude.headless.full is now receipt-bounded (like agy): unknown without a fresh admission
    # receipt — account-live quota is never inferred from lane/session presence or wall-absence.
    assert states["claude.headless.full"] == "unknown"
    assert states["claude.review.opus"] == "unknown"
    assert states["codex.headless.full"] == "fresh"
    assert states["agy.review.direct"] == "unknown"
    assert "gemini.headless.full" not in states
    assert states["glmcp.review.direct"] == "unknown"
    assert states["litellm.local.command-r-35b"] == "fresh"


def test_codex_snapshot_fresh_for_default_appendix_saved_login_witness(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        evidence_refs_override=[
            "remote:hapax-appendix:codex:exec:auth:observed",
            "host:hapax-appendix:codex:exec:auth:saved-login:observed",
        ],
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "fresh"
    assert "codex_exec_auth_witness_absent" not in codex_snapshot["operator_visible_reason"]


def test_codex_snapshot_fresh_for_explicit_local_saved_login_witness(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        evidence_refs_override=["host:local:codex:exec:auth:saved-login:observed"],
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
        extra_env={"HAPAX_CODEX_EXEC_AUTH_HOST": "local"},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "fresh"
    assert "codex_exec_auth_witness_absent" not in codex_snapshot["operator_visible_reason"]


def test_codex_snapshot_unknown_for_local_saved_login_witness_without_dispatch_host(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        evidence_refs_override=["host:local:codex:exec:auth:saved-login:observed"],
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_exec_auth_witness_absent" in codex_snapshot["operator_visible_reason"]


def test_codex_snapshot_unknown_when_exec_auth_receipt_reports_refresh_token_invalidated(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        reason_code="codex_exec_auth_refresh_token_invalidated",
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_exec_auth_refresh_token_invalidated" in codex_snapshot["operator_visible_reason"]
    assert (
        "codex-auth-blocker:codex_exec_auth_refresh_token_invalidated"
        in codex_snapshot["evidence_refs"]
    )


def test_codex_snapshot_unknown_when_exec_auth_probe_not_requested(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        reason_code="codex_exec_auth_probe_not_requested",
        include_failed_reason=False,
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_exec_auth_probe_not_requested" in codex_snapshot["operator_visible_reason"]
    assert (
        "codex-auth-blocker:codex_exec_auth_probe_not_requested" in codex_snapshot["evidence_refs"]
    )


def test_codex_snapshot_unknown_when_observed_receipt_lacks_exec_auth_witness(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(platform_receipts, saved_login_witness=False)

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_exec_auth_witness_absent" in codex_snapshot["operator_visible_reason"]
    assert "codex-auth-blocker:codex_exec_auth_witness_absent" in codex_snapshot["evidence_refs"]


def test_codex_snapshot_unknown_when_observed_receipt_has_only_legacy_exec_auth_refs(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        saved_login_witness=False,
        legacy_exec_auth_witness=True,
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_exec_auth_witness_absent" in codex_snapshot["operator_visible_reason"]
    assert "codex-auth-blocker:codex_exec_auth_witness_absent" in codex_snapshot["evidence_refs"]


@pytest.mark.parametrize("negative_token", ["absent", "not", "unobserved", "timeout"])
def test_codex_snapshot_unknown_when_saved_login_witness_ref_is_negated(
    tmp_path: Path,
    negative_token: str,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        evidence_refs_override=[f"host:{negative_token}:codex:exec:auth:saved-login:observed"],
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_exec_auth_witness_absent" in codex_snapshot["operator_visible_reason"]
    assert "codex-auth-blocker:codex_exec_auth_witness_absent" in codex_snapshot["evidence_refs"]


def test_codex_snapshot_unknown_when_saved_login_witness_host_mismatches_dispatch_host(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts"
    _codex_platform_receipt(
        platform_receipts,
        evidence_refs_override=["host:podium:codex:exec:auth:saved-login:observed"],
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
        extra_env={"HAPAX_DISPATCH_HOST": "appendix"},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_exec_auth_witness_absent" in codex_snapshot["operator_visible_reason"]
    assert "codex-auth-blocker:codex_exec_auth_witness_absent" in codex_snapshot["evidence_refs"]


def test_codex_snapshot_unknown_when_platform_receipt_is_invalid(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts-invalid"
    platform_receipts.mkdir()
    (platform_receipts / "codex.json").write_text("[not a mapping]", encoding="utf-8")

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_platform_capability_receipt_invalid" in codex_snapshot["operator_visible_reason"]
    assert (
        "codex-auth-blocker:codex_platform_capability_receipt_invalid"
        in codex_snapshot["evidence_refs"]
    )


def test_codex_snapshot_unknown_when_platform_receipt_dir_is_missing(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts-absent"

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_platform_capability_receipt_absent" in codex_snapshot["operator_visible_reason"]
    assert (
        "platform-capability-receipt:codex:absent:receipt-dir-missing"
        in codex_snapshot["evidence_refs"]
    )
    assert (
        "codex-auth-blocker:codex_platform_capability_receipt_absent"
        in codex_snapshot["evidence_refs"]
    )


def test_codex_snapshot_unknown_when_no_codex_platform_receipt(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts-empty"
    platform_receipts.mkdir()

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_platform_capability_receipt_absent" in codex_snapshot["operator_visible_reason"]
    assert (
        "platform-capability-receipt:codex:absent:no-codex-receipt"
        in codex_snapshot["evidence_refs"]
    )
    assert (
        "codex-auth-blocker:codex_platform_capability_receipt_absent"
        in codex_snapshot["evidence_refs"]
    )


def test_codex_snapshot_unknown_when_platform_receipt_is_stale(
    tmp_path: Path,
) -> None:
    platform_receipts = tmp_path / "platform-receipts-stale"
    _codex_platform_receipt(
        platform_receipts,
        reason_code="codex_exec_auth_refresh_token_invalidated",
        observed_at="2026-06-09T23:00:00Z",
    )

    result, out = _run_writer(
        tmp_path,
        "--platform-capability-receipt-dir",
        str(platform_receipts),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    codex_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "codex.headless.full"
    )
    assert codex_snapshot["subscription_quota_state"] == "unknown"
    assert "codex_platform_capability_receipt_stale" in codex_snapshot["operator_visible_reason"]
    assert "codex_exec_auth_refresh_token_invalidated" in codex_snapshot["operator_visible_reason"]
    assert (
        "codex-auth-blocker:codex_platform_capability_receipt_stale"
        in codex_snapshot["evidence_refs"]
    )


def test_governance_records_carry_over_unchanged(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    live = json.loads(out.read_text(encoding="utf-8"))
    base = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for key in (
        "transition_budgets",
        "spend_receipts",
        "spend_gate_decisions",
        "provider_dependencies",
        "artifact_provenance",
        "renewal_records",
        "authority_source",
        "paid_api_budget_freshness_ttl_s",
    ):
        assert live[key] == base[key], f"{key} must not be rewritten by telemetry"


def test_unexpired_quota_wall_marks_platform_exhausted(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "theta", "2026-06-10T06:00:00Z")
    _wall_receipt(relay, "cx-amber", "2026-06-09T06:00:00Z")  # expired -> ignored

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["claude.headless.full"] == "exhausted"
    assert states["claude.review.opus"] == "exhausted"
    assert states["codex.headless.full"] == "fresh"
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 1}


def test_claude_route_wall_inhibits_shared_subscription_pool(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "theta",
        "2026-06-10T06:00:00Z",
        route_id="claude.headless.full",
        detected_at="2026-06-09T23:57:00Z",
    )
    _claude_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        route_id="claude.review.opus",
        name="claude-subscription-quota-admission-review.yaml",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    headless_snapshot = _claude_snapshot(payload, "claude.headless.full")
    review_snapshot = _claude_snapshot(payload, "claude.review.opus")
    assert headless_snapshot["subscription_quota_state"] == "exhausted"
    assert any(
        ":route_id:claude.headless.full:" in ref for ref in headless_snapshot["evidence_refs"]
    )
    assert review_snapshot["subscription_quota_state"] == "exhausted"
    assert any(":route_id:claude.headless.full:" in ref for ref in review_snapshot["evidence_refs"])
    assert "shared account-level capacity pool" in review_snapshot["operator_visible_reason"]


def test_quota_wall_route_id_cannot_move_wall_to_another_platform(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "agy-review",
        "2026-06-10T06:00:00Z",
        route_id="claude.review.opus",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["agy.review.direct"] == "unknown"
    assert states["claude.review.opus"] == "unknown"
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"agy": 1}


def test_claude_headless_wall_route_id_is_derived_from_role(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "beta",
        "2026-06-10T06:00:00Z",
        route_id="claude.review.opus",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    review_snapshot = _claude_snapshot(payload, "claude.review.opus")
    assert review_snapshot["subscription_quota_state"] == "exhausted"
    assert any(":route_id:claude.headless.full:" in ref for ref in review_snapshot["evidence_refs"])
    assert not any(
        ":route_id:claude.review.opus:" in ref for ref in review_snapshot["evidence_refs"]
    )


def test_retired_gemini_quota_wall_receipts_warn_and_do_not_seed_routes(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "gemini-iota", "2026-06-10T06:00:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "WARNING ignoring retired Gemini quota-wall receipt" in result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    route_ids = {snapshot["route_id"] for snapshot in payload["quota_snapshots"]}
    assert all(not route_id.startswith("gemini.") for route_id in route_ids if route_id is not None)
    summary = json.loads(result.stdout)
    assert "retired-gemini" not in summary["quota_walls"]


def test_glmcp_role_quota_wall_maps_to_glmcp_not_codex(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "cx-glmcp", "2026-06-10T06:00:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "exhausted"
    assert states["codex.headless.full"] == "fresh"
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"glmcp": 1}


def test_glmcp_quota_wall_beats_fresh_admission_receipt(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "cx-glmcp", "2026-06-10T06:00:00Z")
    _glmcp_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert "quota wall" in glmcp_snapshot["operator_visible_reason"]
    assert any("cx-glmcp-quota-wall.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert not any("glmcp-quota-admission.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"glmcp": 1}
    assert summary["glmcp_admissions"] == 1
    assert summary["glmcp_payg_spend_receipts"] == 0


def test_claude_quota_wall_beats_earlier_admission_receipt(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "theta",
        "2026-06-10T06:00:00Z",
        detected_at="2026-06-09T23:57:00Z",
    )
    _claude_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "exhausted"
    assert "quota wall" in snapshot["operator_visible_reason"]
    assert any("theta-quota-wall.yaml" in ref for ref in snapshot["evidence_refs"])
    assert not any(
        "claude-subscription-quota-admission.yaml" in ref for ref in snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 1}
    assert summary["claude_admissions"] == 1


def test_claude_future_reset_wall_blocks_later_admission_receipt(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "theta",
        "2026-06-10T06:00:00Z",
        detected_at="2026-06-09T23:00:00Z",
    )
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "exhausted"
    assert any("theta-quota-wall.yaml" in ref for ref in snapshot["evidence_refs"])
    assert not any(
        "claude-subscription-quota-admission.yaml" in ref for ref in snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 1}
    assert summary["claude_admissions"] == 1


def test_claude_resetless_after_wall_admission_recovers_shared_subscription_pool(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "theta",
        "unknown",
        detected_at="2026-06-09T23:00:00Z",
    )
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "fresh"
    assert "observed after the active shared-pool wall" in snapshot["operator_visible_reason"]
    assert any(
        "claude-subscription-quota-admission.yaml" in ref for ref in snapshot["evidence_refs"]
    )
    assert any("theta-quota-wall.yaml" in ref for ref in snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 1}
    assert summary["claude_admissions"] == 1


def test_claude_after_wall_admission_blocks_on_legacy_reset_wall(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "theta",
        "2026-06-10T06:00:00Z",
        detected_at="2026-06-09T23:57:00Z",
    )
    _wall_receipt(
        relay,
        "theta-legacy",
        "2026-06-10T06:00:00Z",
        detected_at=None,
    )
    _claude_admission(relay, observed_at="2026-06-09T23:58:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "exhausted"
    assert any("theta-quota-wall.yaml" in ref for ref in snapshot["evidence_refs"])
    assert any("theta-legacy-quota-wall.yaml" in ref for ref in snapshot["evidence_refs"])
    assert not any(
        "claude-subscription-quota-admission.yaml" in ref for ref in snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 2}
    assert summary["claude_admissions"] == 1


def test_claude_after_wall_admission_blocks_when_only_wall_lacks_detected_at(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "theta-legacy",
        "2026-06-10T06:00:00Z",
        detected_at=None,
    )
    _claude_admission(relay, observed_at="2026-06-09T23:58:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "exhausted"
    assert any("theta-legacy-quota-wall.yaml" in ref for ref in snapshot["evidence_refs"])
    assert not any(
        "claude-subscription-quota-admission.yaml" in ref for ref in snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 1}
    assert summary["claude_admissions"] == 1


def test_glmcp_payg_spend_receipt_counts_against_budget_gate(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(
        relay,
        name=spend_receipt_name,
        task_hash="sha256:" + ("a" * 64),
    )
    base = tmp_path / "quota-spend-ledger-fixtures.json"
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for budget in base_payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260706-zai-glmcp-payg-review":
            budget["daily_cap_usd"] = "0.05"
    base.write_text(json.dumps(base_payload), encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(base), now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    receipt = next(
        receipt
        for receipt in payload["spend_receipts"]
        if receipt["spend_id"] == "spend-20260706T140430Z-glmcp-payg-review-test"
    )
    assert receipt["task_hash"] == "sha256:" + ("a" * 64)
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert (
        "spend-gate:glmcp.review.direct:refused_exhausted_budget" in glmcp_snapshot["evidence_refs"]
    )
    assert "matching TransitionBudget cap exhausted" in glmcp_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["glmcp_payg_spend_receipts"] == 1


def _folded_glmcp_payg_spend_ids(tmp_path: Path) -> tuple[list[str], str]:
    """Relay-folded GLMCP spend ids: the output ledger minus the base fixture's own receipts."""
    base_ids = {
        receipt["spend_id"]
        for receipt in json.loads(FIXTURES.read_text(encoding="utf-8"))["spend_receipts"]
    }
    result, out = _run_writer(tmp_path, now=PAYG_NOW)
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    ids = [
        receipt["spend_id"]
        for receipt in payload["spend_receipts"]
        if receipt["route_id"] == "glmcp.review.direct" and receipt["spend_id"] not in base_ids
    ]
    return ids, result.stderr


def test_glmcp_payg_spend_receipt_for_reviewer_default_glm_5_3_is_counted(
    tmp_path: Path,
) -> None:
    """The reviewer has called glm-5.3 since #4692; its spend must reach the cap, not vanish.

    Unsafe case: a writer that folds only glm-5.2 drops every glm-5.3 reservation at the next
    tick, so the budget gate never sees that spend (25 such receipts were dropped by 09-24).
    """
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(
        relay,
        name="glmcp-payg-spend-20260706t140430z-glm53.yaml",
        model_or_engine="glm-5.3",
        model_id="z_ai-glm-5.3",
        estimated_cost_usd="0.123457",
        extra_fields="served_model: glm-5.3\nprice_basis_ref: docs.z.ai-guides-overview-pricing-20260924",
    )

    ids, _stderr = _folded_glmcp_payg_spend_ids(tmp_path)

    assert ids == ["spend-20260706T140430Z-glmcp-payg-review-test"]


def _folded_glmcp_payg_spend(tmp_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Relay-folded GLMCP spend receipts (base fixture receipts excluded) and writer stderr.

    The base is the fixture without provider balance evidence, so the fold itself is observed:
    the fixture's real 2026-09-24 balance would otherwise settle these July receipts.
    """
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for budget in base_payload["transition_budgets"]:
        for field in [key for key in budget if key.startswith("provider_balance_")]:
            del budget[field]
    base = tmp_path / "base-without-balance-evidence.json"
    base.write_text(json.dumps(base_payload), encoding="utf-8")
    base_ids = {receipt["spend_id"] for receipt in base_payload["spend_receipts"]}
    result, out = _run_writer(tmp_path, "--base", str(base), now=PAYG_NOW)
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    receipts = [
        receipt
        for receipt in payload["spend_receipts"]
        if receipt["route_id"] == "glmcp.review.direct" and receipt["spend_id"] not in base_ids
    ]
    return receipts, result.stderr


@pytest.mark.parametrize("model_id", ["z_ai-glm-5.2", "none", ""])
def test_glmcp_payg_spend_receipt_with_unverified_identity_is_frozen_and_counted(
    tmp_path: Path,
    model_id: str,
) -> None:
    """Unsafe case: dropping a mislabelled or unlabelled receipt is fail-open accounting.

    The call may have billed, so the receipt is folded frozen: its estimate counts against the
    caps and the frozen state refuses further paid spend until a reviewed record resolves it."""
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(
        relay,
        name="glmcp-payg-spend-20260706t140430z-identity.yaml",
        model_or_engine="glm-5.3",
        model_id=model_id,
    )

    [receipt], stderr = _folded_glmcp_payg_spend(tmp_path)

    assert receipt["reconciliation_state"] == "frozen_refused"
    assert receipt["estimated_cost_usd"] == "0.05"
    assert receipt.get("actual_cost_usd") is None
    assert "identity unverified" in receipt["reconciliation_reason"]
    assert "freezing GLMCP PAYG spend receipt" in stderr


def test_glmcp_payg_spend_receipt_actual_above_reservation_is_frozen_at_the_actual(
    tmp_path: Path,
) -> None:
    """Unsafe case: a reported actual above the reservation lands unflagged, or not at all."""
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(
        relay,
        name="glmcp-payg-spend-20260706t140430z-over.yaml",
        status="spend_reconciled",
        reconciliation_state="reconciled",
        extra_fields=(
            "actual_cost_usd: 0.09\ncap_remaining_usd: 1.91\n"
            "reconciled_at: 2026-07-06T14:04:40Z\n"
            "reconciliation_reason: actual from provider-reported usage"
        ),
    )

    [receipt], stderr = _folded_glmcp_payg_spend(tmp_path)

    assert receipt["reconciliation_state"] == "frozen_refused"
    assert receipt["estimated_cost_usd"] == "0.09"
    assert "exceeds the reservation" in receipt["reconciliation_reason"]
    assert "freezing GLMCP PAYG spend receipt" in stderr


def test_glmcp_payg_spend_receipt_frozen_by_the_reviewer_stays_frozen_and_counted(
    tmp_path: Path,
) -> None:
    """The reviewer freezes spend it cannot trust (unidentified model, actual above the
    reservation); an unknown status must not make the writer drop it."""
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(
        relay,
        name="glmcp-payg-spend-20260706t140430z-frozen.yaml",
        status="spend_frozen",
        reconciliation_state="frozen_refused",
        estimated_cost_usd="0.14132",
        extra_fields=(
            "reconciled_at: 2026-07-06T14:04:40Z\n"
            "reconciliation_reason: reviewer froze: provider-reported actual exceeds the reservation"
        ),
    )

    [receipt], _stderr = _folded_glmcp_payg_spend(tmp_path)

    assert receipt["reconciliation_state"] == "frozen_refused"
    assert receipt["estimated_cost_usd"] == "0.14132"


def test_glmcp_payg_spend_receipt_reservation_above_task_cap_is_frozen_and_counted(
    tmp_path: Path,
) -> None:
    """A reservation above its task cap (2.00 here) is still spend that may have happened."""
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(
        relay,
        name="glmcp-payg-spend-20260706t140430z-cost.yaml",
        estimated_cost_usd="2.000001",
    )

    [receipt], _stderr = _folded_glmcp_payg_spend(tmp_path)

    assert receipt["reconciliation_state"] == "frozen_refused"
    assert receipt["estimated_cost_usd"] == "2.000001"


UNTRUSTED_RECEIPT_CASES = {
    "no countable reservation": {"estimated_cost_usd": "0"},
    "malformed reservation": {"estimated_cost_usd": "1e-3"},
    "unknown budget": {"budget_id": "tb-20990101-unknown-budget"},
    "authority mismatch": {"authority_case": "CASE-SOMETHING-ELSE"},
    "unsupported tool": {"supported_tool": "some-other-caller"},
    "schema mismatch": {"schema": "hapax.glmcp_payg_spend.v0"},
    "unknown status": {"status": "spend_weird"},
}


def _untrusted_receipt_text(**overrides: str) -> str:
    fields = {
        "schema": "hapax.glmcp_payg_spend.v1",
        "status": "spend_estimated",
        "spend_id": "spend-20260706T140430Z-glmcp-payg-review-untrusted",
        "task_id": "cc-task-glmcp-review-seat-glm52-model-contract-20260706",
        "authority_case": "CASE-CAPACITY-ROUTING-GLMCP-PAYG-20260706",
        "route_id": "glmcp.review.direct",
        "capacity_pool": "api_paid_spend",
        "budget_id": "tb-20260706-zai-glmcp-payg-review",
        "provider": "z_ai",
        "model_or_engine": "glm-5.2",
        "model_id": "z_ai-glm-5.2",
        "effort": "none",
        "quantization": "not_applicable",
        "auth_surface": "api_key",
        "quality_floor": "frontier_review_required",
        "quality_preservation_reason": "receipt-bounded GLMCP review fallback",
        "spend_reason": "quota_exhaustion",
        "estimated_cost_usd": "0.05",
        "created_at": "2026-07-06T14:04:30Z",
        "reconcile_by": "2026-07-07T14:04:30Z",
        "reconciliation_state": "pending",
        "support_artifact_authority": "none",
        "supported_tool": "hapax-glmcp-reviewer",
        "endpoint": "https://api.z.ai/api/paas/v4",
        "billing_mode": "api_credit_payg",
        "payg_fallback": "true",
        "primary_error_class": "quota_exhausted",
        "secret_source": "pass:glmcp/api-key",
        "secret_value_persisted": "false",
        "prompt_or_output_persisted": "false",
        **overrides,
    }
    return "".join(f"{key}: {value}\n" for key, value in fields.items())


@pytest.mark.parametrize(
    ("case", "text"),
    [
        *[
            (case, _untrusted_receipt_text(**overrides))
            for case, overrides in UNTRUSTED_RECEIPT_CASES.items()
        ],
        ("unknown field", _untrusted_receipt_text(injected_field="x")),
        ("not a receipt at all", "\x00\x01 not yaml at all"),
    ],
)
def test_glmcp_payg_untrusted_spend_receipt_is_frozen_and_counted_never_dropped(
    tmp_path: Path,
    case: str,
    text: str,
) -> None:
    """Review r2 item 1: a file where a spend receipt belongs may represent a billed call,
    whatever is wrong with it. It folds as a normalized frozen placeholder: attributed to a
    GLMCP budget, holding at least its reservation (or the budget's per-task cap when none is
    countable), bound to the file's hash, and refusing paid spend until a reviewed record
    resolves it."""
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-payg-spend-20260706t140430z-untrusted.yaml").write_text(text, "utf-8")

    [receipt], stderr = _folded_glmcp_payg_spend(tmp_path)

    assert receipt["reconciliation_state"] == "frozen_refused", case
    assert receipt.get("actual_cost_usd") is None
    assert Decimal(receipt["estimated_cost_usd"]) >= Decimal("0.05"), case
    assert "untrusted" in receipt["reconciliation_reason"], case
    assert any("sha256:" in ref for ref in receipt["artifact_refs"]), case
    assert receipt["budget_id"].startswith("tb-") and "zai-glmcp" in receipt["budget_id"]
    assert "freezing GLMCP PAYG spend receipt" in stderr


def _glmcp_review_request(task_id: str = "another-review-task") -> Any:
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import PaidRouteRequest

    return PaidRouteRequest.model_validate(
        {
            "route_id": "glmcp.review.direct",
            "task_id": task_id,
            "provider": "z_ai",
            "profile": "glmcp-review-direct",
            "task_class": "independent-review",
            "quality_floor": "frontier_review_required",
            "estimated_cost_usd": "0.05",
            "capacity_pool": "api_paid_spend",
        }
    )


def test_glmcp_payg_receipt_with_no_glmcp_budget_is_held_on_an_unbudgeted_block(
    tmp_path: Path,
) -> None:
    """Review r3 (Vibe, Muse N3): with no GLMCP budget at all, a receipt that may have billed
    must still not be dropped. It is held frozen on a synthetic retired "unbudgeted" GLMCP
    budget, which matches the route, so any GLMCP budget added later is refused until the
    spend is resolved."""
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import evaluate_paid_route_eligibility, load_quota_spend_ledger

    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-payg-spend-20260924t200000z-orphan.yaml").write_text(
        _untrusted_receipt_text(
            budget_id="tb-20260924-zai-glm-payg-balance-burn",
            created_at="2026-09-24T20:00:00Z",
            reconcile_by="2026-09-25T20:00:00Z",
        ),
        encoding="utf-8",
    )
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    base_payload["transition_budgets"] = [
        budget
        for budget in base_payload["transition_budgets"]
        if "glmcp-review-direct" not in budget["profiles_allowed"]
    ]
    base_payload["spend_receipts"] = [
        receipt
        for receipt in base_payload["spend_receipts"]
        if receipt["route_id"] != "glmcp.review.direct"
    ]
    base = tmp_path / "base-without-glmcp-budgets.json"
    base.write_text(json.dumps(base_payload), encoding="utf-8")
    now = "2026-09-24T21:00:00Z"

    result, out = _run_writer(tmp_path, "--base", str(base), now=now)

    assert result.returncode == 0, result.stderr
    ledger = load_quota_spend_ledger(out)
    [receipt] = [r for r in ledger.spend_receipts if r.route_id == "glmcp.review.direct"]
    assert receipt.reconciliation_state.value == "frozen_refused"
    [block] = [b for b in ledger.transition_budgets if b.budget_id == receipt.budget_id]
    assert block.lifecycle_state.value == "retired"
    assert block.matches_request(_glmcp_review_request())
    decision = evaluate_paid_route_eligibility(
        ledger, _glmcp_review_request(), now=datetime.fromisoformat("2026-09-24T21:00:00+00:00")
    )
    assert not decision.eligible
    assert "ignoring GLMCP PAYG spend receipt" not in result.stderr


def test_glmcp_payg_untrusted_placeholder_is_named_and_resolvable_by_its_spend_id(
    tmp_path: Path,
) -> None:
    """Review r3 (Muse N1): a placeholder's id is synthetic, so the writer prints it with the
    freeze, and a reviewed governance receipt of that id resolves it like any other."""
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import evaluate_paid_route_eligibility, load_quota_spend_ledger

    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-payg-spend-20260924t200000z-bad.yaml").write_text(
        _untrusted_receipt_text(
            budget_id="tb-20260924-zai-glm-payg-balance-burn",
            authority_case="CASE-SOMETHING-ELSE",
            created_at="2026-09-24T20:00:00Z",
            reconcile_by="2026-09-25T20:00:00Z",
        ),
        encoding="utf-8",
    )
    now = "2026-09-24T21:00:00Z"
    when = datetime.fromisoformat("2026-09-24T21:00:00+00:00")

    result, out = _run_writer(tmp_path, now=now)
    assert result.returncode == 0, result.stderr
    [placeholder] = [
        r for r in load_quota_spend_ledger(out).spend_receipts if "untrusted" in r.spend_id
    ]
    assert placeholder.spend_id in result.stderr
    assert not evaluate_paid_route_eligibility(
        load_quota_spend_ledger(out), _glmcp_review_request(), now=when
    ).eligible

    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    resolution = placeholder.model_dump(mode="json")
    resolution.update(
        reconciliation_state="reconciled",
        actual_cost_usd=resolution["estimated_cost_usd"],
        cap_remaining_usd="76.0",
        reconciled_at="2026-09-24T20:30:00Z",
        reconciliation_reason="governance resolution of an untrusted receipt at its held figure",
    )
    base_payload["spend_receipts"].append(resolution)
    base = tmp_path / "base-with-resolution.json"
    base.write_text(json.dumps(base_payload), encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(base), now=now)
    assert result.returncode == 0, result.stderr
    decision = evaluate_paid_route_eligibility(
        load_quota_spend_ledger(out), _glmcp_review_request(), now=when
    )
    assert decision.eligible, decision.blocking_reasons


def test_glmcp_payg_real_relay_population_settles_to_the_claimed_ledger(tmp_path: Path) -> None:
    """Review r3 dossier (claude-1, exit-predicate adequacy): the PR's post-release figures,
    reproducible from this checkout. The committed fixture plus receipts shaped like the 76
    real relay files: 51 glm-5.2 reconciled; 22 pending, 2 failed and 1 reconciled glm-5.3
    stamped z_ai-glm-5.2; all from 09-17/18 under the expired break-glass budget. Outcome:
    nothing dropped, 25 settled against the balance evidence, $3.80 held on the old budget,
    and the new budget eligible with $76.539721 remaining."""
    sys.path.insert(0, str(REPO_ROOT))
    from collections import Counter

    from shared.quota_spend_ledger import evaluate_paid_route_eligibility, load_quota_spend_ledger

    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    breakglass = {
        "budget_id": "tb-20260916-zai-glmcp-payg-breakglass",
        "secret_source": "filestore:glmcp/api-key",
    }
    reconciled = {
        "status": "spend_reconciled",
        "reconciliation_state": "reconciled",
        "actual_cost_usd": "0.05",
        "cap_remaining_usd": "1.90",
        "reconciliation_reason": "PAYG API call returned model output",
    }
    shapes = (
        [("glm-5.2", "z_ai-glm-5.2", reconciled)] * 51
        + [("glm-5.3", "z_ai-glm-5.2", {})] * 22
        + [
            (
                "glm-5.3",
                "z_ai-glm-5.2",
                {**reconciled, "status": "spend_failed", "actual_cost_usd": "0.00"},
            )
        ]
        * 2
        + [("glm-5.3", "z_ai-glm-5.2", reconciled)]
    )
    for index, (model, model_id, extra) in enumerate(shapes):
        created = datetime(2026, 9, 17, 12, 0, tzinfo=UTC) + timedelta(minutes=30 * index)
        stamp = created.strftime("%Y%m%dT%H%M%SZ")
        overrides = {
            **breakglass,
            **extra,
            "spend_id": f"spend-{stamp}-glmcp-payg-review-shape-{index:03d}",
            "model_or_engine": model,
            "model_id": model_id,
            "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reconcile_by": (created + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if "reconciliation_reason" in extra:
            overrides["reconciled_at"] = (created + timedelta(seconds=10)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        (relay / f"glmcp-payg-spend-{stamp.lower()}-shape-{index:03d}.yaml").write_text(
            _untrusted_receipt_text(**overrides), encoding="utf-8"
        )
    now = "2026-09-24T21:00:00Z"

    result, out = _run_writer(tmp_path, now=now)

    assert result.returncode == 0, result.stderr
    assert "ignoring GLMCP PAYG spend receipt" not in result.stderr
    ledger = load_quota_spend_ledger(out)
    glmcp = [r for r in ledger.spend_receipts if r.route_id == "glmcp.review.direct"]
    assert len(glmcp) == 77  # 76 relay receipts + the committed identity probe
    assert Counter((r.model_or_engine, r.reconciliation_state.value) for r in glmcp) == {
        ("glm-5.2", "reconciled"): 51,
        ("glm-5.3", "settled_by_provider_balance"): 25,
        ("glm-5.3", "reconciled"): 1,
    }
    breakglass_budget = ledger.budget_by_id("tb-20260916-zai-glmcp-payg-breakglass")
    burn_budget = ledger.budget_by_id(BURN_BUDGET_ID)
    assert ledger._budget_spent_usd(breakglass_budget) == Decimal("3.80")
    assert ledger._budget_remaining_usd(burn_budget) == Decimal("76.539721")
    decision = evaluate_paid_route_eligibility(
        ledger, _glmcp_review_request(), now=datetime.fromisoformat("2026-09-24T21:00:00+00:00")
    )
    assert decision.eligible, decision.blocking_reasons
    assert decision.budget_id == BURN_BUDGET_ID


def test_glmcp_payg_failed_spend_receipt_is_folded_at_zero_not_dropped(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(
        relay,
        name="glmcp-payg-spend-20260706t140430z-failed.yaml",
        status="spend_failed",
        reconciliation_state="reconciled",
        extra_fields=(
            "actual_cost_usd: 0.00\ncap_remaining_usd: 2.00\n"
            "reconciled_at: 2026-07-06T14:04:31Z\n"
            "reconciliation_reason: PAYG API call failed before model output"
        ),
    )

    [receipt], _stderr = _folded_glmcp_payg_spend(tmp_path)

    assert receipt["reconciliation_state"] == "reconciled"
    assert receipt["actual_cost_usd"] == "0.00"


def test_glmcp_payg_unverified_identity_never_trusts_the_reported_actual(tmp_path: Path) -> None:
    """Review r2 item 3: identity first. A receipt whose identity is unverified is held at its
    reservation and the dearest-rate ceiling of its reported usage; its actual, priced for an
    unknown model, neither sets nor lowers the held figure."""
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(
        relay,
        name="glmcp-payg-spend-20260706t140430z-identity-actual.yaml",
        model_or_engine="glm-5.3",
        model_id="z_ai-glm-5.2",
        status="spend_reconciled",
        reconciliation_state="reconciled",
        extra_fields=(
            "actual_cost_usd: 0.09\ncap_remaining_usd: 1.91\n"
            "reconciled_at: 2026-07-06T14:04:40Z\n"
            "reconciliation_reason: actual from usage\n"
            "usage_prompt_tokens: 20000\nusage_completion_tokens: 1000"
        ),
    )

    [receipt], _stderr = _folded_glmcp_payg_spend(tmp_path)

    # max(reservation 0.05, (20000 x 1.40 + 1000 x 4.40) / 1M = 0.0324); the 0.09 is not used
    assert receipt["reconciliation_state"] == "frozen_refused"
    assert receipt["estimated_cost_usd"] == "0.05"
    assert "unverified actual not counted" in receipt["reconciliation_reason"]


def test_glmcp_payg_diverged_model_id_map_freezes_instead_of_crashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review r2 item 4: an admitted model missing from the ModelId map is an unverifiable
    identity, not a KeyError that takes the writer down."""
    namespace = runpy.run_path(str(SCRIPT))
    scan = namespace["active_glmcp_payg_spend_receipts"]
    monkeypatch.setitem(scan.__globals__, "GLMCP_MODEL_IDS", {"glm-5.2": "z_ai-glm-5.2"})
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(
        relay,
        name="glmcp-payg-spend-20260706t140430z-diverged.yaml",
        model_or_engine="glm-5.3",
        model_id="z_ai-glm-5.3",
    )
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import load_quota_spend_ledger

    result = scan(
        relay,
        base=load_quota_spend_ledger(FIXTURES),
        now=datetime(2026, 7, 6, 14, 5, tzinfo=UTC),
    )

    [receipt] = result.receipts
    assert receipt.reconciliation_state.value == "frozen_refused"


def test_glmcp_payg_duplicate_relay_spend_id_counts_both(tmp_path: Path) -> None:
    """Two different files naming one spend_id are two possible charges; neither is dropped."""
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_payg_spend(relay, name="glmcp-payg-spend-20260706t140430z-dup-a.yaml")
    _glmcp_payg_spend(
        relay, name="glmcp-payg-spend-20260706t140430z-dup-b.yaml", estimated_cost_usd="0.07"
    )

    receipts, _stderr = _folded_glmcp_payg_spend(tmp_path)

    assert len(receipts) == 2
    assert len({r["spend_id"] for r in receipts}) == 2
    assert sorted(r["reconciliation_state"] for r in receipts) == ["frozen_refused", "pending"]


BURN_BUDGET_ID = "tb-20260924-zai-glm-payg-balance-burn"
RAW_SPEND_ID = "spend-20260920T163624Z-glmcp-payg-review-05c44ca781-7c7117a67a75"


@pytest.mark.parametrize(
    ("model_id", "created_at", "expect_state", "expect_eligible"),
    [
        # the real 09-18 raw shape (glm-5.3 stamped with glm-5.2's id): folded frozen, then
        # settled by the writer against the budget's later provider balance evidence
        ("z_ai-glm-5.2", "2026-09-18T22:35:22Z", "settled_by_provider_balance", True),
        ("z_ai-glm-5.3", "2026-09-18T22:35:22Z", "settled_by_provider_balance", True),
        # after the settlement cut-off the balance cannot have reflected them
        ("z_ai-glm-5.2", "2026-09-23T10:00:00Z", "frozen_refused", False),
        ("z_ai-glm-5.3", "2026-09-23T10:00:00Z", "pending", False),
    ],
)
def test_glmcp_payg_unresolved_raw_on_expired_budget_blocks_unless_the_balance_covers_it(
    tmp_path: Path,
    model_id: str,
    created_at: str,
    expect_state: str,
    expect_eligible: bool,
) -> None:
    """Unsafe case: an unresolved receipt on an expired matching budget either refuses every
    paid call forever, or is unblocked by an invented actual (review r1, M1). The raw receipt
    is folded as it is (frozen or pending, counted, bytes untouched); the new budget opens
    only on its provider-reported balance, and only for spend that settled before it was read."""
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import (
        PaidRouteRequest,
        evaluate_paid_route_eligibility,
        load_quota_spend_ledger,
    )

    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    raw = (
        "schema: hapax.glmcp_payg_spend.v1\nstatus: spend_estimated\n"
        f"spend_id: {RAW_SPEND_ID}\n"
        "task_id: cc-task-gate-connector-classifier-repo-root-repair-20260917-v2\n"
        "authority_case: CASE-CAPACITY-ROUTING-GLMCP-PAYG-20260706\n"
        "route_id: glmcp.review.direct\ncapacity_pool: api_paid_spend\n"
        "budget_id: tb-20260916-zai-glmcp-payg-breakglass\nprovider: z_ai\n"
        f"model_or_engine: glm-5.3\nmodel_id: {model_id}\neffort: none\n"
        "quantization: not_applicable\nauth_surface: api_key\n"
        "quality_floor: frontier_review_required\n"
        "quality_preservation_reason: receipt-bounded GLMCP review fallback\n"
        "spend_reason: quota_exhaustion\nestimated_cost_usd: 0.05\n"
        f"created_at: {created_at}\nreconcile_by: 2026-09-24T06:00:00Z\n"
        "reconciliation_state: pending\nsupport_artifact_authority: none\n"
        "supported_tool: hapax-glmcp-reviewer\nendpoint: https://api.z.ai/api/paas/v4\n"
        "billing_mode: api_credit_payg\npayg_fallback: true\nprimary_error_class: quota_exhausted\n"
        "secret_source: filestore:glmcp/api-key\nsecret_value_persisted: false\n"
        "prompt_or_output_persisted: false\n"
    )
    (relay / "glmcp-payg-spend-20260920t163624z-05c44ca781-7c7117a67a75.yaml").write_text(
        raw, encoding="utf-8"
    )
    now = "2026-09-24T21:00:00Z"

    result, out = _run_writer(tmp_path, now=now)

    assert result.returncode == 0, result.stderr
    ledger = load_quota_spend_ledger(out)
    [folded] = [r for r in ledger.spend_receipts if r.spend_id == RAW_SPEND_ID]
    decision = evaluate_paid_route_eligibility(
        ledger,
        PaidRouteRequest.model_validate(
            {
                "route_id": "glmcp.review.direct",
                "task_id": "some-review-task",
                "provider": "z_ai",
                "profile": "glmcp-review-direct",
                "task_class": "independent-review",
                "quality_floor": "frontier_review_required",
                "estimated_cost_usd": "0.05",
                "capacity_pool": "api_paid_spend",
            }
        ),
        now=datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    assert folded.reconciliation_state.value == expect_state
    assert folded.cost_against_cap() == Decimal("0.05")
    if expect_eligible:
        assert "operator-console-cash-balance-2026-09-24" in (folded.reconciliation_reason or "")
        assert decision.eligible, decision.blocking_reasons
        assert decision.budget_id == BURN_BUDGET_ID
    else:
        assert not decision.eligible
        assert any(
            "overdue" in reason or "frozen" in reason for reason in decision.blocking_reasons
        )


def test_glmcp_payg_frozen_own_spend_resolves_only_by_a_reviewed_governance_record(
    tmp_path: Path,
) -> None:
    """Review r2 item 5, the wedge: frozen spend on the live budget itself stops paid GLMCP
    spend. No balance can settle a budget's own spend. The resolution act is a reviewed
    governance SpendReceipt with the same spend_id in the checked-in fixtures, which a lane
    lands through PR review and release. It needs no operator, and it cites the frozen
    receipt's own provider-reported usage. Frozen -> resolved -> eligible."""
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import (
        PaidRouteRequest,
        evaluate_paid_route_eligibility,
        load_quota_spend_ledger,
    )

    spend_id = "spend-20260924T200000Z-glmcp-payg-review-own-frozen"
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-payg-spend-20260924t200000z-own-frozen.yaml").write_text(
        _untrusted_receipt_text(
            status="spend_frozen",
            spend_id=spend_id,
            task_id="some-review-task",
            budget_id=BURN_BUDGET_ID,
            model_or_engine="glm-5.3",
            model_id="z_ai-glm-5.3",
            estimated_cost_usd="0.141320",
            created_at="2026-09-24T20:00:00Z",
            reconcile_by="2026-09-25T20:00:00Z",
            reconciliation_state="frozen_refused",
            reconciled_at="2026-09-24T20:00:05Z",
            reconciliation_reason="reviewer froze: provider-reported actual exceeds the reservation",
            usage_prompt_tokens="100000",
            usage_completion_tokens="300",
        ),
        encoding="utf-8",
    )
    request = PaidRouteRequest.model_validate(
        {
            "route_id": "glmcp.review.direct",
            "task_id": "another-review-task",
            "provider": "z_ai",
            "profile": "glmcp-review-direct",
            "task_class": "independent-review",
            "quality_floor": "frontier_review_required",
            "estimated_cost_usd": "0.05",
            "capacity_pool": "api_paid_spend",
        }
    )
    now = "2026-09-24T21:00:00Z"
    when = datetime.fromisoformat(now.replace("Z", "+00:00"))

    result, out = _run_writer(tmp_path, now=now)
    assert result.returncode == 0, result.stderr
    wedged = load_quota_spend_ledger(out)
    assert not evaluate_paid_route_eligibility(wedged, request, now=when).eligible

    base = tmp_path / "quota-spend-ledger-fixtures.json"
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    base_payload["spend_receipts"].append(
        {
            "spend_receipt_schema": 1,
            "spend_id": spend_id,
            "task_id": "some-review-task",
            "authority_case": "CASE-CAPACITY-ROUTING-GLMCP-PAYG-20260706",
            "route_id": "glmcp.review.direct",
            "capacity_pool": "api_paid_spend",
            "budget_id": BURN_BUDGET_ID,
            "provider": "z_ai",
            "model_or_engine": "glm-5.3",
            "model_id": "z_ai-glm-5.3",
            "effort": "none",
            "quantization": "not_applicable",
            "auth_surface": "api_key",
            "quality_floor": "frontier_review_required",
            "quality_preservation_reason": "receipt-bounded GLMCP review fallback",
            "spend_reason": "quota_exhaustion",
            "estimated_cost_usd": "0.141320",
            "actual_cost_usd": "0.141320",
            "cap_remaining_usd": "76.398401",
            "created_at": "2026-09-24T20:00:00Z",
            "reconcile_by": "2026-09-25T20:00:00Z",
            "reconciliation_state": "reconciled",
            "reconciled_at": "2026-09-24T20:30:00Z",
            "reconciliation_reason": (
                "governance resolution: provider-reported usage 100000 prompt + 300 completion "
                "tokens on glm-5.3 at list price"
            ),
            "artifact_refs": ["relay-receipt:glmcp-payg-spend-20260924t200000z-own-frozen.yaml"],
            "support_artifact_authority": "none",
        }
    )
    base.write_text(json.dumps(base_payload), encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(base), now=now)
    assert result.returncode == 0, result.stderr
    resolved = load_quota_spend_ledger(out)
    [receipt] = [r for r in resolved.spend_receipts if r.spend_id == spend_id]
    assert receipt.reconciliation_state.value == "reconciled"
    decision = evaluate_paid_route_eligibility(resolved, request, now=when)
    assert decision.eligible, decision.blocking_reasons


def test_glmcp_payg_spend_receipt_legacy_null_optionals_are_counted(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(
        relay,
        name=spend_receipt_name,
        extra_fields=("actual_cost_usd: None\nreconciled_at: None\nreconciliation_reason: None"),
    )
    base = tmp_path / "quota-spend-ledger-fixtures.json"
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for budget in base_payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260706-zai-glmcp-payg-review":
            budget["created_at"] = "2026-07-06T13:00:00Z"
            budget["expires_at"] = "2026-07-07T13:00:00Z"
            budget["subscription_path_checked_at"] = "2026-07-06T13:00:00Z"
    base.write_text(json.dumps(base_payload), encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(base), now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    receipt = next(
        receipt
        for receipt in payload["spend_receipts"]
        if receipt["spend_id"] == "spend-20260706T140430Z-glmcp-payg-review-test"
    )
    assert "task_hash" not in receipt
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert (
        "spend-gate:glmcp.review.direct:eligible_active_budget" in glmcp_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["glmcp_payg_spend_receipts"] == 1
    assert summary["glmcp_ignored_payg_spend_receipts"] == 0


def test_glmcp_payg_spend_receipt_strips_malformed_task_hash_but_counts_spend(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(relay, name=spend_receipt_name, task_hash="not-a-sha256-hash")

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    receipt = next(
        receipt
        for receipt in payload["spend_receipts"]
        if receipt["spend_id"] == "spend-20260706T140430Z-glmcp-payg-review-test"
    )
    assert "task_hash" not in receipt
    assert "stripped malformed optional task_hash" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_payg_spend_receipts"] == 1
    assert summary["glmcp_ignored_payg_spend_receipts"] == 0


def test_glmcp_payg_admission_rechecks_witness_task_cap(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(relay, name=spend_receipt_name)
    base = tmp_path / "quota-spend-ledger-fixtures.json"
    base_payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for budget in base_payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260706-zai-glmcp-payg-review":
            budget["per_task_cap_usd"] = "0.05"
    base.write_text(json.dumps(base_payload), encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(base), now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert (
        "spend-gate:glmcp.review.direct:refused_exhausted_budget" in glmcp_snapshot["evidence_refs"]
    )
    assert "matching TransitionBudget cap exhausted" in glmcp_snapshot["operator_visible_reason"]


def test_glmcp_payg_admission_supersedes_coding_plan_quota_wall(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260706t140430z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(relay, name=spend_receipt_name)

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert any("cx-glmcp-quota-wall.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert any(
        "glmcp-quota-admission-payg.yaml" in ref
        and "endpoint:https://api.z.ai/api/paas/v4" in ref
        and "primary_error_class:quota_exhausted" in ref
        and "quota_wall_evidence_ref:cx-glmcp-quota-wall.yaml" in ref
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "PAYG" in glmcp_snapshot["operator_visible_reason"]
    assert any(
        ref == "spend-gate:glmcp.review.direct:eligible_active_budget"
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "spend-gate-budget:tb-20260706-zai-glmcp-payg-review" in glmcp_snapshot["evidence_refs"]
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"glmcp": 1}
    assert summary["glmcp_admissions"] == 1
    assert summary["glmcp_payg_spend_receipts"] == 1


def test_glmcp_payg_admission_does_not_supersede_without_validated_spend_receipt(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "cx-glmcp", "2026-07-06T16:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref="glmcp-payg-spend-missing.yaml",
    )

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert (
        "spend-gate-blocker:validated-payg-spend-receipt-absent" in glmcp_snapshot["evidence_refs"]
    )
    assert "validated PAYG spend receipt reservation" in glmcp_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 1
    assert summary["glmcp_payg_spend_receipts"] == 0


def test_glmcp_payg_admission_does_not_supersede_wrong_wall_class(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(
        relay,
        "cx-glmcp",
        "2026-07-06T16:00:00Z",
        failure_class="provider_high_traffic",
    )
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        primary_error_class="quota_exhausted",
    )

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert any(
        "failure_class:provider_high_traffic" in ref for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "matching active quota-wall witness" in glmcp_snapshot["operator_visible_reason"]


def test_glmcp_payg_admission_does_not_supersede_without_active_paid_budget(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    spend_receipt_name = "glmcp-payg-spend-20260609t235500z-test.yaml"
    _wall_receipt(relay, "cx-glmcp", "2026-06-10T06:00:00Z")
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
        evidence_ref=spend_receipt_name,
    )
    _glmcp_payg_spend(
        relay,
        name=spend_receipt_name,
        spend_id="spend-20260609T235500Z-glmcp-payg-review-test",
        created_at="2026-06-09T23:55:00Z",
        reconcile_by="2026-06-10T23:55:00Z",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "exhausted"
    assert any("cx-glmcp-quota-wall.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert any("glmcp-quota-admission-payg.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert (
        "spend-gate:glmcp.review.direct:refused_expired_budget" in glmcp_snapshot["evidence_refs"]
    )
    assert "spend-gate-budget:tb-20260706-zai-glmcp-payg-review" in glmcp_snapshot["evidence_refs"]
    assert "paid-spend gate" in glmcp_snapshot["operator_visible_reason"]


def test_glmcp_role_aliases_map_to_glmcp_not_codex(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    for role in ("codex-glmcp", "codex_glmcp", "cx_glmcp", "glmcp", "glm-review", "glmcp-seat"):
        _wall_receipt(relay, role, "2026-06-10T06:00:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "exhausted"
    assert states["codex.headless.full"] == "fresh"
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"glmcp": 6}


def test_fresh_glmcp_admission_receipt_marks_glmcp_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["provider"] == "z_ai-glm-coding-plan"
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert glmcp_snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    assert any("glmcp-quota-admission.yaml" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert any(
        "witness:supported-tool-usage-witness" in ref
        and "supported_tool:hapax-glmcp-reviewer" in ref
        and "endpoint:https://api.z.ai/api/coding/paas/v4" in ref
        and "model:glm-5.2" in ref
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "finite" in glmcp_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 1


def test_fresh_agy_admission_receipt_marks_agy_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _agy_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["provider"] == "google-antigravity-cli-agy"
    assert agy_snapshot["subscription_quota_state"] == "fresh"
    assert agy_snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    assert any("agy-quota-admission.yaml" in ref for ref in agy_snapshot["evidence_refs"])
    assert any(
        "witness:agy-gemini31pro-smoke-witness" in ref
        and "supported_tool:hapax-agy-reviewer" in ref
        and "model:gemini-3.1-pro-preview" in ref
        for ref in agy_snapshot["evidence_refs"]
    )
    assert "receipt-bounded" in agy_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 1


@pytest.mark.parametrize("model", ["gemini-3.1-pro-high", "gemini-3.1-pro-preview"])
def test_agy_admission_accepts_either_pinned_model_id(tmp_path: Path, model: str) -> None:
    """agy renamed the seat; a receipt minted under either id is the same seat."""

    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _agy_admission(relay, observed_at="2026-06-09T23:55:00Z", model=model)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "fresh"
    assert any(f"model:{model}" in ref for ref in agy_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 1


def test_agy_admission_rejects_an_unpinned_model_id(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _agy_admission(relay, observed_at="2026-06-09T23:55:00Z", model="gemini-3.1-pro-low")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:model-missing-or-unsupported" in ref for ref in agy_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 0
    assert summary["agy_ignored_admissions"] == 1


def test_agy_admission_counts_a_doubly_invalid_receipt_once(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _agy_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        model="gemini-3.1-pro-low",
        secret_value_persisted="true",
    )

    result, _ = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 0
    assert summary["agy_ignored_admissions"] == 1


def _kimi_admission(
    relay: Path,
    *,
    observed_at: str,
    stale_after_seconds: int = 900,
    evidence_ref: str = "kimi-smoke-round-trip-witness",
    model: str = "kimi-code/k3",
    name: str = "kimi-quota-admission.yaml",
    secret_value_persisted: str = "false",
    route_id: str = "kimi.interactive.lane",
    measurement: str = "minimal_round_trip_liveness",
    output_digest_sha256: str = "0123456789abcdef" * 4,
    quota_fraction: str = "unobservable",
    limits: str = "availability only; no client-side quota fraction",
    extra_fields: str = "",
) -> None:
    (relay / name).write_text(
        f"""schema: hapax.kimi_quota_admission.v1
status: quota_available
provider: moonshot-kimi-code-managed
capacity_pool: subscription_quota
route_id: {route_id}
supported_tool: hapax-kimi-quota-admission
model: {model}
observed_at: {observed_at}
stale_after_seconds: {stale_after_seconds}
evidence_ref: {evidence_ref}
secret_source: kimi:operator-session
secret_value_persisted: {secret_value_persisted}
prompt_or_output_persisted: false
billing_mode: operator_session_subscription
smoke_command: kimi -p
smoke_returncode: 0
smoke_stdout_validated: true
positive_admission: true
measurement: {measurement}
output_digest_sha256: {output_digest_sha256}
quota_fraction: {quota_fraction}
limits: "{limits}"
{extra_fields}""",
        encoding="utf-8",
    )


def _kimi_snapshot(payload: dict) -> dict:
    return next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "kimi.interactive.lane"
    )


def test_fresh_kimi_admission_receipt_marks_kimi_lane_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["provider"] == "moonshot-kimi-code-managed"
    assert kimi_snapshot["subscription_quota_state"] == "fresh"
    assert kimi_snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    assert any("kimi-quota-admission.yaml" in ref for ref in kimi_snapshot["evidence_refs"])
    assert any(
        "witness:kimi-smoke-round-trip-witness" in ref
        and "supported_tool:hapax-kimi-quota-admission" in ref
        and "model:kimi-code/k3" in ref
        for ref in kimi_snapshot["evidence_refs"]
    )
    assert (
        "availability-measured, not quota-fraction-measured"
        in kimi_snapshot["operator_visible_reason"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 1
    assert summary["kimi_ignored_admissions"] == 0


def test_no_kimi_admission_marks_kimi_lane_unknown(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert "relay-receipt:kimi:quota-admission:absent" in kimi_snapshot["evidence_refs"]
    assert "scripts/hapax-quota-telemetry-writer" in kimi_snapshot["evidence_refs"]
    assert "availability is the only measurable signal" in kimi_snapshot["operator_visible_reason"]
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0


def test_kimi_admission_rejects_the_stale_route_id(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z", route_id="kimi.interactive.full")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:route-id-missing-or-unsupported" in ref for ref in kimi_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_unsupported_model(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z", model="kimi-code/k2")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:model-missing-or-unsupported" in ref for ref in kimi_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_secret_persistence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z", secret_value_persisted="true")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:secret-value-persisted-missing-or-unsupported" in ref
        for ref in kimi_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_non_liveness_measurement(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z", measurement="deep_quota_probe")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:measurement-missing-or-unsupported" in ref
        for ref in kimi_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_malformed_output_digest(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z", output_digest_sha256="not-a-digest")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:output-digest-sha256-missing-or-malformed" in ref
        for ref in kimi_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_fabricated_quota_fraction(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z", quota_fraction="0.87")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:quota-fraction-missing-or-unsupported" in ref
        for ref in kimi_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_secretish_limits(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        limits="headroom 87% remaining, api_key sk-abc123def456",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:limits-missing-or-unsafe" in ref for ref in kimi_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_unsafe_evidence_ref(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z", evidence_ref="bearer token xyz")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:evidence-ref-unsafe" in ref for ref in kimi_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_future_observed_at(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-10T00:05:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:observed-at-is-in-the-future" in ref for ref in kimi_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_expired_receipt(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:00:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:receipt-expired" in ref for ref in kimi_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_oversized_stale_after(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(relay, observed_at="2026-06-09T23:55:00Z", stale_after_seconds=3601)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "ignored:stale-after-seconds-exceeds-maximum" in ref
        for ref in kimi_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_unsupported_key(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        extra_fields="operator_note: forged field\n",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:unsupported-key-on-line" in ref for ref in kimi_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def test_kimi_admission_rejects_unsafe_receipt_name(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _kimi_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        name="kimi-quota-admission-$(whoami).yaml",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    kimi_snapshot = _kimi_snapshot(payload)
    assert kimi_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:unsafe-receipt-name" in ref for ref in kimi_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["kimi_admissions"] == 0
    assert summary["kimi_ignored_admissions"] == 1


def _claude_admission(
    relay: Path,
    *,
    observed_at: str,
    route_id: str = "claude.headless.full",
    stale_after_seconds: str = "900",
    evidence_ref: str = "claude-subscription-headroom-observed-20260609t2355z",
    observation: str = "subscription_quota_headroom_observed",
    secret_value_persisted: str = "false",
    lane_presence_used_as_quota_evidence: str = "false",
    probe_environment_scrubbed: str | None = None,
    name: str = "claude-subscription-quota-admission.yaml",
) -> None:
    probe_environment_line = (
        f"probe_environment_scrubbed: {probe_environment_scrubbed}\n"
        if probe_environment_scrubbed is not None
        else ""
    )
    (relay / name).write_text(
        "schema: hapax.claude_quota_admission.v1\n"
        "status: quota_available\n"
        "provider: anthropic-claude-subscription\n"
        f"route_id: {route_id}\n"
        "capacity_pool: subscription_quota\n"
        "auth_surface: subscription\n"
        f"observation: {observation}\n"
        f"{probe_environment_line}"
        f"observed_at: {observed_at}\n"
        f"stale_after_seconds: {stale_after_seconds}\n"
        f"evidence_ref: {evidence_ref}\n"
        "secret_source: claude:operator-session-subscription\n"
        f"secret_value_persisted: {secret_value_persisted}\n"
        "prompt_or_output_persisted: false\n"
        "billing_mode: operator_session_subscription\n"
        "account_live_quota_observed: true\n"
        f"lane_presence_used_as_quota_evidence: {lane_presence_used_as_quota_evidence}\n"
        "positive_admission: true\n",
        encoding="utf-8",
    )


def _claude_snapshot(payload: dict, route_id: str = "claude.headless.full") -> dict:
    return next(
        snapshot for snapshot in payload["quota_snapshots"] if snapshot["route_id"] == route_id
    )


def _assert_claude_admission_ignored(tmp_path: Path, expected_reason: str) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "unknown"
    assert any(f":ignored:{expected_reason}" in ref for ref in snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1
    assert f"ignoring claude admission receipt: reason={expected_reason}; recheck:" in result.stderr


@pytest.mark.parametrize(
    ("reason", "reason_code"),
    [
        ("receipt expired", "receipt-expired"),
        ("unsafe receipt name", "unsafe-receipt-name"),
        ("duplicate key on line 18", "duplicate-key-on-line-18"),
        (
            "schema missing or unsupported; expected hapax.example.v1",
            "schema-missing-or-unsupported-expected-hapax-example-v1",
        ),
    ],
)
@pytest.mark.parametrize("family", ["claude", "agy"])
def test_ignored_admission_warning_names_each_reason_class(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    family: str,
    reason: str,
    reason_code: str,
) -> None:
    namespace = runpy.run_path(str(SCRIPT))

    namespace[f"_warn_ignored_{family}_admission"](
        tmp_path / f"{family}-quota-admission.yaml",
        reason,
    )

    warning = capsys.readouterr().err
    assert f"ignoring {family} admission receipt: reason={reason_code}; recheck:" in warning
    assert "validation failed" not in warning


@pytest.mark.parametrize(
    ("name", "expected_reason"),
    [
        (
            "claude-subscription-quota-admission-cus_123.yaml",
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            "claude-subscription-quota-admission-lane2.yaml",
            "receipt-name-names-lane-session-presence",
        ),
        (
            "claude-subscription-quota-admission-token.yaml",
            "receipt-name-names-secretish-value",
        ),
    ],
)
def test_rejected_claude_receipt_name_is_hashed_in_ignored_evidence(
    tmp_path: Path,
    name: str,
    expected_reason: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z", name=name)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    evidence_refs = "\n".join(snapshot["evidence_refs"])
    assert snapshot["subscription_quota_state"] == "unknown"
    assert name not in evidence_refs
    assert f":ignored:{expected_reason}" in evidence_refs
    assert "relay-receipt:unsafe-receipt-name-sha256:" in evidence_refs


def test_fresh_claude_admission_receipt_marks_claude_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["provider"] == "anthropic-claude-subscription"
    assert snapshot["subscription_quota_state"] == "fresh"
    assert snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    ref = next(
        r for r in snapshot["evidence_refs"] if "claude-subscription-quota-admission.yaml" in r
    )
    assert ref.endswith(":account-live-quota:observed")
    assert "witness:claude-subscription-headroom-observed-20260609t2355z" in ref
    assert "observation:subscription_quota_headroom_observed" in ref
    assert "receipt-bounded" in snapshot["operator_visible_reason"]
    assert json.loads(result.stdout)["claude_admissions"] == 1


def test_fresh_claude_review_admission_marks_only_review_route_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        route_id="claude.review.opus",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    review_snapshot = _claude_snapshot(payload, "claude.review.opus")
    headless_snapshot = _claude_snapshot(payload, "claude.headless.full")
    assert review_snapshot["subscription_quota_state"] == "fresh"
    assert review_snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    assert headless_snapshot["subscription_quota_state"] == "unknown"
    assert "claude.review.opus" in review_snapshot["operator_visible_reason"]
    assert json.loads(result.stdout)["claude_admissions"] == 1


def test_claude_admission_writer_output_marks_claude_fresh(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    admission_result = subprocess.run(
        [
            sys.executable,
            str(CLAUDE_ADMISSION_SCRIPT),
            "--receipt-dir",
            str(relay),
            "--now",
            "2026-06-09T23:55:00Z",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260609t2355z",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert admission_result.returncode == 0, admission_result.stderr

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "fresh"
    assert snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    assert any(
        ref.endswith(":account-live-quota:observed")
        and "claude-subscription-headroom-observed-20260609t2355z" in ref
        for ref in snapshot["evidence_refs"]
    )
    assert json.loads(result.stdout)["claude_admissions"] == 1


def test_claude_probe_windows_keep_the_admission_receipt_admitted(tmp_path: Path) -> None:
    """The strict receipt parser rejects unknown keys, so the window keys must be admitted."""
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    admission_result = subprocess.run(
        [
            sys.executable,
            str(CLAUDE_ADMISSION_SCRIPT),
            "--receipt-dir",
            str(relay),
            "--now",
            "2026-06-09T23:55:00Z",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260609t2355z",
            "--probe-environment-scrubbed",
            "--five-hour-used-percent",
            "8",
            "--five-hour-resets-at",
            "2026-06-10T03:00:00Z",
            "--seven-day-used-percent",
            "9",
            "--seven-day-resets-at",
            "2026-06-12T22:00:00Z",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert admission_result.returncode == 0, admission_result.stderr
    assert "seven_day_used_percent" in next(relay.glob("*.yaml")).read_text(encoding="utf-8")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "fresh"
    assert json.loads(result.stdout)["claude_admissions"] == 1


V1_SNAPSHOT_FIELDS = {
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


def test_live_ledger_stays_schema_1_until_its_readers_take_2(tmp_path: Path) -> None:
    """reins reads the live file through hapax-spine 0.1.3: Literal[1], extra=forbid."""
    result, out = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert "freeze" not in payload and "operator_reports" not in payload
    assert all(set(row) == V1_SNAPSHOT_FIELDS for row in payload["quota_snapshots"])

    result, out = _run_writer(tmp_path, extra_env={"HAPAX_QUOTA_LEDGER_LIVE_SCHEMA": "2"})
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2 and "freeze" in payload


def test_a_damaged_previous_live_ledger_never_blocks_the_tick(tmp_path: Path) -> None:
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    out.parent.mkdir(parents=True)
    out.write_text('{"truncated": ', encoding="utf-8")
    result, out = _run_writer(tmp_path, extra_env={"HAPAX_QUOTA_LEDGER_LIVE_SCHEMA": "2"})
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["schema_version"] == 2


def test_unreadable_measurements_still_write_the_admission_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shared.quota_headroom as quota_headroom

    def unreadable(*args, **kwargs):
        raise quota_headroom.TraceReadError("corrupt_or_unreadable_source:local-trace:x:0")

    monkeypatch.setattr(quota_headroom, "collect_measurements", unreadable)
    platform_receipts = tmp_path / "platform-receipts"
    platform_receipts.mkdir()
    _codex_platform_receipt(platform_receipts)
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(platform_receipts))
    monkeypatch.setenv("HAPAX_DISPATCH_HOST", "")
    monkeypatch.setenv("HAPAX_DEFAULT_DISPATCH_HOST", "")
    (tmp_path / "relay").mkdir()
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    namespace = runpy.run_path(str(SCRIPT))
    rc = namespace["main"](
        [
            "--skip-receipts",
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(tmp_path / "relay"),
            "--platform-capability-receipt-dir",
            str(platform_receipts),
            "--nvidia-smi",
            str(_fake_nvidia_smi(tmp_path, "echo '1000, 32000'")),
            "--trace-home",
            str(tmp_path / "trace-home"),
        ]
    )
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["quota_snapshots"]


def test_claude_admission_writer_can_target_review_route(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    admission_result = subprocess.run(
        [
            sys.executable,
            str(CLAUDE_ADMISSION_SCRIPT),
            "--receipt-dir",
            str(relay),
            "--now",
            "2026-06-09T23:55:00Z",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260609t2355z",
            "--route-id",
            "claude.review.opus",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert admission_result.returncode == 0, admission_result.stderr
    assert json.loads(admission_result.stdout)["route_id"] == "claude.review.opus"

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert _claude_snapshot(payload, "claude.review.opus")["subscription_quota_state"] == "fresh"
    assert (
        _claude_snapshot(payload, "claude.headless.full")["subscription_quota_state"] == "unknown"
    )


def test_fresh_claude_admission_ref_passes_ledger_validator(tmp_path: Path) -> None:
    # Cross-layer contract: the composite ref the telemetry writer emits is exactly what the ledger
    # accepts as claude admission evidence, so the guarantor attests. Pins telemetry <-> ledger.
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")

    result, out = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    ref = next(
        r for r in snapshot["evidence_refs"] if "claude-subscription-quota-admission.yaml" in r
    )

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import _is_claude_admission_evidence_ref

    assert _is_claude_admission_evidence_ref(ref) is True


def test_fractional_second_claude_admission_ref_is_normalized_for_ledger(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00.123Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "fresh"
    assert snapshot["fresh_until"] == "2026-06-10T00:10:00Z"
    ref = next(
        r for r in snapshot["evidence_refs"] if "claude-subscription-quota-admission.yaml" in r
    )
    assert "observed_at:2026-06-09T23:55:00Z:" in ref
    assert "fresh_until:2026-06-10T00:10:00Z:" in ref

    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import _is_claude_admission_evidence_ref

    assert _is_claude_admission_evidence_ref(ref) is True


def test_fractional_second_claude_admission_expires_at_normalized_boundary(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00.123Z")

    result, out = _run_writer(tmp_path, now="2026-06-10T00:10:00Z")

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "unknown"
    assert any(":ignored:receipt-expired" in ref for ref in snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1


def test_probe_environment_scrub_disclosure_is_accepted(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        probe_environment_scrubbed=(
            "ANTHROPIC_BASE_URL,ANTHROPIC_AUTH_TOKEN,ANTHROPIC_API_KEY,ANTHROPIC_MODEL"
        ),
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "fresh"
    assert json.loads(result.stdout)["claude_admissions"] == 1


def test_claude_admission_rejects_lane_presence_evidence_ref(tmp_path: Path) -> None:
    # Defense in depth: even a receipt naming lane/tmux presence is refused by the scanner.
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        evidence_ref="tmux-hapax-claude-eta-present-20260609",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "unknown"
    assert any(":ignored:" in ref for ref in snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1


def test_rejected_claude_review_admission_evidence_stays_route_scoped(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        route_id="claude.review.opus",
        evidence_ref="tmux-hapax-claude-review-present-20260609",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    review_snapshot = _claude_snapshot(payload, "claude.review.opus")
    headless_snapshot = _claude_snapshot(payload, "claude.headless.full")
    assert review_snapshot["subscription_quota_state"] == "unknown"
    assert any(":route_id:claude.review.opus" in ref for ref in review_snapshot["evidence_refs"])
    assert not any(
        ":route_id:claude.review.opus" in ref for ref in headless_snapshot["evidence_refs"]
    )
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1


def test_claude_admission_rejects_secret_persistence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z", secret_value_persisted="true")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = _claude_snapshot(json.loads(out.read_text(encoding="utf-8")))
    assert snapshot["subscription_quota_state"] == "unknown"
    summary = json.loads(result.stdout)
    assert summary["claude_admissions"] == 0
    assert summary["claude_ignored_admissions"] == 1
    # the receipt field name/value must never echo to stderr (generic warning only).
    assert "secret_value_persisted" not in result.stderr


@pytest.mark.parametrize(
    ("kwargs", "expected_reason"),
    [
        (
            {"observed_at": "2026-06-09T23:00:00Z", "stale_after_seconds": "60"},
            "receipt-expired",
        ),
        ({"observed_at": "2026-06-10T00:01:00Z"}, "observed-at-is-in-the-future"),
        ({"observed_at": "not-a-date"}, "missing-or-malformed-observed-at"),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "stale_after_seconds": "soon"},
            "malformed-stale-after-seconds",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "stale_after_seconds": "0"},
            "non-positive-stale-after-seconds",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "stale_after_seconds": "3601"},
            "stale-after-seconds-exceeds-maximum-3600",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "observation": "lane_presence_seen"},
            "observation-missing-or-unsupported",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "eta"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "cx-theta"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-session-observed-20260609t2355z",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-lane-observed-20260609t2355z",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "vbe-3-headroom"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "mu-headroom"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-sessions-observed-20260609t2355z",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "tmux2-headroom"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-session2-observed-20260609t2355z",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "eta2"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {"observed_at": "2026-06-09T23:55:00Z", "evidence_ref": "eta+present"},
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-headroom-eta2-observed",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude+headroom+eta+observed",
            },
            "evidence-ref-names-lane-session-presence-not-account-live-quota-evidence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billing-cus_123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billing:cus_123-headroom-20260609",
            },
            "evidence-ref-unsafe-expected-sanitized-account-live-observation-reference",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription-sub_123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription-id-123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription_id_123_headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription+id+123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billing+cus_123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billing-cus.123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-account-acct.123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-subscription-sub.123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-cus123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-sub123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-acct123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-billingcus123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-in_123-headroom-20260609",
            },
            "evidence-ref-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "sk-live-secret-token-000000000000000000000000",
            },
            "evidence-ref-unsafe-expected-sanitized-account-live-observation-reference",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "evidence_ref": "claude-si-1abc-headroom",
            },
            "evidence-ref-unsupported-expected-claude-subscription-headroom-witness-reference",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "bad#claude-subscription-quota-admission.yaml",
            },
            "unsafe-receipt-name",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "eta-claude-subscription-quota-admission.yaml",
            },
            "receipt-name-names-lane-session-presence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-lane2.yaml",
            },
            "receipt-name-names-lane-session-presence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-eta2.yaml",
            },
            "receipt-name-names-lane-session-presence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-eta+present.yaml",
            },
            "receipt-name-names-lane-session-presence",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-token.yaml",
            },
            "receipt-name-names-secretish-value",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-cus_123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-subscription-id-123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-subscription_id_123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-subscription+id+123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-billing+cus_123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-cus.123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-acct.123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-sub.123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-cus123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-sub123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-acct123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
        (
            {
                "observed_at": "2026-06-09T23:55:00Z",
                "name": "claude-subscription-quota-admission-billingcus123.yaml",
            },
            "receipt-name-names-billing-or-account-identifier",
        ),
    ],
)
def test_claude_admission_fail_closed_validation_cases(
    tmp_path: Path,
    kwargs: dict[str, str],
    expected_reason: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, **kwargs)

    _assert_claude_admission_ignored(tmp_path, expected_reason)


def test_claude_admission_rejects_unreadable_receipt(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "claude-subscription-quota-admission-invalid-utf8.yaml").write_bytes(b"\xff\xfe\xfa")

    _assert_claude_admission_ignored(tmp_path, "unreadable-receipt-unicodedecodeerror")


def test_claude_admission_rejects_strict_parse_failure(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, observed_at="2026-06-09T23:55:00Z")
    with (relay / "claude-subscription-quota-admission.yaml").open(
        "a",
        encoding="utf-8",
    ) as receipt:
        receipt.write("status: quota_available\n")

    _assert_claude_admission_ignored(tmp_path, "duplicate-key-on-line-18")


def test_agy_admission_rejects_secret_persistence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _agy_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        secret_value_persisted="true",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:secret-value-persisted" in ref for ref in agy_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 0
    assert summary["agy_ignored_admissions"] == 1
    assert (
        "ignoring agy admission receipt: "
        "reason=secret-value-persisted-missing-or-unsupported-expected-false; recheck:"
    ) in result.stderr
    assert "false-negative recovery" in result.stderr
    assert "secret_value_persisted" not in result.stderr


def test_ignored_agy_admission_warning_omits_secretish_receipt_dir(tmp_path: Path) -> None:
    secretish_dir = tmp_path / "sk-secret-token-relay-receipts-000000000000000000000000"
    secretish_dir.mkdir()
    (secretish_dir / "agy-quota-admission-invalid-utf8.yaml").write_bytes(b"\xff\xfe\xfa")

    result, out = _run_writer(tmp_path, "--relay-receipt-dir", str(secretish_dir))

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "unknown"
    assert (
        "ignoring agy admission receipt: reason=unreadable-receipt-unicodedecodeerror; recheck:"
    ) in result.stderr
    assert secretish_dir.name not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 0
    assert summary["agy_ignored_admissions"] == 1


def test_agy_admission_rejects_missing_smoke_validation(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "agy-quota-admission.yaml").write_text(
        """schema: hapax.agy_quota_admission.v1
status: quota_available
provider: google-antigravity-cli-agy
capacity_pool: subscription_quota
route_id: agy.review.direct
supported_tool: hapax-agy-reviewer
model: gemini-3.1-pro-preview
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: agy-gemini31pro-smoke-witness
secret_source: agy:operator-session
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: operator_session_subscription
positive_admission: true
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    agy_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "agy.review.direct"
    )
    assert agy_snapshot["subscription_quota_state"] == "unknown"
    assert any("ignored:smoke-command-missing" in ref for ref in agy_snapshot["evidence_refs"])
    summary = json.loads(result.stdout)
    assert summary["agy_admissions"] == 0
    assert summary["agy_ignored_admissions"] == 1


def test_fresh_glmcp_payg_admission_without_active_wall_stays_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(
        relay,
        observed_at="2026-07-06T14:04:00Z",
        endpoint="https://api.z.ai/api/paas/v4",
        name="glmcp-quota-admission-payg.yaml",
    )

    result, out = _run_writer(tmp_path, now=PAYG_NOW)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["provider"] == "z_ai-glm-coding-plan"
    assert glmcp_snapshot["capacity_pool"] == "subscription_quota"
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        "glmcp-quota-admission-payg.yaml" in ref
        and "endpoint:https://api.z.ai/api/paas/v4" in ref
        and "model:glm-5.2" in ref
        and "primary_error_class:quota_exhausted" in ref
        and "quota_wall_evidence_ref:cx-glmcp-quota-wall.yaml" in ref
        for ref in glmcp_snapshot["evidence_refs"]
    )
    assert not any(ref.startswith("spend-gate:") for ref in glmcp_snapshot["evidence_refs"])
    assert (
        "without an active Coding Plan quota-wall witness"
        in glmcp_snapshot["operator_visible_reason"]
    )
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 1


def test_glmcp_admission_scans_documented_recheck_glob(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        name="manual_glmcp-quota-admission.yaml",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert any(
        "manual_glmcp-quota-admission.yaml" in ref for ref in glmcp_snapshot["evidence_refs"]
    )


def test_glmcp_admission_hashes_unsafe_receipt_name_in_evidence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    unsafe_name = "sk-secret-token-glmcp-quota-admission.yaml"
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        name=unsafe_name,
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "fresh"
    assert any("unsafe-receipt-name-sha256:" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert unsafe_name not in payload_text


@pytest.mark.parametrize("timestamp_field", ["captured_at", "detected_at"])
def test_glmcp_admission_rejects_timestamp_fallback_fields(
    tmp_path: Path,
    timestamp_field: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        name=f"glmcp-quota-admission-{timestamp_field}.yaml",
        timestamp_field=timestamp_field,
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert "unsupported timestamp field; expected observed_at only" in result.stderr
    assert json.loads(result.stdout)["glmcp_admissions"] == 0


def test_glmcp_admission_rejects_claude_code_anthropic_evidence_for_review_route(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(
        relay,
        observed_at="2026-06-09T23:55:00Z",
        supported_tool="claude_code",
        endpoint="https://api.z.ai/api/anthropic",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert "supported_tool missing or unsupported" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_rejects_unsupported_tool_or_endpoint(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-claude-code-coding-endpoint.yaml").write_text(
        """schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: claude_code
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-reviewer-anthropic-endpoint.yaml").write_text(
        """schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/anthropic
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-reviewer-trailing-slash-endpoint.yaml").write_text(
        """schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4/
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert "endpoint missing or unsupported" in result.stderr
    assert "supported_tool missing or unsupported" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_requires_provider_and_route(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-missing-provider.yaml").write_text(
        """status: quota_available
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-missing-route.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert "present but rejected" in glmcp_snapshot["operator_visible_reason"]
    assert not any("quota-admission:absent" in ref for ref in glmcp_snapshot["evidence_refs"])
    assert any(
        ":ignored:provider-missing-or-unsupported" in ref for ref in glmcp_snapshot["evidence_refs"]
    )
    assert any(
        ":ignored:route-id-missing-or-unsupported" in ref for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "provider missing or unsupported" in result.stderr
    assert "route_id missing or unsupported" in result.stderr
    assert "find ~/.cache/hapax/relay/receipts" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0
    assert summary["glmcp_ignored_admissions"] == 2


def test_glmcp_admission_receipt_warns_on_unsupported_status(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-unsupported-status.yaml").write_text(
        """status: ok
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "status missing or unsupported; expected quota_available" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_duplicate_keys(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-duplicate-provider.yaml").write_text(
        """status: quota_available
provider: not-glmcp
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "duplicate key on line" in result.stderr
    assert "duplicate key 'provider'" not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_secretish_unknown_keys_without_echo(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    secretish_key = "sk-live-secret-token-000000000000000000000000"
    (relay / "glmcp-quota-admission-unknown-key.yaml").write_text(
        f"""status: quota_available
{secretish_key}: first
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "unsupported key on line" in result.stderr
    assert secretish_key not in result.stderr
    assert secretish_key not in payload_text
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_non_flat_yaml(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-nested.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
endpoint:
  endpoint: https://api.z.ai/api/coding/paas/v4
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "non-flat line" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_ambiguous_provider_alias(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-ambiguous-provider.yaml").write_text(
        """status: quota_available
provider: z_ai
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "provider ambiguous alias" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_requires_subscription_capacity_pool(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-missing-capacity.yaml").write_text(
        """schema: hapax.glmcp_quota_admission.v1
status: quota_available
provider: z_ai-glm-coding-plan
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "capacity_pool missing or unsupported for endpoint" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


@pytest.mark.parametrize(
    ("field_name", "expected_reason"),
    [
        ("provider", "provider missing or unsupported"),
        ("capacity_pool", "capacity_pool missing or unsupported for endpoint"),
        ("route_id", "route_id missing or unsupported"),
        ("supported_tool", "supported_tool missing or unsupported"),
        ("endpoint", "endpoint missing or unsupported"),
        ("model", "model missing or unsupported"),
        ("observed_at", "missing or malformed observed_at"),
        ("stale_after_seconds", "malformed stale_after_seconds"),
        ("schema", "schema missing or unsupported"),
        ("secret_source", "secret_source missing or unsupported"),
        ("secret_value_persisted", "secret_value_persisted must be false"),
        ("prompt_or_output_persisted", "prompt_or_output_persisted must be false"),
        ("billing_mode", "billing_mode missing or unsupported for endpoint"),
        ("payg_fallback", "payg_fallback missing or unsupported for endpoint"),
    ],
)
def test_glmcp_admission_rejection_warnings_do_not_echo_untrusted_values(
    tmp_path: Path,
    field_name: str,
    expected_reason: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    secretish_value = "sk-live-secret-token-000000000000000000000000"
    fields = {
        "schema": "hapax.glmcp_quota_admission.v1",
        "status": "quota_available",
        "provider": "z_ai-glm-coding-plan",
        "capacity_pool": "subscription_quota",
        "route_id": "glmcp.review.direct",
        "supported_tool": "hapax-glmcp-reviewer",
        "endpoint": "https://api.z.ai/api/coding/paas/v4",
        "model": "glm-5.2",
        "observed_at": "2026-06-09T23:55:00Z",
        "stale_after_seconds": "900",
        "evidence_ref": "supported-tool-usage-witness",
        "secret_source": "pass:glmcp/api-key",
        "secret_value_persisted": "false",
        "prompt_or_output_persisted": "false",
        "billing_mode": "coding_plan_subscription",
        "payg_fallback": "false",
    }
    fields[field_name] = secretish_value
    receipt_body = "".join(f"{key}: {value}\n" for key, value in fields.items())
    (relay / f"glmcp-quota-admission-secretish-{field_name}.yaml").write_text(
        receipt_body,
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert expected_reason in result.stderr
    assert secretish_value not in result.stderr
    assert secretish_value not in payload_text
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


@pytest.mark.parametrize(
    ("field_name", "expected_reason"),
    [
        ("secret_value_persisted", "secret_value_persisted must be false"),
        ("prompt_or_output_persisted", "prompt_or_output_persisted must be false"),
        ("payg_fallback", "payg_fallback missing or unsupported for endpoint"),
    ],
)
def test_glmcp_admission_rejects_noncanonical_false_booleans(
    tmp_path: Path,
    field_name: str,
    expected_reason: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    fields = {
        "schema": "hapax.glmcp_quota_admission.v1",
        "status": "quota_available",
        "provider": "z_ai-glm-coding-plan",
        "capacity_pool": "subscription_quota",
        "route_id": "glmcp.review.direct",
        "supported_tool": "hapax-glmcp-reviewer",
        "endpoint": "https://api.z.ai/api/coding/paas/v4",
        "model": "glm-5.2",
        "observed_at": "2026-06-09T23:55:00Z",
        "stale_after_seconds": "900",
        "evidence_ref": "supported-tool-usage-witness",
        "secret_source": "pass:glmcp/api-key",
        "secret_value_persisted": "false",
        "prompt_or_output_persisted": "false",
        "billing_mode": "coding_plan_subscription",
        "payg_fallback": "false",
    }
    fields[field_name] = "False"
    receipt_body = "".join(f"{key}: {value}\n" for key, value in fields.items())
    (relay / f"glmcp-quota-admission-noncanonical-{field_name}.yaml").write_text(
        receipt_body,
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert expected_reason in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_requires_supported_tool_evidence(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-missing-supported-tool.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-unsupported-endpoint.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/v1
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-unsupported-model.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-4.7
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-missing-evidence.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "supported_tool missing or unsupported" in result.stderr
    assert "unsupported-endpoint" in result.stderr
    assert "expected official Z.ai Coding Plan or PAYG endpoint" in result.stderr
    assert "model missing or unsupported" in result.stderr
    assert "evidence_ref missing" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_stale_glmcp_admission_receipt_keeps_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(relay, observed_at="2026-06-09T23:00:00Z", stale_after_seconds=60)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "receipt expired" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_overlong_glmcp_admission_ttl_keeps_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(relay, observed_at="2026-06-09T23:55:00Z", stale_after_seconds=3601)

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "stale_after_seconds exceeds maximum 3600" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_future_glmcp_admission_receipt_keeps_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _glmcp_admission(relay, observed_at="2026-06-10T00:05:00Z")

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "observed_at is in the future" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


@pytest.mark.parametrize(
    "legacy_timestamp_line",
    [
        "captured_at: 2026-06-10T00:05:00Z",
        "captured_at:",
        "detected_at:",
    ],
)
def test_ambiguous_glmcp_admission_timestamps_keep_glmcp_unknown(
    tmp_path: Path,
    legacy_timestamp_line: str,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-ambiguous-timestamp.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
{legacy_timestamp_line}
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    glmcp_snapshot = next(
        snapshot
        for snapshot in payload["quota_snapshots"]
        if snapshot["route_id"] == "glmcp.review.direct"
    )
    assert glmcp_snapshot["subscription_quota_state"] == "unknown"
    assert any(
        ":ignored:unsupported-timestamp-field" in ref for ref in glmcp_snapshot["evidence_refs"]
    )
    assert "unsupported timestamp field; expected observed_at only" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0
    assert summary["glmcp_ignored_admissions"] == 1


def test_malformed_glmcp_admission_timestamps_are_operator_visible(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-bad-observed-at.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: definitely-not-a-date
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-blank-observed-at.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at:
stale_after_seconds: 900
evidence_ref: supported-tool-usage-witness
secret_source: pass:glmcp/api-key
secret_value_persisted: false
prompt_or_output_persisted: false
billing_mode: coding_plan_subscription
payg_fallback: false
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-bad-stale-after.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: soon
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-zero-stale-after.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 0
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "malformed observed_at" in result.stderr
    assert "malformed stale_after_seconds" in result.stderr
    assert "non-positive stale_after_seconds" in result.stderr
    assert "false-negative recovery" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_requires_explicit_stale_after_seconds(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-missing-stale-after.yaml").write_text(
        """status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "stale_after_seconds missing" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_ttl_rejection_does_not_echo_numeric_secret(
    tmp_path: Path,
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    numeric_secret = "12345678901234567890123456789012"
    (relay / "glmcp-quota-admission-secretish-ttl.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: {numeric_secret}
evidence_ref: supported-tool-usage-witness
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "stale_after_seconds exceeds maximum 3600" in result.stderr
    assert numeric_secret not in result.stderr
    assert numeric_secret not in payload_text
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_glmcp_admission_receipt_rejects_secretish_evidence_ref(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    secretish_ref = "sk-live-secret-token-000000000000000000000000"
    colon_ref = "relay:receipt:ambiguous"
    email_ref = "seat@example.com"
    overlong_secretish_ref = ("a-" * 120) + "sk-live-secret-token-000000000000000000000000"
    (relay / "glmcp-quota-admission-secretish-evidence.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: {secretish_ref}
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-colon-evidence.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: {colon_ref}
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-email-evidence.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: {email_ref}
""",
        encoding="utf-8",
    )
    (relay / "glmcp-quota-admission-overlong-secretish-evidence.yaml").write_text(
        f"""status: quota_available
provider: z_ai-glm-coding-plan
capacity_pool: subscription_quota
route_id: glmcp.review.direct
supported_tool: hapax-glmcp-reviewer
endpoint: https://api.z.ai/api/coding/paas/v4
model: glm-5.2
observed_at: 2026-06-09T23:55:00Z
stale_after_seconds: 900
evidence_ref: {overlong_secretish_ref}
""",
        encoding="utf-8",
    )

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload_text = out.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "evidence_ref unsafe" in result.stderr
    assert secretish_ref not in result.stderr
    assert overlong_secretish_ref not in result.stderr
    assert secretish_ref not in payload_text
    assert colon_ref not in payload_text
    assert email_ref not in payload_text
    assert overlong_secretish_ref not in payload_text
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_unreadable_glmcp_admission_receipt_keeps_glmcp_unknown(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    (relay / "glmcp-quota-admission-invalid-utf8.yaml").write_bytes(b"\xff\xfe\xfa")
    unsafe_dir_name = "sk-secret-token-glmcp-quota-admission.yaml"
    (relay / unsafe_dir_name).mkdir()

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "unreadable receipt UnicodeDecodeError" in result.stderr
    assert "unreadable receipt IsADirectoryError" in result.stderr
    assert unsafe_dir_name not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0


def test_ignored_glmcp_admission_warning_omits_secretish_receipt_dir(tmp_path: Path) -> None:
    secretish_dir = tmp_path / "sk-secret-token-relay-receipts-000000000000000000000000"
    secretish_dir.mkdir()
    (secretish_dir / "glmcp-quota-admission-invalid-utf8.yaml").write_bytes(b"\xff\xfe\xfa")

    result, out = _run_writer(tmp_path, "--relay-receipt-dir", str(secretish_dir))

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["glmcp.review.direct"] == "unknown"
    assert "unreadable receipt UnicodeDecodeError" in result.stderr
    assert secretish_dir.name not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["glmcp_admissions"] == 0
    assert summary["glmcp_ignored_admissions"] == 1


def test_resource_probe_failure_fails_closed_to_unknown(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path, nvidia_body="exit 9")

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["local_resource_state"] == "unknown"
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["litellm.local.command-r-35b"] == "unknown"


def test_vram_pressure_degrades_resource_state(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path, nvidia_body="echo '31000, 32000'")

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["local_resource_state"] in {"yellow", "red"}


def test_unusable_base_ledger_fails_without_writing(tmp_path: Path) -> None:
    bad_base = tmp_path / "bad-base.json"
    bad_base.write_text("{not json", encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(bad_base))

    assert result.returncode == 1
    assert "base ledger unusable" in result.stderr
    assert not out.exists()


def test_output_is_private_and_atomic(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600
    leftovers = [p for p in out.parent.iterdir() if p.name not in {out.name, f"{out.name}.lock"}]
    assert leftovers == []


def test_no_secret_material_in_output(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    for token in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "LITELLM_API_KEY",
        "pass show",
        "hapax-secrets.env",
    ):
        assert token not in text


class TestGlmcpSecretSourceMigration:
    """`secret_source` is a receipt DATA CONTRACT, and the reviewer and this validator cannot
    swap in the same instant.

    The reviewer now emits `filestore:glmcp/api-key` (it reads the FileStore, not pass).
    Rejecting a `pass:`-sourced receipt that was truthful when it was written would drop real
    spend from the ledger, so both are accepted for one receipt lifetime — admission receipts
    carry `stale_after_seconds` <= 3600, so every legacy receipt has expired an hour after the
    reviewer change deploys. The removal condition is stated at the constant.

    This is a versioned enum during a migration, not a fallback: nothing here reaches further
    on failure than the primary path does, and a third value is still refused.
    """

    @staticmethod
    def _sources():
        import runpy

        module = runpy.run_path(
            str(REPO_ROOT / "scripts" / "hapax-quota-telemetry-writer"), run_name="__pin__"
        )
        return module["GLMCP_ADMISSION_SECRET_SOURCES"]

    def test_the_live_source_is_accepted(self) -> None:
        assert "filestore:glmcp/api-key" in self._sources()

    def test_the_legacy_source_is_still_accepted_during_the_migration(self) -> None:
        assert "pass:glmcp/api-key" in self._sources()

    def test_nothing_else_is_accepted(self) -> None:
        for hostile in (
            "",
            "pass:other/key",
            "filestore:other/key",
            "env:GLMCP_API_KEY",
            "operator-attestation",
        ):
            assert hostile not in self._sources(), hostile

    def test_the_reviewer_emits_the_live_source(self) -> None:
        """The producer and the validator must agree, or every glmcp spend receipt is
        rejected and the PAYG ledger silently stops recording."""
        reviewer = (REPO_ROOT / "scripts" / "hapax-glmcp-reviewer").read_text(encoding="utf-8")
        assert '("secret_source", "filestore:glmcp/api-key")' in reviewer
        assert '("secret_source", "pass:glmcp/api-key")' not in reviewer
