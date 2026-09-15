"""`hapax-platform-capability-receipts --show` — the read-only mode the seat refresher consults.

Review finding on #4624, round 9: the mode had no direct tests for an empty platform selection,
a missing receipt, plain-text output, or a directory the loader cannot read.
"""

from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
import runpy
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, current_thread

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-platform-capability-receipts"


@pytest.fixture
def publication_receipts():
    from shared.platform_capability_receipts import PlatformCapabilityReceipt

    now = datetime.now(UTC).replace(microsecond=0)
    surface = {
        "status": "observed",
        "source": "test",
        "observed_at": now,
        "stale_after": "15m",
        "evidence_refs": ["relay-receipt:admission-a:observed_at:2026-09-05T00:00:00Z"],
    }
    receipt_a = PlatformCapabilityReceipt.model_validate(
        {
            "receipt_id": "writer-a",
            "platform": "glmcp",
            "routes": ["glmcp.review.direct"],
            "observed_at": now,
            "stale_after": "15m",
            "cli": {"binary": "test", "available": True},
            "wrapper": {"path": "test", "exists": True, "executable": True},
            "capability": surface,
            "resource": surface,
            "quota": surface,
            "provider_docs": {"refs": ["test:docs"], "fetched_at": now, "stale_after": "30d"},
        }
    )
    receipt_b = receipt_a.model_copy(
        update={
            "receipt_id": "writer-b",
            "observed_at": now + timedelta(seconds=5),
            "quota": receipt_a.quota.model_copy(
                update={
                    "observed_at": now + timedelta(seconds=5),
                    "evidence_refs": ["relay-receipt:admission-b:observed_at:2026-09-05T00:00:05Z"],
                }
            ),
            "known_unknowns": ["longer receipt" * 100],
        }
    )
    return receipt_a, receipt_b, now


def test_concurrent_receipt_publications_never_leave_a_json_tail(
    tmp_path: Path, monkeypatch, publication_receipts, capsys
):
    """B holds flock before replace; A must block, re-read B, and refuse its older observation."""
    from shared.platform_capability_receipts import load_platform_capability_receipts

    receipt_a, receipt_b, now = publication_receipts
    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    path = write_receipt(receipt_a, tmp_path)
    opened, finish, attempted = Event(), Event(), Event()
    real_fdopen, real_flock = os.fdopen, fcntl.flock

    def fdopen(fd, *args, **kwargs):
        stream = real_fdopen(fd, *args, **kwargs)
        if current_thread().name.startswith("receipt-b"):
            opened.set()
            if not finish.wait(10):
                stream.close()
                raise AssertionError("writer B was never released")
        return stream

    def flock(fd, operation):
        if current_thread().name.startswith("receipt-a") and operation == fcntl.LOCK_EX:
            attempted.set()
        return real_flock(fd, operation)

    monkeypatch.setattr(os, "fdopen", fdopen)
    monkeypatch.setattr(fcntl, "flock", flock)
    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="receipt-b") as new_pool,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="receipt-a") as old_pool,
    ):
        newer = new_pool.submit(write_receipt, receipt_b, tmp_path)
        try:
            assert opened.wait(10), "writer B never opened its output"
            older = old_pool.submit(write_receipt, receipt_a, tmp_path)
            assert attempted.wait(2), "older publisher did not acquire the shared flock"
            assert not older.done(), "older publisher must block behind B's transaction"
            assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_a
        finally:
            finish.set()
        assert newer.result(timeout=10) == path
        assert older.result(timeout=10) is None
    # The delayed shorter A must NEVER undo B's renewed admission, nor leave a JSON tail.
    assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_b
    assert "stale_observation_not_published" in capsys.readouterr().err
    assert sorted(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("status", ["error", "unobservable"])
@pytest.mark.parametrize(
    "offset", [-5, 0, 5], ids=["older-failure", "tied-failure", "later-failure"]
)
@pytest.mark.parametrize("negative_first", [False, True], ids=["positive-first", "negative-first"])
def test_failure_observation_order_ignores_publication_clock(
    tmp_path: Path, publication_receipts, capsys, status, offset, negative_first
):
    from shared.platform_capability_receipts import (
        EvidenceStatus,
        load_platform_capability_receipts,
    )

    _, positive, now = publication_receipts
    # A delayed positive can have a later generation clock, and a negative's TTL can
    # exceed the admission's. Neither wall-clock max nor max expiry orders observations.
    positive = positive.model_copy(update={"observed_at": now + timedelta(seconds=200)})
    negative = positive.model_copy(
        update={
            "receipt_id": "failure",
            "observed_at": now + timedelta(seconds=300 if offset < 0 else 100),
            "quota": positive.quota.model_copy(
                update={
                    "status": EvidenceStatus(status),
                    "observed_at": positive.quota.observed_at + timedelta(seconds=offset),
                    "stale_after": "24h",
                    "evidence_refs": [],
                    "reason_codes": [
                        "account_live_quota_receipt_absent"
                        if status == "unobservable"
                        else "admission_failed"
                    ],
                }
            ),
        }
    )
    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    first, second = (negative, positive) if negative_first else (positive, negative)
    write_receipt(first, tmp_path)
    result = write_receipt(second, tmp_path)
    expected = negative if offset > 0 else positive
    assert (
        load_platform_capability_receipts(tmp_path, now=now + timedelta(seconds=301))["glmcp"]
        == expected
    )
    assert (result is None) == (expected == first)
    assert ("stale_observation_not_published" in capsys.readouterr().err) == (expected == first)


@pytest.mark.parametrize("change", ["identity", "extend", "shorten"])
def test_equal_time_admission_identity_and_validity_are_preserved(
    tmp_path: Path, publication_receipts, change
):
    from shared.platform_capability_receipts import load_platform_capability_receipts

    receipt, _, now = publication_receipts
    quota = receipt.quota.model_copy(
        update=(
            {"evidence_refs": ["relay-receipt:distinct-admission"]}
            if change == "identity"
            else {"stale_after": "16m" if change == "extend" else "14m"}
        )
    )
    candidate = receipt.model_copy(update={"quota": quota})
    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    write_receipt(receipt, tmp_path)
    write_receipt(candidate, tmp_path)
    expected = candidate if change == "shorten" else receipt
    assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == expected


def test_process_crash_before_replace_preserves_receipt_and_releases_lock(
    tmp_path: Path, publication_receipts
):
    from shared.platform_capability_receipts import load_platform_capability_receipts

    receipt_a, receipt_b, now = publication_receipts
    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    write_receipt(receipt_a, tmp_path)

    def crash():
        os.replace = lambda *args: os._exit(73)
        write_receipt(receipt_b, tmp_path)

    process = multiprocessing.get_context("fork").Process(target=crash)
    process.start()
    process.join(timeout=10)
    try:
        assert process.exitcode == 73
        assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_a
        assert write_receipt(receipt_b, tmp_path) is not None
        assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_b
    finally:
        if process.is_alive():
            process.kill()
            process.join()


@pytest.mark.parametrize("failure", [None, "fsync", "replace"])
def test_receipt_publication_syncs_complete_private_temp_before_replace(
    tmp_path: Path, monkeypatch, publication_receipts, failure
):
    from shared.platform_capability_receipts import load_platform_capability_receipts

    receipt_a, receipt_b, now = publication_receipts
    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    path = write_receipt(receipt_a, tmp_path)
    original = path.read_bytes()
    real_fsync, real_replace = os.fsync, os.replace
    calls = []

    def fsync(fd):
        temporary = next(p for p in tmp_path.iterdir() if p != path)
        assert temporary.stat().st_ino == os.fstat(fd).st_ino
        assert temporary.stat().st_mode & 0o777 == 0o600
        assert temporary.suffix == ".tmp"  # the plural *.json loader cannot see this file
        assert json.loads(temporary.read_text()) == receipt_b.model_dump(mode="json")
        assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_a
        calls.append("fsync")
        if failure == "fsync":
            raise OSError("injected fsync failure")
        return real_fsync(fd)

    def replace(source, destination):
        assert calls == ["fsync"], "complete receipt must be flushed and fsynced before replace"
        assert Path(source).parent == path.parent
        assert destination == path
        calls.append("replace")
        if failure == "replace":
            raise OSError("injected replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    if failure:
        with pytest.raises(OSError, match=f"injected {failure} failure"):
            write_receipt(receipt_b, tmp_path)
        assert path.read_bytes() == original
    else:
        assert write_receipt(receipt_b, tmp_path) == path
        assert load_platform_capability_receipts(tmp_path, now=now)["glmcp"] == receipt_b
    assert calls == (["fsync"] if failure == "fsync" else ["fsync", "replace"])
    assert sorted(tmp_path.iterdir()) == [path]


def _show(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--show", *args],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_empty_platform_selection_is_refused_with_the_remedy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax" / "platform-capability-receipts").mkdir(parents=True)
    proc = _show(home, "--json")
    assert "Traceback" not in proc.stderr
    assert "--show needs at least one --platform" in proc.stdout + proc.stderr


def test_a_missing_receipt_for_the_named_platform_is_reported_not_invented(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax" / "platform-capability-receipts").mkdir(parents=True)
    proc = _show(home, "--platform", "glmcp", "--json")
    assert "Traceback" not in proc.stderr
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    (row,) = payload["receipts"]
    assert row["platform"] == "glmcp"
    assert row["accepted"] is False
    assert row["reason"] == "receipt_invalid:PlatformCapabilityReceiptError"
    assert payload["directory_error"] is None


@pytest.mark.parametrize("present", [False, True], ids=["missing", "accepted"])
def test_plain_text_mode_prints_a_quota_line_per_receipt(tmp_path: Path, present: bool) -> None:
    from shared.platform_capability_receipts import PlatformCapabilityReceipt

    home = tmp_path / "home"
    receipt_dir = home / ".cache/hapax/platform-capability-receipts"
    receipt_dir.mkdir(parents=True)
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if present:
        surface = {
            "status": "observed",
            "source": "test",
            "observed_at": now,
            "stale_after": "15m",
            "evidence_refs": ["platform-capability-registry:glmcp.review.direct:quota:observed"],
        }
        receipt = PlatformCapabilityReceipt.model_validate(
            {
                "receipt_id": "test-glmcp-show",
                "platform": "glmcp",
                "routes": ["glmcp.review.direct"],
                "observed_at": now,
                "stale_after": "15m",
                "cli": {"binary": "test", "available": True},
                "wrapper": {
                    "path": "scripts/hapax-glmcp-reviewer",
                    "exists": True,
                    "executable": True,
                },
                "capability": surface,
                "resource": surface,
                "quota": surface,
                "provider_docs": {
                    "refs": ["test:provider-docs"],
                    "fetched_at": now,
                    "stale_after": "30d",
                },
            }
        )
        (receipt_dir / "glmcp.json").write_text(receipt.model_dump_json())
    proc = _show(home, "--platform", "glmcp")
    assert "Traceback" not in proc.stderr
    assert proc.returncode == (0 if present else 1)
    if present:
        assert proc.stdout == (
            f"glmcp: accepted=True quota=observed observed_at={now} stale_after=15m\n"
        )
    else:
        assert proc.stdout == (
            "glmcp: accepted=False quota=? observed_at=? stale_after=? "
            "reason=receipt_invalid:PlatformCapabilityReceiptError\n"
        )


def _script_module():
    """The script as a real module, so its own globals can be steered.

    `runpy.run_path` hands back a COPY of the globals; the functions keep looking things up in
    the originals, so patching that dict changes nothing the code reads. The rows below replace
    the ledger reader and the raw-receipt parser, which only works through a module object.
    """

    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader(
        "platform_capability_receipts_script", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _quota_probe(monkeypatch, tmp_path: Path, module, *, admission_at: datetime):
    """One fresh relay admission, seen through `observe_quota`'s own glob and parser."""
    receipts = tmp_path / "relay"
    receipts.mkdir(exist_ok=True)
    (receipts / "glmcp-quota-admission-0001.yaml").write_text("route_id: glmcp.review.direct\n")
    monkeypatch.setattr(module, "QUOTA_RECEIPT_DIR", receipts)
    monkeypatch.setattr(
        module,
        "_fresh_quota_receipt",
        lambda path, *, route_ids, now: {
            "route_id": "glmcp.review.direct",
            "_observed": admission_at,
            "stale_after_seconds": 900,
        },
    )


@pytest.mark.parametrize(
    ("ledger_readable", "ledger_capture", "reason", "supersedes"),
    [
        (False, None, "quota_telemetry_unknown", False),
        (True, "before", "quota_telemetry_unknown", False),
        (True, "same-second", "quota_telemetry_unknown", False),
        (True, "after", "account_live_quota_receipt_absent", True),
    ],
    ids=[
        "unreadable-ledger-over-the-same-admission",
        "readable-ledger-that-has-not-looked-yet",
        "readable-ledger-captured-in-the-admissions-own-second",
        "readable-ledger-that-looked-and-reports-it-gone",
    ],
)
def test_a_failed_ledger_read_is_not_a_later_negative_observation(
    tmp_path: Path, monkeypatch, ledger_readable, ledger_capture, reason, supersedes
) -> None:
    """An UNOBSERVABLE built from a stale ledger revoked a renewal derived from one admission.

    `observe_quota` dated every negative `now` while dating a positive by the admissions it read.
    So a t+6 run whose relay admissions were unchanged but whose validated ledger could not be
    read outranked the t+5-dated positive published from those same admissions, and a later
    identical positive was then refused as older — the coordinator's reproduction, 2026-09-07,
    against the real parser, observer, lock, publisher and loader.

    Four rows, because "readable" turned out to be three facts, not one:

    * unreadable — nothing was established, so the negative is dated by the admissions it could
      not validate and cannot revoke them;
    * readable but captured BEFORE the admission — the ledger has not seen it, same answer
      (review finding, codex, 2026-09-07);
    * readable and captured in the admission's OWN second — indistinguishable from before at
      this resolution, so it establishes nothing either, and `observation_supersedes` already
      decides equal-second ties the same way two hundred lines below (codex again, after the
      first two were repaired with a strict `<`);
    * readable and captured after — an absence this run really observed, which must still be
      able to supersede a renewal. That row is the control, and it never moves.
    """

    module = _script_module()
    base = datetime(2026, 9, 5, tzinfo=UTC)
    admission_at = base + timedelta(seconds=5)
    _quota_probe(monkeypatch, tmp_path, module, admission_at=admission_at)

    def ledger(route_ids, *, now):
        if now == base + timedelta(seconds=8):
            return (
                {
                    "glmcp.review.direct": (
                        ["relay-receipt:glmcp.review.direct:validated"],
                        admission_at + timedelta(seconds=900),
                    )
                },
                True,
                admission_at + timedelta(seconds=1),
            )
        captured = None
        if ledger_readable:
            captured = {
                "before": base,
                "same-second": admission_at,
                "after": now - timedelta(seconds=1),
            }[ledger_capture]
        return {}, ledger_readable, captured

    monkeypatch.setattr(module, "_ledger_fresh_routes", ledger)
    route = type("Route", (), {"route_id": "glmcp.review.direct"})()
    observe_quota, write_receipt = module.observe_quota, module.write_receipt

    positive = observe_quota("glmcp", [route], now=base + timedelta(seconds=8))
    assert positive.status.value == "observed"
    assert positive.observed_at == admission_at, "a positive is dated by its admissions"

    negative_at = base + timedelta(seconds=20)
    negative = observe_quota("glmcp", [route], now=negative_at)
    assert negative.status.value == "unobservable"
    assert negative.reason_codes == [reason]
    assert (negative.observed_at == negative_at) is supersedes, (
        "an observed absence is dated now; a failed read is dated by what it examined"
    )

    out = tmp_path / "receipts"
    write_receipt(_receipt_for(positive, base + timedelta(seconds=8)), out)
    published = write_receipt(_receipt_for(negative, negative_at), out)
    from shared.platform_capability_receipts import load_platform_capability_receipt

    stored = load_platform_capability_receipt(out / "glmcp.json")
    assert bool(published) is supersedes
    assert stored.quota.status.value == ("unobservable" if supersedes else "observed")


def _receipt_for(quota, observed_at: datetime):
    from shared.platform_capability_receipts import PlatformCapabilityReceipt

    surface = {
        "status": "observed",
        "source": "test",
        "observed_at": observed_at,
        "stale_after": "900s",
        "evidence_refs": ["local:glmcp:present"],
    }
    return PlatformCapabilityReceipt.model_validate(
        {
            "receipt_id": f"probe-{observed_at:%Y%m%dT%H%M%SZ}",
            "platform": "glmcp",
            "routes": ["glmcp.review.direct"],
            "observed_at": observed_at,
            "stale_after": "900s",
            "cli": {"binary": "test", "available": True},
            "wrapper": {"path": "test", "exists": True, "executable": True},
            "capability": surface,
            "resource": surface,
            "quota": quota,
            "provider_docs": {
                "refs": ["test:docs"],
                "fetched_at": observed_at,
                "stale_after": "30d",
            },
        }
    )


@pytest.mark.parametrize("stored", ["{", ""], ids=["truncated-json", "empty-file"])
def test_an_unreadable_stored_receipt_is_quarantined_not_a_permanent_block(
    tmp_path: Path, capsys, stored
) -> None:
    """One corrupt file stopped this platform's receipts from ever being regenerated.

    `write_receipt` re-reads the stored receipt under the lock, and the loader's
    `PlatformCapabilityReceiptError` escaped: the run died, the broken bytes stayed, and every
    later run died the same way (coordinator's reproduction with a `glmcp.json` holding one `{`).
    A file that cannot be parsed supplies no ordering evidence — it cannot show it is newer, and
    refusing forever protects nothing, because the plural loader cannot read it for any consumer
    either.

    So it is moved aside, not trusted and not destroyed: the bytes survive under a dated name,
    publication proceeds on properly observed evidence, and the quarantine is announced. The
    valid-prior control below is what keeps this from becoming an overwrite.
    """

    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    from shared.platform_capability_receipts import load_platform_capability_receipt

    out = tmp_path / "receipts"
    out.mkdir()
    (out / "glmcp.json").write_text(stored)
    at = datetime(2026, 9, 5, tzinfo=UTC) + timedelta(seconds=10)
    surface = {
        "status": "observed",
        "source": "test",
        "observed_at": at,
        "stale_after": "900s",
        "evidence_refs": ["relay-receipt:glmcp.review.direct:present"],
    }
    from shared.platform_capability_receipts import SurfaceEvidence

    published = write_receipt(_receipt_for(SurfaceEvidence.model_validate(surface), at), out)

    assert published is not None, "properly observed evidence must still reach disk"
    assert load_platform_capability_receipt(out / "glmcp.json").quota.status.value == "observed"
    kept = sorted(path for path in out.iterdir() if "unreadable" in path.name)
    assert len(kept) == 1, kept
    assert kept[0].read_text() == stored, "the unreadable bytes are preserved, never discarded"
    err = capsys.readouterr().err
    assert "unreadable_receipt_quarantined" in err
    # The diagnostic names where and what kind, never the bytes: a parser's message quotes the
    # input it choked on, and stderr reaches logs and journals the receipt directory does not.
    assert "cause=" in err
    assert not stored or stored not in err.replace("glmcp.json", ""), err


def test_two_quarantines_in_one_second_keep_both_sets_of_bytes(tmp_path: Path, capsys) -> None:
    """The stamp is second-resolution, so it is not a unique name.

    Two unreadable receipts quarantined within one second produced the same target path and
     overwrote the first — the repair that exists to preserve unreadable bytes
    destroyed a set of them (review finding, cx-blue, 2026-09-07 13:30). The name is now claimed
    with O_EXCL under the publication lock, so the filesystem decides and a losing candidate is
    never written over.
    """

    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    from shared.platform_capability_receipts import SurfaceEvidence

    out = tmp_path / "receipts"
    out.mkdir()
    at = datetime(2026, 9, 5, tzinfo=UTC) + timedelta(seconds=10)
    surface = SurfaceEvidence.model_validate(
        {
            "status": "observed",
            "source": "test",
            "observed_at": at,
            "stale_after": "900s",
            "evidence_refs": ["relay-receipt:glmcp.review.direct:present"],
        }
    )
    for corpse in ("first-corrupt", "second-corrupt"):
        (out / "glmcp.json").write_text(corpse)
        assert write_receipt(_receipt_for(surface, at), out) is not None

    kept = sorted(path for path in out.iterdir() if "unreadable" in path.name)
    assert len(kept) == 2, kept
    assert sorted(path.read_text() for path in kept) == ["first-corrupt", "second-corrupt"]
    capsys.readouterr()


def test_a_readable_older_receipt_is_still_retained(tmp_path: Path, capsys) -> None:
    """The control for the row above: a prior this loader CAN read still orders publication."""

    write_receipt = runpy.run_path(str(SCRIPT))["write_receipt"]
    from shared.platform_capability_receipts import (
        SurfaceEvidence,
        load_platform_capability_receipt,
    )

    out = tmp_path / "receipts"
    base = datetime(2026, 9, 5, tzinfo=UTC)
    newer = SurfaceEvidence.model_validate(
        {
            "status": "observed",
            "source": "test",
            "observed_at": base + timedelta(seconds=30),
            "stale_after": "900s",
            "evidence_refs": ["relay-receipt:glmcp.review.direct:present"],
        }
    )
    older = newer.model_copy(update={"observed_at": base + timedelta(seconds=5)})
    write_receipt(_receipt_for(newer, base + timedelta(seconds=30)), out)
    assert write_receipt(_receipt_for(older, base + timedelta(seconds=5)), out) is None
    stored = load_platform_capability_receipt(out / "glmcp.json")
    assert stored.quota.observed_at == base + timedelta(seconds=30)
    assert not [path for path in out.iterdir() if "unreadable" in path.name]
    assert "stale_observation_not_published" in capsys.readouterr().err


def test_an_unloadable_receipt_directory_is_not_accepted(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax").mkdir(parents=True)
    (home / ".cache" / "hapax" / "platform-capability-receipts").write_text("not a directory")
    proc = _show(home, "--platform", "glmcp", "--json")
    assert "Traceback" not in proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    rows = [row for row in payload["receipts"] if row.get("platform") == "glmcp"]
    assert rows and rows[0]["accepted"] is False and rows[0].get("reason"), payload
