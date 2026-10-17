"""Read-only inspection uses the current receipt contract without running probes."""

from __future__ import annotations

import io
import json
import os
import runpy
import stat
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-platform-capability-receipts"


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


@pytest.mark.parametrize("neighbor", [False, True], ids=["current-contract", "malformed-neighbor"])
def test_show_uses_current_contract_without_probes_or_writes(
    tmp_path, monkeypatch, capsys, neighbor
):
    import runpy

    from tests.scripts.test_hapax_glmcp_seat_refresh import _glmcp_receipt_json

    now = datetime.now(UTC).replace(microsecond=0)
    receipt_path = tmp_path / "glmcp.json"
    receipt_path.write_text(_glmcp_receipt_json(status="observed", remaining=900, age=0, now=now))
    assert "load_sets" in receipt_path.read_text()
    if neighbor:
        (tmp_path / "other.json").write_text('{"private_payload": "synthetic-secret-value"}')
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    main = runpy.run_path(str(SCRIPT))["main"]

    def forbidden(*args, **kwargs):
        pytest.fail("--show attempted a probe, writer, or registry refresh")

    for name in ("observe_cli", "write_receipt", "load_platform_capability_registry_for_dispatch"):
        monkeypatch.setitem(main.__globals__, name, forbidden)
    assert main(["--show", "--platform", "glmcp", "--receipt-dir", str(tmp_path), "--json"]) == int(
        neighbor
    )
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["receipts"][0]["accepted"] is (not neighbor)
    if neighbor:
        assert payload["directory_error"] == "receipt_dir_unloadable:PlatformCapabilityReceiptError"
    assert "synthetic-secret-value" not in output.out + output.err
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}


@pytest.fixture
def publisher(monkeypatch):
    write = runpy.run_path(str(SCRIPT))["write_receipt"]

    def forbidden(*args, **kwargs):
        pytest.fail("synthetic publisher test attempted a probe, CLI, or network call")

    monkeypatch.setitem(write.__globals__, "observe_cli", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(write.__globals__["socket"], "socket", forbidden)
    return write


def _publication_receipt(*, age=0, unknown=False, stale=False, padding=""):
    from shared.platform_capability_receipts import PlatformCapabilityReceipt
    from tests.scripts.test_hapax_glmcp_seat_refresh import _glmcp_receipt_json

    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    payload = json.loads(
        _glmcp_receipt_json(
            status="unobservable" if unknown else "observed",
            remaining=900,
            age=age,
            now=now,
            receipt_stale=stale,
        )
    )
    payload["receipt_id"] += padding
    if unknown:
        for name in ("capability", "resource"):
            payload[name] = dict(payload["quota"])
    return PlatformCapabilityReceipt.model_validate(payload), now


def test_atomic_publication_readers_see_complete_receipts_during_two_writers(
    tmp_path, monkeypatch, publisher
):
    from shared.platform_capability_receipts import (
        PlatformCapabilityReceiptError,
        load_platform_capability_receipts,
    )

    initial, now = _publication_receipt(age=120)
    older, _ = _publication_receipt(age=60)
    newer, _ = _publication_receipt(padding="longer-" * 200)
    publisher(initial, tmp_path)
    opened, release = threading.Event(), threading.Event()
    real_open = io.open

    def paused_open(*args, **kwargs):
        stream = real_open(*args, **kwargs)
        if threading.current_thread().name.startswith("publisher-A") and "w" in stream.mode:
            opened.set()
            if not release.wait(10):
                stream.close()
                raise TimeoutError("publisher A barrier was not released")
        return stream

    def read():
        try:
            return load_platform_capability_receipts(tmp_path, now=now)["glmcp"]
        except PlatformCapabilityReceiptError as exc:
            return type(exc).__name__

    monkeypatch.setattr(io, "open", paused_open)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="publisher-A") as pool:
        pending = pool.submit(publisher, older, tmp_path)
        try:
            assert opened.wait(10), "writer never reached its open-before-write boundary"
            before_b = read()
            publisher(newer, tmp_path)
            after_b = read()
        finally:
            release.set()
        pending.result(timeout=10)
    after_a = read()
    assert (before_b, after_b, after_a) == (initial, newer, older)
    # Completion order governs publication; this patch does not order observations.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["glmcp.json"]


def test_atomic_publication_private_complete_file_is_synced_before_one_replace(
    tmp_path, monkeypatch, publisher
):
    from shared.platform_capability_receipts import load_platform_capability_receipts

    receipt, now = _publication_receipt()
    events = []
    real_open, real_create, real_fsync, real_replace = io.open, os.open, os.fsync, os.replace

    class Stream:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.stream.close()

        def write(self, payload):
            events.append("write")
            return self.stream.write(payload)

        def flush(self):
            events.append("flush")
            return self.stream.flush()

    def opened(*args, **kwargs):
        stream = real_open(*args, **kwargs)
        return Stream(stream) if "w" in stream.mode else stream

    def created(path, flags, mode=0o777):
        assert flags & os.O_CREAT and flags & os.O_EXCL
        assert mode == 0o600
        events.append("create")
        return real_create(path, flags, mode)

    def synced(fd):
        assert events == ["create", "write", "flush"]
        assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o600
        real_fsync(fd)
        events.append("fsync")

    def replaced(src, dst):
        src, dst = Path(src), Path(dst)
        assert events == ["create", "write", "flush", "fsync"]
        assert src.parent == tmp_path and src != dst
        assert not src.match("*.json")
        assert list(tmp_path.glob("*.json")) == []
        assert json.loads(src.read_text()) == receipt.model_dump(mode="json")
        assert stat.S_IMODE(src.stat().st_mode) == 0o600
        events.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(io, "open", opened)
    monkeypatch.setattr(os, "open", created)
    monkeypatch.setattr(os, "fsync", synced)
    monkeypatch.setattr(os, "replace", replaced)
    assert publisher(receipt, tmp_path) == tmp_path / "glmcp.json"
    assert events == ["create", "write", "flush", "fsync", "replace"]
    assert load_platform_capability_receipts(tmp_path, now=now) == {"glmcp": receipt}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["glmcp.json"]


@pytest.mark.parametrize("failure", ["serialize", "create", "write", "flush", "fsync", "replace"])
def test_atomic_publication_pre_replace_failure_preserves_canonical_and_other_temps(
    tmp_path, monkeypatch, publisher, failure
):
    initial, _ = _publication_receipt(age=60)
    receipt, _ = _publication_receipt()
    canonical = publisher(initial, tmp_path)
    before = canonical.read_bytes()
    other = tmp_path / ".glmcp.json.another-writer.tmp"
    other.write_bytes(b"another writer's incomplete bytes")
    real_open = io.open
    reached = []

    def fail(*args, **kwargs):
        reached.append(failure)
        raise OSError(f"injected {failure} failure")

    class Stream:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.stream.close()

        def write(self, payload):
            if failure == "write":
                self.stream.write(payload[:20])
                self.stream.flush()
                fail()
            return self.stream.write(payload)

        def flush(self):
            if failure == "flush":
                fail()
            return self.stream.flush()

    def opened(*args, **kwargs):
        stream = real_open(*args, **kwargs)
        return Stream(stream) if "w" in stream.mode else stream

    if failure == "serialize":
        monkeypatch.setattr(json, "dumps", fail)
    elif failure == "create":
        monkeypatch.setattr(os, "open", fail)
    elif failure in ("fsync", "replace"):
        monkeypatch.setattr(os, failure, fail)
    else:
        monkeypatch.setattr(io, "open", opened)
    with pytest.raises(OSError, match=f"injected {failure} failure"):
        publisher(receipt, tmp_path)
    assert reached == [failure]
    assert canonical.read_bytes() == before
    assert other.read_bytes() == b"another writer's incomplete bytes"
    assert sorted(p.name for p in tmp_path.iterdir()) == [other.name, canonical.name]


@pytest.mark.parametrize("case", ["unknown", "stale", "malformed-neighbor"])
def test_atomic_publication_retains_plural_loader_evidence_semantics(tmp_path, publisher, case):
    from shared.platform_capability_receipts import (
        PlatformCapabilityReceiptError,
        load_platform_capability_receipts,
    )

    receipt, now = _publication_receipt(unknown=case == "unknown", stale=case == "stale")
    if case == "malformed-neighbor":
        (tmp_path / "other.json").write_text("{broken")
    publisher(receipt, tmp_path)
    if case == "malformed-neighbor":
        with pytest.raises(PlatformCapabilityReceiptError, match="other.json"):
            load_platform_capability_receipts(tmp_path, now=now)
        return
    expected = {} if case == "stale" else {"glmcp": receipt}
    assert load_platform_capability_receipts(tmp_path, now=now) == expected
