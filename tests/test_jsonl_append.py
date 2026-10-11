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
import shutil
import signal
import subprocess
import sys
from multiprocessing.pool import Pool
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


#: The concurrency test's map normally finishes in a few seconds; a wedge fails the test here
#: instead of running into the shard's wall.
POOL_RESULT_TIMEOUT_S = 120


def _restore_default_sigterm() -> None:
    """Pool initializer: a worker ends on SIGTERM whatever disposition it inherited.

    ``Pool.terminate()`` takes the inqueue lock and never releases it, then relies on SIGTERM
    to end any worker still blocked on that lock. A forked worker inherits its parent's
    SIGTERM disposition, and under xdist an earlier test in the same process can leave a
    handler installed. A worker that survives SIGTERM makes ``terminate()`` join forever;
    that hang ejected the merge groups of #5019 (2026-10-04) and #5088 (2026-10-10).
    """
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _sigterm_disposition(_: object = None) -> str:
    handler = signal.getsignal(signal.SIGTERM)
    return "default" if handler is signal.SIG_DFL else repr(handler)


def _writer_pool(processes: int) -> Pool:
    return mp.get_context("fork").Pool(processes=processes, initializer=_restore_default_sigterm)


def _run_concurrent_writers(path: str, workers: int, per_worker: int, pad_every: int) -> list[int]:
    """Run the writers, then close() and join(): workers exit on their sentinels, so the
    success path takes no lock and sends no signal. ``terminate()`` is the failure path only."""
    pool = _writer_pool(workers)
    try:
        written = pool.map_async(
            _concurrent_worker,
            [(path, wid, per_worker, pad_every) for wid in range(workers)],
        ).get(timeout=POOL_RESULT_TIMEOUT_S)
    except BaseException:
        pool.terminate()
        pool.join()
        raise
    pool.close()
    pool.join()
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


class TestConcurrencyNoInterleave:
    def test_sixteen_writers_two_hundred_records_no_corruption(self, tmp_path: Path) -> None:
        target = tmp_path / "authority-case-ledger.jsonl"
        workers, per_worker, pad_every = 16, 200, 10
        written = _run_concurrent_writers(str(target), workers, per_worker, pad_every)
        assert sum(written) == workers * per_worker

        lines = target.read_text(encoding="utf-8").splitlines()
        # Every line must parse — interleaving above PIPE_BUF would corrupt some.
        parsed = [json.loads(line) for line in lines]
        assert len(parsed) == workers * per_worker, "lost or merged writes"
        seen = {(row["worker"], row["seq"]) for row in parsed}
        expected = {(w, s) for w in range(workers) for s in range(per_worker)}
        assert seen == expected, "interleaving dropped or duplicated records"


class TestPoolTeardown:
    def test_workers_end_on_sigterm_even_when_the_parent_handles_it(self, tmp_path: Path) -> None:
        # The child interpreter stands in for an xdist worker that an earlier test left with
        # a SIGTERM handler. Out of process, a regression fails on the timeout instead of
        # hanging this shard.
        code = "\n".join(
            [
                "import signal, sys",
                f"sys.path[:0] = [{str(REPO_ROOT)!r}, {str(REPO_ROOT / 'tests')!r}]",
                "signal.signal(signal.SIGTERM, lambda *_: None)",
                "from test_jsonl_append import (",
                "    _run_concurrent_writers, _sigterm_disposition, _writer_pool,",
                ")",
                "pool = _writer_pool(2)",
                "try:",
                "    print(pool.apply(_sigterm_disposition))",
                "finally:",
                "    pool.close()",
                "    pool.join()",
                f"print(sum(_run_concurrent_writers({str(tmp_path / 'ledger.jsonl')!r}, 4, 20, 10)))",
            ]
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=90, check=False
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert result.stdout.split() == ["default", "80"]


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
