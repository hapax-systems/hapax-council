"""Tests for shared.jsonl_append — single-writer-safe JSONL append helper.

The load-bearing guarantees (dn-ledger-flock):
  * a record larger than PIPE_BUF (4096B) appended concurrently never interleaves;
  * a Python ``fcntl.flock`` writer and a shell ``flock(1)`` writer serialise on
    the same sidecar lock (cross-language interop, the cc-task-gate bash path);
  * every routed writer reproduces its pre-change bytes EXACTLY (byte identity),
    so the field-fix and the event-sourcing replay round-trip stay uncoupled;
  * the helper fails OPEN (returns False, never raises/blocks) unless the caller
    explicitly asks to propagate (``raising=True``) — NEVER-FREEZE.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import shared.jsonl_append as jsonl_append
from shared.jsonl_append import _lock_path, append_jsonl, append_jsonl_lines


# --- module-level worker for the concurrency test (fork-safe) ------------------
def _concurrent_worker(args: tuple[str, int, int, int]) -> int:
    """Append ``count`` records to ``path``; pad some past PIPE_BUF to force >4096B."""
    path, worker_id, count, pad_every = args
    written = 0
    for seq in range(count):
        record = {"worker": worker_id, "seq": seq, "kind": "concurrency-probe"}
        if pad_every and seq % pad_every == 0:
            record["pad"] = "x" * 6000  # > PIPE_BUF: O_APPEND alone is NOT atomic here
        if append_jsonl(path, record, sort_keys=True):
            written += 1
    return written


class TestLockPath:
    def test_sidecar_is_name_plus_dot_lock(self) -> None:
        assert _lock_path(Path("/a/b/ledger.jsonl")) == Path("/a/b/ledger.jsonl.lock")


class TestRoundTrip:
    def test_append_single_record_roundtrips(self, tmp_path: Path) -> None:
        target = tmp_path / "ledger.jsonl"
        assert append_jsonl(target, {"a": 1, "b": "two"}) is True
        lines = target.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"a": 1, "b": "two"}

    def test_append_lines_writes_every_record(self, tmp_path: Path) -> None:
        target = tmp_path / "ledger.jsonl"
        records = [{"i": i} for i in range(5)]
        assert append_jsonl_lines(records, target) is True
        lines = target.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == records

    def test_empty_iterable_is_noop_success(self, tmp_path: Path) -> None:
        target = tmp_path / "ledger.jsonl"
        assert append_jsonl_lines([], target) is True
        assert not target.exists()  # nothing written, no lock churn

    def test_creates_sidecar_lock_next_to_ledger(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "ledger.jsonl"
        append_jsonl(target, {"a": 1})
        assert (tmp_path / "sub" / "ledger.jsonl.lock").exists()


class TestFailOpen:
    def test_unwritable_path_returns_false_and_does_not_raise(self) -> None:
        # Parent is a file, so mkdir/open fails — must swallow and report False.
        result = append_jsonl("/this/does/not/exist/and/cannot/inv.jsonl", {"a": 1})
        assert result is False

    def test_raising_true_propagates_the_oserror(self, tmp_path: Path) -> None:
        clash = tmp_path / "clash"
        clash.write_text("not a dir", encoding="utf-8")
        target = clash / "ledger.jsonl"  # parent is a regular file -> mkdir raises
        with pytest.raises(OSError):
            append_jsonl(target, {"a": 1}, raising=True)

    def test_short_write_loops_until_record_complete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "ledger.jsonl"
        real_write = os.write
        write_sizes: list[int] = []

        def short_write(fd: int, data) -> int:
            chunk = max(1, len(data) // 2)
            written = real_write(fd, bytes(data[:chunk]))
            write_sizes.append(written)
            return written

        monkeypatch.setattr(jsonl_append.os, "write", short_write)

        assert append_jsonl(target, {"a": "x" * 100}, sort_keys=True) is True
        lines = target.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == [{"a": "x" * 100}]
        assert len(write_sizes) > 1
        assert len(write_sizes) <= 16

    def test_zero_progress_write_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jsonl_append.os, "write", lambda _fd, _data: 0)

        assert append_jsonl(tmp_path / "ledger.jsonl", {"a": 1}) is False

    def test_zero_progress_batched_write_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jsonl_append.os, "write", lambda _fd, _data: 0)

        assert append_jsonl_lines([{"a": 1}, {"b": 2}], tmp_path / "ledger.jsonl") is False


class TestConcurrencyNoInterleave:
    def test_sixteen_writers_two_hundred_records_no_corruption(self, tmp_path: Path) -> None:
        target = tmp_path / "authority-case-ledger.jsonl"
        workers, per_worker, pad_every = 16, 200, 10
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=workers) as pool:
            written = pool.map(
                _concurrent_worker,
                [(str(target), wid, per_worker, pad_every) for wid in range(workers)],
            )
        assert sum(written) == workers * per_worker

        lines = target.read_text(encoding="utf-8").splitlines()
        # Every line must parse — interleaving above PIPE_BUF would corrupt some.
        parsed = [json.loads(line) for line in lines]
        assert len(parsed) == workers * per_worker, "lost or merged writes"
        seen = {(row["worker"], row["seq"]) for row in parsed}
        expected = {(w, s) for w in range(workers) for s in range(per_worker)}
        assert seen == expected, "interleaving dropped or duplicated records"


class TestCrossLanguageLock:
    def test_python_and_shell_flock_share_the_sidecar(self, tmp_path: Path) -> None:
        flock_bin = shutil.which("flock")
        assert flock_bin, "util-linux flock(1) is required (no raw >> fallback)"
        target = tmp_path / "cc-task-gate-decisions.jsonl"
        lock = _lock_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        n = 60
        # Shell writer: large (>PIPE_BUF) records via flock(1) on the SAME sidecar
        # the helper uses. tee -a matches the cc-task-gate.impl.sh wrapping.
        script = f"""
        pad=$(head -c 6000 < /dev/zero | tr '\\0' y)
        ( umask 077; : >> "{lock}" )
        for i in $(seq 1 {n}); do
          printf '{{"src":"bash","i":%d,"pad":"%s"}}\\n' "$i" "$pad" \
            | flock "{lock}" tee -a "{target}" >/dev/null
        done
        """
        proc = subprocess.Popen(["bash", "-c", script])
        for i in range(n):  # Python writer racing the shell writer
            append_jsonl(target, {"src": "py", "i": i, "pad": "x" * 6000}, sort_keys=True)
        proc.wait(timeout=60)
        assert proc.returncode == 0

        lines = target.read_text(encoding="utf-8").splitlines()
        parsed = [json.loads(line) for line in lines]  # raises if any line is corrupt
        assert len(parsed) == 2 * n
        assert sum(1 for r in parsed if r["src"] == "bash") == n
        assert sum(1 for r in parsed if r["src"] == "py") == n


class TestByteIdentity:
    """Each routed writer must reproduce its pre-change bytes EXACTLY."""

    def _written_line(self, tmp_path: Path, **append_kwargs) -> str:
        target = tmp_path / "golden.jsonl"
        record = append_kwargs.pop("record")
        assert append_jsonl(target, record, **append_kwargs) is True
        return target.read_text(encoding="utf-8").splitlines()[0]

    def test_cc_stage_advance_sort_keys_default_separators(self, tmp_path: Path) -> None:
        record = {
            "ts": "2026-06-02T05:00:00Z",
            "kind": "stage_transition",
            "tool": "cc-stage-advance",
            "role": "eta",
            "task_id": "dn-ledger-flock-20260601",
            "authority_case": "CASE-SDLC-REFORM-001",
            "from_stage": "S6_IMPLEMENTATION",
            "to_stage": "S7_RELEASE",
            "note": "café — unicode",
        }
        original = json.dumps(record, sort_keys=True)  # the literal cc-stage-advance call
        assert self._written_line(tmp_path, record=record, sort_keys=True) == original

    def test_cc_scope_widen_sort_keys(self, tmp_path: Path) -> None:
        record = {
            "ts": "2026-06-02T05:00:00Z",
            "kind": "scope_widen",
            "tool": "cc-scope-widen",
            "role": "eta",
            "task_id": "dn-ledger-flock-20260601",
            "added": ["shared/jsonl_append.py"],
            "removed": [],
        }
        original = json.dumps(record, sort_keys=True)
        assert self._written_line(tmp_path, record=record, sort_keys=True) == original

    def test_record_invariant_findings_bare_dumps_preserves_key_order(self, tmp_path: Path) -> None:
        # Bare json.dumps: no sort_keys -> key ORDER is load-bearing.
        record = {
            "ts": "2026-06-02T05:00:00Z",
            "invariant": "INV-3",
            "name": "escape",
            "holds": False,
            "violations": ["BLOCKED:no-escape"],
            "advisory": True,
        }
        original = json.dumps(record)  # the literal record_invariant_findings call
        target = tmp_path / "inv.jsonl"
        assert append_jsonl_lines([record], target) is True
        assert target.read_text(encoding="utf-8").splitlines()[0] == original

    def test_coord_mirror_canonical_json(self, tmp_path: Path) -> None:
        from shared.coord_event_log import _canonical_json

        record = {"sequence": 1, "event_type": "stage", "actor": "eta", "ts": "2026-06-02T05Z"}
        original = _canonical_json(record)
        assert self._written_line(tmp_path, record=record, serialize=_canonical_json) == original

    def test_coord_spool_nested_canonical_json(self, tmp_path: Path) -> None:
        from shared.coord_event_log import _canonical_json

        record = {
            "schema_version": 1,
            "spooled_at": "2026-06-02T05:00:00Z",
            "writer": {"kind": "shim", "name": "cc-stage-advance"},
            "reason": "canonical_append_failed:OSError:disk",
            "event": {"event_id": "abc", "payload": {"b": 2, "a": 1}},
        }
        original = _canonical_json(record)
        assert self._written_line(tmp_path, record=record, serialize=_canonical_json) == original
